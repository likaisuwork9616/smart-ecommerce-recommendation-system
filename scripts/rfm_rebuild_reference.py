"""Independent raw-table oracle for the v2 RFM rebuild (no builder calls)."""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import re

from scripts import rfm_dataset_artifacts as typed

START = datetime(2017, 9, 1)
END = datetime(2018, 9, 1)
MAX = 2**63 - 1


def timestamp(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def amounts(rows, sequence, columns):
    groups = defaultdict(list)
    for row in rows:
        groups[row['order_id']].append(row)
    result = {}
    for oid, group in groups.items():
        seq = [r[sequence] for r in group]
        valid = bool(oid) and len(seq) == len(set(seq)) and all(
            re.fullmatch(r'\d+', s) and int(s) > 0 for s in seq)
        values = {}
        for column in columns:
            texts = [r[column] for r in group]
            cents = [int(Decimal(s) * 100) if re.fullmatch(r'[+-]?\d+(?:\.\d{1,2})?', s)
                     else None for s in texts]
            acceptable = valid and all(v is not None and 0 <= v <= MAX for v in cents)
            total = sum(cents) if acceptable else None
            values[column] = total if total is not None and total <= MAX else None
        result[oid] = values
    return result


def reference_rows(tables):
    """Reclassify events and aggregate Decimal money independently of v1 code."""
    masters = {}
    for name, key in (('orders', 'order_id'), ('customers', 'customer_id')):
        rows = tables[name]
        ids = [r[key] for r in rows]
        if any(not v or v != v.strip() for v in ids) or len(ids) != len(set(ids)):
            raise ValueError('Independent reference requires unique canonical master IDs')
        masters[name] = {r[key]: r for r in rows}
    items = amounts(tables['order_items'], 'order_item_id', ('price', 'freight_value'))
    payments = amounts(tables['order_payments'], 'payment_sequential', ('payment_value',))
    known_total = sum(v for groups in (items, payments) for row in groups.values()
                      for v in row.values() if v is not None)
    if known_total > MAX:
        raise ValueError('Independent reference int64 support bound exceeded')
    orders = []
    for oid, row in sorted(masters['orders'].items()):
        p, a, d = [timestamp(row[k]) for k in (
            'order_purchase_timestamp', 'order_approved_at', 'order_delivered_customer_date')]
        if p is None:
            raise ValueError('Independent reference cannot locate purchase')
        if p >= END:
            continue
        uid = masters['customers'].get(row['customer_id'], {}).get('customer_unique_id')
        if not uid or uid != uid.strip():
            raise ValueError('Independent reference cannot map historical customer')
        checks = ((row['order_status'] != 'delivered', 'status_not_delivered'),
                  (d is None, 'missing_or_invalid_delivery'),
                  (d is not None and d < p, 'delivery_before_purchase'),
                  (d is not None and d >= END, 'delivery_at_or_after_T'),
                  (a is not None and d is not None and not p <= a <= d, 'approval_clock_conflict'))
        reason = next((label for failed, label in checks if failed), 'eligible')
        window = START <= p < END
        price, freight = [items.get(oid, {}).get(k) for k in ('price', 'freight_value')]
        payment = payments.get(oid, {}).get('payment_value')
        difference = payment - price - freight if None not in (price, freight, payment) else None
        orders.append(dict(order_id=oid, customer_unique_id=uid, purchase_at=str(p),
            approval_at=str(a) if a is not None else None, delivery_at=str(d) if d is not None else None,
            in_window=window, history_event_eligible=reason == 'eligible',
            window_event_eligible=window and reason == 'eligible', primary_exclusion_reason=reason,
            window_quarantine=window and reason in ('missing_or_invalid_delivery', 'delivery_before_purchase', 'approval_clock_conflict'),
            approval_missing_or_invalid=a is None, price_complete=price is not None,
            product_cents=price, freight_cents=freight, payment_cents=payment,
            payment_difference_cents=difference))
    universe = sorted({r['customer_unique_id'] for r in orders if r['history_event_eligible']})
    eligible = defaultdict(list)
    quarantine = Counter()
    for row in orders:
        if row['window_event_eligible']:
            eligible[row['customer_unique_id']].append(row)
        if row['window_quarantine']:
            quarantine[row['customer_unique_id']] += 1
    customers = []
    for uid in universe:
        rows = eligible[uid]
        f = len(rows)
        unknown = sum(r['product_cents'] is None for r in rows)
        q = quarantine[uid]
        state = ('active_money_unknown' if unknown else
                 ('active_with_quarantine' if f else 'inactive_with_quarantine') if q else
                 ('active_complete' if f else 'inactive_complete'))
        last = max((r['purchase_at'] for r in rows), default=None)
        seconds = int((END - datetime.fromisoformat(last)).total_seconds()) if last else None
        customers.append(dict(customer_unique_id=uid, S=str(START), T=str(END), activity_state=state,
            rfm_usable=state == 'active_complete', monetary_complete=not (unknown or q),
            last_window_purchase_at=last, recency_seconds=seconds,
            recency_days=seconds / 86400.0 if seconds is not None else None,
            frequency_orders=f, monetary_product_cents=sum(r['product_cents'] for r in rows) if not (unknown or q) else None,
            window_quarantined_orders=q, window_price_unknown_orders=unknown,
            window_approval_missing_or_invalid_orders=sum(r['approval_missing_or_invalid'] for r in rows),
            window_payment_missing_or_invalid_orders=sum(r['payment_cents'] is None for r in rows),
            window_freight_missing_or_invalid_orders=sum(r['freight_cents'] is None for r in rows)))
    return customers, orders


def verify_dataset(tables, dataset):
    customers, orders = reference_rows(tables)
    for name, actual, expected in (('customers', dataset['customers'], customers),
                                  ('orders', dataset['orders'], orders)):
        if not typed._same(actual, expected):
            # Do not disclose individual IDs or amounts in public error messages.
            raise ValueError('Independent raw-source comparison failed: ' + name)
    receipt = {'accepted': True, 'customer_rows': len(customers), 'order_rows': len(orders),
               'cells_compared': (len(customers) + len(orders)) * 16,
               'independent_event_and_decimal_money_reconstruction': True,
               'exact_types_nulls_and_binary64': True}
    rosters = {'customer_ids': [r['customer_unique_id'] for r in customers],
               'order_ids': [r['order_id'] for r in orders],
               'window_order_ids': [r['order_id'] for r in orders if r['window_event_eligible']]}
    return receipt, rosters
