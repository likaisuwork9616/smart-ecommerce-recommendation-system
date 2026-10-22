"""Strict private CSV bundle persistence and semantic readback for Stage 6."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import uuid

from scripts import audit_rfm_feasibility as base
from scripts import freeze_rfm_dataset_spec as frozen

FILES = ('customers.csv', 'order_decisions.csv', 'manifest.json')
MAX = 2**63 - 1
MIN = -(2**63)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def _digest(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def bundle_guard(output):
    output = Path(output)
    if not output.is_dir() or {p.name for p in output.iterdir()} != set(FILES):
        raise ValueError('Bundle must contain exactly the three contracted files')
    if any((output / name).is_symlink() for name in FILES):
        raise ValueError('Bundle files must not be symlinks')
    return {name: _digest((output / name).read_bytes()) for name in FILES}


def _cell(value, kind):
    nullable = kind.startswith('nullable_')
    kind = kind.removeprefix('nullable_')
    if value is None:
        if not nullable:
            raise ValueError('Null in a required field')
        return ''
    if kind == 'bool':
        if type(value) is not bool:
            raise ValueError('Expected a bool')
        return 'true' if value else 'false'
    if kind in ('int64', 'nonnegative_int64'):
        if type(value) is not int or not MIN <= value <= MAX or (kind.startswith('nonnegative') and value < 0):
            raise ValueError('Expected a checked int64')
        return str(value)
    if kind == 'float64':
        if type(value) is not float or not math.isfinite(value):
            raise ValueError('Expected finite binary64')
        return format(value, '.17g')
    if type(value) is not str or not value or value != value.strip():
        raise ValueError('Expected a nonempty string')
    if kind in ('timestamp', 'timestamp_before_T'):
        stamp = base.clock(value)
        if stamp is None or (kind == 'timestamp_before_T' and stamp >= frozen.CUTOFF):
            raise ValueError('Invalid timestamp')
    return value


def _parse(text, kind):
    if text == '' and kind.startswith('nullable_'):
        return None
    simple = kind.removeprefix('nullable_')
    if simple == 'bool':
        if text not in ('true', 'false'):
            raise ValueError('Noncanonical bool')
        value = text == 'true'
    elif simple in ('int64', 'nonnegative_int64'):
        if not re.fullmatch(r'(?:0|-[1-9]\d*|[1-9]\d*)', text):
            raise ValueError('Noncanonical integer')
        value = int(text)
    elif simple == 'float64':
        value = float(text)
    else:
        value = text
    if _cell(value, kind) != text:
        raise ValueError('Noncanonical serialized value')
    return value


def _csv_bytes(rows, schema):
    names = [name for name, _ in schema]
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(names)
    for row in rows:
        if list(row) != names:
            raise ValueError('Row schema or column order differs')
        writer.writerow([_cell(row[name], kind) for name, kind in schema])
    return stream.getvalue().encode('utf-8')


def _read_csv(path, schema):
    data = path.read_bytes()
    rows = list(csv.reader(io.StringIO(data.decode('utf-8'), newline='')))
    if not rows or rows[0] != [name for name, _ in schema]:
        raise ValueError('CSV schema differs')
    result = []
    for values in rows[1:]:
        if len(values) != len(schema):
            raise ValueError('CSV width differs')
        result.append({name: _parse(value, kind) for value, (name, kind) in zip(values, schema)})
    if _csv_bytes(result, schema) != data:
        raise ValueError('CSV bytes are not canonical')
    return result


def _same(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is float:
        return struct.pack('!d', left) == struct.pack('!d', right)
    if isinstance(left, dict):
        return set(left) == set(right) and all(_same(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def validate_semantics(dataset, contract):
    """Reconstruct customer values from the full ledger; no source reclassification."""
    if contract['policy'] != frozen.policy() or contract['planned_schemas'] != frozen.schemas():
        raise ValueError('Frozen contract differs')
    customers, orders = dataset['customers'], dataset['orders']
    for rows, key in ((customers, 'customer_unique_id'), (orders, 'order_id')):
        ids = [row[key] for row in rows]
        if ids != sorted(set(ids)):
            raise ValueError('IDs must be complete unique canonical order')
    grouped = defaultdict(list)
    universe = set()
    for row in orders:
        purchase = base.clock(row['purchase_at'])
        approval = base.clock(row['approval_at'])
        delivery = base.clock(row['delivery_at'])
        reason = row['primary_exclusion_reason']
        if reason not in frozen.schemas()['primary_exclusion_precedence']:
            raise ValueError('Unknown exclusion reason')
        if row['in_window'] != (frozen.START <= purchase < frozen.CUTOFF):
            raise ValueError('Window flag differs')
        eligible = reason == 'eligible'
        if row['history_event_eligible'] != eligible or row['window_event_eligible'] != (eligible and row['in_window']):
            raise ValueError('Eligibility flags differ')
        if eligible and (delivery is None or not purchase <= delivery < frozen.CUTOFF or
                         (approval is not None and not purchase <= approval <= delivery)):
            raise ValueError('Eligible event leaks cutoff or violates chronology')
        valid_reason = {
            'status_not_delivered': True,  # Snapshot status is bound to raw-source acceptance.
            'missing_or_invalid_delivery': delivery is None,
            'delivery_before_purchase': delivery is not None and delivery < purchase,
            'delivery_at_or_after_T': delivery is not None and delivery >= frozen.CUTOFF,
            'approval_clock_conflict': (delivery is not None and purchase <= delivery < frozen.CUTOFF
                                        and approval is not None and not purchase <= approval <= delivery),
            'eligible': True,
        }
        if not valid_reason[reason]:
            raise ValueError('Exclusion reason contradicts ledger clocks')
        if row['approval_missing_or_invalid'] != (approval is None):
            raise ValueError('Approval quality flag differs')
        quarantine = row['in_window'] and reason in ('missing_or_invalid_delivery', 'delivery_before_purchase', 'approval_clock_conflict')
        if row['window_quarantine'] != quarantine:
            raise ValueError('Quarantine flag differs')
        if row['price_complete'] != (row['product_cents'] is not None):
            raise ValueError('Price completeness differs')
        amounts = [row[k] for k in ('product_cents', 'freight_cents', 'payment_cents')]
        delta = amounts[2] - amounts[0] - amounts[1] if all(v is not None for v in amounts) else None
        if row['payment_difference_cents'] != delta:
            raise ValueError('Reconciliation differs')
        grouped[row['customer_unique_id']].append(row)
        if eligible:
            universe.add(row['customer_unique_id'])
    if universe != {row['customer_unique_id'] for row in customers}:
        raise ValueError('Customer universe differs from eligible history')
    for customer in customers:
        rows = grouped[customer['customer_unique_id']]
        selected = [r for r in rows if r['window_event_eligible']]
        n = len(selected)
        quarantine = sum(r['window_quarantine'] for r in rows)
        unknown = sum(not r['price_complete'] for r in selected)
        last = max((r['purchase_at'] for r in selected), default=None)
        seconds = int((frozen.CUTOFF - base.clock(last)).total_seconds()) if last else None
        state = ('active_money_unknown' if unknown else
                 ('active_with_quarantine' if n else 'inactive_with_quarantine') if quarantine else
                 'active_complete' if n else 'inactive_complete')
        monetary = None if unknown or quarantine else sum(r['product_cents'] for r in selected)
        expected = {
            'customer_unique_id': customer['customer_unique_id'],
            'S': str(frozen.START), 'T': str(frozen.CUTOFF), 'activity_state': state,
            'rfm_usable': state == 'active_complete', 'monetary_complete': monetary is not None,
            'last_window_purchase_at': last, 'recency_seconds': seconds,
            'recency_days': seconds / 86400 if seconds is not None else None,
            'frequency_orders': n, 'monetary_product_cents': monetary,
            'window_quarantined_orders': quarantine, 'window_price_unknown_orders': unknown,
            'window_approval_missing_or_invalid_orders': sum(r['approval_missing_or_invalid'] for r in selected),
            'window_payment_missing_or_invalid_orders': sum(r['payment_cents'] is None for r in selected),
            'window_freight_missing_or_invalid_orders': sum(r['freight_cents'] is None for r in selected),
        }
        if not _same(customer, expected):
            raise ValueError('Customer R/F/M, mask, state or quality counters differ')
    _validate_summary(dataset)
    return True


def _validate_summary(dataset):
    """Check every population/money summary value derivable from the two ledgers.

    Raw item/payment quality and raw future row counts require the bound source
    audit; the order ledger intentionally does not repeat those raw tables.
    """
    orders, customers, summary = dataset['orders'], dataset['customers'], dataset['summary']
    history = [r for r in orders if r['history_event_eligible']]
    window = [r for r in orders if r['window_event_eligible']]
    quarantined = [r for r in orders if r['window_quarantine']]
    universe = {r['customer_unique_id'] for r in customers}
    active = {r['customer_unique_id'] for r in window}
    masked = {r['customer_unique_id'] for r in customers if r['monetary_product_cents'] is None}
    reasons = dict(sorted(Counter(r['primary_exclusion_reason'] for r in orders).items()))
    known = [r for r in window if r['product_cents'] is not None]
    published = sum(r['monetary_product_cents'] for r in customers if r['monetary_product_cents'] is not None)
    masked_known = sum(r['product_cents'] for r in known if r['customer_unique_id'] in masked)
    states = {state: 0 for state in frozen.policy()['activity_states']}
    states.update(Counter(r['activity_state'] for r in customers))
    def support(column):
        values = [r[column] for r in window if r[column] is not None]
        return {'valid_orders': len(values), 'unknown_or_invalid_orders': len(window) - len(values),
                'sum_cents_on_valid_orders': sum(values) if values else None}
    def reconcile(rows):
        deltas = [r['payment_difference_cents'] for r in rows if r['payment_difference_cents'] is not None]
        return {
            'comparable_orders': len(deltas), 'exact_equal_cents_orders': sum(v == 0 for v in deltas),
            'nonzero_difference_orders': sum(v != 0 for v in deltas),
            'payment_higher_orders': sum(v > 0 for v in deltas),
            'payment_lower_orders': sum(v < 0 for v in deltas),
            'absolute_difference_above_one_cent_orders': sum(abs(v) > 1 for v in deltas),
            'sum_payment_minus_items_freight_cents': sum(deltas) if deltas else None,
            'one_cent_is_business_acceptance_tolerance': False,
            'equal_total_is_proof_of_net_settlement': False,
        }
    expected = {
        'source': {'purchase_before_T_orders': len(orders)},
        'history': {
            'event_candidates_before_approval_check': len(history) + reasons.get('approval_clock_conflict', 0),
            'approval_conflict_orders': reasons.get('approval_clock_conflict', 0),
            'event_eligible_orders': len(history), 'customer_universe': len(customers),
            'approval_missing_or_invalid_eligible_orders': sum(r['approval_missing_or_invalid'] for r in history),
            'order_decisions_scope_rows': len(orders), 'mutually_exclusive_primary_reasons': reasons,
        },
        'window': {
            'event_candidates_before_approval_check': len(window) + sum(r['in_window'] and r['primary_exclusion_reason'] == 'approval_clock_conflict' for r in orders),
            'approval_conflict_orders': sum(r['in_window'] and r['primary_exclusion_reason'] == 'approval_clock_conflict' for r in orders),
            'event_eligible_orders': len(window), 'active_customers': len(active),
            'zero_eligible_window_customers': len(customers) - len(active),
            'price_unknown_orders': len(window) - len(known),
            'approval_missing_or_invalid_eligible_orders': sum(r['approval_missing_or_invalid'] for r in window),
            'price': support('product_cents'), 'freight': support('freight_cents'), 'payments': support('payment_cents'),
            'payment_reconciliation': reconcile(window),
        },
        'window_quarantine': {
            'orders': len(quarantined),
            'primary_reasons': dict(sorted(Counter(r['primary_exclusion_reason'] for r in quarantined).items())),
            'orders_linked_to_universe': sum(r['customer_unique_id'] in universe for r in quarantined),
            'orders_outside_universe': sum(r['customer_unique_id'] not in universe for r in quarantined),
            'customers_inside_universe': len({r['customer_unique_id'] for r in quarantined} & universe),
            'not_completed_before_T_orders': sum(r['in_window'] and r['primary_exclusion_reason'] == 'delivery_at_or_after_T' for r in orders),
        },
        'customer_states': states,
        'customer_money_conservation': {
            'eligible_window_product_known_orders': len(known),
            'eligible_window_product_unknown_orders': len(window) - len(known),
            'eligible_window_product_cents_on_known_orders': sum(r['product_cents'] for r in known),
            'published_customer_product_cents': published,
            'known_product_cents_masked_customer_subsets': masked_known,
            'known_product_orders_in_masked_customer_subsets': sum(r['customer_unique_id'] in masked for r in known),
            'unknown_product_orders_in_masked_customer_subsets': sum(r['customer_unique_id'] in masked for r in window if r['product_cents'] is None),
            'masked_customers': len(masked), 'unmasked_customers': len(customers) - len(masked),
            'inactive_complete_zero_customers': states['inactive_complete'],
            'known_product_cents_equal_published_plus_masked_known': sum(r['product_cents'] for r in known) == published + masked_known,
            'unknown_product_amounts_are_zero_filled': False,
        },
        'reconciliation': {'all_before_T': reconcile(orders), 'history_event_eligible': reconcile(history),
                           'window_event_eligible': reconcile(window)},
    }
    def compare(actual, wanted):
        if isinstance(wanted, dict):
            if not isinstance(actual, dict) or not set(wanted) <= set(actual):
                raise ValueError('Missing aggregate population or money summary')
            for key in wanted:
                compare(actual[key], wanted[key])
        elif not _same(actual, wanted):
            raise ValueError('Aggregate population or money summary differs from ledger')
    compare(summary, expected)
    if not summary.get('invariants') or any(value is not True for value in summary['invariants'].values()):
        raise ValueError('Aggregate invariant failed')


def _spec_descriptor(contract, bindings):
    matches = [b for b in bindings if b['path'] == frozen.SPEC]
    if len(matches) != 1:
        raise ValueError('Exactly one frozen contract binding is required')
    return matches[0]


def read_bundle(output, contract, source_bindings):
    output = Path(output)
    guard = bundle_guard(output)
    manifest = base.read_json(output / 'manifest.json')
    if set(manifest) != set(frozen.schemas()['manifest.json']):
        raise ValueError('Manifest keys differ')
    if (not _same(manifest['specification_bytes_sha'], _spec_descriptor(contract, source_bindings)) or
        not _same(manifest['source_bindings'], source_bindings) or not _same(manifest['schema'], contract['planned_schemas'])):
        raise ValueError('Manifest source version or schema differs')
    if not _same(manifest['private_bytes_sha'], {name: guard[name] for name in FILES[:2]}):
        raise ValueError('Private CSV digest differs')
    customers = _read_csv(output / FILES[0], contract['planned_schemas'][FILES[0]])
    orders = _read_csv(output / FILES[1], contract['planned_schemas'][FILES[1]])
    if not _same(manifest['rows'], {FILES[0]: len(customers), FILES[1]: len(orders)}):
        raise ValueError('Manifest row count differs')
    dataset = {'customers': customers, 'orders': orders, 'summary': manifest['population_and_state_counts']}
    validate_semantics(dataset, contract)
    if not _same(manifest['readback_acceptance'], _acceptance(dataset)):
        raise ValueError('Manifest acceptance differs')
    if json_bytes(manifest) != (output / FILES[2]).read_bytes():
        raise ValueError('Manifest bytes are not canonical')
    return dataset


def _acceptance(dataset):
    return {'all_values_read_back': True, 'canonical_ids': True, 'schema_types_nulls': True,
            'customer_order_semantics': True,
            'rows': {FILES[0]: len(dataset['customers']), FILES[1]: len(dataset['orders'])},
            'cells_compared': (len(dataset['customers']) + len(dataset['orders'])) * 16}


def verify_bundle(output, contract, source_bindings, expected_guard=None):
    if expected_guard is not None and not _same(bundle_guard(output), expected_guard):
        raise ValueError('Immutable private output guard differs')
    return _acceptance(read_bundle(output, contract, source_bindings))


def write_bundle(dataset, contract, source_bindings, output):
    output = Path(output)
    if output.exists():
        raise ValueError('Entire private output namespace must be absent')
    validate_semantics(dataset, contract)
    payload = {
        FILES[0]: _csv_bytes(dataset['customers'], contract['planned_schemas'][FILES[0]]),
        FILES[1]: _csv_bytes(dataset['orders'], contract['planned_schemas'][FILES[1]]),
    }
    manifest = {
        'specification_bytes_sha': _spec_descriptor(contract, source_bindings),
        'source_bindings': source_bindings, 'schema': contract['planned_schemas'],
        'rows': _acceptance(dataset)['rows'],
        'private_bytes_sha': {name: _digest(data) for name, data in payload.items()},
        'population_and_state_counts': dataset['summary'],
        'readback_acceptance': _acceptance(dataset),
    }
    payload[FILES[2]] = json_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name + '.staging-' + uuid.uuid4().hex)
    staging.mkdir()
    # A failed stage is deliberately retained as private evidence, never published.
    for name, data in payload.items():
        with (staging / name).open('xb') as stream:
            stream.write(data)
    restored = read_bundle(staging, contract, source_bindings)
    if not _same(restored['customers'], dataset['customers']) or not _same(restored['orders'], dataset['orders']):
        raise ValueError('Full typed CSV readback differs')
    if restored['summary'] != dataset['summary']:
        raise ValueError('Aggregate manifest readback differs')
    staging.rename(output)
    return verify_bundle(output, contract, source_bindings)
