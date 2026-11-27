#!/usr/bin/env python3
"""Task 04 - aDR 복구 계획 드릴 / 정리 / Failover / Failback 실행기.

SCP 6.11.3 실측: 드릴·전환은 '복구 계획(Recovery Plan)' 단위로, 콘솔 API(4430 /admin/...)로 실행된다.
상태 추적은 GET /admin/view/dr-rp-list 의 status(action/state)와 task_progress 로 한다.
실행 API(경로·본문)는 endpoints.json 에 정의한다. 기본은 dry-run.
.env 의 ADR_PLAN 을 지정하면 -p 를 생략할 수 있다.
종료 코드: 0 성공 / 1 점검·검증 실패 또는 실행 거부 / 2 오류(API·인증·타임아웃) / 130 사용자 중단

./run.sh list                                        # 복구 계획 목록과 상태
./run.sh status   -p aDR-Auto-SCP-Test               # 한 계획의 현재 상태
./run.sh drill    -p aDR-Auto-SCP-Test --execute --step   # 단계마다 Enter로 진행 (시연용)
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
import time

from adr_common import build_drill_body, check_rp, find_rp, log, notify, rp_list, rp_status, wait_rp
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
STEP_DESC = {
    "drill_start": "드릴 시작 (DR 사이트에 테스트 VM 생성·기동)",
    "verify": "서비스 확인 (VERIFY_TARGETS 포트 응답)",
    "drill_cleanup": "테스트 종료 (드릴 VM 정리)",
    "clear_state": "상태 정리 (계획을 Ready로)",
    "failover": "Failover (DR 사이트로 전환)",
    "failback": "Failback (원본 사이트로 복귀)",
}
RESULT = {}


def write_result(**kw):
    """마지막 실행 결과를 LOG_DIR/last-result.json 에 남긴다 (webhook /status, 모니터링용)."""
    RESULT.update(kw)
    d = env("LOG_DIR", "") or os.path.join(HERE, "logs")
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "last-result.json"), "w", encoding="utf-8") as f:
            json.dump(RESULT, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def pause(step, enabled):
    if not enabled:
        return
    try:
        ans = input(f"\n>>> 다음 단계: {STEP_DESC.get(step, step)}  [Enter=진행 / s=건너뛰기 / q=중단] ")
    except EOFError:
        ans = ""
    ans = ans.strip().lower()
    if ans == "q":
        raise KeyboardInterrupt
    return ans == "s"


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
    need = ep.get("require_state")
    cur = (rp.get("status") or {}).get("state")
    if need and cur not in need:
        raise SCPError(f"{name}: 현재 상태 '{cur}'에서는 실행할 수 없습니다 (필요: {', '.join(need)})")
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
                before=before_pair, before_failed=(rp.get("task_progress") or {}).get("failed") or 0)
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


def cmd_status(cc, plan):
    rp = find_rp(cc, plan)
    act, state, prog = rp_status(rp)
    print(json.dumps({"id": rp["id"], "name": rp["name"], "state": state, "action": act,
                      "progress": prog, "vm": rp.get("server_num")}, ensure_ascii=False, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["list", "status"] + list(PLAN))
    ap.add_argument("-p", "--plan", help="복구 계획 이름 또는 ID")
    ap.add_argument("--execute", action="store_true", help="실제 실행 (없으면 dry-run)")
    ap.add_argument("--confirm", help="failover/failback 시 복구 계획 이름을 그대로 입력")
    ap.add_argument("--keep", action="store_true", help="drill 후 정리하지 않음")
    ap.add_argument("--step", action="store_true", help="단계마다 Enter를 눌러 진행 (시연·교육용)")
    ap.add_argument("--no-notify", action="store_true", help="이번 실행은 알림 보내지 않음")
    ap.add_argument("--skip-precheck", action="store_true")
    ap.add_argument("--trust", default="", help="랩 검증용: 쉼표로 지정한 단계를 이번 실행에서만 verified로 취급")
    a = ap.parse_args()
    load_env()

    cc = ConsoleClient.from_env()
    clients = {"console": cc, "openapi": lambda: SCPClient.from_env()}
    if a.action == "list":
        return cmd_list(cc)
    a.plan = a.plan or env("ADR_PLAN", "")
    if not a.plan:
        log("-p/--plan 필요 (또는 .env의 ADR_PLAN). ./run.sh list 로 이름 확인")
        return 1
    if a.action == "status":
        return cmd_status(cc, a.plan)
    return run_plan(a, cc, clients)


def run_plan(a, cc, clients):
    eps = load_endpoints()
    for t in filter(None, (x.strip() for x in a.trust.split(","))):
        if t in eps:
            eps[t]["verified"] = True
            log(f"[주의] '{t}' 단계를 이번 실행에서만 검증된 것으로 취급합니다 (--trust)")
    rp = find_rp(cc, a.plan)

    def refuse(msg):
        log(msg)
        if a.execute:
            write_result(action=a.action, plan=rp["name"], status="refused", exit_code=1, message=msg,
                         finished=time.strftime("%Y-%m-%d %H:%M:%S"))
            if not a.no_notify:
                notify(f"aDR {a.action} [{rp['name']}] 실행 안 함: {msg}", ok=False)
        return 1

    first = PLAN[a.action][0]
    need = (eps.get(first) or {}).get("require_state")
    if not a.skip_precheck and not check_rp(rp, need) and a.execute:
        act, state, _ = rp_status(rp)
        return refuse(f"사전 점검 FAIL (현재 상태 {state}/{act or '-'}) - 중단 (--skip-precheck로 무시 가능)")

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
        return refuse(f"실행 불가 - 미등록: {missing or '-'}, 미검증: {unverified or '-'}")
    if a.action in DANGEROUS and a.confirm != rp["name"]:
        return refuse(f"{a.action}은 --confirm '{rp['name']}' 로 복구 계획 이름을 정확히 입력해야 실행됩니다")

    t0 = time.time()
    done = []
    write_result(action=a.action, plan=rp["name"], started=time.strftime("%Y-%m-%d %H:%M:%S"),
                 status="running", steps=done)

    def finish(code, msg):
        took = int(time.time() - t0)
        write_result(status="success" if code == 0 else "failed", exit_code=code, message=msg,
                     finished=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=took)
        if not a.no_notify:
            notify(f"aDR {a.action} [{rp['name']}] {msg}\n단계: {' → '.join(done) or '-'}\n"
                   f"소요 {took // 60}분 {took % 60}초 · {socket.gethostname()}", ok=code == 0)
        return code

    try:
        for i, s in enumerate(steps, 1):
            if pause(s, a.step):
                log(f"[{i}/{len(steps)}] {s} 건너뜀")
                continue
            log(f"[{i}/{len(steps)}] {STEP_DESC.get(s, s)}")
            ok = run_step(clients, eps, s, rp)
            if not ok:
                log(f"{s} 단계 실패")
                if a.action == "drill" and not a.keep:
                    log("검증 실패해도 드릴 환경은 정리합니다")
                    run_step(clients, eps, "drill_cleanup", rp)
                    run_step(clients, eps, "clear_state", rp)
                    done.extend(["drill_cleanup", "clear_state"])
                return finish(1, f"{s} 단계 실패")
            done.append(s)
    except KeyboardInterrupt:
        log("사용자가 중단했습니다. 현재 상태: ./run.sh status / 정리: ./run.sh cleanup --execute")
        return finish(130, "사용자 중단")
    except (SCPError, LookupError, RuntimeError, TimeoutError) as e:
        log(f"오류: {e}")
        return finish(2, f"오류: {e}")
    log(f"{a.action} 완료")
    return finish(0, "완료")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (SCPError, LookupError, RuntimeError, TimeoutError) as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(2)
