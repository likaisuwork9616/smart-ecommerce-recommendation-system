"""Replay development aggregates only after a complete independent query comparison.

The caller binds the complete primary JSONL byte stream to its ranking and source
checks. This stage reads those same bytes again and uses the original independent
four-arm fold and visitor-cluster bootstrap, without another fit or prediction.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from scripts.retailrocket_session_knn_checks_v4 import clear_caches, terms
from scripts.retailrocket_session_knn_readback import GROUPS, METRICS, close, exact, positive_table
from scripts.retailrocket_session_knn_readback_v2 import replay_global


ARMS = ('P0', 'C1', 'D1', 'K1')
OUTCOMES = ('both', 'k1_only', 'c1_only', 'neither')
HIT_OUTCOME = {(True, True): 'both', (True, False): 'k1_only',
               (False, True): 'c1_only', (False, False): 'neither'}
ROOT = Path(__file__).resolve().parents[1]
STAGE12 = Path('reports/stage12')


class HitCounts:
    def __init__(self):
        self.queries = 0
        self.hits = dict.fromkeys(ARMS, 0)
        self.paired = dict.fromkeys(OUTCOMES, 0)

    def add(self, hits, outcome):
        self.queries += 1
        for arm in ARMS:
            self.hits[arm] += hits[arm]
        self.paired[outcome] += 1

    def checked(self, fold):
        exact(self.queries, fold['queries'])
        for arm in ARMS:
            rate = self.hits[arm] / self.queries if self.queries else None
            close(rate, fold['arms'][arm]['metrics']['hit_rate'])
        exact(self.queries, sum(self.paired.values()))
        exact(self.hits['K1'], self.paired['k1_only'] + self.paired['both'])
        exact(self.hits['C1'], self.paired['c1_only'] + self.paired['both'])
        return {'queries': self.queries, 'hits': self.hits, 'K1_vs_C1': self.paired}


class VerifiedQueryStream:
    """Read-only adapter for the frozen V2 global fold's ledger interface."""

    def __init__(self, path, query_count, digest, watch):
        self.path = path
        self.query_count = query_count
        self.digest = digest
        self.watch = watch
        self.stages = {}
        self.main = HitCounts()
        self.conditional = HitCounts()
        self.slices = {field: {group: HitCounts() for group in groups}
                       for field, groups in GROUPS.items()}

    def iter_records(self):
        digest = hashlib.sha256()
        previous = None
        count = 0
        with self.path.open('rb') as stream:
            for line in stream:
                self.watch()
                digest.update(line)
                row = json.loads(line)
                key = row['key']
                if previous is not None and key <= previous:
                    raise ValueError('Unordered or duplicate K1 query during aggregate replay')
                previous = key
                count += 1
                if count > self.query_count:
                    raise ValueError('Extra query during aggregate replay')

                targets = row['targets']
                precise = {}
                hits = {}
                for arm in ARMS:
                    binary, precise[arm] = terms(row['predictions'][arm]['ids'], targets)
                    actual = row['terms'][arm]
                    if any(type(actual[m]) is not float or not math.isfinite(actual[m])
                           for m in ('dcg', 'idcg', *METRICS)):
                        raise ValueError('Non-binary64 metric during aggregate replay')
                    close(actual, binary)
                    hits[arm] = binary['hits'] > 0

                # Frozen contrasts use the paired, verified binary64 query terms.
                # Decimal values above serve the separately defined per-arm folds.
                delta = {'K1_minus_' + arm: {
                    m: row['terms']['K1'][m] - row['terms'][arm][m] for m in METRICS}
                    for arm in ('C1', 'P0', 'D1')}
                exact(row['delta'], delta)
                delta_hex = {name: {m: d.hex() for m, d in metrics.items()}
                             for name, metrics in delta.items()}
                outcome = HIT_OUTCOME[hits['K1'], hits['C1']]
                self.main.add(hits, outcome)
                if row['reachable_targets'] == len(targets):
                    self.conditional.add(hits, outcome)
                if row['slices'].keys() != self.slices.keys():
                    raise ValueError('Incomplete query slice family in aggregate replay')
                for field, group in row['slices'].items():
                    self.slices[field][group].add(hits, outcome)
                yield {'key': key, 'payload': {
                    'expected': row, 'precise': precise, 'delta_hex': delta_hex}}

        if count != self.query_count or digest.hexdigest() != self.digest:
            raise ValueError('K1 query count or SHA-256 differs from complete independent verification')

    def get_stage(self, name):
        return self.stages.get(name)

    def seal_stage(self, name, receipt):
        # Keep these function-local stage results until the complete fold returns.
        self.stages[name] = receipt

    def paired_hits(self, aggregate):
        return {
            'main': self.main.checked(aggregate['main']),
            'conditional': self.conditional.checked(aggregate['conditional']),
            'slices': {field: {group: counts.checked(aggregate['slices'][field][group])
                               for group, counts in groups.items()}
                       for field, groups in self.slices.items()},
        }


