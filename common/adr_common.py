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
