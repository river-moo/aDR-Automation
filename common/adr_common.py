"""aDR 사전 점검 공통 로직 (03-adr-precheck, 04-adr-drill에서 같이 씀)."""
import time


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def find_policy(c, key):
    """정책 ID 또는 정책 이름으로 찾기."""
    for p in c.list_protections():
        if key in (p.get("id"), p.get("name")):
            return p
    raise LookupError(f"DR 정책을 찾을 수 없음: {key}")


def check_policy(c, policy, out=log):
    """정책 1개 점검. (ok 여부, 결과 dict) 반환."""
    res = {"id": policy["id"], "name": policy["name"], "type": policy.get("type"),
           "enable": policy.get("enable"), "checks": []}

    def add(level, msg):
        res["checks"].append({"level": level, "msg": msg})
        out(f"  [{level}] {msg}")

    out(f"정책: {policy['name']} ({policy.get('type')}) id={policy['id']}")
    if not policy.get("enable"):
        add("FAIL", "정책이 비활성 상태")
    cfg = policy.get("config") or {}
    src, dst = cfg.get("source") or {}, cfg.get("destination") or {}
    res["source"], res["destination"] = src, dst
    add("INFO", f"보호 사이트 {src.get('site_id')} / AZ {src.get('az_id')} ({src.get('type')}) "
                f"-> DR 사이트 {dst.get('site_id')} / AZ {dst.get('az_id')}")
    if policy.get("next_trigger_time"):
        add("INFO", "다음 동기화 " + time.strftime("%Y-%m-%d %H:%M", time.localtime(policy["next_trigger_time"] / 1000)))

    members = sorted(policy.get("servers") or [], key=lambda s: s.get("recover_priority", 99))
    if not members:
        add("FAIL", "보호 VM이 없음")
    try:
        protected = {v["id"]: v for v in c.list_protected_servers(policy["id"])}
    except Exception as e:  # noqa: BLE001
        protected = None
        add("WARN", f"보호 VM 상세 조회 실패: {e}")
    res["servers"] = []
    for s in members:
        vm = (protected or {}).get(s["id"])
        name = (vm or {}).get("name", "?")
        row = {"id": s["id"], "name": name, "priority": s.get("recover_priority"),
               "enable": s.get("enable"), "status": (vm or {}).get("status")}
        res["servers"].append(row)
        if not s.get("enable"):
            add("WARN", f"{name} ({s['id']}) 정책 안에서 비활성")
        elif protected is not None and not vm:
            add("FAIL", f"{s['id']} 가 보호 VM 목록에 없음")
        else:
            add("OK", f"{name} 우선순위 {s.get('recover_priority')} 상태 {row['status']}")
    ok = not any(c_["level"] == "FAIL" for c_ in res["checks"])
    res["result"] = "PASS" if ok else "FAIL"
    return ok, res


# ================================================================ 복구 계획 (콘솔 API)
# 6.11.3 실측: GET /admin/view/dr-rp-list
#   status.action : drill / ... (마지막 동작), status.state : ready(대기) / finish(동작 완료) / ...
#   task_progress : {total, succeed, failed, canceled}
RP_LIST = "/admin/view/dr-rp-list"


def rp_list(cc):
    return cc.request("GET", RP_LIST, params={"start": 0, "limit": 200, "sort": "state", "direct": "ASC"}).get("data", [])


def find_rp(cc, key):
    """복구 계획 이름 또는 ID로 찾기."""
    for rp in rp_list(cc):
        if key in (rp.get("id"), rp.get("name")):
            return rp
    raise LookupError(f"복구 계획을 찾을 수 없음: {key}")


def rp_status(rp):
    st = rp.get("status") or {}
    return st.get("action"), st.get("state"), rp.get("task_progress") or {}


