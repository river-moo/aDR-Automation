"""Sangfor SCP OpenAPI 공통 클라이언트 (SCP 6.11.3 OpenAPI 문서 P20260430 기준).

인증 (SCP_AUTH 값):
  ec2   : AK/SK로 AWS4-HMAC-SHA256 서명 (문서 권장 방식, 6.3.0+)
  token : 계정/비밀번호로 토큰 발급 (v2 -> v1 순서로 시도), 24시간 유효
  auto  : AK/SK가 있으면 ec2, 없으면 token
"""
import datetime
import hashlib
import hmac
import json
import os
import string
import time
import urllib.parse
import uuid

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TASK_DONE = {"finish"}
TASK_FAILED = {"failure", "canceled"}


class SCPError(RuntimeError):
    pass


# ---------------------------------------------------------------- .env 로더
def load_env(path=None):
    """KEY=VALUE 형식의 .env를 읽어 os.environ에 넣는다 (이미 설정된 값은 유지).
    run.sh가 SCP_ENV_FILE에 태스크 폴더의 .env 경로를 넣어준다."""
    path = path or os.environ.get("SCP_ENV_FILE", ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            os.environ.setdefault(k.strip(), v)


def env(name, default=None, required=False):
    v = os.environ.get(name) or default  # 빈 값(KEY=)은 기본값으로
    if required and not v:
        raise SCPError(f".env에 {name} 값이 없습니다")
    return v


# ---------------------------------------------------------------- EC2 서명
def _quote_qs(params):
    pairs = []
    for k in sorted(params):
        v = params[k]
        v = v if isinstance(v, str) else str(v)
        pairs.append(urllib.parse.quote(k, safe="") + "=" + urllib.parse.quote(v, safe="-_~"))
    return "&".join(pairs)


class EC2Auth(requests.auth.AuthBase):
    """SCP 문서 2.6.1.2 예제(EC2RequestAuth + keystone Ec2Signer v4)를 그대로 옮긴 것."""

    SIGNED_HEADERS = "cookie;x-amz-date"

    def __init__(self, ak, sk, region="cn-south-1", service="sdk-api", sign_query=False):
        self.ak, self.sk = ak, sk.encode()
        self.region, self.service = region, service
        self.sign_query = sign_query

    @staticmethod
    def _h(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    def __call__(self, r):
        t = datetime.datetime.utcnow()
        amzdate, datestamp = t.strftime("%Y%m%dT%H%M%SZ"), t.strftime("%Y%m%d")
        scope = f"{datestamp}/{self.region}/{self.service}/aws4_request"
        r.headers["X-Amz-Date"] = amzdate
        u = urllib.parse.urlparse(r.url)
        params = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True)) if self.sign_query else {}
        canon_qs = "" if r.method.upper() == "POST" else _quote_qs(params)
        lower = {k.lower().strip(): str(v).strip() for k, v in r.headers.items()}
        canon_headers = "".join(f"{h}:{lower[h]}\n" for h in self.SIGNED_HEADERS.split(";") if h in lower)
        body = r.body or b""
        body = body.encode() if isinstance(body, str) else body
        cr = "\n".join([r.method.upper(), u.path, canon_qs, canon_headers,
                        self.SIGNED_HEADERS, hashlib.sha256(body).hexdigest()])
        sts = "\n".join(["AWS4-HMAC-SHA256", amzdate, scope, hashlib.sha256(cr.encode()).hexdigest()])
        k = self._h(b"AWS4" + self.sk, datestamp)
        for part in (self.region, self.service, "aws4_request"):
            k = self._h(k, part)
        sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
        r.headers["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={self.ak}/{scope}, "
                                      f"SignedHeaders={self.SIGNED_HEADERS}, Signature={sig}")
        return r


