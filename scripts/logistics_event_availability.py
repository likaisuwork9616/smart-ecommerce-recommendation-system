"""Event-time feasibility helpers; no model or target is fitted or scored.

CSV event timestamps stand in for availability only under a timely logging
assumption. They do not establish actual ingestion or historical revisions.
"""
from __future__ import annotations

import numbers

import numpy as np
import pandas as pd


def _times(values, name):
    result = pd.to_datetime(values, errors='raise', format='mixed')
    if result.dt.tz is not None:
        raise ValueError(f'{name} requires timezone-naive timestamps')
    return result


def event_asof_features(orders, query_times):
    """Mask future event values; final status never defines the as-of phase.

    Feature observations are strictly before the query. Reminder eligibility
    conservatively excludes delivery at the query, as well as before it.
    The approval timestamp itself is an allowed trigger, hence query>=approval.
    """
    required = ('order_purchase_timestamp', 'order_approved_at', 'order_delivered_carrier_date',
                'order_delivered_customer_date', 'order_estimated_delivery_date')
    if set(required).difference(orders.columns):
        raise ValueError('Missing required milestone timestamps')
    if isinstance(query_times, pd.Series):
        if not query_times.index.equals(orders.index):
            raise ValueError('Query timestamps must have the same ordered index')
        queries = query_times.copy()
    else:
        values = np.asarray(query_times)
        if values.ndim != 1 or len(values) != len(orders):
            raise ValueError('Require one query timestamp per order')
        queries = pd.Series(values, index=orders.index)
    q = _times(queries, 'query')
    purchase, approval, carrier, delivery, promise = [_times(orders[key], key) for key in required]
    valid = q.notna() & purchase.notna() & approval.notna() & (approval >= purchase) & (q >= approval)
    carrier_past = valid & carrier.notna() & (carrier < q)
    carrier_observed = carrier_past & (carrier >= approval)
    carrier_invalid = carrier_past & (carrier < approval)
    delivered = valid & delivery.notna() & (delivery <= q)
    delivery_observed = valid & delivery.notna() & (delivery < q)
    deadline = promise.dt.normalize() + pd.Timedelta(days=1)
    promise_expired = valid & promise.notna() & (q >= deadline)
    eligible = valid & ~delivered & ~carrier_invalid
    phase = np.select([~valid, delivered, carrier_invalid, carrier_observed],
                      ['invalid', 'delivered', 'invalid', 'in_transit'], default='pre_handover')
    # pre_handover describes absence of an observed event, not proof of no shipment.
    day = 86400.
    output = pd.DataFrame({
        'valid_approval_query': valid,
        'carrier_observed': carrier_observed,
        'carrier_known_invalid': carrier_invalid,
        'delivery_observed': delivery_observed,
        'already_delivered_by_query': delivered,
        'eligible_for_reminder': eligible,
        'promise_expired': promise_expired,
        'eligible_for_advance_reminder': eligible & promise.notna() & ~promise_expired,
        'observed_phase': phase,
        'approval_age_days': ((q - approval).dt.total_seconds() / day).where(valid),
        'approval_to_carrier_days': ((carrier - approval).dt.total_seconds() / day).where(carrier_observed),
        'transit_age_days': ((q - carrier).dt.total_seconds() / day).where(carrier_observed),
        'promise_remaining_days': ((promise.dt.normalize() + pd.Timedelta(days=1) - q).dt.total_seconds() / day).where(valid),
    }, index=orders.index)
    return output


def history_support_counts(queries, events, group_column, window_days=90):
    """Count independent past events in [query-window, query), without labels."""
    if (isinstance(window_days, (bool, np.bool_)) or not isinstance(window_days, numbers.Integral)
            or window_days <= 0):
        raise ValueError('window_days must be a positive integer')
    if {'prediction_time', group_column}.difference(queries.columns) or {'event_time', group_column}.difference(events.columns):
        raise ValueError('Missing query/event grouping columns')
    qt, et = _times(queries.prediction_time, 'query'), _times(events.event_time, 'event')
    result = np.zeros(len(queries), dtype=np.int64)
    event_groups = {}
    selected = events[group_column].notna() & et.notna()
    event_frame = pd.DataFrame({'group':events[group_column].to_numpy(),
                                'time':et.to_numpy(dtype='datetime64[ns]')})
    for key, group in event_frame.loc[selected.to_numpy()].groupby('group', sort=False):
        event_groups[key] = np.sort(group.time.to_numpy(dtype='datetime64[ns]'))
    span = np.timedelta64(int(window_days), 'D')
    for position, (key, timestamp) in enumerate(zip(queries[group_column], qt, strict=True)):
        if pd.isna(key) or pd.isna(timestamp) or key not in event_groups:
            continue
        times = event_groups[key]
        query = np.datetime64(timestamp.to_datetime64(), 'ns')
        result[position] = np.searchsorted(times, query, side='left') - np.searchsorted(times, query-span, side='left')
    return pd.Series(result, index=queries.index, name='past_event_count')


