#!/usr/bin/env python3
"""Task 04 - aDR 복구 계획 드릴 / 정리 / Failover / Failback 실행기.

SCP 6.11.3 실측: 드릴·전환은 '복구 계획(Recovery Plan)' 단위로, 콘솔 API(4430 /admin/...)로 실행된다.
상태 추적은 GET /admin/view/dr-rp-list 의 status(action/state)와 task_progress 로 한다.
실행 API(경로·본문)는 Task 02 캡처 결과를 endpoints.json 에 채운다. 기본은 dry-run.

./run.sh list                                        # 복구 계획 목록과 상태
./run.sh drill    -p aDR-Auto-SCP-Test               # 드릴 계획만 출력 (dry-run)
./run.sh drill    -p aDR-Auto-SCP-Test --execute     # 점검 -> 드릴 -> 완료 대기 -> 검증 -> 정리
./run.sh drill    -p aDR-Auto-SCP-Test --execute --keep   # 드릴 VM 남겨두기
./run.sh cleanup  -p aDR-Auto-SCP-Test --execute     # 드릴 정리(테스트 종료)만
./run.sh clear    -p aDR-Auto-SCP-Test --execute     # 끝난 계획 상태를 Ready로 정리만
./run.sh failover -p aDR-Auto-SCP-Test --execute --confirm aDR-Auto-SCP-Test
./run.sh failback -p aDR-Auto-SCP-Test --execute --confirm aDR-Auto-SCP-Test
"""
import argparse
import json
import os
import socket
import sys

from adr_common import build_drill_body, check_rp, find_rp, log, rp_list, rp_status, wait_rp
from scp_client import ConsoleClient, SCPClient, SCPError, call_endpoint, env, load_env

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = {
    "drill": ["drill_start", "verify", "drill_cleanup", "clear_state"],
    "cleanup": ["drill_cleanup", "clear_state"],
    "clear": ["clear_state"],
    "failover": ["failover", "verify"],
    "failback": ["failback", "verify"],
}
DANGEROUS = {"failover", "failback"}


def load_endpoints():
    path = env("ENDPOINTS_FILE", os.path.join(HERE, "endpoints.json"))
    with open(path, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f)["endpoints"].items() if not k.startswith("_")}


def verify_targets():
    """VERIFY_TARGETS=host:port,host:port 형식으로 서비스 포트 확인."""
    targets = [t.strip() for t in env("VERIFY_TARGETS", "").split(",") if t.strip()]
    if not targets:
        log("  검증 대상(VERIFY_TARGETS)이 없어 서비스 확인을 건너뜁니다")
        return True
    ok = True
    for t in targets:
        h, _, p = t.rpartition(":")
        try:
            socket.create_connection((h, int(p)), timeout=int(env("VERIFY_TIMEOUT", "5"))).close()
            log(f"  [OK]   {t} 응답")
        except (OSError, ValueError) as e:
            log(f"  [FAIL] {t} 응답 없음: {e}")
            ok = False
    return ok


def run_step(clients, eps, name, rp):
    if name == "verify":
        return verify_targets()
    ep = eps[name]
    client = clients["console"] if ep.get("api", "console") == "console" else clients["openapi"]()
    before = (rp.get("status") or {}).get("ulog_id")
    before_pair = ((rp.get("status") or {}).get("action"), (rp.get("status") or {}).get("state"))
    st = rp.get("status") or {}
    variables = {"rp_id": rp["id"], "rp_name": rp["name"], "project_id": rp.get("project_id", ""),
                 "drlog_id": st.get("drlog_id") or "", "drlog_root_id": st.get("drlog_root_id") or ""}
    if ep.get("body_builder") == "drill":
        ep = dict(ep, body=build_drill_body(clients["console"], rp, env("DRILL_NEED_SYNC", "0"),
                                            env("DRILL_RESOURCE_RESERVE", "0")))
    log(f"{name}: {ep['method']} {ep['path']}")
    try:
        resp = call_endpoint(client, ep, name, **variables)
    except SCPError as e:
        if "HTTP 405" not in str(e):
            raise
        alt = "PUT" if ep["method"] == "POST" else "POST"
        log(f"  HTTP 405 (메서드 불일치, 실행 안 됨) -> {alt}로 재시도")
        resp = call_endpoint(client, dict(ep, method=alt), name, **variables)
    log(f"  응답: {json.dumps(resp, ensure_ascii=False)[:300]}")
    w = ep.get("wait")
    if w:
        wait_rp(clients["console"], rp["id"], w["until_state"], action=w.get("action"), before_ulog=before,
                timeout=int(env("TASK_TIMEOUT", "3600")), interval=int(env("TASK_POLL_INTERVAL", "10")),
                before=before_pair)
    rp.update(find_rp(clients["console"], rp["id"]))  # 다음 단계를 위해 최신 상태로
    return True


