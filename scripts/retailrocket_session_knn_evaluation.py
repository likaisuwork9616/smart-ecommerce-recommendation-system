"""Pure validation-role four-arm evaluation; no real-data loader or execution CLI."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math

from scripts import retailrocket_session_knn as k
from scripts import retailrocket_popularity as p

ARMS = ('P0','C1','D1','K1')
CONTROLS = ('C1','P0','D1')
DIAGNOSTICS = ('history_size','unknown_seeds','eligible_neighbors','current_session_excluded',
               'selected_neighbor_count','boundary_ties_excluded','positive_candidates','zero_fill_slots','fallback_reason')


def exact(a,b,label):
    if json.dumps(a,sort_keys=True,allow_nan=False) != json.dumps(b,sort_keys=True,allow_nan=False):
        raise ValueError('Reference identity differs: '+label)


class Fold:
    def __init__(self,catalog):
        self.arms = {a:p.Aggregate(catalog) for a in ARMS}
        self.delta = {a:{m:[] for m in p.METRICS} for a in CONTROLS}

    def add(self,q,predictions,terms,reachable):
        for arm in ARMS:
            self.arms[arm].add(q,predictions[arm],terms[arm],reachable)
        for control in CONTROLS:
            for m in p.METRICS:
                self.delta[control][m].append(terms['K1'][m]-terms[control][m])

    def result(self):
        arms = {a:f.result() for a,f in self.arms.items()}; n = arms['K1']['queries']
        comparisons = {}
        for control in CONTROLS:
            values = {m:math.fsum(xs)/n if n else None for m,xs in self.delta[control].items()}
            for m in ('visitor_macro_ndcg','catalog_coverage'):
                x,y = arms['K1']['metrics'][m],arms[control]['metrics'][m]
                values[m] = x-y if x is not None and y is not None else None
            comparisons['K1_minus_'+control] = {'delta_metrics':values}
        return {'arms':arms,'comparisons':comparisons,'queries':n,'visitors':arms['K1']['visitors']}


def evaluate(ranker, baskets, queries, references, reference_draws, control_fit_ids, validation_window,
             expected, emit_query=None, emit_bootstrap=None, watch=lambda: None):
    lo,hi = validation_window
    if (type(lo) is not int or type(hi) is not int or lo != ranker.model.audit['end_ms'] or lo >= hi
            or set(control_fit_ids) != {'P0','C1','D1'}):
        raise ValueError('Validation window/control identity')
    histories = k.Histories(baskets); saved = iter(references)
    folds = {'main':Fold(ranker.catalog),'conditional':Fold(ranker.catalog)}
    groups = {f:{g:Fold(ranker.catalog) for g in names} for f,names in p.GROUPS.items()}
    diagnostics = {name:Counter() for name in DIAGNOSTICS}
    cross = Counter(); deltas = []; previous = None; roster = hashlib.sha256()
    for raw,index in queries:
        watch()
        if raw.role != 'validation' or not lo <= raw.query_ms < hi:
            raise ValueError('Only contracted validation queries accepted')
        if previous is not None and raw.key() <= previous:
            raise ValueError('Duplicate/unordered query')
        previous = raw.key()
        if type(index) is not int or index < 1:
            raise ValueError('Invalid basket index')
        history = histories.at(raw,index)
        q = replace(raw,current_size=len(histories.current.items))
        ref = next(saved,None)
        if ref is None:
            raise ValueError('Missing reference query')
        exact(ref['control_fit_ids'],control_fit_ids,'control provenance')
        exact(ref['key'],list(q.key()),'query key')
        exact(ref['history'],list(history),'history')
        exact(ref['targets'],list(q.targets),'targets')
        history_sha = hashlib.sha256(k.encoded(list(history)).encode()).hexdigest()
        exact(ref['history_sha256'],history_sha,'history hash')
        reachable = sum(ranker.catalog.contains(i,q.query_ms) for i in q.targets)
        if (q.candidate_count != ranker.catalog.size(q.query_ms) or ref['candidate_count'] != q.candidate_count
                or q.reachable_count != reachable or ref['reachable_targets'] != reachable
                or type(q.all_reachable) is not bool or q.all_reachable != (reachable == len(q.targets))):
            raise ValueError('Full candidate/target denominator differs')
        names = p.slice_names(q,ranker.model.support)
        exact(ref['slices'],names,'slices')
        predictions = {}; terms = {}
        for arm in ('P0','C1','D1'):
            pred = ref['predictions'][arm]; metric = ref['terms'][arm]
            if arm != 'P0' and pred['fit_id'] != control_fit_ids[arm]:
                raise ValueError('Control fit identity differs')
            # P0's original three-arm record does not carry its fit_id; caller binds it separately.
            if (pred['candidate_count'] != q.candidate_count or len(pred['ids']) != min(10,q.candidate_count)
                    or len(pred['ids']) != len(set(pred['ids']))
                    or any(not ranker.catalog.contains(p.item(i),q.query_ms) for i in pred['ids'])
                    or metric['target_count'] != len(q.targets)
                    or any(type(metric[m]) is not float or not math.isfinite(metric[m]) for m in p.METRICS)):
                raise ValueError('Invalid control prediction/metric')
            predictions[arm] = deepcopy(pred); terms[arm] = deepcopy(metric)
        predictions['K1'] = ranker.rank(q.query_ms,history,(q.visitorid,q.session_start_ms),watch)
        terms['K1'] = p.metric_terms(predictions['K1']['ids'],q.targets)
        pred = predictions['K1']
        if pred['fallback_reason'] is not None and pred['ids'] != predictions['P0']['ids']:
            raise ValueError('Complete fallback differs from P0')
        folds['main'].add(q,predictions,terms,reachable)
        if q.all_reachable:
            folds['conditional'].add(q,predictions,terms,reachable)
        for family,group in names.items():
            groups[family][group].add(q,predictions,terms,reachable)
        delta = {'K1_minus_'+arm:{m:terms['K1'][m]-terms[arm][m] for m in p.METRICS} for arm in CONTROLS}
        deltas.append((q.visitorid,delta['K1_minus_C1']['ndcg']))
        row = {'key':list(q.key()),'history':list(history),'history_sha256':history_sha,'targets':list(q.targets),
               'candidate_count':q.candidate_count,'reachable_targets':reachable,'predictions':predictions,
               'terms':terms,'delta':delta,'slices':names}
        if emit_query:
            emit_query(row)
        roster.update((k.encoded(list(q.key()))+'\n').encode())
        for name in DIAGNOSTICS:
            diagnostics[name][str(pred[name]) if name != 'fallback_reason' else pred[name] or 'positive_evidence'] += 1
        cross[k.encoded([pred['fallback_reason'] is not None,
            predictions['C1']['positive_candidates'] == 0,predictions['D1']['positive_candidates'] == 0,names['target_model']])] += 1
    if next(saved,None) is not None:
        raise ValueError('Extra reference query')
    main = folds['main'].result(); floor = max(50,(main['queries']+99)//100)
    result = {'main':main,'conditional':folds['conditional'].result(),'slices':{},'support_floor_queries':floor,
              'diagnostics':{name:dict(count) for name,count in diagnostics.items()},
              'fallback_cold_cross_tabs':dict(cross),'roster_sha256':roster.hexdigest()}
    for family,buckets in groups.items():
        result['slices'][family] = {}
        for group,fold in buckets.items():
            summary = fold.result(); n = summary['queries']
            summary['support'] = 'empty' if not n else 'descriptive_only' if n < floor else 'sufficient_query_count'
            result['slices'][family][group] = summary
    for name,value in expected.items():
        if name == 'support_floor_queries':
            actual = floor
        else:
            actual = main['arms']['K1'][name]
        if type(actual) is not type(value) or actual != value:
            raise ValueError('Fixed validation denominator changed: '+name)
    result['uncertainty'] = k.bootstrap(deltas,reference_draws,emit_bootstrap,watch)
    return result