def check_rp(rp, need_states=None, out=log):
    """복구 계획 점검. need_states가 있으면 현재 state가 그 안에 있어야 PASS."""
    ok = True
    action, state, prog = rp_status(rp)
    out(f"복구 계획: {rp['name']} id={rp['id']} 상태={state} (마지막 동작 {action}), VM {rp.get('server_num')}대")
    for side in ("src_sites", "des_sites"):
        for s in rp.get(side) or []:
            lvl = "OK" if s.get("status") == "normal" else "FAIL"
            ok &= lvl == "OK"
            out(f"  [{lvl}] {'보호' if side == 'src_sites' else 'DR'} 사이트 {s.get('az_name')} "
                f"({s.get('version')}) 상태 {s.get('status')}")
    if not rp.get("server_num"):
        out("  [FAIL] 계획에 VM이 없음"); ok = False
    if need_states and state not in need_states:
        out(f"  [FAIL] 현재 상태 '{state}'에서는 실행할 수 없음 (필요: {', '.join(need_states)})"); ok = False
    if rp.get("last_drill_time"):
        out(f"  [INFO] 마지막 드릴 {rp['last_drill_time']}")
    return ok


def wait_rp(cc, rp_id, until_states, action=None, before_ulog=None, timeout=3600, interval=10, out=log):
    """복구 계획 상태가 until_states 중 하나가 될 때까지 대기. 실패 작업이 생기면 예외.
    before_ulog: 실행 전 status.ulog_id. 이전 동작의 완료 상태를 새 동작 완료로 착각하지 않도록
    ulog_id가 바뀐 뒤의 상태만 인정한다."""
    end = time.time() + timeout
    seen = None
    started = time.time()
    while time.time() < end:
        rp = find_rp(cc, rp_id)
        act, state, prog = rp_status(rp)
        cur = (act, state, prog.get("succeed"), prog.get("failed"), prog.get("total"))
        if cur != seen:
            out(f"  상태 {state} (동작 {act}) 진행 {prog.get('succeed', 0)}/{prog.get('total', 0)} "
                f"실패 {prog.get('failed', 0)}  [{int(time.time() - started)}s]")
            seen = cur
        if prog.get("failed"):
            raise RuntimeError(f"복구 계획 작업 실패 {prog.get('failed')}건 - 콘솔 Tasks에서 원인 확인")
        new_run = before_ulog is None or (rp.get("status") or {}).get("ulog_id") != before_ulog
        if new_run and state in until_states and (action is None or act == action):
            return rp
        time.sleep(interval)
    raise TimeoutError(f"대기 시간 초과 ({timeout}s): 마지막 상태 {seen}")


# ================================================================ 드릴 본문 자동 생성
# 6.11.3 실측: GET /admin/view/dr-server-list 의 VM 행에 드릴 본문 값이 모두 들어 있다.
SERVER_LIST = "/admin/view/dr-server-list"


def server_list(cc):
    rows, start = [], 0
    while True:
        d = cc.request("GET", SERVER_LIST, params={"start": start, "limit": 100})
        page = d.get("data", [])
        rows.extend(page)
        if len(page) < 100:
            return rows
        start += 100


def build_drill_body(cc, rp, need_sync=0, resource_reserve=0):
    """콘솔 'Perform DR Test' 창이 보내는 본문을 그대로 만든다 (복구 시점은 최신 = 생략)."""
    rows = {r["id"]: r for r in server_list(cc)}
    servers, missing = [], []
    for pg in rp.get("pgs") or []:
        for s in pg.get("servers") or []:
            row = rows.get(s["server_id"])
            if not row:
                missing.append(s["server_id"])
                continue
            clusters = lambda key: [{"cluster_id": c["cluster_id"], "status": c["status"]}  # noqa: E731
                                    for c in row.get(key) or []]
            servers.append({
                "pg_id": (row.get("pg") or {}).get("pg_id") or pg.get("pg_id"),
                "server_id": row["id"],
                "src_clusters": clusters("src_clusters"),
                "des_clusters": clusters("des_clusters"),
                "protection_id": (row.get("protection") or {}).get("id"),
                "recovery_storage_id": row.get("recovery_storage_id"),
            })
    if missing:
        raise LookupError(f"dr-server-list에 없는 VM: {', '.join(missing)}")
    bad = [s["server_id"] for s in servers
           if not (s["protection_id"] and s["recovery_storage_id"] and s["src_clusters"] and s["des_clusters"])]
    if bad:
        raise LookupError(f"드릴 본문 값이 비어 있는 VM: {', '.join(bad)}")
    return {"drill": {"rps": [{"rp_id": rp["id"], "servers": servers}],
                      "need_sync": int(need_sync), "enable_resource_reserve": int(resource_reserve)}}
