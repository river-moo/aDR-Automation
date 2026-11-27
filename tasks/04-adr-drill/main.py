#!/usr/bin/env python3
"""Task 04 - aDR 드릴 / Failover / Failback 실행기.

공식 OpenAPI에 없는 동작은 Task 02로 캡처해서 endpoints.json에 채운 뒤 사용한다.
기본은 dry-run(계획만 출력). 실제 실행은 --execute.

./run.sh drill    -p ERP-DR                  # 드릴 계획만 출력
./run.sh drill    -p ERP-DR --execute        # 사전점검 -> 드릴 시작 -> 대기 -> 검증 -> 정리
./run.sh drill    -p ERP-DR --execute --keep # 드릴 VM을 정리하지 않고 남김
./run.sh cleanup  -p ERP-DR --execute        # 남겨둔 드릴 정리만
./run.sh failover -p ERP-DR --execute --confirm ERP-DR
./run.sh failback -p ERP-DR --execute --confirm ERP-DR
"""
import argparse
import os
import socket
import sys

from adr_common import check_policy, find_policy, log
from scp_client import SCPClient, SCPError, env, load_env

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = {
    "drill": ["drill_start", "verify", "drill_cleanup"],
    "cleanup": ["drill_cleanup"],
    "failover": ["failover", "verify"],
    "failback": ["failback", "verify"],
}
DANGEROUS = {"failover", "failback"}


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


def run_step(c, name, policy):
    if name == "verify":
        return verify_targets()
    ep = c.internal[name]
    log(f"{name}: {ep['method']} {ep['path']}")
    resp = c.call_internal(name, protection_id=policy["id"], policy_name=policy["name"])
    if ep.get("async"):
        field = ep.get("task_id_field", "task_id")
        task_id = resp.get(field) if isinstance(resp, dict) else None
        if not task_id:
            raise SCPError(f"{name} 응답에 '{field}'가 없습니다: {str(resp)[:300]}")
        c.wait_task(task_id, timeout=int(env("TASK_TIMEOUT", "3600")),
                    interval=int(env("TASK_POLL_INTERVAL", "10")), log=log)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=list(PLAN))
    ap.add_argument("-p", "--policy", required=True, help="정책 이름 또는 ID")
    ap.add_argument("--execute", action="store_true", help="실제 실행 (없으면 dry-run)")
    ap.add_argument("--confirm", help="failover/failback 시 정책 이름을 그대로 입력")
    ap.add_argument("--keep", action="store_true", help="drill 후 정리하지 않음")
    ap.add_argument("--skip-precheck", action="store_true")
    a = ap.parse_args()
    load_env()

    c = SCPClient.from_env()
    c.load_internal(env("ENDPOINTS_FILE", os.path.join(HERE, "endpoints.json")))
    policy = find_policy(c, a.policy)

    if not a.skip_precheck:
        ok, _ = check_policy(c, policy)
        if not ok:
            log("사전 점검 FAIL - 중단합니다 (--skip-precheck로 무시 가능)")
            return 1

    steps = [s for s in PLAN[a.action] if not (a.keep and s == "drill_cleanup")]
    api_steps = [s for s in steps if s != "verify"]
    missing = [s for s in api_steps if s not in c.internal]
    unverified = [s for s in api_steps if s in c.internal and not c.internal[s].get("verified")]

    if not a.execute:
        log(f"[dry-run] {a.action} 실행 순서")
        for s in steps:
            ep = c.internal.get(s)
            state = "" if s == "verify" else (" (endpoints.json에 없음)" if not ep else
                                               "" if ep.get("verified") else " (verified:false)")
            log(f"  - {s}: {ep['method'] + ' ' + ep['path'] if ep else 'VERIFY_TARGETS 포트 확인'}{state}")
        log("실제 실행: --execute")
        return 0

    if missing or unverified:
        log(f"실행 불가 - 미등록: {missing or '-'}, 미검증: {unverified or '-'}")
        return 1
    if a.action in DANGEROUS and a.confirm != policy["name"]:
        log(f"{a.action}은 --confirm '{policy['name']}' 로 정책 이름을 정확히 입력해야 실행됩니다")
        return 1

    for s in steps:
        if not run_step(c, s, policy):
            log(f"{s} 단계 실패")
            if a.action == "drill" and not a.keep:
                log("검증 실패해도 드릴 환경은 정리합니다")
                run_step(c, "drill_cleanup", policy)
            return 1
    log(f"{a.action} 완료")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SCPError, LookupError) as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(2)
