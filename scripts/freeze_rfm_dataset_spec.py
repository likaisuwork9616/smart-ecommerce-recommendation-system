"""Freeze a retrospective RFM contract and audit support; no dataset builder."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts import audit_rfm_feasibility as base

CODE = 'scripts/freeze_rfm_dataset_spec.py'
TEST = 'tests/test_rfm_dataset_spec.py'
SPEC = 'reports/stage6/rfm_dataset_specification.json'
OUTPUT = 'reports/stage6/rfm_dataset_contract_audit.json'
START = datetime(2017, 9, 1)
CUTOFF = datetime(2018, 9, 1)


def policy():
    return {
        'scope': 'frozen_retrospective_snapshot_RFM_dataset_contract_no_builder',
        'S_inclusive': str(START), 'T_exclusive': str(CUTOFF),
        'window_days': 365, 'history_start': 'first_observed_purchase_not_complete_lifetime',
        'clock': 'strict_source_naive_seconds_no_timezone_or_DST_assignment',
        'customer_key': 'customer_unique_id_via_unique_customer_id_mapping',
        'universe': 'customers_with_at_least_one_history_event_eligible_order_before_T_independent_of_money',
        'history_event_eligible': ['purchase<T', 'snapshot_status=delivered',
                                  'purchase<=delivery<T', 'nonempty_unique_customer_mapping',
                                  'if_approval_parseable_purchase<=approval<=delivery'],
        'window_event_eligible': 'history_event_eligible_AND_S<=purchase<T',
        'approval_missing_or_invalid': 'flag_nonblocking_not_replaced_by_purchase',
        'clock_anomaly': 'quarantine_by_comparison_in_all_history_not_by_fixed_count_59',
        'window_quarantine': 'delivered_purchase_in_window_AND_missing_delivery_or_delivery<purchase_or_parseable_approval_conflict_when_delivery<T',
        'delivery_at_or_after_T': 'not_completed_before_T_not_quality_quarantine',
        'R': {'event': 'last_eligible_window_purchase', 'unit': 'elapsed_days',
              'integer_seconds_then_divisor': 86400, 'rounding': 'none_no_floor_no_calendar_day',
              'active_range': '(0,365]', 'no_eligible_window_order': None},
        'F': 'distinct_window_event_eligible_order_id_not_filtered_for_missing_money',
        'M': {'source': 'sum_all_eligible_window_item_price_integer_cents',
              'unit': 'nominal_BRL_product_gross_snapshot_not_net_or_settlement',
              'freight': 'separate_optional_reconciliation',
              'payments': 'separate_optional_reconciliation_no_installment_multiplier_or_fallback',
              'unknown': 'null_if_any_eligible_window_price_unknown_OR_any_window_quarantine_for_customer',
              'zero': '0_only_when_no_eligible_window_orders_and_no_window_quarantine',
              'negative_invalid_duplicate_item_or_overflow': 'unknown_not_drop_order_not_zero'},
        'zero_activity': 'retain_history_customer_R=null_F=0_M=0_only_clean_inactive',
        'activity_states': ['active_complete', 'active_money_unknown', 'active_with_quarantine',
                            'inactive_complete', 'inactive_with_quarantine'],
        'state_priority': 'eligible_price_unknown_then_window_quarantine_then_clean_active_or_inactive',
        'rfm_usable': 'true_only_active_complete_for_research_not_segmentation_authorization',
        'partial_values': 'R_and_F_describe_eligible_subset_even_when_M_masked_and_rfm_usable_false',
        'source_failures': 'missing_duplicate_master_keys_or_unlocatable_purchase_or_unmapped_history_identity_stop',
        'join': 'independent_item_payment_order_aggregates_then_order_left_join_no_silent_denominator_loss',
        'monetary_precision': 'strict_decimal_to_int64_cents_checked_sum_no_float_rounding',
        'support_money_guard': 'sum_all_known_nonnegative_order_amounts_across_price_freight_payment<=int64_max_guarantees_subset_sums_and_differences; otherwise_stop_support_audit',
        'quality_count_scope': 'approval_price_payment_freight_unknown_counts_on_window_event_eligible_orders; window_quarantine_separately_on_potential_delivered_window_orders',
        'outputs': {'private_namespace': '.runtime/stage6_rfm_dataset_v1/',
                    'status': 'planned_not_created_builder_not_implemented',
                    'canonical_order': 'customer_unique_id_ascending; order_id_ascending',
                    'write': 'preflight_whole_bundle_no_different_overwrite_readback_all_values',
                    'format': 'UTF8_CSV_nullable_empty_not_zero_float64_17_significant_digits_strict_JSON',
                    'csv_boolean_literals': ['true', 'false'],
                    'timestamp_format': '%Y-%m-%d %H:%M:%S',
                    'integer_format': 'base10_no_thousands_separator',
                    'null': 'empty_CSV_cell_only_for_nullable_fields_JSON_null'},
        'operational_as_of_accepted': False, 'source_completeness_accepted': False,
        'refund_net_money_supported': False, 'builder_implemented': False,
        'RFM_values_built': False, 'segmentation': False, 'training': False, 'dashboard': False,
        'stage4': {'status': 'pending_data', 'daily_budget': 0.1, 'seeds': [11, 29, 42, 73, 101]},
        'stage5': {'status': 'pending_data', 'H60_roles_scores_and_window_purposes_unchanged': True},
    }


def schemas():
    return {
        'customers.csv': [
            ['customer_unique_id', 'nonempty_unique_string'], ['S', 'timestamp'], ['T', 'timestamp'],
            ['activity_state', 'enum'], ['rfm_usable', 'bool'], ['monetary_complete', 'bool'],
            ['last_window_purchase_at', 'nullable_timestamp'], ['recency_seconds', 'nullable_int64'],
            ['recency_days', 'nullable_float64'], ['frequency_orders', 'nonnegative_int64'],
            ['monetary_product_cents', 'nullable_nonnegative_int64'],
            ['window_quarantined_orders', 'nonnegative_int64'],
            ['window_price_unknown_orders', 'nonnegative_int64'],
            ['window_approval_missing_or_invalid_orders', 'nonnegative_int64'],
            ['window_payment_missing_or_invalid_orders', 'nonnegative_int64'],
            ['window_freight_missing_or_invalid_orders', 'nonnegative_int64'],
        ],
        'order_decisions.csv': [
            ['order_id', 'nonempty_unique_string'], ['customer_unique_id', 'nonempty_string'],
            ['purchase_at', 'timestamp_before_T'], ['approval_at', 'nullable_timestamp'],
            ['delivery_at', 'nullable_timestamp'], ['in_window', 'bool'],
            ['history_event_eligible', 'bool'], ['window_event_eligible', 'bool'],
            ['primary_exclusion_reason', 'enum'], ['window_quarantine', 'bool'],
            ['approval_missing_or_invalid', 'bool'], ['price_complete', 'bool'],
            ['product_cents', 'nullable_nonnegative_int64'], ['freight_cents', 'nullable_nonnegative_int64'],
            ['payment_cents', 'nullable_nonnegative_int64'], ['payment_difference_cents', 'nullable_int64'],
        ],
        'manifest.json': ['specification_bytes_sha', 'source_bindings', 'schema', 'rows',
                          'private_bytes_sha', 'population_and_state_counts', 'readback_acceptance'],
        'order_decisions_scope': 'all_source_orders_with_purchase<T_not_only_eligible_orders',
        'primary_exclusion_precedence': ['status_not_delivered', 'missing_or_invalid_delivery',
                                         'delivery_before_purchase', 'delivery_at_or_after_T',
                                         'approval_clock_conflict', 'eligible'],
        'source_exclusion_summary': 'purchase>=T_counts_without_future_customer_rows; unlocatable_purchase_stops',
    }


def specification(root=ROOT):
    root = Path(root)
    previous = base.read_json(root / base.SPEC)
    if base.specification(root) != previous:
        raise ValueError('Prior inventory source or specification changed')
    old_report = base.read_json(root / base.OUTPUT)
    if old_report['specification'] != base.descriptor(root / base.SPEC, root):
        raise ValueError('Prior inventory report binding differs')
    return {'format_version': 1, 'policy': policy(), 'planned_schemas': schemas(),
            'source_headers': previous['source_headers'], 'columns_read': previous['columns_read'],
            'sources': [*previous['sources'], *[base.descriptor(root / p, root) for p in
                         (base.SPEC, base.OUTPUT, CODE, TEST)]]}


def verify_sources(spec, root=ROOT):
    paths = [x['path'] for x in spec['sources']]
    if len(paths) != len(set(paths)) or spec['policy'] != policy() or spec['planned_schemas'] != schemas():
        raise ValueError('Duplicate sources or changed contract')
    for expected in spec['sources']:
        if base.descriptor(Path(root) / expected['path'], root) != expected:
            raise ValueError('Bound source changed: ' + expected['path'])


def event_decision(row):
    purchase = base.clock(row['order_purchase_timestamp'])
    approval = base.clock(row['order_approved_at'])
    delivery = base.clock(row['order_delivered_customer_date'])
    if purchase is None:
        raise ValueError('Unlocatable purchase prevents complete population audit')
    in_window = START <= purchase < CUTOFF
    reason = 'eligible'
    if purchase >= CUTOFF:
        reason = 'purchase_at_or_after_T'
    elif row['order_status'] != 'delivered':
        reason = 'status_not_delivered'
    elif delivery is None:
        reason = 'missing_or_invalid_delivery'
    elif delivery < purchase:
        reason = 'delivery_before_purchase'
    elif delivery >= CUTOFF:
        reason = 'delivery_at_or_after_T'
    elif approval is not None and (approval < purchase or approval > delivery):
        reason = 'approval_clock_conflict'
    return {'history_eligible': reason == 'eligible', 'in_window': in_window,
            'reason': reason, 'approval_unknown': approval is None,
            'window_quarantine': in_window and reason in {
                'missing_or_invalid_delivery', 'delivery_before_purchase', 'approval_clock_conflict'}}


def activity_state(window_orders, price_unknown_orders, quarantined_orders):
    if window_orders < 0 or price_unknown_orders < 0 or quarantined_orders < 0 or price_unknown_orders > window_orders:
        raise ValueError('Invalid support counts')
    if price_unknown_orders:
        state = 'active_money_unknown'
    elif quarantined_orders:
        state = 'active_with_quarantine' if window_orders else 'inactive_with_quarantine'
    else:
        state = 'active_complete' if window_orders else 'inactive_complete'
    return {'state': state, 'monetary_complete': not (price_unknown_orders or quarantined_orders),
            'rfm_usable': state == 'active_complete'}


def verify_money_support_bound(items, payments):
    known_total = sum(group[column]['cents'] for groups, column in
                      ((items, 'price'), (items, 'freight_value'), (payments, 'payment_value'))
                      for group in groups.values() if base.good(group, column))
    if known_total > 2**63 - 1:
        raise ValueError('Known money totals exceed conservative int64 subset guarantee')
    return True


def audit_support(tables):
    orders = base.unique_rows(tables['orders'], 'order_id')
    customers = base.unique_rows(tables['customers'], 'customer_id')
    mapping = {oid: customers.get(row['customer_id'], {}).get('customer_unique_id', '')
               for oid, row in orders.items()}
    decisions = {oid: event_decision(row) for oid, row in orders.items()}
    if any(not mapping[oid] for oid, row in orders.items()
           if base.clock(row['order_purchase_timestamp']) < CUTOFF):
        raise ValueError('Unmapped historical identity prevents population reconciliation')
    history = {oid for oid, d in decisions.items() if d['history_eligible']}
    window = {oid for oid in history if decisions[oid]['in_window']}
    quarantined = {oid for oid, d in decisions.items() if d['window_quarantine']}
    universe = {mapping[oid] for oid in history}
    item, _ = base.money_inventory(tables['order_items'], 'order_item_id', ['price', 'freight_value'], set(orders))
    payment, _ = base.money_inventory(tables['order_payments'], 'payment_sequential', ['payment_value'], set(orders))
    verify_money_support_bound(item, payment)
    window_customer_counts = Counter(mapping[oid] for oid in window)
    quarantine_customer_counts = Counter(mapping[oid] for oid in quarantined)
    price_unknown = {oid for oid in window if not base.good(item.get(oid), 'price')}
    unknown_customer_counts = Counter(mapping[oid] for oid in price_unknown)
    state_counts = Counter({state: 0 for state in policy()['activity_states']})
    for customer in universe:
        state_counts[activity_state(window_customer_counts[customer], unknown_customer_counts[customer],
                                    quarantine_customer_counts[customer])['state']] += 1
    history_pre_clock = history | {oid for oid, d in decisions.items() if d['reason'] == 'approval_clock_conflict'}
    window_pre_clock = {oid for oid in history_pre_clock if decisions[oid]['in_window']}
    reason_counts = Counter(d['reason'] for oid, d in decisions.items()
                            if base.clock(orders[oid]['order_purchase_timestamp']) < CUTOFF)
    return {
        'status': 'contract_support_audited_no_RFM_dataset_or_builder',
        'history': {'event_candidates_before_approval_check': len(history_pre_clock),
                    'approval_conflict_orders': reason_counts['approval_clock_conflict'],
                    'event_eligible_orders': len(history), 'customer_universe': len(universe),
                    'approval_missing_or_invalid_eligible_orders': sum(decisions[x]['approval_unknown'] for x in history),
                    'eligible_orders_missing_items': sum(oid not in item for oid in history),
                    'eligible_orders_missing_payments': sum(oid not in payment for oid in history),
                    'order_decisions_scope_rows': sum(reason_counts.values()),
                    'mutually_exclusive_primary_reasons': dict(sorted(reason_counts.items()))},
        'window': {'event_candidates_before_approval_check': len(window_pre_clock),
                   'approval_conflict_orders': sum(d['in_window'] and d['reason'] == 'approval_clock_conflict' for d in decisions.values()),
                   'event_eligible_orders': len(window), 'active_customers': len(window_customer_counts),
                   'zero_eligible_window_customers': len(universe - set(window_customer_counts)),
                   'price_unknown_orders': len(price_unknown),
                   'approval_missing_or_invalid_eligible_orders': sum(decisions[x]['approval_unknown'] for x in window),
                   'price': base.money_support(window, item, 'price'),
                   'freight': base.money_support(window, item, 'freight_value'),
                   'payments': base.money_support(window, payment, 'payment_value'),
                   'payment_reconciliation': base.reconcile(window, item, payment)},
        'window_quarantine': {'orders': len(quarantined),
                              'primary_reasons': dict(sorted(Counter(decisions[x]['reason'] for x in quarantined).items())),
                              'orders_linked_to_universe': sum(mapping[x] in universe for x in quarantined),
                              'orders_outside_universe': sum(mapping[x] not in universe for x in quarantined),
                              'customers_inside_universe': len({mapping[x] for x in quarantined if mapping[x] in universe}),
                              'not_completed_before_T_orders': sum(d['in_window'] and d['reason'] == 'delivery_at_or_after_T' for d in decisions.values())},
        'customer_state_support_only': dict(state_counts),
        'acceptance': {'population_equals_active_plus_zero': len(universe) == len(window_customer_counts) + len(universe - set(window_customer_counts)),
                       'states_cover_universe': sum(state_counts.values()) == len(universe),
                       'window_customers_subset_of_history': set(window_customer_counts) <= universe,
                       'known_money_int64_subset_guarantee': True,
                       'builder_implemented': False, 'individual_RFM_values_built': False,
                       'private_dataset_created': False, 'segmentation_training_dashboard': False},
    }


def run(root=ROOT, specification_only=False):
    root = Path(root)
    proposed = specification(root)
    if specification_only:
        base.immutable_write(root / SPEC, proposed)
        return {'status': 'RFM_dataset_contract_frozen_no_builder', 'output': SPEC}
    if base.read_json(root / SPEC) != proposed:
        raise ValueError('Contract differs; stop instead of rewriting')
    verify_sources(proposed, root)
    result = audit_support(base.read_tables(root))
    old = base.read_json(root / base.OUTPUT)['results']['candidate_window_support']
    if result['window']['event_candidates_before_approval_check'] != old['input_supported_orders']:
        raise ValueError('Prior candidate scope mismatch')
    if not all(result['acceptance'][key] for key in
               ('population_equals_active_plus_zero', 'states_cover_universe', 'window_customers_subset_of_history')):
        raise ValueError('Population or state reconciliation failed')
    verify_sources(proposed, root)
    payload = {'format_version': 1, 'specification': base.descriptor(root / SPEC, root),
               'policy': proposed['policy'], 'results': result,
               'limitations': ['Final snapshot event proxy, not operational as-of or complete lifetime.',
                               'No ingestion/revision/refund/settlement or upstream completion evidence.',
                               'Customer state counts are metadata support, not built per-customer RFM.']}
    base.immutable_write(root / OUTPUT, payload)
    return {'status': result['status'], 'output': OUTPUT,
            'customer_universe': result['history']['customer_universe']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(run(specification_only=args.specification_only), ensure_ascii=False))


if __name__ == '__main__':
    main()
