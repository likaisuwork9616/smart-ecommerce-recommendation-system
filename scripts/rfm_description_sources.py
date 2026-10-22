"""Read-only RFM input provenance and independent full source-ID rosters.

``metadata_snapshot`` only hashes CSV bytes. ``read_inputs`` is a future
execution operation: it parses the accepted bundle and the two minimum event /
identity source projections, without rebuilding RFM or describing any values.
"""
from __future__ import annotations

import csv
from pathlib import Path

from scripts import verify_rfm_description as prior

base, artifacts, same = prior.base, prior.artifacts, prior.same
evaluation = prior.prior
build = evaluation.prior
contract = evaluation.dataset_contract
ROOT = Path(__file__).resolve().parents[1]
PROJECTION = {name: tuple(base.COLUMNS[name]) for name in ('orders', 'customers')}
PROOF_FIELDS = (
    'order_id', 'customer_unique_id', 'purchase_at', 'approval_at', 'delivery_at',
    'in_window', 'history_event_eligible', 'window_event_eligible',
    'primary_exclusion_reason', 'window_quarantine', 'approval_missing_or_invalid',
)


def _require(condition, message):
    if condition is not True:
        raise ValueError(message)


def metadata_snapshot(root=ROOT):
    """Verify the whole accepted 33-source chain, then bind all 35 public inputs.

    No CSV header or value parser is used. Private fingerprints stay in this
    returned private-capable object, never in a public aggregate projection.
    """
    root = Path(root)
    implementation = base.read_json(root / prior.SPEC)
    report = prior.verify_sources(implementation, root)
    sources = [*implementation['sources'], *[
        base.descriptor(root / path, root) for path in (prior.SPEC, prior.OUTPUT)]]
    _require(len(sources) == 35 and len({item['path'] for item in sources}) == 35,
             'The complete thirty-five original execution inputs are required')
    private_paths = sorted({prior.GUARD, prior.RECEIPT, evaluation.GUARD,
                            *evaluation.PRIVATE_METADATA})
    accepted = base.read_json(root / build.OUTPUT)
    snapshot = {
        'format_version': 1,
        'public_sources': sources,
        'private_inputs': [base.descriptor(root / path, root) for path in private_paths],
        'accepted_bundle': artifacts.bundle_guard(root / build.PRIVATE),
        'accepted_rows': accepted['acceptance']['rows'],
        'metadata_checks': report['accepted_dataset_metadata']['checks'],
    }
    _require(same(report, prior.verify_sources(implementation, root)),
             'Accepted metadata changed during the input snapshot')
    return snapshot


def _key(value):
    return type(value) is str and bool(value) and value == value.strip()


def derive_roster(tables):
    """Independently derive source IDs and per-order event proofs, never money.

    The universe is reconstructed from the original event / identity projections,
    not from the already filtered customer or order output CSVs. Future unmapped
    orders remain outside the pre-T roster; any unmapped historical order fails.
    """
    _require(type(tables) is dict and set(tables) == set(PROJECTION),
             'Exactly the original order and customer projections are required')
    for name, columns in PROJECTION.items():
        _require(type(tables[name]) is list, 'Source projections must be lists')
        for row in tables[name]:
            _require(type(row) is dict and set(columns) <= set(row)
                     and all(type(value) is str for value in row.values()),
                     'Source rows must retain all required raw string fields')
    orders = base.unique_rows(tables['orders'], 'order_id')
    customers = base.unique_rows(tables['customers'], 'customer_id')
    _require(all(_key(value) for value in orders) and all(_key(value) for value in customers),
             'Required source master IDs must be canonical nonempty strings')
    customer_ids, order_ids, window_order_ids, proofs = set(), [], [], []
    for oid in sorted(orders):
        row = orders[oid]
        decision = contract.event_decision(row)
        purchase = base.clock(row['order_purchase_timestamp'])
        if purchase >= contract.CUTOFF:
            continue
        uid = customers.get(row['customer_id'], {}).get('customer_unique_id', '')
        _require(_key(uid), 'Unmapped historical identity prevents full source-ID acceptance')
        order_ids.append(oid)
        history = decision['history_eligible']
        window = history and decision['in_window']
        if history:
            customer_ids.add(uid)
        if window:
            window_order_ids.append(oid)
        approval = base.clock(row['order_approved_at'])
        delivery = base.clock(row['order_delivered_customer_date'])
        proofs.append({
            'order_id': oid, 'customer_unique_id': uid, 'purchase_at': str(purchase),
            'approval_at': str(approval) if approval is not None else None,
            'delivery_at': str(delivery) if delivery is not None else None,
            'in_window': decision['in_window'], 'history_event_eligible': history,
            'window_event_eligible': window, 'primary_exclusion_reason': decision['reason'],
            'window_quarantine': decision['window_quarantine'],
            'approval_missing_or_invalid': decision['approval_unknown'],
        })
    return {'customer_ids': sorted(customer_ids), 'order_ids': order_ids,
            'window_order_ids': window_order_ids, 'order_proofs': proofs}


