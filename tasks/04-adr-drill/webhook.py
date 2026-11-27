#!/usr/bin/env python3
"""Task 04 - HTTP 웹훅 수신기. 모니터링 경보, 사내 메신저 봇, 휴대폰 단축어, Jenkins 등에서
HTTP 요청 한 번으로 trigger.sh 를 실행한다. 표준 라이브러리만 사용.

실행:  ./run.sh --webhook          (상시 실행은 systemd/adr-webhook.service)
호출:
  curl -X POST -H "Authorization: Bearer $TOKEN" http://서버:8780/run/drill
  curl -X POST -H "Authorization: Bearer $TOKEN" -d '{"plan":"aDR-Auto-SCP-Test"}' http://서버:8780/run/drill
  curl -H "Authorization: Bearer $TOKEN" http://서버:8780/status
  curl http://서버:8780/health
응답: 202 접수 / 401 토큰 오류 / 403 허용 안 된 동작 / 409 이미 실행 중
"""
import hmac
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from scp_client import env, load_env

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = {"proc": None, "action": None, "started": None, "source": None}


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg, flush=True)


def running():
    p = STATE["proc"]
    return p is not None and p.poll() is None


class H(BaseHTTPRequestHandler):
    server_version = "adr-webhook"

    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        token = env("WEBHOOK_TOKEN", "")
        got = self.headers.get("Authorization", "")
        got = got[7:] if got.lower().startswith("bearer ") else self.headers.get("X-ADR-Token", "")
        if not got:  # 헤더를 못 넣는 도구용 (?token=)
            got = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        return bool(token) and hmac.compare_digest(got.encode(), token.encode())

    def log_message(self, fmt, *args):
        msg = fmt % args
        if "token=" in msg:  # 주소에 넣은 토큰은 로그에 남기지 않음
            import re
            msg = re.sub(r"token=[^&\s\"]*", "token=***", msg)
        log(f"{self.client_address[0]} {msg}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"ok": True, "running": running()})
        if not self._authed():
            return self._send(401, {"error": "token"})
        if path == "/status":
            d = env("LOG_DIR", "") or os.path.join(HERE, "logs")
            last = {}
            try:
                with open(os.path.join(d, "last-result.json"), encoding="utf-8") as f:
                    last = json.load(f)
            except (OSError, ValueError):
                pass
            return self._send(200, {"running": running(), "current": STATE["action"] if running() else None,
                                    "started": STATE["started"], "last_result": last})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authed():
            return self._send(401, {"error": "token"})
        if not path.startswith("/run/"):
            return self._send(404, {"error": "not found"})
        action = path[5:]
        allowed = [x.strip() for x in env("WEBHOOK_ALLOWED", "drill,cleanup,clear").split(",") if x.strip()]
        if action not in allowed:
            return self._send(403, {"error": f"허용 안 된 동작: {action}", "allowed": allowed})
        if running():
            return self._send(409, {"error": "이미 실행 중", "current": STATE["action"], "started": STATE["started"]})
        n = int(self.headers.get("Content-Length") or 0)
        body = {}
        if n:
            try:
                body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
            except ValueError:
                return self._send(400, {"error": "JSON 본문 오류"})
        args = [os.path.join(HERE, "trigger.sh"), action]
        plan = str(body.get("plan") or "").strip()
        if plan:
            args += ["-p", plan]
        src = f"webhook:{self.client_address[0]}"
        STATE.update(proc=subprocess.Popen(args, cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, env=dict(os.environ, TRIGGER_SOURCE=src)),
                     action=action, started=time.strftime("%Y-%m-%d %H:%M:%S"), source=src)
        log(f"실행 접수: {action} plan={plan or '(ADR_PLAN)'} from {src}")
        return self._send(202, {"accepted": True, "action": action, "plan": plan or env("ADR_PLAN", ""),
                                "status_url": "/status"})


def main():
    load_env()
    token = env("WEBHOOK_TOKEN", "")
    if len(token) < 16:
        print("WEBHOOK_TOKEN 을 16자 이상으로 .env 에 설정하세요 (예: openssl rand -hex 24)", file=sys.stderr)
        return 1
    bind, port = env("WEBHOOK_BIND", "0.0.0.0"), int(env("WEBHOOK_PORT", "8780"))
    log(f"웹훅 수신 대기: http://{bind}:{port}  허용 동작: {env('WEBHOOK_ALLOWED', 'drill,cleanup,clear')}")
    try:
        HTTPServer((bind, port), H).serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
