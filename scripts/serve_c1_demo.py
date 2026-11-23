"""Serve the local product recommendation lookup and historical validation replay."""
import argparse
import json
import sqlite3
import sys
from bisect import bisect_left
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from scripts.basket_demo_model import BasketDemoModel
from scripts.c1_demo_model import C1DemoModel
from scripts.c1_demo_replay import ReplayLibrary
from scripts.k1_recency_replay import load_k1_recency_replay


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "recommendations"
AS_OF = "2015-08-01T00:00:00Z"
SCENARIOS = ("browse", "cart", "purchase")
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


def handler_for(model: C1DemoModel, replay: ReplayLibrary | None = None, baskets: BasketDemoModel | None = None,
                *, k1_recency=None):
    def seen_in_browse(item_id):
        return any(item["item_id"] == item_id for item in model.search(item_id, limit=1))

    basket_only = sorted(item for item in baskets.item_ids if not seen_in_browse(item)) if baskets else []

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
                if replay is None and k1_recency is None:
                    self.json_response(HTTPStatus.SERVICE_UNAVAILABLE, {
                        "error": "本機缺少可核對的 Stage 10 回放資料。還原保存包後請重新啟動服務。"
                    })
                else:
                    payload = dict(replay.payload()) if replay is not None else {}
                    if k1_recency is not None:
                        payload["k1_recency"] = k1_recency
                    self.json_response(HTTPStatus.OK, payload)
                return

            query = parse_qs(url.query, keep_blank_values=True)
            if url.path == "/api/catalog":
                prefix = query.get("prefix", [""])[0]
                items = model.search(prefix)
                total = len(model)
                if query.get("scope") == ["product"]:
                    total += len(basket_only)
                    if prefix.isascii() and prefix.isdigit():
                        start = bisect_left(basket_only, prefix)
                        stop = bisect_left(basket_only, prefix + ":", lo=start)
                        items.extend({"item_id": item} for item in basket_only[start:min(stop, start + 8)])
                        items = sorted(items, key=lambda entry: entry["item_id"])[:8]
                self.json_response(HTTPStatus.OK, {"as_of": AS_OF, "total": total, "items": items})
                return
            if url.path != "/api/recommendations":
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "找不到這個頁面。"})
                return

            ids = query.get("item_id", [])
            if len(ids) != 1 or not ids[0].isascii() or not ids[0].isdigit():
                self.json_response(HTTPStatus.BAD_REQUEST, {"error": "請輸入一個數字商品 ID。"})
                return
            scenarios = query.get("scenario", ["browse"])
            if len(scenarios) != 1 or scenarios[0] not in SCENARIOS:
                self.json_response(HTTPStatus.BAD_REQUEST, {"error": "請選擇瀏覽、加購或購買推薦。"})
                return
            item_id, scenario = ids[0], scenarios[0]
            try:
                if scenario == "browse":
                    result = model.recommend(item_id)
                elif baskets is None:
                    self.json_response(HTTPStatus.SERVICE_UNAVAILABLE, {
                        "error": "加購與購買推薦尚未載入，請確認本機的 Stage 8 事件資料庫。"
                    })
                    return
                elif item_id in baskets.item_ids or seen_in_browse(item_id):
                    result = baskets.recommend(scenario, item_id)
                else:
                    raise KeyError(item_id)
            except KeyError:
                message = "訓練商品目錄中找不到這個 ID。"
                if scenario == "browse" and baskets is not None and item_id in baskets.item_ids:
                    message = "此商品有加購或購買訓練紀錄，請切換到對應的推薦。"
                self.json_response(HTTPStatus.NOT_FOUND, {"error": message})
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
            print("正在從固定訓練窗準備加購與購買索引…", flush=True)
            baskets = BasketDemoModel.load(ROOT)
        except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
            baskets = None
            print(f"加購與購買索引無法載入：{exc}", file=sys.stderr)
        try:
            replay = ReplayLibrary.load(ROOT)
        except (OSError, ValueError, KeyError) as exc:
            replay = None
            print(f"回放資料無法載入。商品查詢仍可使用。\n{exc}", file=sys.stderr)
        try:
            k1_recency = load_k1_recency_replay(ROOT)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            k1_recency = None
            print(f"K1 留一席回放無法載入：{exc}", file=sys.stderr)
        server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                     handler_for(model, replay, baskets, k1_recency=k1_recency))
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