def build_history_feasibility(tables, cutoff='2018-05-01'):
    """Aggregate prospective handover-history support in the inspected window.

    Include valid approval/handover records regardless of final order status.
    Primary seller and route are static order-level proxies, not package scans.
    """
    orders, items = tables['orders'].copy(), tables['items'].copy()
    customers, sellers = tables['customers'], tables['sellers']
    for name in ('order_purchase_timestamp', 'order_approved_at', 'order_delivered_carrier_date'):
        orders[name] = _times(orders[name], name)
    stop = pd.Timestamp(cutoff)
    valid = orders.order_approved_at.notna() & orders.order_purchase_timestamp.notna()
    valid &= (orders.order_approved_at >= orders.order_purchase_timestamp) & (orders.order_approved_at < stop)
    orders = orders.loc[valid].copy()
    items['price'] = pd.to_numeric(items.price, errors='raise')
    items['order_item_id'] = pd.to_numeric(items.order_item_id, errors='raise')
    primary = items.sort_values(['order_id', 'price', 'order_item_id'], ascending=[True, False, True], kind='stable').drop_duplicates('order_id')
    frame = orders.merge(primary[['order_id','seller_id']], on='order_id', how='left', validate='one_to_one')
    frame = frame.merge(customers[['customer_id','customer_state']], on='customer_id', how='left', validate='many_to_one')
    frame = frame.merge(sellers[['seller_id','seller_state']], on='seller_id', how='left', validate='many_to_one')
    frame['route'] = frame.seller_state + '->' + frame.customer_state
    frame['prediction_time'] = frame.order_approved_at
    frame['global_group'] = 'all_valid_handovers'
    handover = frame.order_delivered_carrier_date
    event_mask = handover.notna() & (handover >= frame.order_approved_at) & (handover < stop)
    events = frame.loc[event_mask].copy()
    events['event_time'] = events.order_delivered_carrier_date
    support = {name: history_support_counts(frame, events, column)
               for name,column in (('global','global_group'),('primary_seller','seller_id'),('state_route','route'))}
    months = frame.prediction_time.dt.strftime('%Y-%m')

    def summary(mask):
        result = {'query_rows': int(mask.sum()), 'groups': {}}
        for name, values in support.items():
            sample = values.loc[mask]
            result['groups'][name] = {
                'no_past_event_rows': int(sample.eq(0).sum()),
                'at_least_one_event_rows': int(sample.ge(1).sum()),
                'at_least_five_event_rows': int(sample.ge(5).sum()),
                'at_least_twenty_event_rows': int(sample.ge(20).sum()),
                'at_least_five_event_fraction': float(sample.ge(5).mean()) if len(sample) else None,
                'support_median': float(sample.median()) if len(sample) else None,
                'support_max': int(sample.max()) if len(sample) else None,
            }
        return result

    return {
        'cutoff_exclusive': stop.isoformat(), 'window_days': 90,
        'event_rows': len(events), 'query_rows': len(frame),
        'event_definition': 'Valid approval<=carrier<cutoff, independent of final status; each query uses carrier in [query-90days,query).',
        'source_assumptions': 'Export event time stands for timely availability; order-level primary seller chosen by highest item price then lowest item ID; route uses static master states.',
        'not_measured': 'Support only; no fitted model, recall estimate, latency feature selection by target, or post-cutoff order outcomes.',
        'overall': summary(pd.Series(True,index=frame.index)),
        'by_approval_month': {month: summary(months.eq(month)) for month in sorted(months.unique())},
    }
