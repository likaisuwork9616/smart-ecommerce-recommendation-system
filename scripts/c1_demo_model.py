"""Single-item browsing at the close of the frozen Retailrocket C1 training window."""
import csv
import hashlib
import json
import sqlite3
from bisect import bisect_left
from contextlib import closing
from pathlib import Path


RELEASE = "reports/stage10/retailrocket_c1_p0_v1_research_release.json"
C1 = "shop-mysql-runtime/retailrocket_cooccurrence_paired_v1"
EDGES = f"{C1}/oracle.sqlite"
QUERIES = f"{C1}/queries.jsonl"
SUPPORT = f"{C1}/support.csv"
POPULARITY = "shop-mysql-runtime/retailrocket_popularity_v1/development/item_counts.csv"


def read_counts(path: Path, column: str) -> dict[str, int]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {row["itemid"]: int(row[column]) for row in csv.DictReader(stream)}


class C1DemoModel:
    def __init__(self, database: Path, sessions: dict[str, int], views: dict[str, int]):
        self._database_uri = database.resolve().as_uri() + "?mode=ro&immutable=1"
        self._sessions = sessions
        self._views = views
        self._ids = sorted(sessions)
        self._popular = sorted(views, key=lambda item: (-views[item], int(item)))

    @classmethod
    def load(cls, root: Path):
        """Load accepted train counts and check the published identities of all inputs."""
        root = Path(root)
        receipt = json.loads((root / RELEASE).read_text(encoding="utf-8"))
        sources = {entry["path"]: entry for entry in receipt["sources"]}
        for name in (EDGES, SUPPORT, POPULARITY):
            path = root / name
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != sources[name]["sha256"]:
                raise ValueError(f"本機檔案與已驗收的研究版本不符：{name}")
        return cls(root / EDGES, read_counts(root / SUPPORT, "support"),
                   read_counts(root / POPULARITY, "count"))

    def __len__(self):
        return len(self._ids)

    def _item(self, item_id: str) -> dict:
        return {"item_id": item_id, "sessions": self._sessions[item_id],
                "views": self._views[item_id]}

    def search(self, prefix: str = "", limit: int = 8) -> list[dict]:
        """Show popular examples by default and the exact ID first for prefix searches."""
        if limit <= 0:
            return []
        if not prefix:
            return [self._item(item) for item in self._popular[:limit]]
        if not prefix.isascii() or not prefix.isdigit():
            return []
        start = bisect_left(self._ids, prefix)
        stop = bisect_left(self._ids, prefix + ":", lo=start)  # ':' sorts after '9'.
        return [self._item(item) for item in self._ids[start:min(start + limit, stop)]]

    def recommend(self, item_id: str) -> dict:
        item = self._item(item_id)
        # The accepted oracle indexed both directions of the frozen train edges.
        sql = """
            SELECT b, n FROM edges WHERE a = ?
            UNION ALL
            SELECT a, n FROM edges WHERE b = ?
        """
        with closing(sqlite3.connect(self._database_uri, uri=True)) as connection:
            neighbors = dict(connection.execute(sql, (item_id, item_id)))
        # For a single seed the C1 denominator is identical for every neighbor.
        # Integer shared-session counts preserve exact C1 ordering before P0/ID ties.
        ranked = sorted(neighbors, key=lambda other: (-neighbors[other], -self._views[other], int(other)))[:10]
        # All fitted items precede the cutoff. Unfitted items have zero C1 and P0
        # scores and cannot enter the top ten ahead of positive-view training items.
        if len(ranked) < 10:
            ranked.extend(other for other in self._popular[:10] if other not in neighbors)
        recommendations = [
            {"rank": rank, "item_id": other, "views": self._views[other],
             "co_sessions": neighbors.get(other, 0),
             "source": "cooccurrence" if other in neighbors else "popularity"}
            for rank, other in enumerate(ranked[:10], start=1)
        ]
        return {**item, "positive_candidates": len(neighbors), "recommendations": recommendations}
