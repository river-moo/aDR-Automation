#!/usr/bin/env python3
"""Task 01 - SCP 접속·인증 점검.

./run.sh            # .env 설정으로 접속, 인증, 버전, 리소스 풀, DR 정책 API까지 확인
./run.sh --raw      # 응답 원문(JSON)도 출력
./run.sh --console  # 콘솔 내부 API(4430) 인증 방식 점검 (aDR 드릴용)
"""
import argparse
import json
import socket
import sys
import urllib.parse

from scp_client import ConsoleClient, SCPClient, SCPError, env, load_env


def step(title, fn, raw=False):
    try:
        r = fn()
        print(f"[OK]   {title}")
        if raw:
            print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
        return r
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {title}: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--console", action="store_true", help="콘솔 내부 API(4430) 인증 점검")
    a = ap.parse_args()
    load_env()
    if a.console:
        sys.exit(console_probe(a.raw))

    host = env("SCP_HOST", required=True)
    u = urllib.parse.urlparse(host if host.startswith("http") else "https://" + host)
    port = u.port or 443
    print(f"대상: {u.hostname}:{port}  인증: {env('SCP_AUTH', 'auto')}")

    # 1) TCP 연결
    try:
        socket.create_connection((u.hostname, port), timeout=5).close()
        print(f"[OK]   TCP {u.hostname}:{port} 연결")
    except OSError as e:
        print(f"[FAIL] TCP {u.hostname}:{port} 연결 불가: {e}")
        print("       -> 방화벽, 라우팅, SCP_HOST 값을 확인하세요")
        sys.exit(2)

    c = SCPClient.from_env()
    if c.mode == "token":
        if not step("토큰 로그인", c.login):
            sys.exit(3)

    ver = step("SCP 버전 조회 (/janus/20180725/system/version)", c.version, a.raw)
    azs = step("리소스 풀 조회 (/janus/20180725/azs)", c.list_azs, a.raw)

    # EC2 서명에서 쿼리스트링 포함 여부 자동 판별 (6.11.3 실측 기본값은 0)
    if c.mode == "ec2" and azs is None and ver is not None:
        flip = not c.s.auth.sign_query
        print(f"       쿼리스트링 서명 방식을 바꿔 다시 시도합니다 (SCP_EC2_SIGN_QUERY={int(flip)})")
        c.s.auth.sign_query = flip
        azs = step("리소스 풀 조회 (재시도)", c.list_azs, a.raw)
        if azs is not None:
            print(f"       -> .env에 SCP_EC2_SIGN_QUERY={int(flip)} 으로 설정하세요")

    if azs:
        for z in azs:
            print(f"         - {z.get('id')}  {z.get('name')}  type={z.get('type')}")

    pols = step("DR 정책 조회 (/janus/20240725/protections, 6.11.1+)", c.list_protections, a.raw)
    if pols is not None:
        print(f"         DR 정책 {len(pols)}개")
        for p in pols:
            print(f"         - {p.get('id')}  {p.get('type')}  {p.get('name')}")

    ok = ver is not None and azs is not None
    print("\n결과:", "정상 - 다음 태스크 진행 가능" if ok else "실패 - 위 [FAIL] 항목 확인")
    if not ok and c.mode == "ec2":
        print("힌트: AK/SK가 맞는지, SCP 시각과 이 서버 시각이 맞는지(NTP) 확인하세요. 서명은 시간에 민감합니다.")
    sys.exit(0 if ok else 1)


def console_probe(raw=False):
    """콘솔 API에 어떤 토큰이 통하는지 확인하고 .env에 넣을 값을 알려준다."""
    port = int(env("CONSOLE_PORT", "4430"))
    print(f"콘솔 API 점검: {env('SCP_HOST')}:{port} /admin/view/dr-protection-list")
    tried = []

    def attempt(label, make):
        try:
            c = make()
            d = c.dr_protection_list()
            print(f"[OK]   {label}")
            if raw:
                print(json.dumps(d, ensure_ascii=False, indent=2)[:3000])
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {label}: {e}")
            tried.append(label)
            return False

    if env("SCP_USER") and env("SCP_PASS"):
        if attempt("OpenAPI 토큰(/janus/v2/authenticate)을 콘솔 토큰으로 사용", lambda: ConsoleClient.from_env_with("janus")):
            print("\n결과: 자동 로그인 가능 -> .env에 CONSOLE_TOKEN_SOURCE=janus (SCP_USER/SCP_PASS 필요)")
            return 0
    else:
        print("[SKIP] SCP_USER/SCP_PASS가 비어 있어 OpenAPI 토큰 방식은 건너뜀 (.env에 admin 계정 입력 후 재시도)")

    if env("CONSOLE_TOKEN"):
        if attempt("브라우저에서 복사한 CONSOLE_TOKEN 사용", lambda: ConsoleClient.from_env_with("manual")):
            print("\n결과: 수동 토큰은 동작 -> 자동화하려면 콘솔 로그인 캡처(00_login.har)가 필요합니다")
            return 0
    else:
        print("[SKIP] CONSOLE_TOKEN 비어 있음 (브라우저 쿠키 aCMPAuthToken 값을 넣으면 수동 방식 점검)")

    print("\n결과: 콘솔 API 인증 방법을 아직 못 찾음 -> 콘솔 로그인 과정을 HAR로 캡처해 주세요")
    return 1


if __name__ == "__main__":
    try:
        main()
    except SCPError as e:
        sys.exit(f"오류: {e}")