def cmd_list(cc):
    rows = rp_list(cc)
    if not rows:
        log("복구 계획이 없습니다")
    for rp in rows:
        act, state, prog = rp_status(rp)
        print(f"{rp['id']}  {state:<8} 마지막동작={act or '-':<8} VM {rp.get('server_num')}대  "
              f"진행 {prog.get('succeed', 0)}/{prog.get('total', 0)} 실패 {prog.get('failed', 0)}  {rp['name']}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["list"] + list(PLAN))
    ap.add_argument("-p", "--plan", help="복구 계획 이름 또는 ID")
    ap.add_argument("--execute", action="store_true", help="실제 실행 (없으면 dry-run)")
    ap.add_argument("--confirm", help="failover/failback 시 복구 계획 이름을 그대로 입력")
    ap.add_argument("--keep", action="store_true", help="drill 후 정리하지 않음")
    ap.add_argument("--skip-precheck", action="store_true")
    ap.add_argument("--trust", default="", help="랩 검증용: 쉼표로 지정한 단계를 이번 실행에서만 verified로 취급")
    a = ap.parse_args()
    load_env()

    cc = ConsoleClient.from_env()
    clients = {"console": cc, "openapi": lambda: SCPClient.from_env()}
    if a.action == "list":
        return cmd_list(cc)
    if not a.plan:
        log("-p/--plan 필요 (./run.sh list 로 이름 확인)")
        return 1

    eps = load_endpoints()
    for t in filter(None, (x.strip() for x in a.trust.split(","))):
        if t in eps:
            eps[t]["verified"] = True
            log(f"[주의] '{t}' 단계를 이번 실행에서만 검증된 것으로 취급합니다 (--trust)")
    rp = find_rp(cc, a.plan)
    first = PLAN[a.action][0]
    need = (eps.get(first) or {}).get("require_state")
    if not a.skip_precheck and not check_rp(rp, need) and a.execute:
        log("사전 점검 FAIL - 중단합니다 (--skip-precheck로 무시 가능)")
        return 1

    steps = [s for s in PLAN[a.action] if not (a.keep and s in ("drill_cleanup", "clear_state"))]
    api_steps = [s for s in steps if s != "verify"]
    missing = [s for s in api_steps if s not in eps]
    unverified = [s for s in api_steps if s in eps and not eps[s].get("verified")]

    if not a.execute:
        log(f"[dry-run] {a.action} 실행 순서")
        for s in steps:
            ep = eps.get(s)
            if s == "verify":
                log("  - verify: VERIFY_TARGETS 포트 확인")
                continue
            tag = " (endpoints.json에 없음)" if not ep else ("" if ep.get("verified") else " (verified:false)")
            wait = f" -> 상태 {ep['wait']['until_state']} 대기" if ep and ep.get("wait") else ""
            log(f"  - {s}: {ep['method'] + ' ' + ep['path'] if ep else ''}{wait}{tag}")
            if ep and ep.get("body_builder") == "drill":
                body = build_drill_body(cc, rp, env("DRILL_NEED_SYNC", "0"), env("DRILL_RESOURCE_RESERVE", "0"))
                log("    자동 생성 본문: " + json.dumps(body, ensure_ascii=False))
        log("실제 실행: --execute")
        return 0

    if missing or unverified:
        log(f"실행 불가 - 미등록: {missing or '-'}, 미검증: {unverified or '-'}")
        return 1
    if a.action in DANGEROUS and a.confirm != rp["name"]:
        log(f"{a.action}은 --confirm '{rp['name']}' 로 복구 계획 이름을 정확히 입력해야 실행됩니다")
        return 1

    for s in steps:
        ok = run_step(clients, eps, s, rp)
        if not ok:
            log(f"{s} 단계 실패")
            if a.action == "drill" and not a.keep:
                log("검증 실패해도 드릴 환경은 정리합니다")
                run_step(clients, eps, "drill_cleanup", rp)
                run_step(clients, eps, "clear_state", rp)
            return 1
    log(f"{a.action} 완료")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SCPError, LookupError, RuntimeError, TimeoutError) as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(2)
