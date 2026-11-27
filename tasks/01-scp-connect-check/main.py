#!/usr/bin/env python3
"""Task 01 - SCP 접속·인증 점검.

./run.sh            # .env 설정으로 접속, 인증, 버전, 리소스 풀, DR 정책 API까지 확인
./run.sh --raw      # 응답 원문(JSON)도 출력
./run.sh --console  # 콘솔 내부 API(4430) 인증 방식 점검 (aDR 드릴용)
./run.sh --get /admin/view/running-ulog-list          # 콘솔 조회 API 응답 보기 (GET만)
./run.sh --get /admin/view/dr-rp-list -q start=0 -q limit=50
./run.sh --csrf-probe   # 콘솔 변경 요청용 CSRF 토큰을 어디서 받는지 진단 (상태 변경 없음)
./run.sh --console-login  # 콘솔 로그인(/ticket) + 쓰기 권한(CSRF) 점검. 암호화 방식 최대 2가지 시도
"""
import argparse
import json
import re
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
    ap.add_argument("--get", metavar="PATH", help="콘솔 조회 API(GET) 응답 출력 (예: /admin/view/dr-rp-list)")
    ap.add_argument("-q", action="append", default=[], metavar="KEY=VALUE", help="--get 쿼리 파라미터")
    ap.add_argument("-o", "--out", help="--get 응답을 파일로 저장")
    ap.add_argument("--csrf-probe", action="store_true", help="콘솔 CSRF 토큰 발급 위치 진단")
    ap.add_argument("--console-login", action="store_true", help="콘솔 /ticket 로그인 + 쓰기(CSRF) 점검")
    a = ap.parse_args()
    load_env()
    if a.get:
        sys.exit(console_get(a.get, a.q, a.out))
    if a.csrf_probe:
        sys.exit(csrf_probe())
    if a.console_login:
        sys.exit(console_login_probe())
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


def console_get(path, qs, out=None):
    """읽기 전용 탐색용: 콘솔 GET API를 불러 JSON을 그대로 출력한다."""
    if not path.startswith("/"):
        path = "/" + path
    params = dict(q.split("=", 1) for q in qs) or None
    c = ConsoleClient.from_env()
    d = c.request("GET", path, params=params)
    text = json.dumps(d, ensure_ascii=False, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"저장: {out} ({len(text)} bytes)")
    else:
        print(text)
    return 0


def _shape(o, depth=0):
    """값은 가리고 구조(키 이름)만 보여준다."""
    if isinstance(o, dict):
        return {k: _shape(v, depth + 1) if depth < 4 else "…" for k, v in o.items()}
    if isinstance(o, list):
        return [_shape(o[0], depth + 1)] if o else []
    if isinstance(o, str):
        return f"<str {len(o)}>"
    return type(o).__name__


