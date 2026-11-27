#!/usr/bin/env python3
"""Task 03 - aDR 사전 점검 (읽기 전용, 공식 OpenAPI만 사용).

./run.sh                 # 모든 DR 정책 점검
./run.sh -p ERP-DR       # 정책 이름 또는 ID 하나만
./run.sh --no-report     # 리포트 파일 저장 안 함

결과: reports/precheck-YYYYmmdd-HHMMSS.md / .json
종료코드: 0 전부 PASS, 1 FAIL 있음, 2 오류
"""
import argparse
import json
import os
import sys
import time

from adr_common import check_policy, find_policy, log
from scp_client import SCPClient, SCPError, env, load_env


def to_md(results, host):
    lines = [f"# aDR 사전 점검 리포트", "",
             f"- SCP: `{host}`", f"- 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 정책 {len(results)}개, PASS {sum(r['result'] == 'PASS' for r in results)}개", ""]
    for r in results:
        lines += [f"## {r['name']} — {r['result']}", "",
                  f"- 유형 `{r['type']}`, 활성 `{r['enable']}`, ID `{r['id']}`", "",
                  "| 우선순위 | VM | 상태 | 정책 내 활성 |", "|---|---|---|---|"]
        for s in r.get("servers", []):
            lines.append(f"| {s['priority']} | {s['name']} | {s['status']} | {s['enable']} |")
        lines += ["", "| 결과 | 내용 |", "|---|---|"]
        lines += [f"| {c['level']} | {c['msg']} |" for c in r["checks"]]
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--policy", help="정책 이름 또는 ID (생략 시 전체)")
    ap.add_argument("--no-report", action="store_true")
    a = ap.parse_args()
    load_env()
    c = SCPClient.from_env()

    policies = [find_policy(c, a.policy)] if a.policy else c.list_protections()
    if not policies:
        log("DR 정책이 없습니다")
        return 1
    results = []
    for p in policies:
        _, r = check_policy(c, p)
        results.append(r)

    failed = [r["name"] for r in results if r["result"] != "PASS"]
    log(f"요약: {len(results)}개 중 PASS {len(results) - len(failed)}개" + (f", FAIL: {', '.join(failed)}" if failed else ""))

    if not a.no_report:
        rdir = env("REPORT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports"))
        os.makedirs(rdir, exist_ok=True)
        stem = os.path.join(rdir, time.strftime("precheck-%Y%m%d-%H%M%S"))
        with open(stem + ".md", "w", encoding="utf-8") as f:
            f.write(to_md(results, env("SCP_HOST")))
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log(f"리포트: {stem}.md")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SCPError, LookupError) as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(2)
