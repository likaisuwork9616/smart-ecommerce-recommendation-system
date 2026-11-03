"""Equivalent independent-oracle checks and bounded synthetic benchmarks.

No production model, loader or evaluator is imported.  Metric cache entries
come from the frozen Decimal oracle.  Exact-check acceleration is restricted
to ordinary JSON values; every unsupported or nonmatching case delegates to
the frozen JSON encoder comparison, preserving its rejection semantics.
"""
from copy import deepcopy
from decimal import getcontext
from functools import lru_cache
import json
import math
from statistics import median
import sys
from time import perf_counter

from scripts.retailrocket_popularity_oracle import (
    terms as _frozen_terms, discounts as _discounts)
from scripts.retailrocket_session_knn_oracle import exact as _frozen_exact


# Selected only after a bounded synthetic benchmark; importing never benchmarks.
EXACT_STRATEGY = 'frozen'
_FALLBACK = object()
_CACHE_CONTEXT = None
_context_fallbacks = 0
_label_fallbacks = 0


def _context_token():
    context = getcontext()
    return (context.prec, context.rounding, context.Emin, context.Emax,
            context.capitals, context.clamp, tuple(context.traps.values()),
            tuple(_discounts().values()))


@lru_cache(maxsize=4096)
def _pattern_terms(places, target_count):
    # Only rank membership and the full target count affect the frozen result.
    # Synthetic disjoint labels feed the unchanged frozen arithmetic.
    targets = tuple('hit:' + str(index) for index in range(target_count))
    ranks = set(places)
    hit = 0
    predicted = []
    for rank in range(1, max(places, default=0) + 1):
        if rank in ranks:
            predicted.append(targets[hit])
            hit += 1
        else:
            predicted.append('miss:' + str(rank))
    return _frozen_terms(predicted, targets)


def terms(ids, targets):
    """Validate first, cache by hit ranks/full truth count, return fresh dicts.

    The numeric context and frozen discount values must match the cache's
    initial context.  A different context uses the original function directly.
    ``clear_caches`` is a run-boundary operation, not a concurrent mutation API.
    """
    global _CACHE_CONTEXT, _context_fallbacks, _label_fallbacks
    # The pattern proof assumes ordinary, stable scalar equality.  Let the
    # original function own validation for custom containers/labels unchanged.
    plain_labels = (str, int, float, bool, type(None))
    if (type(ids) not in (list, tuple) or type(targets) not in (list, tuple)
            or any(type(value) not in plain_labels for value in ids)
            or any(type(value) not in plain_labels for value in targets)):
        _label_fallbacks += 1
        binary, precise = _frozen_terms(ids, targets)
        return dict(binary), dict(precise)
    if not targets or len(targets) != len(set(targets)):
        raise ValueError('Oracle invalid full target set')
    if len(ids) > 10 or len(ids) != len(set(ids)):
        raise ValueError('Oracle invalid predictions')
    truth = set(targets)
    places = tuple(rank for rank, item in enumerate(ids, 1) if item in truth)
    token = _context_token()
    if _CACHE_CONTEXT is None:
        _CACHE_CONTEXT = token
    if token != _CACHE_CONTEXT:
        _context_fallbacks += 1
        binary, precise = _frozen_terms(ids, targets)
    else:
        binary, precise = _pattern_terms(places, len(targets))
    return dict(binary), dict(precise)


def clear_caches():
    global _CACHE_CONTEXT, _context_fallbacks, _label_fallbacks
    _pattern_terms.cache_clear()
    _CACHE_CONTEXT = None
    _context_fallbacks = 0
    _label_fallbacks = 0


def cache_info():
    return {'terms': dict(_pattern_terms.cache_info()._asdict()),
            'context_fallbacks': _context_fallbacks, 'label_fallbacks': _label_fallbacks,
            'exact_strategy': EXACT_STRATEGY}


def _safe_integer(value):
    bits = value.bit_length()
    if bits <= 1024:
        # The smallest enabled CPython decimal digit limit is 640 digits.
        return True
    limit = sys.get_int_max_str_digits()
    # A deliberately conservative fast domain; boundary cases use JSON itself.
    return bool(limit and bits <= 3 * limit)


