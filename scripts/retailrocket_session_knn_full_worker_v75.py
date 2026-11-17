"""V75 synthetic-only full-order V2 readback with the frozen V4 exact core.

This is a new adapter: frozen V2/V4 modules are unchanged. The public orchestrator
must admit a sealed artificial bundle before constructing this trusted internal
API. There is deliberately no real-data CLI or selected-ordinal entry point.
No ranking, fixture construction or measurement occurs at import time.
"""
from bisect import bisect_left
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback_v2 as core
from scripts import retailrocket_session_knn_sql_v4 as sql
from scripts import retailrocket_session_knn_checks_v4 as checks
from scripts.retailrocket_session_knn_readback import (
    rows, ids, read_rows, num, close, GROUPS, METRICS, FIELDS, dump, exact)


REQUIRED_STAGES = ('reconstruction', 'queries', 'global', 'bootstrap')
MAX_SYNTHETIC_QUERIES = 129


def _validate_binding(binding):
    if type(binding) is not dict or binding.get('profile') != 'synthetic_only':
        raise cp.IntegrityError('V75 requires an admitted synthetic-only binding')
    count = binding.get('expected_queries')
    visitors = binding.get('expected_visitors')
    if type(count) is not int or not 1 <= count <= MAX_SYNTHETIC_QUERIES:
        raise cp.IntegrityError('V75 artificial query count must be an exact integer in 1..129')
    if type(visitors) is not int or not 1 <= visitors <= count:
        raise cp.IntegrityError('V75 artificial visitor count is invalid')
    if type(binding.get('bootstrap_replicates')) is not int or binding['bootstrap_replicates'] != 2000:
        raise cp.IntegrityError('V75 requires the original 2000 artificial draws')
    if type(binding.get('fixture_id')) is not str or not binding['fixture_id']:
        raise cp.IntegrityError('V75 fixture identity is missing')
    config = binding.get('configuration')
    if type(config) is not dict or config.get('synthetic_acceptance_only') is not True:
        raise cp.IntegrityError('V75 only accepts explicitly artificial configurations')
    fixed = config.get('fixed_validation', {})
    for field, expected in [('queries', count), ('visitors', visitors)]:
        if type(fixed.get(field)) is not int or fixed[field] != expected:
            raise cp.IntegrityError('V75 configuration and admitted counts differ')
    return count


def _validate_config(config, binding):
    _validate_binding(binding)
    if cp.encoded(config) != cp.encoded(binding['configuration']):
        raise cp.IntegrityError('V75 worker configuration differs from admitted binding')


class FullCheckpointStore(cp.CheckpointStore):
    """Retain V2 completion and source checks; add the V74 locked query guard."""

    def __init__(self, folder, binding, **kwargs):
        _validate_binding(binding)
        super().__init__(folder, binding, **kwargs)

    @classmethod
    def create(cls, folder, binding, deadline_utc, budget_seconds, *,
               expected_queries=None, required_stages=REQUIRED_STAGES, **kwargs):
        count = _validate_binding(binding)
        if expected_queries is None:
            expected_queries = count
        if type(expected_queries) is not int or expected_queries != count:
            raise cp.IntegrityError('V75 expected queries differ from admitted fixture')
        if tuple(required_stages) != REQUIRED_STAGES:
            raise cp.IntegrityError('V75 requires all four frozen completion stages')
        for key, value in [('max_chunk_rows', 64), ('chunk_queries', 64),
                           ('max_chunk_seconds', 120), ('chunk_seconds', 120)]:
            if key in kwargs and (type(kwargs[key]) is bool or kwargs[key] != value):
                raise cp.IntegrityError('V75 retains the original 64-query/120-second safe boundary')
        return super().create(folder, binding, deadline_utc, budget_seconds,
                              expected_queries=count, required_stages=REQUIRED_STAGES, **kwargs)

    def _load(self):
        super()._load()
        count = _validate_binding(self.binding)
        if (type(self.run.get('expected_queries')) is not int
                or self.run['expected_queries'] != count
                or self.run.get('required_stages') != list(REQUIRED_STAGES)
                or type(self.run.get('max_chunk_rows')) is not int
                or self.run['max_chunk_rows'] != 64
                or type(self.run.get('max_chunk_seconds')) is bool
                or self.run['max_chunk_seconds'] != 120):
            raise cp.IntegrityError('V75 persisted run does not match its synthetic completion contract')

    def _complete_checks(self):
        self._require_writer()
        summary, stages = super()._complete_checks()
        self.fault('before_queries_completion_guard')
        value = cp.read(self.folder / 'stages' / 'queries.json')
        receipt = value.get('receipt')
        count = self.binding['expected_queries']
        if (value.get('run_sha256') != self.run_sha
                or cp.encoded(value.get('ledger')) != cp.encoded(summary)
                or type(receipt) is not dict
                or type(receipt.get('queries')) is not int
                or receipt['queries'] != count
                or type(receipt.get('paired_streams_eof_checked')) is not bool
                or receipt['paired_streams_eof_checked'] is not True):
            raise cp.IntegrityError('V75 locked queries completion guard rejected stage semantics')
        # The same current stage must be the one returned to parent candidate /
        # finalize / supersede logic; first candidate creation needs no candidate.
        current = cp.descriptor(self.folder, 'stages/queries.json')
        if current not in stages:
            raise cp.IntegrityError('V75 queries stage changed during locked completion')
        return summary, stages

    def seal_stage(self, name, receipt, artifacts=()):
        result = super().seal_stage(name, receipt, artifacts)
        self.fault('after_stage_' + name)
        return result


