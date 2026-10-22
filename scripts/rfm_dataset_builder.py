"""Pure Stage 6 RFM builder for the frozen retrospective snapshot contract.

This module accepts the four already guarded source tables. It has no file I/O,
does not fit models, and does not interpret reviews or any model scores. Source
byte verification and private bundle persistence belong to the execution entry.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from scripts import audit_rfm_feasibility as base
from scripts import freeze_rfm_dataset_spec as contract

INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)
TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'


def _checked_sum(values: Iterable[int], *, nonnegative: bool = True) -> int:
    """Add exact Python integers while enforcing the output int64 contract."""
    total = 0
    for value in values:
        if type(value) is not int or (nonnegative and value < 0):
            raise ValueError('Expected an exact nonnegative integer amount')
        total += value
        if not INT64_MIN <= total <= INT64_MAX:
            raise OverflowError('Checked int64 sum overflow')
    return total


def _timestamp(value):
    return value.strftime(TIMESTAMP_FORMAT) if value is not None else None


def _validate_input(tables, spec):
    if (not isinstance(spec, dict) or type(spec.get('format_version')) is not int
            or spec['format_version'] != 1):
        raise ValueError('Unsupported frozen dataset specification')
    if spec.get('policy') != contract.policy() or spec.get('planned_schemas') != contract.schemas():
        raise ValueError('Frozen RFM policy or schema differs')
    if spec.get('columns_read') != base.COLUMNS:
        raise ValueError('Frozen source columns differ')
    if not isinstance(tables, dict) or set(tables) != set(base.COLUMNS):
        raise ValueError('Exactly the four frozen source tables are required')
    for name, columns in base.COLUMNS.items():
        if not isinstance(tables[name], list):
            raise ValueError('Source tables must be lists of raw string dictionaries')
        for row in tables[name]:
            if not isinstance(row, dict) or not set(columns) <= set(row):
                raise ValueError('Required source columns are missing: ' + name)
            if any(type(value) is not str for value in row.values()):
                raise ValueError('All raw source values must be strings: ' + name)


def _money_groups(rows, sequence_key, columns, known_order_ids):
    """Independent order aggregates; an invalid field remains unknown.

    Duplicate/invalid detail keys invalidate every amount on that order. Amount
    parsing or overflow invalidates only the affected amount. A price failure
    never removes an order from the event population.
    """
    groups = {}
    seen, duplicate_pairs = set(), set()
    quality = Counter({key: 0 for key in (
        'missing_order_id_rows', 'orphan_order_rows', 'invalid_sequence_rows',
        'duplicate_key_excess_rows')})
    column_quality = {column: Counter({key: 0 for key in (
        'invalid_rows', 'negative_rows', 'aggregate_overflow_orders')}) for column in columns}
    for row in rows:
        oid, sequence = row['order_id'], row[sequence_key]
        pair = (oid, sequence)
        quality['missing_order_id_rows'] += int(not oid)
        quality['orphan_order_rows'] += int(bool(oid) and oid not in known_order_ids)
        quality['invalid_sequence_rows'] += int(not base.positive_sequence(sequence))
        if pair in seen:
            duplicate_pairs.add(pair)
            quality['duplicate_key_excess_rows'] += 1
        seen.add(pair)
        group = groups.setdefault(oid, {
            'rows': 0, 'key_valid': True,
            **{column: {'cents': 0, 'valid': True} for column in columns}})
        group['rows'] += 1
        group['key_valid'] = bool(group['key_valid'] and oid and base.positive_sequence(sequence))
        for column in columns:
            amount = base.cents(row[column])
            column_quality[column]['invalid_rows'] += int(amount is None)
            column_quality[column]['negative_rows'] += int(amount is not None and amount < 0)
            field = group[column]
            if amount is None or amount < 0:
                field.update(cents=None, valid=False)
            elif field['valid']:
                try:
                    field['cents'] = _checked_sum((field['cents'], amount))
                except OverflowError:
                    field.update(cents=None, valid=False)
                    column_quality[column]['aggregate_overflow_orders'] += 1
    for oid, _ in duplicate_pairs:
        groups[oid]['key_valid'] = False
    report = {
        'rows': len(rows),
        'distinct_order_ids_including_missing': len(groups),
        'duplicate_key_groups': len(duplicate_pairs),
        'quality': dict(quality),
        'amount_quality': {column: dict(counts) for column, counts in column_quality.items()},
    }
    return groups, report


def _amount(groups, oid, column):
    group = groups.get(oid)
    return group[column]['cents'] if base.good(group, column) else None


def _money_support(order_ids, groups, column):
    values = [_amount(groups, oid, column) for oid in order_ids]
    known = [value for value in values if value is not None]
    return {
        'valid_orders': len(known),
        'unknown_or_invalid_orders': len(values) - len(known),
        'sum_cents_on_valid_orders': _checked_sum(known) if known else None,
    }


def _reconciliation(order_rows):
    differences = [row['payment_difference_cents'] for row in order_rows
                   if row['payment_difference_cents'] is not None]
    return {
        'comparable_orders': len(differences),
        'exact_equal_cents_orders': sum(value == 0 for value in differences),
        'nonzero_difference_orders': sum(value != 0 for value in differences),
        'payment_higher_orders': sum(value > 0 for value in differences),
        'payment_lower_orders': sum(value < 0 for value in differences),
        'absolute_difference_above_one_cent_orders': sum(abs(value) > 1 for value in differences),
        'sum_payment_minus_items_freight_cents': (
            _checked_sum(differences, nonnegative=False) if differences else None),
        'one_cent_is_business_acceptance_tolerance': False,
        'equal_total_is_proof_of_net_settlement': False,
    }


def build_dataset(tables, spec):
    """Return canonical customer rows, pre-T order decisions and aggregate QA.

    ``tables`` contains the four raw-string list-of-dict inputs selected by
    ``audit_rfm_feasibility.read_tables``. ``spec`` is the frozen specification,
    verified for policy/schema here; the caller verifies its bound source bytes.
    The returned ledger preserves parsed future approval/delivery timestamps as
    exclusion evidence. It is an audit ledger, not an operational as-of feature.
    No source dictionary or specification is mutated.
    """
    _validate_input(tables, spec)
    orders = base.unique_rows(tables['orders'], 'order_id')
    customers = base.unique_rows(tables['customers'], 'customer_id')
    decisions = {oid: contract.event_decision(row) for oid, row in orders.items()}
    clocks = {oid: {
        'purchase': base.clock(row['order_purchase_timestamp']),
        'approval': base.clock(row['order_approved_at']),
        'delivery': base.clock(row['order_delivered_customer_date']),
    } for oid, row in orders.items()}
    mapping = {oid: customers.get(row['customer_id'], {}).get('customer_unique_id', '')
               for oid, row in orders.items()}
    before_T = {oid for oid in orders if clocks[oid]['purchase'] < contract.CUTOFF}
    if any(not mapping[oid] for oid in before_T):
        raise ValueError('Unmapped historical identity prevents population reconciliation')

    items, item_quality = _money_groups(
        tables['order_items'], 'order_item_id', ('price', 'freight_value'), set(orders))
    payments, payment_quality = _money_groups(
        tables['order_payments'], 'payment_sequential', ('payment_value',), set(orders))
    # Keep the frozen source support gate in addition to checked actual sums.
    contract.verify_money_support_bound(items, payments)

    history = {oid for oid, decision in decisions.items() if decision['history_eligible']}
    window = {oid for oid in history if decisions[oid]['in_window']}
    quarantined = {oid for oid, decision in decisions.items() if decision['window_quarantine']}
    universe = {mapping[oid] for oid in history}
    by_customer = defaultdict(list)
    quarantine_counts = Counter(mapping[oid] for oid in quarantined)
    for oid in window:
        by_customer[mapping[oid]].append(oid)

    order_rows = []
    for oid in sorted(before_T):
        decision, times = decisions[oid], clocks[oid]
        product = _amount(items, oid, 'price')
        freight = _amount(items, oid, 'freight_value')
        payment = _amount(payments, oid, 'payment_value')
        difference = None
        if all(value is not None for value in (product, freight, payment)):
            difference = _checked_sum((payment, -product, -freight), nonnegative=False)
        order_rows.append({
            'order_id': oid,
            'customer_unique_id': mapping[oid],
            'purchase_at': _timestamp(times['purchase']),
            'approval_at': _timestamp(times['approval']),
            'delivery_at': _timestamp(times['delivery']),
            'in_window': decision['in_window'],
            'history_event_eligible': decision['history_eligible'],
            'window_event_eligible': oid in window,
            'primary_exclusion_reason': decision['reason'],
            'window_quarantine': decision['window_quarantine'],
            'approval_missing_or_invalid': decision['approval_unknown'],
            'price_complete': product is not None,
            'product_cents': product,
            'freight_cents': freight,
            'payment_cents': payment,
            'payment_difference_cents': difference,
        })

    customer_rows = []
    for uid in sorted(universe):
        eligible = by_customer.get(uid, [])
        price_unknown = sum(_amount(items, oid, 'price') is None for oid in eligible)
        state = contract.activity_state(len(eligible), price_unknown, quarantine_counts[uid])
        last_purchase = max((clocks[oid]['purchase'] for oid in eligible), default=None)
        seconds = int((contract.CUTOFF - last_purchase).total_seconds()) if last_purchase is not None else None
        monetary = (_checked_sum(_amount(items, oid, 'price') for oid in eligible)
                    if state['monetary_complete'] else None)
        customer_rows.append({
            'customer_unique_id': uid,
            'S': _timestamp(contract.START),
            'T': _timestamp(contract.CUTOFF),
            'activity_state': state['state'],
            'rfm_usable': state['rfm_usable'],
            'monetary_complete': state['monetary_complete'],
            'last_window_purchase_at': _timestamp(last_purchase),
            'recency_seconds': seconds,
            'recency_days': seconds / 86400.0 if seconds is not None else None,
            'frequency_orders': len(eligible),
            'monetary_product_cents': monetary,
            'window_quarantined_orders': quarantine_counts[uid],
            'window_price_unknown_orders': price_unknown,
            'window_approval_missing_or_invalid_orders': sum(decisions[oid]['approval_unknown'] for oid in eligible),
            'window_payment_missing_or_invalid_orders': sum(_amount(payments, oid, 'payment_value') is None for oid in eligible),
            'window_freight_missing_or_invalid_orders': sum(_amount(items, oid, 'freight_value') is None for oid in eligible),
        })

    state_counts = Counter({state: 0 for state in contract.policy()['activity_states']})
    state_counts.update(row['activity_state'] for row in customer_rows)
    primary_reasons = Counter(decisions[oid]['reason'] for oid in before_T)
    history_pre_clock = history | {oid for oid in before_T if decisions[oid]['reason'] == 'approval_clock_conflict'}
    window_pre_clock = {oid for oid in history_pre_clock if decisions[oid]['in_window']}
    price_unknown = {oid for oid in window if _amount(items, oid, 'price') is None}
    masked_customers = {row['customer_unique_id'] for row in customer_rows
                        if row['monetary_product_cents'] is None}
    known_prices = [(oid, _amount(items, oid, 'price')) for oid in window
                    if _amount(items, oid, 'price') is not None]
    source_known = _checked_sum(value for _, value in known_prices)
    published = _checked_sum(row['monetary_product_cents'] for row in customer_rows
                             if row['monetary_product_cents'] is not None)
    masked_known = _checked_sum(value for oid, value in known_prices if mapping[oid] in masked_customers)
    money_conservation = {
        'eligible_window_product_known_orders': len(known_prices),
        'eligible_window_product_unknown_orders': len(price_unknown),
        'eligible_window_product_cents_on_known_orders': source_known,
        'published_customer_product_cents': published,
        'known_product_cents_masked_customer_subsets': masked_known,
        'known_product_orders_in_masked_customer_subsets': sum(mapping[oid] in masked_customers for oid, _ in known_prices),
        'unknown_product_orders_in_masked_customer_subsets': sum(mapping[oid] in masked_customers for oid in price_unknown),
        'masked_customers': len(masked_customers),
        'unmasked_customers': len(universe) - len(masked_customers),
        'inactive_complete_zero_customers': state_counts['inactive_complete'],
        'known_product_cents_equal_published_plus_masked_known': source_known == _checked_sum((published, masked_known)),
        'unknown_product_amounts_are_zero_filled': False,
    }
    window_rows = [row for row in order_rows if row['window_event_eligible']]
    history_rows = [row for row in order_rows if row['history_event_eligible']]
    invariants = {
        'population_equals_active_plus_zero': len(universe) == len(by_customer) + sum(row['frequency_orders'] == 0 for row in customer_rows),
        'states_cover_universe': sum(state_counts.values()) == len(universe),
        'window_customers_subset_of_history': set(by_customer) <= universe,
        'window_orders_subset_of_history': window <= history,
        'decisions_cover_each_pre_T_source_order': len(order_rows) == len(before_T),
        'frequency_sum_equals_window_orders': _checked_sum(row['frequency_orders'] for row in customer_rows) == len(window),
        'money_mask_applied': all((row['monetary_product_cents'] is None) == (row['window_price_unknown_orders'] > 0 or row['window_quarantined_orders'] > 0) for row in customer_rows),
        'money_conservation_on_known_subsets': money_conservation['known_product_cents_equal_published_plus_masked_known'],
        'known_money_int64_subset_guarantee': True,
        'active_recency_valid': all(row['recency_seconds'] is not None and 0 < row['recency_seconds'] <= 365 * 86400 and row['recency_days'] == row['recency_seconds'] / 86400.0 for row in customer_rows if row['frequency_orders']),
        'inactive_recency_null': all(row['last_window_purchase_at'] is None and row['recency_seconds'] is None and row['recency_days'] is None for row in customer_rows if not row['frequency_orders']),
    }
    if not all(invariants.values()):
        raise ValueError('RFM population, amount or event invariant failed')
    summary = {
        'source': {
            'orders': len(orders), 'customer_master_rows': len(customers),
            'order_item_rows': len(tables['order_items']),
            'order_payment_rows': len(tables['order_payments']),
            'purchase_before_T_orders': len(before_T),
            'purchase_at_or_after_T_orders': len(orders) - len(before_T),
            'unmapped_future_orders': sum(not mapping[oid] for oid in set(orders) - before_T),
        },
        'history': {
            'event_candidates_before_approval_check': len(history_pre_clock),
            'approval_conflict_orders': primary_reasons['approval_clock_conflict'],
            'event_eligible_orders': len(history), 'customer_universe': len(universe),
            'approval_missing_or_invalid_eligible_orders': sum(decisions[oid]['approval_unknown'] for oid in history),
            'eligible_orders_missing_items': sum(oid not in items for oid in history),
            'eligible_orders_missing_payments': sum(oid not in payments for oid in history),
            'order_decisions_scope_rows': len(order_rows),
            'mutually_exclusive_primary_reasons': dict(sorted(primary_reasons.items())),
        },
        'window': {
            'event_candidates_before_approval_check': len(window_pre_clock),
            'approval_conflict_orders': sum(decisions[oid]['reason'] == 'approval_clock_conflict' and decisions[oid]['in_window'] for oid in before_T),
            'event_eligible_orders': len(window), 'active_customers': len(by_customer),
            'zero_eligible_window_customers': sum(row['frequency_orders'] == 0 for row in customer_rows),
            'price_unknown_orders': len(price_unknown),
            'approval_missing_or_invalid_eligible_orders': sum(decisions[oid]['approval_unknown'] for oid in window),
            'price': _money_support(window, items, 'price'),
            'freight': _money_support(window, items, 'freight_value'),
            'payments': _money_support(window, payments, 'payment_value'),
            'payment_reconciliation': _reconciliation(window_rows),
        },
        'window_quarantine': {
            'orders': len(quarantined),
            'primary_reasons': dict(sorted(Counter(decisions[oid]['reason'] for oid in quarantined).items())),
            'orders_linked_to_universe': sum(mapping[oid] in universe for oid in quarantined),
            'orders_outside_universe': sum(mapping[oid] not in universe for oid in quarantined),
            'customers_inside_universe': len({mapping[oid] for oid in quarantined if mapping[oid] in universe}),
            'not_completed_before_T_orders': sum(row['in_window'] and row['primary_exclusion_reason'] == 'delivery_at_or_after_T' for row in order_rows),
        },
        'customer_states': dict(state_counts),
        'customer_money_conservation': money_conservation,
        'reconciliation': {
            'all_before_T': _reconciliation(order_rows),
            'history_event_eligible': _reconciliation(history_rows),
            'window_event_eligible': _reconciliation(window_rows),
        },
        'money_quality': {'items': item_quality, 'payments': payment_quality},
        'invariants': invariants,
    }
    return {'customers': customer_rows, 'orders': order_rows, 'summary': summary}