def verify_aggregate(primary, paths, config, model, *, queries_checked,
                     verified_query_sha256, watch=lambda: None):
    """Return a statistical-stage receipt; this does not publish a K1 acceptance.

    `queries_checked` and `verified_query_sha256` come from an independent full
    row comparison through paired EOF. `model` carries the independently verified
    fit_audit and raw train support. `paths` and `config` are the frozen V1 inputs.
    All input bytes must remain bound through the caller's final source guard.
    """
    exact(queries_checked, config['fixed_validation']['queries'])
    if not isinstance(verified_query_sha256, str) or not re.fullmatch('[0-9a-f]{64}', verified_query_sha256):
        raise ValueError('Expected a SHA-256 from the complete independent K1 query comparison')
    records = VerifiedQueryStream(primary / 'queries.jsonl', queries_checked, verified_query_sha256, watch)
    clear_caches()
    try:
        replay = replay_global(primary, paths, config, records, model, watch)
    finally:
        clear_caches()
    aggregate = replay['aggregate']
    exact(records.get_stage('global'), {'queries': queries_checked, 'roster_sha256': aggregate['roster_sha256']})
    exact(records.get_stage('bootstrap'), aggregate['uncertainty'])
    return {
        'status': 'passed',
        'stage': 'development_aggregate_and_original_visitor_draws',
        'queries_sha256': verified_query_sha256,
        'queries': replay['queries_checked'],
        'roster_sha256': aggregate['roster_sha256'],
        'bootstrap_replicates': replay['bootstrap_replicates'],
        'paired_hits': records.paired_hits(aggregate),
        'aggregate': aggregate,
    }


def checked_small_input(path, binding):
    data = path.read_bytes()
    if len(data) != binding['bytes'] or hashlib.sha256(data).hexdigest() != binding['sha256']:
        raise ValueError('Changed statistical stage source: ' + path.name)
    return data


def checked_prerequisites(out, expected_count, query_digest):
    signatures = {}
    rosters = set()
    for name in ('k1_cohort.json', 'k1_predictions.json'):
        data = (out / name).read_bytes()
        receipt = json.loads(data)
        exact(receipt['status'], 'passed')
        exact(receipt['queries'], expected_count)
        exact(receipt['queries_sha256'], query_digest)
        if not re.fullmatch('[0-9a-f]{64}', receipt['roster_sha256']):
            raise ValueError('Invalid verified query roster digest')
        rosters.add(receipt['roster_sha256'])
        signatures[name] = hashlib.sha256(data).hexdigest()
    if len(rosters) != 1:
        raise ValueError('Independent cohort and prediction rosters differ')
    return rosters.pop(), signatures


def write_result(path, value):
    # Readers see either the complete receipt or no receipt. An existing result
    # cannot be replaced, even when two publishers act concurrently.
    descriptor, temp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def run_stage(out, root=ROOT):
    out = Path(out).resolve(strict=True)
    receipt_path = out / 'k1_aggregate.json'
    if receipt_path.exists():
        raise FileExistsError('Aggregate receipt already exists: ' + str(receipt_path))
    runtime = root / 'shop-mysql-runtime'
    primary = runtime / 'retailrocket_session_knn_paired_v1'
    paths = {'dataset': runtime / 'retailrocket_dataset_v1',
             'P0': runtime / 'retailrocket_popularity_v1' / 'development',
             'C1': runtime / 'retailrocket_cooccurrence_paired_v1'}
    if any(out.is_relative_to(folder) for folder in (primary, *paths.values())):
        raise ValueError('The result directory is inside an immutable source directory')
    attempt = json.loads((root / STAGE12 / 'retailrocket_session_knn_v1_validation_attempt.json').read_bytes())
    spec_record = attempt['specification']
    spec = json.loads(checked_small_input(root / spec_record['path'], spec_record))
    config = spec['configuration']
    bindings = {r['path']: r for r in [*spec['direct_input_bindings'], *attempt['preservation']['execution_artifacts']]}

    query_path = primary / 'queries.jsonl'
    query_binding = bindings[query_path.relative_to(root).as_posix()]
    query_count = config['fixed_validation']['queries']
    roster, prerequisites = checked_prerequisites(out, query_count, query_binding['sha256'])
    exact(query_path.stat().st_size, query_binding['bytes'])
    sources = (primary / 'fit_audit.json', primary / 'aggregate.json', primary / 'bootstrap.jsonl',
               paths['dataset'] / 'catalog.csv', paths['P0'] / 'item_counts.csv',
               paths['C1'] / 'support.csv', paths['C1'] / 'bootstrap.jsonl')
    bound = {path: bindings[path.relative_to(root).as_posix()] for path in sources}
    for path, source in bound.items():
        checked_small_input(path, source)
    model = {'support': positive_table(paths['C1'] / 'support.csv', ['itemid', 'support'], lambda: None),
             'fit_audit': json.loads((primary / 'fit_audit.json').read_bytes())}
    result = verify_aggregate(primary, paths, config, model, queries_checked=query_count,
                              verified_query_sha256=query_binding['sha256'])
    exact(result['roster_sha256'], roster)
    for path, source in bound.items():
        checked_small_input(path, source)
    if checked_prerequisites(out, query_count, query_binding['sha256']) != (roster, prerequisites):
        raise ValueError('Independent prerequisite receipts changed during statistical replay')
    result['prerequisite_sha256'] = prerequisites
    result['inputs'] = [{k: record[k] for k in ('path', 'bytes', 'sha256')}
                        for record in [spec_record, query_binding, *bound.values()]]
    write_result(receipt_path, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='Directory containing the two verified query receipts')
    run_stage(parser.parse_args().out)
