"""Publish anonymous product recommendations for the frozen homepage popularity lists."""
import argparse
import hashlib
import json
from pathlib import Path

from scripts.basket_demo_model import BasketDemoModel
from scripts.c1_demo_model import C1DemoModel
from scripts.evaluate_cart_recommendations import ROOT, TOP_K
from scripts.export_home_popularity import OUTPUT as HOME_POPULARITY


SOURCE_RECEIPT = ROOT / ".runtime/verification/public-recommendation-demo-20261123/source-receipt.json"
# Pins all private raw-ID/alias bindings from the two previously published product cases.
ALIAS_DIGEST = "71d57cebf30a704b917b772e4976c7f0e0f668f918353b7ab320e1961b6fb0fa"
OUTPUT = ROOT / "docs/recommendation-demo/popular-products.json"


def product_cards(home, legacy_aliases, browsing, baskets):
    aliases = dict(legacy_aliases)
    original_ids = {alias: item for item, alias in aliases.items()}
    next_number = max(int(alias) for alias in original_ids if alias.isdecimal()) + 1
    seeds = {row["item"] for rows in home["rankings"].values() for row in rows}
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


def export(receipt):
    aliases = json.loads(receipt.read_bytes())["aliases"]
    encoded = json.dumps(aliases, sort_keys=True, separators=(",", ":")).encode("ascii")
    if hashlib.sha256(encoded).hexdigest() != ALIAS_DIGEST:
        raise ValueError("Private aliases differ from the verified original product cases")
    home = json.loads(HOME_POPULARITY.read_bytes())
    return product_cards(home, aliases, C1DemoModel.load(ROOT), BasketDemoModel.load(ROOT))


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
