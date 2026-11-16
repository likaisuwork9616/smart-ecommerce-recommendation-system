"""Pair all saved contained-interval load summaries without scope selection."""
from copy import deepcopy
from math import isfinite
from statistics import median

from scripts.retailrocket_session_knn_entry_load_v59 import SCHEDULE, ORDERS
from scripts.retailrocket_session_knn_coarse_phases_v60 import PHASES
from scripts.retailrocket_session_knn_contained_load_v61 import METRICS


def _number(value, name, *, positive=False):
    try:
        valid = (type(value) in (int, float) and isfinite(value)
                 and (value > 0 if positive else value >= 0))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Finite nonnegative summary value required: ' + name)


def _distribution(values):
    available = [value for value in values if value is not None]
    return dict(count=len(values), valid=len(available), missing=len(values)-len(available),
        min=min(available) if available else None,
        median=median(available) if available else None,
        max=max(available) if available else None)


def _delta(candidate, reference):
    return {name: (None if candidate[name] is None or reference[name] is None
                   else candidate[name]-reference[name]) for name in METRICS}


def summarize_window(entries):
    """Keep all six formal pairs and seven phases; warm entries stay separate.

    Per-phase summary payloads were validated by the contained-load core and
    are carried unchanged. Null resource values remain null in paired deltas.
    Full-entry differences retain their separate timer and are never inferred
    by adding the seven selected phases or resource intervals.
    """
    if not isinstance(entries, dict) or set(entries) != {row['label'] for row in SCHEDULE}:
        raise ValueError('Exactly fourteen original entry labels required')
    for label, entry in entries.items():
        if not isinstance(entry, dict) or not {'entry_seconds', 'phases'} <= set(entry):
            raise ValueError('Entry timer and phase summaries required')
        _number(entry['entry_seconds'], label + '.entry_seconds', positive=True)
        phases = entry['phases']
        if not isinstance(phases, dict) or set(phases) != set(PHASES):
            raise ValueError('Exactly seven fixed phases required for every entry')
        for phase in PHASES:
            row = phases[phase]
            if (not isinstance(row, dict) or not {'summary', 'metrics'} <= set(row)
                    or not isinstance(row['summary'], dict)
                    or not isinstance(row['metrics'], dict) or set(row['metrics']) != set(METRICS)):
                raise ValueError('Complete fixed contained-load metrics and summary required')
            for name, value in row['metrics'].items():
                if value is not None:
                    _number(value, label + '.' + phase + '.' + name)

    formal = {row['label']: deepcopy(entries[row['label']]) for row in SCHEDULE[2:]}
    warm = {row['label']: deepcopy(entries[row['label']]) for row in SCHEDULE[:2]}
    pairs = []
    for pair, order in enumerate(ORDERS, 1):
        reference, candidate = (formal[f'pair_{pair}_{arm}'] for arm in ('R', 'C'))
        phases = {}
        for phase in PHASES:
            r, c = (entry['phases'][phase]['metrics'] for entry in (reference, candidate))
            phases[phase] = dict(R=deepcopy(r), C=deepcopy(c), delta_C_minus_R=_delta(c, r))
        pairs.append(dict(pair=pair, order=order,
            full_entry_delta_C_minus_R=candidate['entry_seconds']-reference['entry_seconds'], phases=phases))

    summaries = {}
    for phase in PHASES:
        summaries[phase] = {arm: {
            metric: _distribution([formal[f'pair_{pair}_{arm}']['phases'][phase]['metrics'][metric]
                                   for pair in range(1, 7)]) for metric in METRICS}
            for arm in ('R', 'C')}
        summaries[phase]['paired_delta_summary'] = {
            metric: _distribution([pair['phases'][phase]['delta_C_minus_R'][metric] for pair in pairs])
            for metric in METRICS}
    return dict(formal_entries=formal, warm_entries=warm, pairs=pairs, formal_by_phase=summaries)
