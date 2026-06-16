#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DATA_DIR = os.environ.get("LIUREN_DATA_DIR", "/var/lib/liuren")
DB_PATH = os.path.join(DATA_DIR, "cases.db")
TOKEN_HASH = os.environ.get("LIUREN_TOKEN_HASH", "")
HOST = os.environ.get("LIUREN_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("LIUREN_API_PORT", "8787"))
AI_API_KEY = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL") or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
AI_BASE_URL = os.environ.get("AI_BASE_URL") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
AI_API_STYLE = os.environ.get("AI_API_STYLE", "responses")
AI_MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "900"))


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            create table if not exists cases (
                id text primary key,
                payload text not null,
                updated_at integer not null
            )
            """
        )
        db.execute("create index if not exists idx_cases_updated_at on cases(updated_at)")


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def token_ok(header):
    if not TOKEN_HASH:
        return False
    if not header or not header.startswith("Bearer "):
        return False
    token = header[7:].strip()
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, TOKEN_HASH)


def normalize_case(case):
    if not isinstance(case, dict):
        raise ValueError("case must be object")
    case_id = str(case.get("id") or "").strip()
    if not case_id:
        raise ValueError("case id is required")
    now = int(time.time())
    case["id"] = case_id
    case["cloudUpdatedAt"] = now
    return case_id, case, now


def build_ai_prompt(payload):
    case = payload.get("case") or {}
    reading = payload.get("reading") or {}
    frame = payload.get("frame") or {}
    chuan = frame.get("chuan") or {}
    event_type = case.get("eventType", "")
    target = case.get("target", "")
    target_for_ai = "这个标的" if "投资" in event_type or "求财" in event_type else target
    question = case.get("question", "")
    if target:
        question = question.replace(target, target_for_ai)
    extra_warning = ""
    if "健康" in event_type or "忧患" in event_type:
        extra_warning = "本次是健康相关事项，必须提醒：这不是医疗诊断，身体不适要以检查和医嘱为准。"
    elif "投资" in event_type or "求财" in event_type:
        extra_warning = "本次是投资求财事项，必须提醒：这不构成投资建议，只能作为仓位、节奏和风险观察参考。"
    plain = "\n".join(
        [
            f"事项类型：{event_type}",
            f"所问对象：{target_for_ai}",
            f"判断重点：{case.get('focus', '')}",
            f"观察周期：{case.get('horizon', '')}",
            f"所问问题：{question}",
            f"规则引擎结论：{case.get('decision', '')}",
            f"三传：初传 {chuan.get('chuan1', '')}，中传 {chuan.get('chuan2', '')}，末传 {chuan.get('chuan3', '')}",
            f"规则总象：{reading.get('summary', '')}",
            f"所问分析：{reading.get('matter', '')}",
            extra_warning,
            "请只整理这一课的判断表达。",
        ]
    )
    return (
        "你是一个严谨的大六壬观事表达整理助手。"
        "底层排盘和初判已经由规则引擎给出，你不要重新玄断，不要夸大确定性，"
        "只根据输入内容，把当前这一课的判断整理成更清楚、更贴近所问之事的中文。"
        "你不是在设计模板，也不是在举例填空。\n\n"
        "严禁事项：\n"
        "1. 不要讲金融产品常识、市场数据、政策、资金流向、成交量、均线、支撑位、技术指标。\n"
        "2. 不要把三传解释成宏观、行业、技术指标这类现代分析框架。\n"
        "3. 不要编造输入里没有的信息。\n"
        "4. 不要说“如果你需要进一步细化”。\n"
        "5. 不要把用户输入当成让你改格式。\n\n"
        "6. 不要给出输入以外的外部原因，只能围绕规则总象、三传、规则引擎结论、风险和行动节奏。\n\n"
        "输出要求：\n"
        "1. 用普通人能看懂的话，不要堆术语。\n"
        "2. 分为五段：本课看什么、主要判断、风险与变数、行动建议、复盘观察点。\n"
        "3. 如果是健康问题，必须提醒不能替代医疗检查。\n"
        "4. 如果是投资问题，必须提醒不构成投资建议，重点放在仓位、节奏、风险。\n"
        "5. 不要说绝对话，不要制造恐惧。\n"
        "6. 语言要简洁、稳、有人味。\n\n"
        "下面是本次观事记录，请直接输出整理结果：\n"
        + plain
    )


def parse_responses_text(data):
    text = data.get("output_text")
    if text:
        return text
    parts = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                parts.append(content.get("text", ""))
    return "\n".join([p for p in parts if p]).strip()


def clean_ai_text(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^<think>.*", "", text, flags=re.S).strip()
    return text


def parse_chat_text(data):
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return clean_ai_text(content)
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(item.get("text") or item.get("content") or "")
            return clean_ai_text("\n".join([p for p in parts if p]))
    return ""


def call_ai_reading(payload):
    if not AI_API_KEY:
        raise RuntimeError("AI 未配置：服务器缺少 AI_API_KEY")
    prompt = build_ai_prompt(payload)
    if AI_API_STYLE == "chat_completions":
        req_body = {
            "model": AI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "你负责把大六壬规则引擎的结构化结果整理成清楚、克制、可复盘的中文表达。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": AI_MAX_TOKENS,
        }
        endpoint = AI_BASE_URL.rstrip("/") + "/chat/completions"
        parser = parse_chat_text
    else:
        req_body = {
            "model": AI_MODEL,
            "input": [
                {
                    "role": "system",
                    "content": "你负责把大六壬规则引擎的结构化结果整理成清楚、克制、可复盘的中文表达。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": AI_MAX_TOKENS,
        }
        endpoint = AI_BASE_URL.rstrip("/") + "/responses"
        parser = parse_responses_text
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(req_body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + AI_API_KEY,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI 调用失败：HTTP {exc.code} {detail[:300]}")
    text = parser(data)
    if not text:
        raise RuntimeError("AI 未返回可用文本")
    return clean_ai_text(text)

class Handler(BaseHTTPRequestHandler):
    server_version = "LiurenCaseAPI/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            json_response(self, 200, {"ok": True, "service": "liuren-api"})
            return
        if path != "/api/cases":
            json_response(self, 404, {"ok": False, "error": "not found"})
            return
        if not token_ok(self.headers.get("Authorization")):
            json_response(self, 401, {"ok": False, "error": "unauthorized"})
            return
        with sqlite3.connect(DB_PATH) as db:
            rows = db.execute("select payload from cases order by updated_at desc").fetchall()
        cases = [json.loads(row[0]) for row in rows]
        json_response(self, 200, {"ok": True, "cases": cases})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/ai/reading":
            if not token_ok(self.headers.get("Authorization")):
                json_response(self, 401, {"ok": False, "error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(min(length, 500_000))
                data = json.loads(raw.decode("utf-8") or "{}")
                text = call_ai_reading(data)
                json_response(self, 200, {"ok": True, "reading": text, "model": AI_MODEL})
            except Exception as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        if path != "/api/cases":
            json_response(self, 404, {"ok": False, "error": "not found"})
            return
        if not token_ok(self.headers.get("Authorization")):
            json_response(self, 401, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(min(length, 2_000_000))
            data = json.loads(raw.decode("utf-8") or "{}")
            incoming = data.get("cases")
            if not isinstance(incoming, list):
                raise ValueError("cases must be array")
            saved = 0
            with sqlite3.connect(DB_PATH) as db:
                for item in incoming:
                    case_id, case, updated_at = normalize_case(item)
                    payload = json.dumps(case, ensure_ascii=False, separators=(",", ":"))
                    db.execute(
                        """
                        insert into cases(id, payload, updated_at)
                        values(?, ?, ?)
                        on conflict(id) do update set
                            payload=excluded.payload,
                            updated_at=excluded.updated_at
                        """,
                        (case_id, payload, updated_at),
                    )
                    saved += 1
            json_response(self, 200, {"ok": True, "saved": saved})
        except Exception as exc:
            json_response(self, 400, {"ok": False, "error": str(exc)})


def main():
    init_db()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Liuren API listening on {HOST}:{PORT}, data={DB_PATH}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
