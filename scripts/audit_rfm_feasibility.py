"""Read-only Stage 6 input inventory; never build customer RFM or segments."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = 'reports/stage6/rfm_feasibility_specification.json'
OUTPUT = 'reports/stage6/rfm_feasibility.json'
CODE = 'scripts/audit_rfm_feasibility.py'
TEST = 'tests/test_rfm_feasibility.py'
EVENT = 'reports/stage4/event_source_availability.json'
EVENT_SHA = 'fc5fdf4018a8b3d3202d8b7efb325904f215de78e4fe4871e48fe3e79ca29ee8'
START = datetime(2017, 9, 1)
CUTOFF = datetime(2018, 9, 1)
COLUMNS = {
    'orders': ['order_id', 'customer_id', 'order_status', 'order_purchase_timestamp',
               'order_approved_at', 'order_delivered_customer_date'],
    'customers': ['customer_id', 'customer_unique_id'],
    'order_items': ['order_id', 'order_item_id', 'price', 'freight_value'],
    'order_payments': ['order_id', 'payment_sequential', 'payment_type',
                       'payment_installments', 'payment_value'],
}
FILES = {key: f'data/raw/olist/olist_{key}_dataset.csv' for key in COLUMNS}


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('Non-finite JSON value')
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      object_pairs_hook=pairs, parse_constant=reject)


def descriptor(path, root=ROOT):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Source must be an existing project file')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
            'sha256': digest.hexdigest()}


def immutable_write(path, payload):
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')
    path = Path(path)
    if path.exists() and path.read_bytes() != data:
        raise ValueError('Refusing to overwrite different inventory bytes')
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)


def policy():
    return {
        'scope': 'snapshot_input_inventory_only_no_customer_RFM_or_segmentation',
        'candidate_window': {'start_inclusive': str(START), 'cutoff_exclusive': str(CUTOFF),
                             'status': 'candidate_for_support_inventory_not_final_RFM_contract',
                             'time_zone': 'source_naive_unverified_no_UTC_assignment'},
        'customer_key': 'customer_unique_id_via_many_orders_to_unique_customer_id_mapping',
        'candidate_order_rule': 'purchase_in_window_final_delivered_purchase_le_delivery_lt_T',
        'approval_is_eligibility_requirement': False,
        'primary_money_candidate': 'sum_item_price_in_integer_cents_product_gross_snapshot',
        'freight': 'separate_not_primary_M',
        'payments': 'independent_order_aggregation_reconciliation_only_not_instalments_multiplier',
        'missing_invalid_money': 'unknown_never_zero_or_payment_fallback',
        'prospective_R': 'T_minus_last_purchase_of_same_eligible_set_elapsed_days_rounding_not_frozen',
        'prospective_F': 'distinct_order_ids_in_same_window',
        'prospective_M': 'product_price_sum_in_same_window_not_net_revenue',
        'customer_universe_and_zero_activity_policy': 'must_freeze_before_builder_not_chosen_here',
        'operational_as_of_proven': False, 'refund_net_revenue_available': False,
        'source_completeness_proven': False, 'RFM_values_built': False,
        'segments_built': False, 'model_training': False, 'dashboard': False,
        'stage4': {'status': 'pending_data', 'daily_budget': 0.1, 'seeds': [11, 29, 42, 73, 101]},
        'stage5': {'status': 'pending_data', 'H60_and_frozen_scores_unchanged': True},
    }


def specification(root=ROOT):
    root = Path(root)
    event = descriptor(root / EVENT, root)
    if event['sha256'] != EVENT_SHA:
        raise ValueError('Frozen source inventory changed')
    previous = {x['path']: x for x in read_json(root / EVENT)['raw_sources']}
    raw = []
    headers = {}
    for name, rel in FILES.items():
        actual = descriptor(root / rel, root)
        if actual != {key: previous[rel][key] for key in ('path', 'bytes', 'sha256')}:
            raise ValueError('Original source bytes changed: ' + rel)
        with (root / rel).open(encoding='utf-8-sig', newline='') as stream:
            header = next(csv.reader(stream))
        if len(header) != len(set(header)) or not set(COLUMNS[name]) <= set(header):
            raise ValueError('Unexpected source schema')
        headers[name] = header
        raw.append(actual)
    return {'format_version': 1, 'policy': policy(), 'columns_read': COLUMNS,
            'source_headers': headers,
            'sources': [event, *raw, *[descriptor(root / path, root) for path in
                        (CODE, TEST, 'sql/03_business_analysis.sql')]]}


def verify_sources(spec, root=ROOT):
    paths = [x['path'] for x in spec['sources']]
    if len(paths) != len(set(paths)):
        raise ValueError('Duplicate source binding')
    if spec['policy'] != policy() or spec['columns_read'] != COLUMNS:
        raise ValueError('Inventory policy differs')
    for expected in spec['sources']:
        if descriptor(Path(root) / expected['path'], root) != expected:
            raise ValueError('Bound source changed: ' + expected['path'])


def clock(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value or ''):
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def cents(value):
    if not re.fullmatch(r'[+-]?\d+(?:\.\d{1,2})?', value or ''):
        return None
    result = int(Decimal(value) * 100)
    return result if abs(result) <= 2**63 - 1 else None


def positive_sequence(value):
    return bool(re.fullmatch(r'\d+', value or '') and int(value) > 0)


def unique_rows(rows, key):
    result = {}
    for row in rows:
        value = row[key]
        if not value or value in result:
            raise ValueError('Missing or duplicate required master key: ' + key)
        result[value] = row
    return result


def read_tables(root):
    tables = {}
    for name, rel in FILES.items():
        with (Path(root) / rel).open(encoding='utf-8-sig', newline='') as stream:
            tables[name] = [{key: row[key] for key in COLUMNS[name]} for row in csv.DictReader(stream)]
    return tables


def money_inventory(rows, sequence_key, money_columns, known_ids):
    groups = {}
    seen, duplicates = set(), set()
    quality = Counter()
    for row in rows:
        oid, seq = row['order_id'], row[sequence_key]
        pair = (oid, seq)
        quality['missing_order_id_rows'] += int(not oid)
        quality['orphan_order_rows'] += int(bool(oid) and oid not in known_ids)
        quality['invalid_sequence_rows'] += int(not positive_sequence(seq))
        if pair in seen:
            duplicates.add(pair)
            quality['duplicate_key_excess_rows'] += 1
        seen.add(pair)
        if oid not in groups:
            groups[oid] = {'rows': 0, 'key_valid': True,
                           **{col: {'cents': 0, 'valid': True} for col in money_columns}}
        group = groups[oid]
        group['rows'] += 1
        group['key_valid'] &= bool(oid) and positive_sequence(seq)
        for col in money_columns:
            value = cents(row[col])
            quality[col + '_invalid_rows'] += int(value is None)
            quality[col + '_negative_rows'] += int(value is not None and value < 0)
            group[col]['valid'] &= value is not None and value >= 0
            if value is not None:
                group[col]['cents'] += value
    for oid, _ in duplicates:
        groups[oid]['key_valid'] = False
    for name in ['missing_order_id_rows', 'orphan_order_rows', 'invalid_sequence_rows', 'duplicate_key_excess_rows']:
        quality[name] += 0
    totals = {}
    for col in money_columns:
        values = [cents(row[col]) for row in rows]
        totals[col] = {'parseable_rows': sum(x is not None for x in values),
                       'sum_parseable_cents': sum(x for x in values if x is not None),
                       'invalid_rows': quality[col + '_invalid_rows'],
                       'negative_rows': quality[col + '_negative_rows']}
    return groups, {'rows': len(rows), 'distinct_order_ids_including_missing': len(groups),
                    'duplicate_key_groups': len(duplicates), 'quality': dict(quality), 'money': totals}


def good(group, column):
    return bool(group and group['key_valid'] and group[column]['valid'])


def reconcile(order_ids, items, payments):
    comparable = [oid for oid in order_ids if good(items.get(oid), 'price')
                  and good(items.get(oid), 'freight_value') and good(payments.get(oid), 'payment_value')]
    deltas = [payments[oid]['payment_value']['cents'] - items[oid]['price']['cents']
              - items[oid]['freight_value']['cents'] for oid in comparable]
    return {'comparable_orders': len(comparable),
            'exact_equal_cents_orders': sum(x == 0 for x in deltas),
            'nonzero_difference_orders': sum(x != 0 for x in deltas),
            'payment_higher_orders': sum(x > 0 for x in deltas),
            'payment_lower_orders': sum(x < 0 for x in deltas),
            'absolute_difference_above_one_cent_orders': sum(abs(x) > 1 for x in deltas),
            'sum_payment_minus_items_freight_cents': sum(deltas) if deltas else None,
            'one_cent_is_business_acceptance_tolerance': False,
            'equal_total_is_proof_of_net_settlement': False}


def money_support(order_ids, groups, column):
    valid = [groups[oid][column]['cents'] for oid in order_ids if good(groups.get(oid), column)]
    return {'valid_orders': len(valid), 'unknown_or_invalid_orders': len(order_ids) - len(valid),
            'sum_cents_on_valid_orders': sum(valid) if valid else None}


def inventory(tables):
    orders = unique_rows(tables['orders'], 'order_id')
    customers = unique_rows(tables['customers'], 'customer_id')
    ids = set(orders)
    clocks = {key: {oid: clock(row[key]) for oid, row in orders.items()} for key in
              ['order_purchase_timestamp', 'order_approved_at', 'order_delivered_customer_date']}
    time_profile = {}
    for key, values in clocks.items():
        valid = [x for x in values.values() if x is not None]
        missing = sum(not row[key] for row in orders.values())
        time_profile[key] = {'valid': len(valid), 'missing': missing,
                             'invalid_nonmissing': len(orders) - len(valid) - missing,
                             'min': str(min(valid)) if valid else None,
                             'max': str(max(valid)) if valid else None}
    purchase = clocks['order_purchase_timestamp']
    approval = clocks['order_approved_at']
    delivery = clocks['order_delivered_customer_date']
    mapping = {oid: customers.get(row['customer_id'], {}).get('customer_unique_id', '')
               for oid, row in orders.items()}
    customer_counts = Counter(value for value in mapping.values() if value)
    item, item_report = money_inventory(tables['order_items'], 'order_item_id', ['price', 'freight_value'], ids)
    pay, pay_report = money_inventory(tables['order_payments'], 'payment_sequential', ['payment_value'], ids)
    payment_types = dict(sorted(Counter(row['payment_type'] for row in tables['order_payments']).items()))
    both = [oid for oid in orders if oid in item and oid in pay]
    ledger = []
    current = set(orders)
    def step(label, predicate):
        nonlocal current
        after = {oid for oid in current if predicate(oid)}
        ledger.append({'rule': label, 'remaining_orders': len(after),
                       'excluded_from_previous': len(current - after)})
        current = after
    step('valid_purchase_clock', lambda oid: purchase[oid] is not None)
    step('purchase_in_candidate_window', lambda oid: START <= purchase[oid] < CUTOFF)
    step('snapshot_status_delivered', lambda oid: orders[oid]['order_status'] == 'delivered')
    step('valid_delivery_clock', lambda oid: delivery[oid] is not None)
    step('delivery_not_before_purchase', lambda oid: delivery[oid] >= purchase[oid])
    step('delivery_strictly_before_candidate_T', lambda oid: delivery[oid] < CUTOFF)
    time_eligible = len(current)
    step('mapped_nonempty_customer_unique_id', lambda oid: bool(mapping[oid]))
    step('present_valid_item_price_and_key', lambda oid: good(item.get(oid), 'price'))
    candidate_ids = set(current)
    monthly = defaultdict(lambda: Counter())
    for oid, row in orders.items():
        if purchase[oid] is None:
            continue
        month = purchase[oid].strftime('%Y-%m')
        monthly[month]['all_orders'] += 1
        monthly[month]['snapshot_delivered'] += int(row['order_status'] == 'delivered')
        monthly[month]['delivered_with_valid_event_before_T'] += int(
            row['order_status'] == 'delivered' and delivery[oid] is not None
            and purchase[oid] <= delivery[oid] < CUTOFF)
    return {
        'status': 'input_inventory_completed_candidate_contract_not_RFM_implementation',
        'identity': {'order_rows': len(orders), 'customer_rows': len(customers),
                     'required_master_keys_present_unique': True,
                     'distinct_order_customer_ids': len({row['customer_id'] for row in orders.values()}),
                     'customer_unique_ids_in_master': len({row['customer_unique_id'] for row in customers.values() if row['customer_unique_id']}),
                     'missing_unique_id_master_rows': sum(not row['customer_unique_id'] for row in customers.values()),
                     'orphan_customer_id_orders': sum(row['customer_id'] not in customers for row in orders.values()),
                     'orders_missing_unique_id_mapping': sum(not value for value in mapping.values()),
                     'mapped_unique_customers_all_source': len(customer_counts),
                     'mapped_customers_with_multiple_source_orders': sum(value > 1 for value in customer_counts.values()),
                     'mapping_reuse_is_RFM_frequency': False},
        'orders': {'status_counts': dict(sorted(Counter(row['order_status'] for row in orders.values()).items())),
                   'clocks': time_profile,
                   'approval_before_purchase': sum(approval[oid] is not None and purchase[oid] is not None and approval[oid] < purchase[oid] for oid in orders),
                   'delivery_before_purchase': sum(delivery[oid] is not None and purchase[oid] is not None and delivery[oid] < purchase[oid] for oid in orders),
                   'delivery_before_approval': sum(delivery[oid] is not None and approval[oid] is not None and delivery[oid] < approval[oid] for oid in orders),
                   'monthly_purchase_counts': [{'purchase_month': month, **counts} for month, counts in sorted(monthly.items())]},
        'items': item_report, 'payments': {**pay_report, 'payment_type_rows': payment_types,
                   'installments_used_as_multiplier': False},
        'order_joins': {'orders_missing_items': sum(oid not in item for oid in orders),
                       'orders_missing_payments': sum(oid not in pay for oid in orders),
                       'orders_with_both_sources': len(both),
                       'multi_item_and_multi_payment_orders': sum(item[oid]['rows'] > 1 and pay[oid]['rows'] > 1 for oid in both),
                       'naive_inner_item_payment_join_rows': sum(item[oid]['rows'] * pay[oid]['rows'] for oid in both),
                       'order_aggregate_join_rows': len(both)},
        'payment_vs_product_plus_freight': reconcile(ids, item, pay),
        'candidate_window_support': {'start_inclusive': str(START), 'cutoff_exclusive': str(CUTOFF),
                    'status': 'support_only_not_frozen_customer_RFM_dataset', 'sequential_order_ledger': ledger,
                    'time_status_eligible_orders': time_eligible, 'input_supported_orders': len(candidate_ids),
                    'distinct_customer_unique_ids': len({mapping[oid] for oid in candidate_ids}),
                    'price': money_support(candidate_ids, item, 'price'),
                    'freight': money_support(candidate_ids, item, 'freight_value'),
                    'payments': money_support(candidate_ids, pay, 'payment_value'),
                    'payment_reconciliation': reconcile(candidate_ids, item, pay),
                    'orders_without_valid_payment_reconciliation': sum(not good(pay.get(oid), 'payment_value') for oid in candidate_ids),
                    'orders_without_valid_freight_reconciliation': sum(not good(item.get(oid), 'freight_value') for oid in candidate_ids),
                    'orders_with_missing_approval': sum(approval[oid] is None for oid in candidate_ids),
                    'orders_with_delivery_before_approval': sum(approval[oid] is not None and delivery[oid] < approval[oid] for oid in candidate_ids),
                    'full_upstream_or_operational_as_of_accepted': False},
        'not_executed': ['customer_RFM_values', 'RFM_scores', 'quantiles', 'segments',
                         'training', 'predictions', 'business_effectiveness', 'dashboard'],
    }


def run(root=ROOT, specification_only=False):
    root = Path(root)
    proposed = specification(root)
    if specification_only:
        immutable_write(root / SPEC, proposed)
        return {'status': 'specification_frozen_input_inventory_only', 'output': SPEC}
    if read_json(root / SPEC) != proposed:
        raise ValueError('Specification or source differs; stop instead of refreezing')
    verify_sources(proposed, root)
    result = inventory(read_tables(root))
    verify_sources(proposed, root)
    report = {'format_version': 1, 'specification': descriptor(root / SPEC, root),
              'policy': proposed['policy'], 'source_headers': proposed['source_headers'],
              'results': result,
              'limitations': ['Snapshot final status and events are retrospective proxies, not original availability.',
                              'No original ingestion, revisions, refunds or source completion evidence.',
                              'Candidate dates are for support inventory, not a final RFM scoring contract.',
                              'No customer RFM, segments, predictive performance or operational acceptance.']}
    immutable_write(root / OUTPUT, report)
    return {'status': result['status'], 'output': OUTPUT,
            'input_supported_orders': result['candidate_window_support']['input_supported_orders']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(run(specification_only=args.specification_only), ensure_ascii=False))


if __name__ == '__main__':
    main()