def _source_projections(root, frozen_headers):
    tables = {}
    for name, columns in PROJECTION.items():
        with (root / base.FILES[name]).open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            _require(same(reader.fieldnames, frozen_headers[name]),
                     'Original source header differs from the frozen evidence')
            rows = []
            for row in reader:
                _require(set(row) == set(frozen_headers[name])
                         and all(type(value) is str for value in row.values()),
                         'Ragged original event or identity source row')
                rows.append({column: row[column] for column in columns})
            tables[name] = rows
    return tables


def _check_dataset_roster(dataset, roster, frozen_contract):
    _require(type(dataset) is dict and set(dataset) == {'customers', 'orders', 'summary'},
             'Accepted dataset payload differs')
    for key, filename in (('customers', 'customers.csv'), ('orders', 'order_decisions.csv')):
        _require(type(dataset[key]) is list, 'Accepted dataset rows must be lists')
        artifacts._csv_bytes(dataset[key], frozen_contract['planned_schemas'][filename])
    artifacts.validate_semantics(dataset, frozen_contract)
    _require(same([row['customer_unique_id'] for row in dataset['customers']], roster['customer_ids']),
             'Accepted customer IDs differ from the independent full source roster')
    _require(same([row['order_id'] for row in dataset['orders']], roster['order_ids']),
             'Accepted pre-T order IDs differ from the independent full source roster')
    _require(same([row['order_id'] for row in dataset['orders'] if row['window_event_eligible']],
                  roster['window_order_ids']),
             'Accepted window order IDs differ from the independent full source roster')
    actual_proofs = [{key: row[key] for key in PROOF_FIELDS} for row in dataset['orders']]
    _require(same(actual_proofs, roster['order_proofs']),
             'Accepted event decisions or customer mappings differ from original source proofs')


def read_inputs(root, expected_snapshot):
    """Future execution: load the accepted bundle and verify full source-ID proof.

    The current preparation task must not call this against real data. There is
    no write, builder, descriptor, segmentation or training operation here.
    """
    root = Path(root)
    before = metadata_snapshot(root)
    _require(same(before, expected_snapshot), 'Frozen execution input snapshot differs before parsing')
    frozen_contract = base.read_json(root / contract.SPEC)
    build_specification = base.read_json(root / build.SPEC)
    evaluation_specification = base.read_json(root / evaluation.SPEC)
    dataset = artifacts.read_bundle(root / build.PRIVATE, frozen_contract, build_specification['sources'])
    _require(same({'customers.csv': len(dataset['customers']), 'order_decisions.csv': len(dataset['orders'])},
                  before['accepted_rows']), 'Accepted dataset row counts differ')
    roster = derive_roster(_source_projections(root, frozen_contract['source_headers']))
    _check_dataset_roster(dataset, roster, frozen_contract)
    after = metadata_snapshot(root)
    _require(same(before, after), 'Frozen execution inputs changed during complete roster readback')
    return {'dataset': dataset, 'evaluation_spec': evaluation_specification,
            'customer_ids': roster['customer_ids'], 'order_ids': roster['order_ids'],
            'window_order_ids': roster['window_order_ids'], 'snapshot': after}
