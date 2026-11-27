"""Publish anonymous recommendations for products on the frozen homepage lists."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from scripts.basket_demo_model import BasketDemoModel
from scripts.c1_demo_model import C1DemoModel
from scripts.evaluate_cart_recommendations import DB, ROOT, TOP_K
from scripts.export_home_popularity import OUTPUT as HOME_POPULARITY
from scripts.score_home_first_view_acceptance import FROZEN_WINDOWS, frozen_rankings


SOURCE_RECEIPT = ROOT / ".runtime/verification/public-recommendation-demo-20261123/source-receipt.json"
# Pins all private raw-ID/alias bindings from the two previously published product cases.
ALIAS_DIGEST = "71d57cebf30a704b917b772e4976c7f0e0f668f918353b7ab320e1961b6fb0fa"
OUTPUT = ROOT / "docs/recommendation-demo/popular-products.json"


def cards_for_seeds(seeds, aliases, browsing, baskets):
    """Build cards in alias order, registering previously unseen recommendation targets."""
    original_ids = {alias: item for item, alias in aliases.items()}
    next_number = max(int(alias) for alias in original_ids if alias.isdecimal()) + 1
    cards = {}
    for seed in sorted(seeds, key=int):
        item = original_ids[seed]
        rankings = {}
        for mode in ("browse", "cart", "purchase"):
            response = browsing.recommend(item) if mode == "browse" else baskets.recommend(mode, item)
            rows = response["recommendations"]
            items = {row["item_id"] for row in rows}
            if len(rows) != TOP_K or len(items) != TOP_K or item in items:
                raise ValueError(f"Expected ten distinct other items for {seed}/{mode}")
            public_rows = []
            for row in rows:
                target = row["item_id"]
                if target not in aliases:
                    aliases[target] = str(next_number)
                    next_number += 1
                source = "popular" if row["source"] == "popularity" else row["source"]
                public_rows.append([aliases[target], source])
            rankings[mode] = public_rows
        cards[seed] = {"item": seed, "rankings": rankings}
    return cards


def register_first_view_items(aliases, candidate):
    next_number = max(int(value) for value in aliases.values() if value.isdecimal()) + 1
    for item, _ in candidate:
        if item not in aliases:
            aliases[item] = str(next_number)
            next_number += 1


def product_cards_with_aliases(home, legacy_aliases, browsing, baskets, *, candidate=()):
    aliases = dict(legacy_aliases)
    homepage_seeds = {row["item"] for rows in home["rankings"].values() for row in rows}
    cards = cards_for_seeds(homepage_seeds, aliases, browsing, baskets)
    # All existing detail targets receive their published aliases before any
    # first-view items. Reserve the whole first-view list before its card targets.
    register_first_view_items(aliases, candidate)
    extra_seeds = {aliases[item] for item, _ in candidate} - homepage_seeds
    cards.update(cards_for_seeds(extra_seeds, aliases, browsing, baskets))
    return cards, aliases


def product_cards(home, legacy_aliases, browsing, baskets, *, candidate=()):
    cards, _ = product_cards_with_aliases(home, legacy_aliases, browsing, baskets, candidate=candidate)
    return cards


def load_product_inputs(receipt):
    aliases = json.loads(receipt.read_bytes())["aliases"]
    encoded = json.dumps(aliases, sort_keys=True, separators=(",", ":")).encode("ascii")
    if hashlib.sha256(encoded).hexdigest() != ALIAS_DIGEST:
        raise ValueError("Private aliases differ from the verified original product cases")
    home = json.loads(HOME_POPULARITY.read_bytes())
    return home, aliases, C1DemoModel.load(ROOT), BasketDemoModel.load(ROOT)


def load_home_rankings():
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return frozen_rankings(db, FROZEN_WINDOWS)


def export(receipt):
    _, candidate = load_home_rankings()
    return product_cards(*load_product_inputs(receipt), candidate=candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-receipt", type=Path, default=SOURCE_RECEIPT,
                        help="private alias receipt from the original public product cases")
    parser.add_argument("--check", action="store_true", help="compare with the published snapshot")
    args = parser.parse_args()
    cards = export(args.source_receipt)
    if args.check:
        if cards != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Published product recommendations differ from the frozen models")
        print(f"All three top tens and sources match for {len(cards)} homepage products.")
    else:
        OUTPUT.write_text(json.dumps(cards, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