# ---------------------------------------------------------------- 클라이언트
class SCPClient:
    def __init__(self, host, auth="auto", ak=None, sk=None, username=None, password=None,
                 region="cn-south-1", service="sdk-api", sign_query=False, verify=False, timeout=30):
        self.base = host if host.startswith("http") else f"https://{host}"
        self.timeout = timeout
        self.s = requests.Session()
        self.s.verify = verify
        self.s.headers.update({"Content-Type": "application/json",
                               "Cookie": f"aCMPAuthToken={uuid.uuid4().hex}"})
        self.mode = auth if auth != "auto" else ("ec2" if ak and sk else "token")
        self.username, self.password = username, password
        self.token_expires = 0
        self.internal = {}
        if self.mode == "ec2":
            if not (ak and sk):
                raise SCPError("SCP_AUTH=ec2 인데 SCP_AK/SCP_SK가 비어 있습니다")
            self.s.auth = EC2Auth(ak, sk, region, service, sign_query)
        elif not (username and password):
            raise SCPError("SCP_AUTH=token 인데 SCP_USER/SCP_PASS가 비어 있습니다")

    @classmethod
    def from_env(cls):
        return cls(env("SCP_HOST", required=True), auth=env("SCP_AUTH", "auto"),
                   ak=env("SCP_AK"), sk=env("SCP_SK"),
                   username=env("SCP_USER"), password=env("SCP_PASS"),
                   region=env("SCP_EC2_REGION", "cn-south-1"), service=env("SCP_EC2_SERVICE", "sdk-api"),
                   sign_query=env("SCP_EC2_SIGN_QUERY", "0") == "1",
                   verify=env("SCP_VERIFY_TLS", "0") == "1", timeout=int(env("SCP_TIMEOUT", "30")))

    # -------- 토큰 인증
    def login(self):
        from binascii import a2b_hex
        from Crypto.Cipher import PKCS1_OAEP, PKCS1_v1_5
        from Crypto.PublicKey import RSA
        from Crypto.Util.number import bytes_to_long
        errors = []
        for ver, prefix in (("v2", "/janus/v2"), ("v1", "/janus")):
            try:
                r = self.s.get(self.base + prefix + "/public-key", timeout=self.timeout)
                r.raise_for_status()
                b = r.json()
                mod = (b.get("public_key") or (b.get("data") or {}).get("public_key") or "").strip()
                mod = "0" + mod if len(mod) % 2 else mod
                pub = RSA.construct((bytes_to_long(a2b_hex(mod)), 0x10001)).publickey()
                cipher = PKCS1_OAEP.new(pub) if ver == "v2" else PKCS1_v1_5.new(pub)
                enc = cipher.encrypt(self.password.encode()).hex()
                body = {"auth": {"passwordCredentials": {"username": self.username, "password": enc}}}
                r = self.s.post(self.base + prefix + "/authenticate", json=body, timeout=self.timeout)
                r.raise_for_status()
                tok = r.json()["data"]["access"]["token"]["id"]
                self.s.headers["Authorization"] = f"Token {tok}"
                self.token_expires = time.time() + 23 * 3600
                return ver
            except Exception as e:  # noqa: BLE001
                errors.append(f"{ver}: {e}")
        raise SCPError("토큰 로그인 실패 - " + " / ".join(errors))

    # -------- 공통 호출
    def request(self, method, path, params=None, body=None):
        if self.mode == "token" and time.time() > self.token_expires:
            self.login()
        try:
            r = self.s.request(method, self.base + path, params=params,
                               data=json.dumps(body) if body is not None else None, timeout=self.timeout)
        except requests.RequestException as e:
            raise SCPError(f"{method} {path} 접속 실패: {e}")
        if r.status_code == 204 or not r.content:
            if r.status_code >= 400:
                raise SCPError(f"{method} {path} -> HTTP {r.status_code}")
            return {}
        try:
            data = r.json()
        except ValueError:
            raise SCPError(f"{method} {path} -> HTTP {r.status_code}, JSON 아님: {r.text[:200]}")
        bad = data.get("code") not in (None, 0, "0") or data.get("errcode") not in (None, "", 0, "0")
        if r.status_code >= 400 or bad:
            raise SCPError(f"{method} {path} -> HTTP {r.status_code}: {data.get('message') or data}")
        return data.get("data", data) if isinstance(data, dict) else data

    def list_all(self, path, params=None, limit=10000):
        params = dict(params or {}, page_num=0, page_size=100)
        items = []
        while len(items) < limit:
            d = self.request("GET", path, params=params)
            if isinstance(d, list):
                return d
            items.extend(d.get("data", []))
            nxt = d.get("next_page_num")
            if nxt in ("", None):
                break
            params["page_num"] = nxt
        return items

    # -------- 문서화된 API
    def version(self):
        return self.request("GET", "/janus/20180725/system/version")

    def list_azs(self):
        return self.list_all("/janus/20180725/azs")

    def list_protections(self, **filters):
        """DR 정책 목록 (6.11.1+). type: cdp_disaster / backup_disaster / vmware_disaster"""
        return self.list_all("/janus/20240725/protections", filters)

    def list_protected_servers(self, protection_id=None):
        p = {"in_protection": 1}
        if protection_id:
            p["protection_id"] = protection_id
        return self.list_all("/janus/20220725/servers", p)

    def site_metrics(self, object_id):
        return self.request("GET", f"/janus/20180725/metrics/{object_id}", params={"object_type": "disaster"})

    def get_task(self, task_id):
        return self.request("GET", f"/janus/20180725/tasks/{task_id}")

    def wait_task(self, task_id, timeout=3600, interval=10, log=print):
        end = time.time() + timeout
        while time.time() < end:
            t = self.get_task(task_id)
            log(f"  task {task_id}: {t.get('status')} {t.get('progress')}%")
            if t.get("status") in TASK_DONE:
                return t
            if t.get("status") in TASK_FAILED:
                raise SCPError(f"작업 실패: {t.get('description')} ({t.get('status')})")
            time.sleep(interval)
        raise SCPError(f"작업 대기 시간 초과: {task_id}")

    # -------- 캡처한 내부 API (endpoints.json)
    def load_internal(self, path="endpoints.json"):
        with open(path, encoding="utf-8") as f:
            self.internal = {k: v for k, v in json.load(f)["endpoints"].items() if not k.startswith("_")}
        return self.internal

    def call_internal(self, name, **vars_):
        ep = self.internal.get(name)
        if not ep:
            raise SCPError(f"endpoints.json에 '{name}' 항목이 없습니다")
        return call_endpoint(self, ep, name, **vars_)


