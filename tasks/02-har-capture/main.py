#!/usr/bin/env python3
"""Task 02 - SCP 콘솔 HAR 캡처에서 API 호출만 뽑아 카탈로그로 정리한다.

사용법:
    ./run.sh har/02_drill_start.har                       # 화면에 요약
    ./run.sh har/02_drill_start.har -k protect,drill      # 키워드 필터
    ./run.sh har/02_drill_start.har -o out/02_drill.md    # md + json + endpoints 후보 저장

- 정적 리소스(js/css/img/font)는 제외
- UUID·숫자 ID는 {id}로 정규화해서 같은 API끼리 묶음
- token, password, cookie, Authorization 값은 자동 마스킹
"""
import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from urllib.parse import urlparse, parse_qsl

STATIC_EXT = re.compile(r"\.(js|css|png|jpe?g|gif|svg|ico|woff2?|ttf|map|html?)$", re.I)
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
HEX32 = re.compile(r"\b[0-9a-fA-F]{32}\b")
NUM = re.compile(r"(?<!/janus)/\d{3,}(?=/|$)")  # /janus/20240725 같은 API 버전은 유지
SECRET_KEYS = re.compile(r"(passw|token|secret|cookie|authorization|credential|^(ak|sk|access_key|secret_key)$)", re.I)
SECRET_HEADERS = {"authorization", "cookie", "set-cookie", "x-auth-token", "x-csrf-token"}


def normalize(path):
    path = UUID.sub("{id}", path)
    path = HEX32.sub("{id}", path)
    return NUM.sub("/{n}", path)


def mask(obj):
    if isinstance(obj, dict):
        return {k: ("***" if SECRET_KEYS.search(k) and not isinstance(v, (dict, list)) else mask(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(x) for x in obj[:3]]  # 리스트는 앞 3개만
    return obj


def parse_body(text):
    if not text:
        return None
    try:
        return mask(json.loads(text))
    except (ValueError, TypeError):
        return text[:500]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("har")
    ap.add_argument("-k", "--keywords", default="", help="쉼표로 구분한 경로 키워드 (예: protect,dr,drill)")
    ap.add_argument("-o", "--out", help="마크다운 출력 파일")
    args = ap.parse_args()

    with open(args.har, encoding="utf-8") as f:
        entries = json.load(f)["log"]["entries"]
    kws = [k.strip().lower() for k in args.keywords.split(",") if k.strip()]

    catalog = OrderedDict()
    for e in entries:
        req, res = e["request"], e["response"]
        u = urlparse(req["url"])
        if STATIC_EXT.search(u.path) or req["method"] == "OPTIONS":
            continue
        ctype = next((h["value"] for h in res.get("headers", []) if h["name"].lower() == "content-type"), "")
        if "json" not in ctype and req["method"] == "GET":
            continue
        npath = normalize(u.path)
        if kws and not any(k in npath.lower() or k in (req.get("postData", {}).get("text", "").lower()) for k in kws):
            continue
        key = f'{req["method"]} {npath}'
        item = catalog.setdefault(key, {
            "method": req["method"], "path": npath, "count": 0, "first_seen": e.get("startedDateTime"),
            "sample_url": UUID.sub("{id}", req["url"]),
            "query": {k: ("***" if SECRET_KEYS.search(k) else v) for k, v in parse_qsl(u.query)},
            "req_headers": sorted({h["name"] for h in req["headers"]
                                   if h["name"].lower() not in SECRET_HEADERS and not h["name"].startswith(":")}),
            "auth_headers": sorted({h["name"] for h in req["headers"] if h["name"].lower() in SECRET_HEADERS}),
            "request_body": parse_body(req.get("postData", {}).get("text")),
            "status": res["status"],
            "response_body": parse_body(res.get("content", {}).get("text")),
        })
        item["count"] += 1

    lines = [f"# SCP 캡처 API 카탈로그 ({len(catalog)}개)\n", f"원본: `{args.har}`\n"]
    for key, it in catalog.items():
        lines.append(f"## `{key}`\n")
        lines.append(f"- 호출 {it['count']}회, 최초 {it['first_seen']}, 응답 {it['status']}")
        lines.append(f"- 예시 URL: `{it['sample_url']}`")
        if it["auth_headers"]:
            lines.append(f"- 인증 헤더: {', '.join(it['auth_headers'])}")
        if it["query"]:
            lines.append(f"- 쿼리: `{json.dumps(it['query'], ensure_ascii=False)}`")
        if it["request_body"] is not None:
            lines.append("- 요청 본문:\n```json\n" + json.dumps(it["request_body"], ensure_ascii=False, indent=2) + "\n```")
        if it["response_body"] is not None:
            body = json.dumps(it["response_body"], ensure_ascii=False, indent=2)
            lines.append("- 응답 본문(앞부분):\n```json\n" + body[:2000] + "\n```")
        lines.append("")
    md = "\n".join(lines)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        stem = args.out.rsplit(".", 1)[0]
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(list(catalog.values()), f, ensure_ascii=False, indent=2)
        # 04-adr-drill/endpoints.json 에 옮겨 붙일 후보 (변경 계열 호출만)
        cands = {}
        for i, it in enumerate(v for v in catalog.values() if v["method"] in ("POST", "PUT", "DELETE")):
            cands[f"candidate_{i + 1}"] = {
                "method": it["method"], "path": it["path"].replace("{id}", "${protection_id}"),
                "body": it["request_body"] if isinstance(it["request_body"], (dict, list)) else None,
                "async": True, "task_id_field": "task_id", "verified": False,
                "_sample_response": it["response_body"]}
        with open(stem + ".endpoints-candidates.json", "w", encoding="utf-8") as f:
            json.dump({"endpoints": cands}, f, ensure_ascii=False, indent=2)
        print(f"{len(catalog)}개 API -> {args.out}", file=sys.stderr)
    else:
        print(md)


if __name__ == "__main__":
    main()
