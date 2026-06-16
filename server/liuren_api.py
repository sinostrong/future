#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DATA_DIR = os.environ.get("LIUREN_DATA_DIR", "/var/lib/liuren")
DB_PATH = os.path.join(DATA_DIR, "cases.db")
TOKEN_HASH = os.environ.get("LIUREN_TOKEN_HASH", "")
HOST = os.environ.get("LIUREN_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("LIUREN_API_PORT", "8787"))


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
