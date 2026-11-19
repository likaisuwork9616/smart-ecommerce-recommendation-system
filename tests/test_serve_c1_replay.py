import json
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
from unittest.mock import MagicMock

from scripts.c1_demo_model import C1DemoModel
from scripts.c1_demo_replay import ReplayLibrary
from scripts.serve_c1_demo import handler_for


class ReplayRoutesTest(unittest.TestCase):
    def open_server(self, replay=None):
        model = MagicMock(spec=C1DemoModel)
        model.search.return_value = [{"item_id": "1"}]
        server = HTTPServer(("127.0.0.1", 0), handler_for(model, replay))
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
        replay.payload.return_value = {"cases": [{"id": "neither"}]}
        self.assertEqual(self.get(self.open_server(replay), "/api/replay"),
                         (200, replay.payload.return_value))

    def test_missing_replay_does_not_disable_product_lookup(self):
        port = self.open_server()
        status, data = self.get(port, "/api/replay")
        self.assertEqual(status, 503)
        self.assertIn("error", data)
        status, catalog = self.get(port, "/api/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["items"], [{"item_id": "1"}])
