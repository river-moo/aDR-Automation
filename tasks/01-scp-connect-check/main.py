#!/usr/bin/env python3
"""Task 01 - SCP 접속·인증 점검.

./run.sh            # .env 설정으로 접속, 인증, 버전, 리소스 풀, DR 정책 API까지 확인
./run.sh --raw      # 응답 원문(JSON)도 출력
"""
import argparse
import json
import socket
import sys
import urllib.parse

from scp_client import SCPClient, SCPError, env, load_env


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
    a = ap.parse_args()
    load_env()

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

    # EC2 서명에서 쿼리스트링 포함 여부 자동 판별
    if c.mode == "ec2" and azs is None and ver is not None:
        print("       쿼리스트링을 서명에서 빼고 다시 시도합니다 (SCP_EC2_SIGN_QUERY=0)")
        c.s.auth.sign_query = False
        azs = step("리소스 풀 조회 (재시도)", c.list_azs, a.raw)
        if azs is not None:
            print("       -> .env에 SCP_EC2_SIGN_QUERY=0 으로 설정하세요")

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


if __name__ == "__main__":
    try:
        main()
    except SCPError as e:
        sys.exit(f"오류: {e}")
