"""Export one August gain and one loss from the returning-home paired development study."""
import argparse
from contextlib import closing
import json
import sqlite3

from scripts.evaluate_august_home_browse import load_study_inputs
from scripts.evaluate_august_returning_home import candidate_ranking, returning_visitors
from scripts.evaluate_august_returning_home_paired_slots import OUTPUT as AUGUST, score_visitors, slotted
from scripts.evaluate_cart_popular_fill import first_hit
from scripts.evaluate_cart_recommendations import DB, ROOT
from scripts.export_popular_product_recommendations import (
    OUTPUT as PRODUCT_CARDS, SOURCE_RECEIPT, load_home_rankings, load_product_inputs, product_cards_with_aliases,
)


OUTPUT = ROOT / "docs/recommendation-demo/returning-home-cases.json"


def public_case(seed, targets, popular, model, aliases, ranks, count):
    _, original, _ = candidate_ranking(seed, popular, model)
    baseline, _ = slotted(popular, seed)
    candidate, _ = slotted(original, seed)
    first_views = sorted(targets, key=int)
    next_alias = max(int(alias) for alias in aliases.values() if alias.isdecimal()) + 1
    for item in [seed, *first_views, *baseline, *candidate]:
        if item not in aliases:
            aliases[item] = str(next_alias)
            next_alias += 1
    actual = [aliases[item] for item in first_views]
    arms = [[aliases[item] for item in ranking] for ranking in (baseline, candidate)]
    if tuple(first_hit(arm, actual) for arm in arms) != ranks:
        raise ValueError("Public rankings differ from the scored visitor's first-hit ranks")
    return {"count": count, "previous": aliases[seed], "actual": actual, "baseline": arms[0], "candidate": arms[1]}


def export():
    ranking, scope, windows = load_study_inputs()
    home, legacy, model, baskets = load_product_inputs(SOURCE_RECEIPT)
    _, first_view = load_home_rankings()
    cards, aliases = product_cards_with_aliases(home, legacy, model, baskets, candidate=first_view)
    if cards != json.loads(PRODUCT_CARDS.read_bytes()) or any(aliases[item] != alias for item, alias in ranking):
        raise ValueError("Item aliases differ from the published homepage or product cards")

    popular = [item for item, _ in ranking]
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        visitors = list(returning_visitors(db, windows))
    exclusive_ranks = {}

    def capture(visitor, first_view_time, base_rank, candidate_rank):
        if (base_rank is None) != (candidate_rank is None):
            exclusive_ranks[visitor] = (base_rank, candidate_rank)

    result = score_visitors(visitors, popular, model, rank_audit=capture)
    archive = json.loads(AUGUST.read_bytes())
    if scope != archive["utc_windows_start_inclusive_end_exclusive"] or any(
        value != archive[field] for field, value in result.items()
    ):
        raise ValueError("August roster, paired ranks or totals differ from the archived development report")
    counts = {"gained": result["overall"]["candidate_only_gained"], "lost": result["overall"]["baseline_only_lost"]}
    cases = {}
    # Use the first single-target visitor in each group in the frozen roster order.
    for visitor, _, seed, _, targets in visitors:
        if visitor not in exclusive_ranks or len(targets) != 1:
            continue
        ranks = exclusive_ranks[visitor]
        group = "gained" if ranks[0] is None else "lost"
        if group not in cases:
            cases[group] = public_case(seed, targets, popular, model, aliases, ranks, counts[group])
            if len(cases) == len(counts):
                return {key: cases[key] for key in counts}
    raise ValueError("August roster lacks a single-target case for one of the outcomes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="rebuild and compare with the public cases")
    args = parser.parse_args()
    cases = export()
    if args.check:
        if cases != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Published returning-home cases differ from the August replay")
    else:
        OUTPUT.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8", newline="\n")
    for group, case in cases.items():
        ranks = [first_hit(case[arm], case["actual"]) for arm in ("baseline", "candidate")]
        print(f"{group} ({case['count']} visitors): baseline rank {ranks[0]}, candidate rank {ranks[1]}")


if __name__ == "__main__":
    main()