def create_store(folder, binding, deadline_utc, budget_seconds, **kwargs):
    return FullCheckpointStore.create(folder, binding, deadline_utc, budget_seconds, **kwargs)


def open_store(folder, binding, **kwargs):
    return FullCheckpointStore.open(folder, binding, **kwargs)


def _key_csv(row):
    return row['visitorid'], num(row['session_start_ms']), num(row['query_ms'])


def verify_queries_full(primary,paths,config,store,model,watch=lambda:None,fault=lambda point:None):
    _validate_config(config, store.binding)
    store._require_writer()
    source,p0,c1,d1=(paths[x] for x in ('dataset','P0','C1','D1'))
    audit=model['fit_audit']; support=model['support']
    counts,catalog=core.load_context(paths,config,support,watch)
    prepared=sql.prepare_catalog(catalog,counts,watch)
    first_times=sorted(catalog.values())
    database=store.folder/'independent.sqlite'
    if any(Path(str(database)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise cp.IntegrityError('Sealed model has an unexpected SQLite journal')
    db=sqlite3.connect(database.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        db.execute('PRAGMA temp_store=MEMORY')
        db.set_progress_handler(lambda:(watch() or 0),10000)
        controls=[iter(read_rows(p0/name,FIELDS[name])) for name in ('ranked_queries.csv','query_metrics.csv','query_slices.csv')]
        controls += [iter(rows(c1/'queries.jsonl',watch)),iter(rows(d1/'queries.jsonl',watch))]
        outputs=iter(rows(primary/'queries.jsonl',watch)); previous=None
        committed=store.recover()['records']; saved=iter(store.iter_records()); ordinal=-1
        lo,hi=config['validation_window_ms']
        query_stream=iter(read_rows(source/'queries.csv',config['schemas']['queries.csv']))
        for raw in query_stream:
            watch()
            if raw['role']!='validation': continue
            ordinal+=1
            if ordinal<committed:
                record=next(saved)
                key=[raw['visitorid'],num(raw['session_start_ms']),num(raw['query_ms'])]
                exact(record['key'],key)
                prefix=[next(stream,None) for stream in controls]
                actual=next(outputs,None)
                if any(row is None for row in prefix) or actual is None:
                    raise ValueError('Missing source row while replaying committed prefix')
                for row in prefix[:3]:
                    if (_key_csv(row)!=tuple(key) or row['role']!='validation'):
                        raise ValueError('Prefix control CSV identity differs')
                for row in [*prefix[3:],actual]:
                    exact(row['key'],key)
                exact(actual,record['payload']['expected'])
                previous=tuple(key)
                fault('prefix_replayed')
                continue
            v=raw['visitorid'];num(v);s,t,nt,index=(num(raw[f]) for f in ('session_start_ms','query_ms','next_view_ms','basket_index'))
            key=(v,s,t)
            if previous is not None and key<=previous: raise ValueError('Oracle duplicate/unordered query')
            previous=key
            if not lo<=t<nt<hi or s>t or nt-t>1800000 or t+1800000>hi:
                raise ValueError('Oracle validation clock/horizon')
            for f,value in [('status','labelled'),('next_role','validation'),('next_in_session','1'),('mature','1'),('cross_role','0')]:
                if raw[f]!=value: raise ValueError('Oracle query label state')
            current=db.execute('SELECT k,n FROM h WHERE v=? AND s=? AND t=?',key).fetchone()
            if current is None or current[0]!=index: raise ValueError('Oracle missing current basket')
            history=set()
            for (text,) in db.execute('SELECT items FROM h WHERE v=? AND s=? AND t<=? ORDER BY t',key):
                watch();history.update(json.loads(text))
            history=sorted(history,key=int); targets=ids(raw['target_items'])
            successor=db.execute('SELECT t,k,role,items FROM h WHERE v=? AND s=? AND t>? ORDER BY t LIMIT 1',key).fetchone()
            if successor is None or successor[:3]!=(nt,index+1,'validation'):
                raise ValueError('Oracle next-basket identity')
            exact(sorted(targets,key=int),sorted(json.loads(successor[3]),key=int))
            reachable=sum(i in catalog and catalog[i]<t for i in targets); candidate=bisect_left(first_times,t)
            if (len(targets)!=num(raw['target_count']) or reachable!=num(raw['reachable_target_count'])
                    or candidate!=num(raw['candidate_count']) or raw['all_targets_reachable']!=str(int(reachable==len(targets)))):
                raise ValueError('Oracle full query denominators')
            values=[next(stream,None) for stream in controls]; actual=next(outputs,None)
            if any(x is None for x in values) or actual is None: raise ValueError('Oracle missing paired row')
            rank,metric,slices,one,three=values
            for r in (rank,metric,slices):
                if (r['visitorid'],num(r['session_start_ms']),num(r['query_ms']))!=key or r['role']!='validation':
                    raise ValueError('Oracle original P0 key/role')
            if rank['fit_id']!=config['control_fit_ids']['P0']: raise ValueError('Oracle P0 fit')
            p0ids=json.loads(rank['top10_items'])
            exact(json.loads(rank['top10_scores']),[counts.get(i,0) for i in p0ids])
            p0pred={'ids':p0ids,'candidate_count':num(rank['candidate_count'])}
            p0terms={m:float(metric[m]) for m in ('dcg','idcg',*METRICS)}
            p0terms.update(target_count=num(metric['target_count']),hits=num(metric['hits']),
                           first_hit_rank=num(metric['first_hit_rank']) if metric['first_hit_rank'] else None)
            if num(metric['reachable_target_count'])!=reachable or metric['all_targets_reachable']!=raw['all_targets_reachable']:
                raise ValueError('Oracle P0 target denominator')
            train=num(raw['train_view_events']); known=sum(i in support for i in targets)
            activity='0' if not train else '1' if train==1 else '2-5' if train<=5 else '6+'
            if raw['visitor_seen_before_fit'] not in ('0','1') or raw['train_activity_slice']!=activity:
                raise ValueError('Oracle visitor/activity state')
            names={'visitor_history':'seen' if raw['visitor_seen_before_fit']=='1' else 'new',
                'current_basket':'multiple' if current[1]>1 else 'single','target_basket':'multiple' if len(targets)>1 else 'single',
                'train_activity':activity,'target_model':'all_positive' if known==len(targets) else 'all_zero' if not known else 'mixed'}
            identity={'key':list(key),'history':history,'history_sha256':hashlib.sha256(dump(history).encode()).hexdigest(),
                      'targets':targets,'candidate_count':candidate,'reachable_targets':reachable,'slices':names}
            for ref in (one,three):
                for f,value in identity.items(): exact(ref[f],value)
                exact(ref['predictions']['P0'],p0pred);exact(ref['terms']['P0'],p0terms)
            exact({f:slices[f] for f in GROUPS},names)
            exact(one['predictions']['C1'],three['predictions']['C1']);exact(one['terms']['C1'],three['terms']['C1'])
            for arm in ('C1','D1'):
                if three['predictions'][arm]['fit_id']!=config['control_fit_ids'][arm]: raise ValueError('Oracle control fit')
            def query_watch():
                watch();fault('query_work')
            pred=dict(three['predictions'],K1=sql.predict(db,support,audit['fit_id'],prepared.counts,prepared,t,history,(v,s),query_watch))
            binary={};precise={}
            for arm in ('P0','C1','D1','K1'):
                prediction=pred[arm]
                if (prediction['candidate_count']!=candidate or len(prediction['ids'])!=min(10,candidate)
                        or any(i not in catalog or catalog[i]>=t for i in prediction['ids'])):
                    raise ValueError('Oracle complete causal control/K1 list')
                independently,precise[arm]=checks.terms(prediction['ids'],targets)
                if any(type(actual['terms'][arm][m]) is not float or not math.isfinite(actual['terms'][arm][m])
                       for m in ('dcg','idcg',*METRICS)):
                    raise ValueError('Oracle expected finite binary64 metric fields')
                close(actual['terms'][arm],independently)
                binary[arm]=actual['terms'][arm] if arm=='K1' else three['terms'][arm]
                if arm!='K1': exact(actual['terms'][arm],binary[arm])
            delta={'K1_minus_'+a:{m:binary['K1'][m]-binary[a][m] for m in METRICS} for a in ('C1','P0','D1')}
            expected=dict(identity,predictions=pred,terms=binary,delta=delta);exact(actual,expected)
            if pred['K1']['fallback_reason'] is not None: exact(pred['K1']['ids'],pred['P0']['ids'])
            payload={'expected':expected,
                'precise':{arm:{m:str(value) for m,value in metrics.items()} for arm,metrics in precise.items()},
                'delta_hex':{arm:{m:value.hex() for m,value in metrics.items()} for arm,metrics in delta.items()}}
            fault('before_append')
            store.append_verified(ordinal,list(key),payload)
            fault('query_verified')
        if any(next(stream,None) is not None for stream in [*controls,outputs]): raise ValueError('Oracle extra paired row')
        store.flush_chunk()
        if ordinal+1!=config['fixed_validation']['queries']:
            raise ValueError('Incomplete full validation query coverage')
        core.seal_consistent(store,'queries',{'queries':ordinal+1,'paired_streams_eof_checked':True})
        fault('after_queries_sealed')
        return {'queries':ordinal+1}
    finally:
        for stream in [*locals().get('controls',[]),locals().get('outputs'),
                       locals().get('query_stream'),locals().get('saved')]:
            if stream is not None and hasattr(stream,'close'):
                stream.close()
        db.close()


def verify_full(primary, paths, config, store, watch=lambda: None, fault=lambda point: None):
    """Read every original artificial query; caller owns the worker writer lock.

    The V2 reconstruction and full global/original-draw unit are reused directly.
    Each attempt has a fresh V4 metric cache, including fault/recovery attempts.
    The result method label names the actual V4 core; it is never a real-scale
    acceptance, capacity result, or a clock/performance calibration.
    """
    if not isinstance(store, FullCheckpointStore):
        raise cp.IntegrityError('V75 requires its locked queries completion store')
    store._require_writer()
    _validate_config(config, store.binding)
    checks.clear_caches()
    try:
        if (store.folder / 'candidate.json').exists():
            store.supersede_candidate()
        model = core.prepare_model(primary, paths, config, store, watch, fault)
        verify_queries_full(primary, paths, config, store, model, watch, fault)
        result = core.replay_global(primary, paths, config, store, model, watch, fault)
        result['ranking_method'] = 'independent_SQL_positive_overlap_exact_v4_full_order_v75'
        result['entry_profile'] = 'synthetic_only'
        result['real_full_acceptance'] = False
        fault('before_candidate')
        store.write_candidate(result)
        return result
    finally:
        checks.clear_caches()
