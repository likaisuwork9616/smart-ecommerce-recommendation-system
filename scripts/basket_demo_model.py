"""Single-item cart and purchase recommendations from the frozen training window."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.evaluate_cart_popular_fill import popular_fill
from scripts.evaluate_cart_recommendations import DB, TOP_K, WINDOWS, activity_rows, build_model
from scripts.evaluate_purchase_baskets import build_baskets, build_lists, purchase_rows


CART_REPORT = "reports/stage13/retailrocket_cart_next_add_201508.json"
PURCHASE_REPORT = "reports/stage13/retailrocket_purchase_basket_201508.json"


class BasketDemoModel:
    def __init__(self, cart_model, purchase_neighbors, popular_purchases):
        self._cart = cart_model
        self._purchase_neighbors = purchase_neighbors
        self._purchase_prefix = popular_purchases[:TOP_K + 1]
        self.item_ids = frozenset(cart_model.cart_items).union(popular_purchases)

    @classmethod
    def load(cls, root: Path):
        cart_report = json.loads((root / CART_REPORT).read_bytes())
        purchase_report = json.loads((root / PURCHASE_REPORT).read_bytes())
        path = root / DB
        source = cart_report["source_database"]
        if (source != purchase_report["source_database"] or source["path"] != DB
                or path.stat().st_size != source["bytes"]):
            raise ValueError("本機事件資料庫與加購、購買訓練報告不符。")
        uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            cart = build_model(activity_rows(db, "train", *WINDOWS["train"]))
            baskets, counts = build_baskets(purchase_rows(db, "train"))
            neighbors, popularity, support = build_lists(baskets)
        if cart.training != cart_report["training"] or {**counts, **support} != purchase_report["training"]:
            raise ValueError("加購或購買索引與已驗證的訓練統計不符。")
        return cls(cart, neighbors, popularity)

    def recommend(self, scenario, item_id):
        if scenario == "cart":
            related, popular = self._cart.rank(item_id)
            evidence = "coadd"
        elif scenario == "purchase":
            related = self._purchase_neighbors.get(item_id, ())
            popular = [item for item in self._purchase_prefix if item != item_id][:TOP_K]
            evidence = "cobuy"
        else:
            raise ValueError(f"Unknown basket recommendation scenario: {scenario}")
        return {
            "scenario": scenario,
            "item_id": item_id,
            "recommendations": [
                {"rank": rank, "item_id": item, "source": source}
                for rank, (item, source) in enumerate(popular_fill(related, popular, original=evidence), 1)
            ],
        }
