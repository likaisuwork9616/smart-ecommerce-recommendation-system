"""D1 three-arm validation adapter; original P0/C1 outputs are read-only controls."""
from collections import Counter
from contextlib import ExitStack
import csv
from dataclasses import replace
import hashlib
import json
import math

from scripts import retailrocket_directed as d
from scripts import retailrocket_popularity as p
from scripts import retailrocket_popularity_io as old
from scripts import retailrocket_cooccurrence_io as inherited

ARTIFACTS=('support.csv','edges.csv','train_sessions.jsonl','queries.jsonl','bootstrap.jsonl','fit_audit.json','aggregate.json')
EDGE_HEADER=['itemid_from','itemid_to','count']
dump=inherited.dump
close=inherited.close
baskets=inherited.baskets
queries=inherited.queries
controls=inherited.controls
CONTRASTS={'D1_minus_C1':'C1','D1_minus_P0':'P0'}


def jsonlines(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            value=json.loads(line)
            if not isinstance(value,dict):raise ValueError('Expected JSONL object')
            yield value


def references(baseline,c1_reference):
    counts={};support={};pairs={}
    for r in old.records(baseline/'item_counts.csv',old.HEADERS['item_counts.csv']):
        i=p.item(r['itemid']);n=old.number(r['count'])
        if i in counts or n<1:raise ValueError('Invalid reused P0 counts')
        counts[i]=n
    for r in old.records(c1_reference/'support.csv',['itemid','support']):
        i=p.item(r['itemid']);n=old.number(r['support'])
        if i in support or n<1:raise ValueError('Invalid reused C1 support')
        support[i]=n
    for r in old.records(c1_reference/'pairs.csv',['itemid_a','itemid_b','count']):
        a=p.item(r['itemid_a']);b=p.item(r['itemid_b']);n=old.number(r['count'])
        if (a,b) in pairs or int(a)>=int(b) or n<1:raise ValueError('Invalid reused C1 pairs')
        pairs[a,b]=n
    return counts,support,pairs


class ThreeFold:
    def __init__(self,cat):
        self.arms={a:p.Aggregate(cat) for a in ('P0','C1','D1')}
        self.deltas={c:{m:[] for m in p.METRICS} for c in CONTRASTS}
    def add(self,q,pred,terms,reachable):
        for a,fold in self.arms.items():fold.add(q,pred[a],terms[a],reachable)
        for c,control in CONTRASTS.items():
            for m in p.METRICS:self.deltas[c][m].append(terms['D1'][m]-terms[control][m])
    def result(self):
        arms={a:v.result() for a,v in self.arms.items()};n=arms['D1']['queries'];comparisons={}
        for c,control in CONTRASTS.items():
            delta={m:math.fsum(v)/n if n else None for m,v in self.deltas[c].items()}
            for m in ('visitor_macro_ndcg','catalog_coverage'):
                a,b=arms['D1']['metrics'][m],arms[control]['metrics'][m]
                delta[m]=a-b if a is not None and b is not None else None
            comparisons[c]={'delta_metrics':delta}
        return arms,{'queries':n,'visitors':arms['D1']['visitors'],'comparisons':comparisons}


def build(folder,source,baseline,c1_reference,schemas,policy,parent,expected_p0=None,expected_c1=None,watch=lambda:None):
    counts,support,pairs=references(baseline,c1_reference)
    start=old.ms(policy['comparison']['fit_start_inclusive_utc']);end=old.ms(policy['comparison']['fit_end_exclusive_utc'])
    cat=old.catalog(source,schemas)
    if any((folder/name).exists() for name in ARTIFACTS):raise FileExistsError('D1 output exists; preserve partial/complete output')
    with ExitStack() as stack:
        handles={name:stack.enter_context((folder/name).open('x',encoding='utf-8',newline='')) for name in ARTIFACTS if name!='support.csv'}
        with (c1_reference/'support.csv').open('rb') as src,(folder/'support.csv').open('xb') as dst:
            while block:=src.read(1024*1024):watch();dst.write(block)
        model=d.fit(baskets(source,schemas,('train',)),start,end,support,pairs,counts,
                    lambda row:handles['train_sessions.jsonl'].write(dump(row)+'\n'),watch)
        writer=csv.writer(handles['edges.csv'],lineterminator='\n');writer.writerow(EDGE_HEADER)
        for a,b in sorted(model.edges,key=lambda e:(int(e[0]),int(e[1]))):
            watch();writer.writerow([a,b,model.edges[a,b]])
        audit=dict(model.audit,fit_id=model.fit_id)
        handles['fit_audit.json'].write(dump(audit)+'\n')
        ranker=d.Ranker(model,counts,cat)
        histories=d.Histories(baskets(source,schemas,('warmup','train','validation')))
        p0_control=iter(controls(baseline));c1_control=iter(jsonlines(c1_reference/'queries.jsonl'))
        previous=None;records=[];roster=hashlib.sha256();main=ThreeFold(cat);conditional=ThreeFold(cat)
        groups={f:{g:ThreeFold(cat) for g in names} for f,names in p.GROUPS.items()}
        diagnostics={name:Counter() for name in ('history_size','supported_seeds','outgoing_seeds','positive_evidence',
                                                 'fallback_reason','zero_fill_slots','incoming_target_support')}
        implication={k:0 for k in ('C1_full_fallback_queries','D1_full_fallback_queries',
                                   'C1_full_fallback_and_D1_positive','additional_D1_full_fallback_queries')}
        for raw,index in queries(source,schemas,parent):
            watch()
            if previous is not None and raw.key()<=previous:raise ValueError('Duplicate/unordered query roster')
            previous=raw.key();history=histories.at(raw,index);q=replace(raw,current_size=len(histories.current.items))
            saved0=next(p0_control,None);saved1=next(c1_control,None)
            if saved0 is None or saved1 is None:raise ValueError('Missing P0 or C1 paired query')
            rank,metric,saved_slices=saved0
            if ((rank['visitorid'],old.number(rank['session_start_ms']),old.number(rank['query_ms']))!=q.key()
                    or rank['role']!='validation' or saved1['key']!=list(q.key())):
                raise ValueError('Three-way query roster not one-to-one')
            if rank['fit_id']!=policy['reference_identity']['P0_fit_id']:raise ValueError('Wrong reused P0 fit')
            history_hash=hashlib.sha256(dump(list(history)).encode()).hexdigest()
            if saved1['history']!=list(history) or saved1['history_sha256']!=history_hash or saved1['targets']!=list(q.targets):
                raise ValueError('C1 current history/target identity changed')
            pred0={'ids':json.loads(rank['top10_items']),'candidate_count':old.number(rank['candidate_count'])}
            terms0={k:float(metric[k]) for k in ('dcg','idcg',*p.METRICS)}
            terms0.update(target_count=old.number(metric['target_count']),hits=old.number(metric['hits']),
                          first_hit_rank=old.number(metric['first_hit_rank']) if metric['first_hit_rank'] else None)
            if pred0!=saved1['predictions']['P0'] or terms0!=saved1['terms']['P0']:
                raise ValueError('P0 originals and stored C1 control values differ')
            pred1=saved1['predictions']['C1'];terms1=saved1['terms']['C1']
            if pred1['fit_id']!=policy['reference_identity']['C1_fit_id']:raise ValueError('Wrong reused C1 fit')
            for pred,terms in ((pred0,terms0),(pred1,terms1)):
                if (pred['candidate_count']!=cat.size(q.query_ms) or len(pred['ids'])!=min(10,q.candidate_count)
                        or len(set(pred['ids']))!=len(pred['ids']) or any(not cat.contains(p.item(i),q.query_ms) for i in pred['ids'])):
                    raise ValueError('Reference candidate/list mismatch')
                if any(not math.isfinite(v) for v in terms.values() if type(v) is float):raise ValueError('Nonfinite reference metric')
            pred2=ranker.rank(q.query_ms,history);terms2=p.metric_terms(pred2['ids'],q.targets)
            reachable=sum(cat.contains(i,q.query_ms) for i in q.targets)
            if (q.candidate_count!=pred2['candidate_count'] or saved1['candidate_count']!=q.candidate_count
                    or q.reachable_count!=reachable or saved1['reachable_targets']!=reachable
                    or q.all_reachable!=(reachable==len(q.targets)) or terms0['target_count']!=len(q.targets)
                    or terms1['target_count']!=len(q.targets) or metric['reachable_target_count']!=str(reachable)
                    or old.boolean(metric['all_targets_reachable'])!=q.all_reachable):
                raise ValueError('Three-arm full target/candidate denominator mismatch')
            memberships=p.slice_names(q,counts)
            if saved1['slices']!=memberships or any(saved_slices[k]!=v for k,v in memberships.items()):
                raise ValueError('Shared support/slice definitions changed')
            if pred2['supported_seeds']!=pred1['supported_seeds'] or pred2['positive_candidates']>pred1['positive_candidates']:
                raise ValueError('D1/C1 support or positive-set upper bound failed')
            c1_fallback=pred1['positive_candidates']==0;d1_fallback=pred2['positive_candidates']==0
            implication['C1_full_fallback_queries']+=c1_fallback
            implication['D1_full_fallback_queries']+=d1_fallback
            implication['C1_full_fallback_and_D1_positive']+=c1_fallback and not d1_fallback
            implication['additional_D1_full_fallback_queries']+=d1_fallback and not c1_fallback
            if c1_fallback and not d1_fallback:raise ValueError('C1 full fallback must imply D1 full fallback')
            if d1_fallback and pred2['ids']!=pred0['ids']:raise ValueError('Full D1 fallback differs from original P0')
            predictions={'P0':saved1['predictions']['P0'],'C1':pred1,'D1':pred2}
            terms={'P0':saved1['terms']['P0'],'C1':terms1,'D1':terms2}
            main.add(q,predictions,terms,reachable)
            if q.all_reachable:conditional.add(q,predictions,terms,reachable)
            for family,g in memberships.items():groups[family][g].add(q,predictions,terms,reachable)
            delta={c:{m:terms2[m]-terms[control][m] for m in p.METRICS} for c,control in CONTRASTS.items()}
            records.append((q.visitorid,delta['D1_minus_C1']['ndcg']))
            incoming=sum(i in ranker.incoming for i in q.targets)
            incoming_group='all' if incoming==len(q.targets) else 'none' if incoming==0 else 'mixed'
            output={'key':list(q.key()),'history':list(history),'history_sha256':history_hash,'targets':list(q.targets),
                    'candidate_count':q.candidate_count,'reachable_targets':reachable,'predictions':predictions,
                    'terms':terms,'delta':delta,'slices':memberships,'incoming_target_support':incoming_group}
            handles['queries.jsonl'].write(dump(output)+'\n');roster.update((dump(list(q.key()))+'\n').encode())
            diagnostics['history_size'][str(len(history))]+=1
            for name in ('supported_seeds','outgoing_seeds','zero_fill_slots'):diagnostics[name][str(pred2[name])]+=1
            e=pred2['positive_candidates'];diagnostics['positive_evidence']['0' if not e else '1-9' if e<10 else 'at_least_10']+=1
            diagnostics['fallback_reason'][pred2['fallback_reason'] or 'positive_evidence']+=1
            diagnostics['incoming_target_support'][incoming_group]+=1
        if next(p0_control,None) is not None or next(c1_control,None) is not None:raise ValueError('Extra P0/C1 query')
        arms,paired=main.result();conditional_arms,paired['conditional']=conditional.result()
        floor=max(50,(paired['queries']+99)//100);paired['slices']={}
        for a in arms:arms[a].update(conditional=conditional_arms[a],support_floor_queries=floor,slices={})
        for family,buckets in groups.items():
            paired['slices'][family]={}
            for a in arms:arms[a]['slices'][family]={}
            for g,fold in buckets.items():
                ga,gp=fold.result();n=gp['queries'];label='empty' if not n else 'descriptive_only' if n<floor else 'sufficient_query_count'
                gp['support']=label;paired['slices'][family][g]=gp
                for a in arms:ga[a]['support']=label;arms[a]['slices'][family][g]=ga[a]
        if expected_p0 is not None:close(arms['P0'],expected_p0)
        if expected_c1 is not None:close(arms['C1'],expected_c1)
        fixed=policy['fixed_validation'];actual=arms['D1']
        for key in ('queries','visitors','target_occurrences','reachable_target_occurrences','all_targets_reachable_queries','candidate_union_items','support_floor_queries'):
            if actual[key]!=fixed[key]:raise ValueError('Fixed validation denominator changed: '+key)
        for family,g,key in [('visitor_history','new','new_visitor_queries'),('current_basket','multiple','multi_item_current_queries'),('target_basket','multiple','multi_item_target_queries')]:
            if actual['slices'][family][g]['queries']!=fixed[key]:raise ValueError('Fixed slice changed')
        if {g:v['queries'] for g,v in actual['slices']['target_model'].items()}!=fixed['target_model_query_counts']:
            raise ValueError('Shared target support partitions changed')
        uncertainty=d.bootstrap(records,jsonlines(c1_reference/'bootstrap.jsonl'),
                                lambda row:handles['bootstrap.jsonl'].write(dump(row)+'\n'),watch)
        result={'arms':arms,'paired':paired,'diagnostics':dict({k:dict(v) for k,v in diagnostics.items()},
                    c1_full_fallback_implication=implication),'uncertainty':uncertainty,'roster_sha256':roster.hexdigest()}
        handles['aggregate.json'].write(dump(result)+'\n')
    return {'fit_audit':audit,'aggregate':result}