def _equal_json(actual, expected, actual_stack, expected_stack):
    actual_type, expected_type = type(actual), type(expected)
    scalar_types = (str, int, float, bool, type(None))
    container_types = (dict, list, tuple)
    if (actual_type not in scalar_types + container_types
            or expected_type not in scalar_types + container_types):
        return _FALLBACK
    if actual_type in (list, tuple) and expected_type in (list, tuple):
        kind = 'array'
    elif actual_type is not expected_type:
        return False
    elif actual_type is str:
        if not actual.isascii() or not expected.isascii():
            return _FALLBACK
        return actual == expected
    elif actual_type is int:
        if not _safe_integer(actual) or not _safe_integer(expected):
            return _FALLBACK
        return actual == expected
    elif actual_type is float:
        if not math.isfinite(actual) or not math.isfinite(expected):
            return _FALLBACK
        return actual == expected and (actual != 0.0 or
               math.copysign(1.0, actual) == math.copysign(1.0, expected))
    elif actual_type is bool or actual_type is type(None):
        return actual is expected
    else:
        kind = 'object'
    if kind == 'object':
        if any(type(key) is not str or not key.isascii() for key in actual):
            return _FALLBACK
        if any(type(key) is not str or not key.isascii() for key in expected):
            return _FALLBACK
        if len(actual) != len(expected) or actual.keys() != expected.keys():
            return False
    elif len(actual) != len(expected):
        return False
    actual_id, expected_id = id(actual), id(expected)
    if actual_id in actual_stack or expected_id in expected_stack:
        return _FALLBACK
    actual_stack.add(actual_id); expected_stack.add(expected_id)
    try:
        if kind == 'object':
            for key in expected:
                result = _equal_json(actual[key], expected[key], actual_stack, expected_stack)
                if result is not True:
                    return result
        else:
            for left, right in zip(actual, expected):
                result = _equal_json(left, right, actual_stack, expected_stack)
                if result is not True:
                    return result
        return True
    finally:
        actual_stack.remove(actual_id); expected_stack.remove(expected_id)


def recursive_exact(actual, expected):
    """Fast affirmation for the safe domain; frozen authority for everything else."""
    try:
        result = _equal_json(actual, expected, set(), set())
    except RecursionError:
        result = _FALLBACK
    if result is not True:
        # Mismatches also use the frozen checker.  This preserves exceptions
        # from unsupported, nonfinite, circular and digit-limited JSON values.
        return _frozen_exact(actual, expected)


def exact(actual, expected):
    if EXACT_STRATEGY == 'typed_recursive':
        return recursive_exact(actual, expected)
    return _frozen_exact(actual, expected)


def _benchmark_payload(neighbors):
    selected = [{'key': [str(1000 + index), 10 + index], 'intersection': 1 + index % 3,
                 'union': 4 + index % 5, 'similarity': [1 + index % 3, 4 + index % 5]}
                for index in range(neighbors)]
    prediction = {'fit_id': 'synthetic-only-fit', 'ids': [str(i) for i in range(1, 11)],
                  'scores': [[i, i + 1] for i in range(1, 11)],
                  'candidate_count': 222754, 'selected_neighbors': selected,
                  'selected_neighbor_count': neighbors, 'boundary_similarity': [1, 4],
                  'current_session_excluded': 0, 'fallback_reason': None,
                  'diagnostic_flag': False, 'signed_zero': -0.0}
    return {'key': ['synthetic-visitor', 10, 110], 'history': ['1', '2', '99'],
            'predictions': {'K1': prediction, 'P0': {'ids': ['1', '2'], 'candidate_count': 222754}},
            'terms': {'K1': {'ndcg': 0.5, 'hits': 1, 'first_hit_rank': 2}},
            'delta': {'K1_minus_P0': {'ndcg': 0.25, 'hit_rate': 1.0}},
            'engineering_fixture_only': True}


def benchmark_exact(*, repeats=5, number=20, neighbors=500):
    """Bounded synthetic equal-schema benchmark; no data, model or file access."""
    if (type(repeats) is not int or not 1 <= repeats <= 20
            or type(number) is not int or not 1 <= number <= 200
            or type(neighbors) is not int or not 1 <= neighbors <= 500):
        raise ValueError('Invalid bounded synthetic exact benchmark dimensions')
    left = _benchmark_payload(neighbors)
    right = deepcopy(left)
    _frozen_exact(left, right); recursive_exact(left, right)
    functions = {'frozen': _frozen_exact, 'typed_recursive': recursive_exact}
    timings = {name: [] for name in functions}
    for repeat in range(repeats):
        order = tuple(functions) if repeat % 2 == 0 else tuple(reversed(functions))
        for name in order:
            started = perf_counter()
            for _ in range(number):
                functions[name](left, right)
            timings[name].append((perf_counter() - started) / number)
    medians = {name: median(values) for name, values in timings.items()}
    faster = medians['typed_recursive'] < 0.95 * medians['frozen']
    return {'kind': 'bounded_synthetic_exact_microbenchmark', 'real_data_accessed': False,
            'neighbors': neighbors, 'repeats': repeats, 'calls_per_repeat': number,
            'schema_json_bytes': len(json.dumps(left, sort_keys=True, allow_nan=False).encode()),
            'per_call_seconds': timings, 'median_per_call_seconds': medians,
            'recursive_clearly_faster_on_this_fixture': faster,
            'recommended_strategy': 'typed_recursive' if faster else 'frozen',
            'default_strategy': EXACT_STRATEGY,
            'interpretation': 'Equal 500-neighbor artificial-schema checks only; not paired-query or full-readback speedup.'}