def call_endpoint(client, ep, name, **vars_):
    """endpoints.json 항목 하나를 호출. path/body/query의 ${변수}를 치환한다."""
    if not ep.get("verified"):
        raise SCPError(f"'{name}'은 아직 검증되지 않은 엔드포인트입니다 (verified: true 필요)")
    sub = lambda s: string.Template(s).substitute(vars_)  # noqa: E731
    body = ep.get("body")
    if body is not None:
        body = json.loads(sub(json.dumps(body)))
    params = {k: sub(str(v)) for k, v in (ep.get("query") or {}).items()} or None
    return client.request(ep["method"], sub(ep["path"]), params=params, body=body)


# ---------------------------------------------------------------- 콘솔(4430) 세션
class ConsoleClient:
    """SCP 웹 콘솔 내부 API (https://HOST:4430/admin/...) 호출용.

    콘솔 요청 형태 (6.11.3 캡처):
      Cookie: aCMPAuthToken=<토큰>; CSRFPreventionToken=<csrf>; login=local
      Client_token: <토큰>             (aCMPAuthToken과 같은 값)
      Csrfpreventiontoken: <csrf>      (쿠키와 같은 값)
      X-Requested-With: XMLHttpRequest
    토큰 얻는 방법 (CONSOLE_TOKEN_SOURCE):
      ticket : 콘솔과 같은 로그인(POST /ticket) - 조회·변경 모두 가능 (기본)
      janus  : OpenAPI 토큰 로그인 결과를 재사용 - 조회(GET)만 가능, 변경 요청은 CSRF 거부
      manual : 브라우저에서 복사한 CONSOLE_TOKEN / CONSOLE_CSRF 사용 (테스트용, 세션 만료 시 갱신)
    """

    def __init__(self, host, port=4430, token=None, csrf=None, verify=False, timeout=30):
        pu = urllib.parse.urlparse(host if host.startswith("http") else "https://" + host)
        self.base = f"{pu.scheme}://{pu.hostname}:{port}"
        self.api_base = f"{pu.scheme}://{pu.netloc}"  # 공개키는 OpenAPI(기본 443) 쪽
        self.timeout = timeout
        self.s = requests.Session()
        self.s.verify = verify
        self.set_token(token, csrf)

    def set_token(self, token, csrf=None, keep_cookies=False):
        self.token = token
        self.csrf = csrf or uuid.uuid4().hex  # 조회(GET)는 임의 값도 통과, 변경 요청은 ticket 로그인 값 필요
        self.s.headers.update({"Content-Type": "application/json; charset=utf-8",
                               "X-Requested-With": "XMLHttpRequest",
                               "Client_token": token or "", "Csrfpreventiontoken": self.csrf, "Sid": "",
                               "Referer": self.base + "/"})
        if not keep_cookies:
            self.s.cookies.clear()
        for k, v in (("aCMPAuthToken", token or ""), ("CSRFPreventionToken", self.csrf),
                     ("login", "local"), ("language", "en_US")):
            self.s.cookies.set(k, v)

    # -------- 콘솔 로그인 (6.11.3 실측: POST /ticket, 폼 형식)
    #   본문: username, password(RSA 암호화 16진수), status=agree, user_login=true
    #   응답: data.client_token(=aCMPAuthToken), data.CSRFPreventionToken
    ENC_MODES = {
        "page-pkcs1": ("page", "pkcs1"),   # 6.11.3 실측: 로그인 화면 HTML의 RSAModulus
        "v2-oaep": ("/janus/v2/public-key", "oaep"),
        "v1-pkcs1": ("/janus/public-key", "pkcs1"),
        "v2-pkcs1": ("/janus/v2/public-key", "pkcs1"),
        "v1-oaep": ("/janus/public-key", "oaep"),
    }

    def _encrypt(self, plaintext, mode):
        from binascii import a2b_hex
        from Crypto.Cipher import PKCS1_OAEP, PKCS1_v1_5
        from Crypto.PublicKey import RSA
        from Crypto.Util.number import bytes_to_long
        import re
        key_path, pad = self.ENC_MODES[mode]
        exp = 0x10001
        if key_path == "page":
            html = self.login_page or ""
            m = re.search(r"RSAModulus\s*[:=]\s*['\"]([0-9A-Fa-f]+)['\"]", html)
            if not m:
                raise SCPError("[console] 로그인 화면에서 RSAModulus를 찾지 못했습니다")
            mod = m.group(1)
            e = re.search(r"RSAExponent\s*[:=]\s*['\"]?([0-9A-Fa-fx]+)['\"]?", html)
            if e:
                v = e.group(1).lower()
                exp = int(v, 16) if (v.startswith("0x") or any(c in "abcdef" for c in v) or v == "10001") else int(v)
        else:
            r = self.s.get(self.api_base + key_path, timeout=self.timeout)
            r.raise_for_status()
            b = r.json()
            mod = (b.get("public_key") or (b.get("data") or {}).get("public_key") or "").strip()
        if len(mod) % 2:  # 앞자리 0이 빠진 16진수(jsbn 형식) 보정 - 6.11.3 v1 공개키 실측
            mod = "0" + mod
        pub = RSA.construct((bytes_to_long(a2b_hex(mod)), exp)).publickey()
        cipher = PKCS1_OAEP.new(pub) if pad == "oaep" else PKCS1_v1_5.new(pub)
        return cipher.encrypt(plaintext.encode()).hex().zfill(len(mod))

    def login_ticket(self, username, password, mode):
        """콘솔 로그인 버튼과 같은 흐름 (6.11.3 로그인 JS 48214 모듈 ge() 실측):
          1) GET /login -> window.VMP.data.ticket(UUID)을 CSRFPreventionToken 쿠키로, RSAModulus
          2) POST /logout (헤더 csrfpreventiontoken=ticket) - 로그인 화면이 먼저 호출
          3) GET /salt -> {salt, timestamp}
          4) 평문 = salt가 있으면 "timestamp#salt#password", 없으면 password
             RSA(RSAModulus, e=10001) PKCS#1 v1.5 -> 16진수(키 길이로 0 채움)
          5) POST /ticket (폼: username, password, status=agree, user_login=true)
          6) 응답 data.client_token / data.CSRFPreventionToken 으로 이후 요청"""
        import re
        self.s.cookies.clear()
        for h in ("Client_token", "Csrfpreventiontoken", "Sid"):
            self.s.headers.pop(h, None)
        self.s.cookies.set("language", "en_US")
        self.s.cookies.set("UEDC_LOGIN_LANGUAGE", "en_US")
        r = self.s.get(self.base + "/login", timeout=self.timeout)
        self.login_page = r.text
        m = re.search(r"VMP\.data\.ticket\s*=\s*['\"]([^'\"]+)['\"]", self.login_page)
        if not m:
            raise SCPError("[console] 로그인 화면에서 ticket 값을 찾지 못했습니다")
        ticket = m.group(1)
        self.s.cookies.set("CSRFPreventionToken", ticket)
        ajax = {"X-Requested-With": "XMLHttpRequest", "Accept-Language": "en_US",
                "Origin": self.base, "Referer": self.base + "/login"}
        try:
            self.s.post(self.base + "/logout", headers=dict(ajax, csrfpreventiontoken=ticket), timeout=self.timeout)
        except requests.RequestException:
            pass
        self.s.cookies.set("CSRFPreventionToken", ticket)  # 로그아웃 응답이 쿠키를 지워도 화면처럼 티켓 유지
        r = self.s.get(self.base + "/salt", headers=ajax, timeout=self.timeout)
        try:
            salt = (r.json() or {}).get("data") or {}
        except ValueError:
            raise SCPError(f"[console] /salt 응답이 JSON이 아님 (HTTP {r.status_code})")
        plain = f"{salt.get('timestamp')}#{salt.get('salt')}#{password}" if salt.get("salt") else password
        form = {"username": username, "password": self._encrypt(plain, mode),
                "status": "agree", "user_login": "true"}
        r = self.s.post(self.base + "/ticket", data=form, timeout=self.timeout, headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest", "Csrfpreventiontoken": "",
            "Origin": self.base, "Referer": self.base + "/login"})
        try:
            j = r.json()
        except ValueError:
            raise SCPError(f"[console] /ticket 로그인 응답이 JSON이 아님 (HTTP {r.status_code})")
        d = j.get("data") or {}
        if not (j.get("success") == 1 and d.get("client_token") and d.get("CSRFPreventionToken")):
            raise SCPError(f"[console] /ticket 로그인 실패({mode}): {j.get('message') or j.get('dbgmsg') or str(j)[:200]}")
        self._activate_session(d["client_token"], d["CSRFPreventionToken"])
        return d

    def _looks_ok(self):
        """조회 한 번으로 세션이 살아 있는지 확인 (로그인 화면 HTML이면 실패)."""
        try:
            r = self.s.get(self.base + "/admin/view/dr-rp-list", params={"start": 0, "limit": 1}, timeout=self.timeout)
            return r.headers.get("Content-Type", "").startswith("application/json") and "success" in r.text[:2000]
        except requests.RequestException:
            return False

    def _server_cookie_names(self):
        return sorted({c.name for c in self.s.cookies if c.domain})

    def _activate_session(self, token, csrf):
        """로그인 직후 세션을 쓰는 방법을 순서대로 시도하고, 통한 방법을 self.login_variant에 남긴다.
          A) 서버가 준 쿠키만 유지 + CSRF/헤더만 추가 (중복 쿠키 없음)
          B) A + 콘솔 첫 화면 GET / (브라우저처럼 세션 활성화)
          C) 스크립트가 쿠키를 직접 덮어씀 (예전 방식)"""
        jar = self.s.cookies
        # 도메인 없이 넣었던 스크립트 쿠키 제거 -> 서버가 준 쿠키만 남김
        for c in list(jar):
            if not c.domain:
                jar.clear(c.domain, c.path, c.name)
        host = urllib.parse.urlparse(self.base).hostname
        self.token, self.csrf = token, csrf
        self.s.headers.update({"Client_token": token, "Csrfpreventiontoken": csrf, "Sid": "",
                               "X-Requested-With": "XMLHttpRequest", "Referer": self.base + "/",
                               "Content-Type": "application/json; charset=utf-8"})
        for name, val in (("CSRFPreventionToken", csrf), ("language", "en_US")):
            jar.set(name, val, domain=host, path="/")
        if not any(c.name == "aCMPAuthToken" for c in jar):
            jar.set("aCMPAuthToken", token, domain=host, path="/")
        if self._looks_ok():
            self.login_variant = "A(서버 쿠키 유지)"
            return
        try:
            self.s.get(self.base + "/", timeout=self.timeout)
        except requests.RequestException:
            pass
        if self._looks_ok():
            self.login_variant = "B(첫 화면 GET 후)"
            return
        self.set_token(token, csrf, keep_cookies=False)
        if self._looks_ok():
            self.login_variant = "C(쿠키 직접 설정)"
            return
        raise SCPError("[console] 로그인은 성공했지만 세션 사용 실패 (A/B/C 모두 로그인 화면으로 이동). "
                       f"서버 쿠키: {self._server_cookie_names()}")

    @classmethod
    def from_env_with(cls, src):
        os.environ["CONSOLE_TOKEN_SOURCE"] = src
        return cls.from_env()

    @classmethod
    def from_env(cls, api=None):
        src = env("CONSOLE_TOKEN_SOURCE", "ticket")
        c = cls(env("SCP_HOST", required=True), port=int(env("CONSOLE_PORT", "4430")),
                verify=env("SCP_VERIFY_TLS", "0") == "1", timeout=int(env("SCP_TIMEOUT", "30")))
        if src == "ticket":
            if not (env("SCP_USER") and env("SCP_PASS")):
                raise SCPError("CONSOLE_TOKEN_SOURCE=ticket 은 SCP_USER/SCP_PASS가 필요합니다")
            c.login_ticket(env("SCP_USER"), env("SCP_PASS"), env("CONSOLE_LOGIN_ENC", "page-pkcs1"))
        elif src == "manual":
            c.set_token(env("CONSOLE_TOKEN", required=True), env("CONSOLE_CSRF"))
        else:
            api = api or SCPClient(env("SCP_HOST"), auth="token", username=env("SCP_USER"),
                                   password=env("SCP_PASS"), verify=env("SCP_VERIFY_TLS", "0") == "1")
            if api.mode != "token":
                raise SCPError("CONSOLE_TOKEN_SOURCE=janus 는 SCP_USER/SCP_PASS 토큰 로그인이 필요합니다")
            api.login()
            c.set_token(api.s.headers["Authorization"].split(" ", 1)[1])
        return c

    def request(self, method, path, params=None, body=None):
        try:
            r = self.s.request(method, self.base + path, params=params,
                               data=json.dumps(body) if body is not None else None, timeout=self.timeout)
        except requests.RequestException as e:
            raise SCPError(f"[console] {method} {path} 접속 실패: {e}")
        self._sync_csrf(r)
        if r.status_code in (401, 403):
            raise SCPError(f"[console] {method} {path} -> HTTP {r.status_code} (토큰/CSRF 거부): {r.text[:200]}")
        try:
            data = r.json()
        except ValueError:
            raise SCPError(f"[console] {method} {path} -> HTTP {r.status_code}, JSON 아님"
                           f" (로그인 페이지로 리다이렉트됐을 수 있음): {r.text[:200]}")
        if r.status_code >= 400 or (isinstance(data, dict) and data.get("success") in (0, False)):
            raise SCPError(f"[console] {method} {path} -> HTTP {r.status_code}: "
                           f"{data.get('dbgmsg') or data.get('msg') or str(data)[:300]}")
        return data

    CSRF_NAMES = ("CSRFPreventionToken", "csrfpreventiontoken", "csrf_token", "csrfToken", "CSRF_TOKEN")

    def _sync_csrf(self, r):
        """서버가 내려준 CSRF 토큰(Set-Cookie)이 있으면 쿠키와 헤더를 그 값으로 맞춘다."""
        for name in self.CSRF_NAMES:
            v = r.cookies.get(name)
            if v and v != self.csrf:
                self.csrf = v
                self.s.headers["Csrfpreventiontoken"] = v
                self.s.cookies.set("CSRFPreventionToken", v)
                return True
        return False

    def dr_protection_list(self):
        return self.request("GET", "/admin/view/dr-protection-list",
                            params={"start": 0, "limit": 50, "sort": "name", "direct": "ASC"})