def csrf_probe():
    """후보 위치마다 CSRF 관련 쿠키·헤더·응답 필드가 나오는지 본다. 값은 가린다."""
    import requests
    host = env("SCP_HOST", required=True)
    pu = urllib.parse.urlparse(host if host.startswith("http") else "https://" + host)
    h, scheme = pu.hostname, pu.scheme
    port = env("CONSOLE_PORT", "4430")
    s = requests.Session()
    s.verify = env("SCP_VERIFY_TLS", "0") == "1"

    def show(label, r):
        names = sorted(set(r.cookies.keys()))
        hdr = {k: v for k, v in r.headers.items() if "csrf" in k.lower() or "token" in k.lower() or k.lower() == "set-cookie"}
        print(f"\n== {label}: HTTP {r.status_code}")
        print(f"   Set-Cookie 이름: {names or '-'}")
        for k, v in hdr.items():
            print(f"   헤더 {k}: " + re.sub(r"=([^;]{6})[^;]*", r"=\1…", v)[:300])
        try:
            j = r.json()
            text = json.dumps(_shape(j), ensure_ascii=False)
            print("   응답 구조: " + text[:1500])
        except ValueError:
            body = r.text
            hits = re.findall(r"(?i)[^\n]{0,40}csrf[^\n]{0,60}", body)[:5]
            print(f"   응답: HTML/텍스트 {len(body)}자" + (", csrf 언급: " + " | ".join(re.sub(r"([\"'=:]\s*[\"']?)([A-Za-z0-9_-]{4})[A-Za-z0-9_-]+", r"\1\2…", x.strip())[:100] for x in hits) if hits else ""))

    import re
    c = SCPClient(host, auth="token", username=env("SCP_USER"), password=env("SCP_PASS"),
                  verify=s.verify)
    # 1) OpenAPI v2 로그인 응답 전체 구조
    from binascii import a2b_hex
    from Crypto.Cipher import PKCS1_OAEP
    from Crypto.PublicKey import RSA
    from Crypto.Util.number import bytes_to_long
    r = s.get(c.base + "/janus/v2/public-key", timeout=30)
    b = r.json()
    mod = b.get("public_key") or (b.get("data") or {}).get("public_key")
    enc = PKCS1_OAEP.new(RSA.construct((bytes_to_long(a2b_hex(mod)), 0x10001))).encrypt(env("SCP_PASS").encode()).hex()
    r = s.post(c.base + "/janus/v2/authenticate", json={"auth": {"passwordCredentials": {"username": env("SCP_USER"), "password": enc}}}, timeout=30)
    show("1. OpenAPI 로그인 /janus/v2/authenticate", r)
    tok = r.json()["data"]["access"]["token"]["id"]

    base = f"{scheme}://{h}:{port}"
    s.cookies.set("aCMPAuthToken", tok)
    s.cookies.set("login", "local")
    common = {"Client_token": tok, "X-Requested-With": "XMLHttpRequest", "Referer": base + "/"}
    show("2. 콘솔 첫 페이지 GET /", s.get(base + "/", headers=common, timeout=30))
    show("3. 콘솔 조회 GET /admin/view/dr-rp-list", s.get(base + "/admin/view/dr-rp-list", params={"start": 0, "limit": 1}, headers=common, timeout=30))
    for path in ("/admin/users/self", "/admin/tokens/self", "/admin/tokens"):
        show(f"4. 후보 GET {path}", s.get(base + path, headers=common, timeout=30))
    show("5. 세션 연장 POST /admin/tokens/extend-expiration (상태 변경 아님)",
         s.post(base + "/admin/tokens/extend-expiration", headers=dict(common, **{"Content-Type": "application/json"}), data="{}", timeout=30))
    print("\n세션 쿠키 이름 전체:", sorted(set(s.cookies.keys())))
    return 0


def console_login_probe():
    """콘솔 /ticket 로그인 방식을 찾고, 쓰기 요청이 CSRF를 통과하는지 확인한다.
    로그인 실패가 쌓이면 계정이 잠길 수 있어 최대 2가지 방식만 시도한다."""
    user, pw = env("SCP_USER"), env("SCP_PASS")
    if not (user and pw):
        print("[FAIL] .env에 SCP_USER/SCP_PASS가 필요합니다")
        return 1
    fixed = env("CONSOLE_LOGIN_ENC")
    modes = [fixed] if fixed else ["v1-pkcs1", "v2-oaep"]
    for mode in modes:
        c = ConsoleClient(env("SCP_HOST"), port=int(env("CONSOLE_PORT", "4430")),
                          verify=env("SCP_VERIFY_TLS", "0") == "1")
        try:
            d = c.login_ticket(user, pw, mode)
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] 로그인 방식 {mode}: {e}")
            continue
        print(f"[OK]   콘솔 로그인 성공 (방식 {mode}, 사용자 {d.get('username')}, 접속 IP {d.get('client_ip')})")
        try:
            c.request("GET", "/admin/view/dr-rp-list", params={"start": 0, "limit": 1})
            print("[OK]   조회(GET) 동작")
            c.request("POST", "/admin/tokens/extend-expiration", body={})
            print("[OK]   쓰기 요청 CSRF 통과 (세션 연장 POST, 상태 변경 없음)")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] 로그인 후 요청 실패: {e}")
            return 1
        print(f"\n결과: .env에 아래 두 줄을 넣으세요\n  CONSOLE_TOKEN_SOURCE=ticket\n  CONSOLE_LOGIN_ENC={mode}")
        return 0
    print("\n결과: 콘솔 로그인 실패. 계정 잠금 방지를 위해 더 시도하지 않습니다."
          "\n      비밀번호 확인 후, 브라우저 로그인 직전 GET 요청 중 'key'가 들어간 요청 이름을 알려주세요.")
    return 1


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
