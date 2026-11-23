import json
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
from unittest.mock import MagicMock

from scripts.c1_demo_model import C1DemoModel
from scripts.c1_demo_replay import ReplayLibrary
from scripts.serve_c1_demo import WEB, handler_for


class ReplayRoutesTest(unittest.TestCase):
    def open_server(self, replay=None, *, k1_recency=None):
        model = MagicMock(spec=C1DemoModel)
        model.search.return_value = [{"item_id": "1"}]
        server = HTTPServer(("127.0.0.1", 0), handler_for(model, replay, k1_recency=k1_recency))
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        return server.server_port

    def get(self, port, path):
        connection = HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_serves_selected_cases(self):
        replay = MagicMock(spec=ReplayLibrary)
        replay.payload.return_value = {
            "cases": [{"id": "neither"}],
            "cart": {"total_queries": 3, "cases": [{"id": "hit", "count": 1}, {"id": "miss", "count": 2}]},
            "cart_fill": {"total_queries": 2, "cases": [{"id": "empty", "count": 1}, {"id": "short", "count": 1}]},
            "purchase_fill": {"scorable_queries": 3, "overlap_queries": 2, "cases": [
                {"id": "short_gain", "count": 2}, {"id": "popular_later", "count": 2},
            ]},
        }
        self.assertEqual(self.get(self.open_server(replay), "/api/replay"),
                         (200, replay.payload.return_value))

    def test_k1_recency_is_available_alongside_existing_replays(self):
        replay = MagicMock(spec=ReplayLibrary)
        replay.payload.return_value = {"cases": [{"id": "neither"}]}
        k1_recency = {"cases": [{"id": "gained"}, {"id": "lost"}]}
        expected = {**replay.payload.return_value, "k1_recency": k1_recency}
        self.assertEqual(self.get(self.open_server(replay, k1_recency=k1_recency), "/api/replay"), (200, expected))
        self.assertEqual(self.get(self.open_server(k1_recency=k1_recency), "/api/replay"),
                         (200, {"k1_recency": k1_recency}))
        self.assertNotIn("k1_recency", replay.payload.return_value)

    def test_deep_links_serve_the_replay_page(self):
        port = self.open_server()
        page = (WEB / "replay.html").read_bytes()
        for case in ("cart_hit", "cart_miss", "cart_fill_empty", "cart_fill_short",
                     "purchase_fill_short_gain", "purchase_fill_popular_later",
                     "k1_recency_gained", "k1_recency_lost"):
            with self.subTest(case=case):
                connection = HTTPConnection("127.0.0.1", port, timeout=3)
                try:
                    connection.request("GET", "/replay?case=" + case)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), page)
                finally:
                    connection.close()

    def test_missing_replay_does_not_disable_product_lookup(self):
        port = self.open_server()
        status, data = self.get(port, "/api/replay")
        self.assertEqual(status, 503)
        self.assertIn("error", data)
        status, catalog = self.get(port, "/api/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["items"], [{"item_id": "1"}])
