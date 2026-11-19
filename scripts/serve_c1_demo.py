"""Serve the local C1 product lookup and historical validation replay."""
import argparse
import json
import sqlite3
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from scripts.c1_demo_model import C1DemoModel
from scripts.c1_demo_replay import ReplayLibrary


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "recommendations"
AS_OF = "2015-08-01T00:00:00Z"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/styles.css": ("styles.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
    "/replay": ("replay.html", "text/html"),
    "/replay/": ("replay.html", "text/html"),
    "/replay.css": ("replay.css", "text/css"),
    "/replay.js": ("replay.js", "text/javascript"),
}


def handler_for(model: C1DemoModel, replay: ReplayLibrary | None = None):
    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # The browser can cancel a request when a different item is selected.

        def json_response(self, status, payload):
            self.send_bytes(status, "application/json", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path in ASSETS:
                filename, content_type = ASSETS[url.path]
                self.send_bytes(HTTPStatus.OK, content_type, (WEB / filename).read_bytes())
                return

            if url.path == "/api/replay":
                if replay is None:
                    self.json_response(HTTPStatus.SERVICE_UNAVAILABLE, {
                        "error": "本機缺少可核對的 Stage 10 回放資料。還原保存包後請重新啟動服務。"
                    })
                else:
                    self.json_response(HTTPStatus.OK, replay.payload())
                return

            query = parse_qs(url.query, keep_blank_values=True)
            if url.path == "/api/catalog":
                prefix = query.get("prefix", [""])[0]
                self.json_response(HTTPStatus.OK, {"as_of": AS_OF, "total": len(model), "items": model.search(prefix)})
                return
            if url.path != "/api/recommendations":
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "找不到這個頁面。"})
                return

            ids = query.get("item_id", [])
            if len(ids) != 1 or not ids[0].isascii() or not ids[0].isdigit():
                self.json_response(HTTPStatus.BAD_REQUEST, {"error": "請輸入一個數字商品 ID。"})
                return
            try:
                result = model.recommend(ids[0])
            except KeyError:
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "訓練商品目錄中找不到這個 ID。"})
                return
            except sqlite3.Error:
                self.json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "暫時無法讀取本機推薦索引。"})
                return
            self.json_response(HTTPStatus.OK, {"as_of": AS_OF, **result})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        model = C1DemoModel.load(ROOT)
        try:
            replay = ReplayLibrary.load(ROOT)
        except (OSError, ValueError, KeyError) as exc:
            replay = None
            print(f"回放資料無法載入。商品查詢仍可使用。\n{exc}", file=sys.stderr)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(model, replay))
    except (OSError, ValueError, KeyError) as exc:
        sys.exit(f"無法啟動推薦展示。請確認 Stage 10 研究檔案與連接埠。\n{exc}")
    with server:
        print(f"C1 · {len(model):,} items · http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
