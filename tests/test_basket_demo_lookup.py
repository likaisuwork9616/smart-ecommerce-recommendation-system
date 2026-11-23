import json
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread

from scripts.basket_demo_model import BasketDemoModel
from scripts.evaluate_cart_recommendations import CartModel
from scripts.serve_c1_demo import AS_OF, handler_for


class BrowseFixture:
    items = ("1", "200", "4", "99")

    def __len__(self):
        return len(self.items)

    def search(self, prefix="", limit=8):
        return [{"item_id": item} for item in self.items if item.startswith(prefix)][:limit]

    def recommend(self, item):
        if item not in self.items:
            raise KeyError(item)
        return {"item_id": item, "sessions": 12, "views": 13, "positive_candidates": 1,
                "recommendations": [
                    {"item_id": "4", "rank": 1, "source": "cooccurrence", "views": 3, "co_sessions": 2}
                ]}


class BasketDemoLookupTest(unittest.TestCase):
    def setUp(self):
        popular = [str(i) for i in range(1, 12)]
        cart = CartModel({"1": ["11", "3"], "99": popular[:10]}, popular, {*popular, "99"}, {})
        self.baskets = BasketDemoModel(cart, {"1": ("9", "3")}, popular + ["21"])

    def open_server(self, baskets):
        server = HTTPServer(("127.0.0.1", 0), handler_for(BrowseFixture(), baskets=baskets))
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

    def test_same_item_returns_each_ranking_and_preserves_browse_response(self):
        port = self.open_server(self.baskets)
        path = "/api/recommendations?item_id=1"
        expected = {"as_of": AS_OF, **BrowseFixture().recommend("1")}
        self.assertEqual(self.get(port, path), (200, expected))
        self.assertEqual(self.get(port, path + "&scenario=browse"), (200, expected))
        for scenario, label, items in (
            ("cart", "coadd", ("11", "3", "2", "4", "5", "6", "7", "8", "9", "10")),
            ("purchase", "cobuy", ("9", "3", "2", "4", "5", "6", "7", "8", "10", "11")),
        ):
            with self.subTest(scenario=scenario):
                status, payload = self.get(port, path + "&scenario=" + scenario)
                self.assertEqual((status, payload["scenario"], payload["as_of"]), (200, scenario, AS_OF))
                self.assertEqual(payload["recommendations"], [
                    {"item_id": item, "rank": i, "source": label if i <= 2 else "popular"}
                    for i, item in enumerate(items, 1)
                ])

    def test_empty_and_full_related_lists_are_preserved_or_filled(self):
        port = self.open_server(self.baskets)
        for seed, scenario, source in (("200", "cart", "popular"), ("21", "purchase", "popular"),
                                       ("99", "cart", "coadd")):
            with self.subTest(seed=seed, scenario=scenario):
                status, payload = self.get(port, f"/api/recommendations?item_id={seed}&scenario={scenario}")
                self.assertEqual(status, 200)
                self.assertEqual(payload["recommendations"], [
                    {"item_id": str(rank), "rank": rank, "source": source} for rank in range(1, 11)
                ])

    def test_combined_search_includes_items_without_views(self):
        port = self.open_server(self.baskets)
        base = "/api/catalog?prefix=21"
        self.assertEqual(self.get(port, base), (200, {"as_of": AS_OF, "total": 4, "items": []}))
        self.assertEqual(self.get(port, base + "&scope=product"),
                         (200, {"as_of": AS_OF, "total": 14, "items": [{"item_id": "21"}]}))
        status, payload = self.get(port, "/api/recommendations?item_id=21")
        self.assertEqual(status, 404)
        self.assertIn("切換", payload["error"])

    def test_unknown_items_and_modes_return_clear_errors(self):
        port = self.open_server(self.baskets)
        for path, expected in (
            ("?item_id=999&scenario=cart", 404),
            ("?item_id=999&scenario=purchase", 404),
            ("?item_id=1&scenario=basket", 400),
            ("?item_id=1&scenario=cart&scenario=purchase", 400),
            ("?item_id=abc&scenario=cart", 400),
        ):
            with self.subTest(path=path):
                status, data = self.get(port, "/api/recommendations" + path)
                self.assertEqual(status, expected)
                self.assertIn("error", data)

    def test_missing_baskets_keep_browse_and_catalog_usable(self):
        port = self.open_server(None)
        self.assertEqual(self.get(port, "/api/recommendations?item_id=1")[0], 200)
        self.assertEqual(self.get(port, "/api/catalog?scope=product")[1]["total"], 4)
        for scenario in ("cart", "purchase"):
            status, response = self.get(port, f"/api/recommendations?item_id=1&scenario={scenario}")
            self.assertEqual(status, 503)
            self.assertIn("Stage 8", response["error"])
