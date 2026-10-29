"""Artificial accepted-format CSV/JSONL sources; never parse real validation rows."""
from collections import Counter
from copy import deepcopy
import csv
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from scripts import retailrocket_popularity as p
from scripts import retailrocket_popularity_io as old
from scripts import retailrocket_cooccurrence as c
from scripts import retailrocket_directed as d
from scripts import retailrocket_session_knn_io as adapter
from scripts import retailrocket_session_knn_readback as oracle
from scripts import run_retailrocket_session_knn_v1 as entry
from tests.test_retailrocket_session_knn import fixture_inputs

BASE=entry.ROOT/entry.VERIFY/'tests'


def write_csv(path,header,rows):
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,header,lineterminator='\n');writer.writeheader();writer.writerows(rows)


def csv_rows(path):
    with path.open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream);return reader.fieldnames,list(reader)


def write_lines(path,values):
    path.write_text(''.join(adapter.dump(r)+'\n' for r in values),encoding='utf-8')


def make_fixture(base=None,boundary=False):
    root=Path(base or BASE)/uuid.uuid4().hex;root.mkdir(parents=True)
    paths={key:root/key for key in ('dataset','P0','C1','D1')}
    for folder in paths.values():folder.mkdir()
    raw,counts,support,catalog,queries,refs,draws,fits,expected=fixture_inputs(boundary)
    factor=10000
    baskets=[replace(b,session=b.session*factor,time=b.time*factor) for b in raw]
    queries=[(replace(q,session_start_ms=q.session_start_ms*factor,query_ms=q.query_ms*factor),index) for q,index in queries]
    catalog=[(i,t*factor) for i,t in catalog];cat=p.Catalog(catalog)
    lineage=[]
    cm=c.fit(baskets,10*factor,100*factor,counts,
        lambda key,items,n,o:lineage.append({'key':list(key),'items':items,'baskets':n,'basket_memberships':o}))
    dm=d.fit(baskets,10*factor,100*factor,cm.support,cm.pairs,counts)
    fits=dict(fits,C1=cm.fit_id,D1=dm.fit_id)
    for ref in refs:
        ref['key'][1]*=factor;ref['key'][2]*=factor
        ref['predictions']['C1']['fit_id']=cm.fit_id;ref['predictions']['D1']['fit_id']=dm.fit_id
        ref['control_fit_ids']=dict(fits)
    schemas=entry.read('reports/stage8/retailrocket_build_v1_specification.json')['schemas']
    bvalues=[dict(visitorid=b.visitor,session_start_ms=b.session,query_ms=b.time,role=b.role,basket_index=b.index,
                  items=adapter.dump(list(b.items)),source_records='[]',context_item_occurrences=len(b.items)) for b in baskets]
    # Poison every non-role field, including timestamps: neither path may decode test/tail payloads.
    for role in ('reserved_test','tail'):
        bvalues.append(dict.fromkeys(schemas['baskets.csv'],'POISON')|{'role':role})
    write_csv(paths['dataset']/'baskets.csv',schemas['baskets.csv'],bvalues)
    qvalues=[]
    for q,index in queries:
        successor=min((b for b in baskets if b.visitor==q.visitorid and b.session==q.session_start_ms and b.time>q.query_ms),key=lambda b:b.time)
        qvalues.append(dict(visitorid=q.visitorid,session_start_ms=q.session_start_ms,query_ms=q.query_ms,role='validation',
            basket_index=index,context_item_occurrences=q.current_size,next_view_ms=successor.time,next_role='validation',
            next_in_session='1',mature='1',cross_role='0',status='labelled',candidate_count=q.candidate_count,
            target_items=adapter.dump(list(q.targets)),target_count=len(q.targets),reachable_target_count=q.reachable_count,
            all_targets_reachable=str(int(q.all_reachable)),visitor_seen_before_fit=str(int(q.visitor_seen)),
            targets_seen_before_fit='unused',train_view_events=q.train_views,train_activity_slice=p.activity(q.train_views)))
    for role in ('train','reserved_test','tail'):
        qvalues.append(dict.fromkeys(schemas['queries.csv'],'POISON')|{'role':role})
    write_csv(paths['dataset']/'queries.csv',schemas['queries.csv'],qvalues)
    write_csv(paths['dataset']/'catalog.csv',schemas['catalog.csv'],[{'itemid':i,'first_view_ms':t} for i,t in catalog])
    write_csv(paths['P0']/'item_counts.csv',old.HEADERS['item_counts.csv'],[{'itemid':i,'count':n} for i,n in counts.items()])
    p0rows={name:[] for name in ('ranked_queries.csv','query_metrics.csv','query_slices.csv')}
    for (q,index),ref in zip(queries,refs):
        pred=dict(ref['predictions']['P0'],fit_id=fits['P0'],scores=[counts.get(i,0) for i in ref['predictions']['P0']['ids']])
        for name,row in old.artifact_rows(q,pred,ref['terms']['P0'],ref['slices']).items():
            p0rows[name].append({field:old.cell(value) for field,value in zip(old.HEADERS[name],row)})
    for name,values in p0rows.items():write_csv(paths['P0']/name,old.HEADERS[name],values)
    write_csv(paths['C1']/'support.csv',['itemid','support'],[{'itemid':i,'support':n} for i,n in support.items()])
    write_lines(paths['C1']/'train_sessions.jsonl',lineage)
    c1rows=[];d1rows=[]
    for ref in refs:
        row={k:deepcopy(v) for k,v in ref.items() if k!='control_fit_ids'}
        d1rows.append(row)
        one=deepcopy(row);one['predictions'].pop('D1');one['terms'].pop('D1');c1rows.append(one)
    write_lines(paths['C1']/'queries.jsonl',c1rows);write_lines(paths['D1']/'queries.jsonl',d1rows)
    write_lines(paths['C1']/'bootstrap.jsonl',draws)
    for arm in ('P0','C1','D1'):(paths[arm]/'fit_audit.json').write_text(adapter.dump({'fit_id':fits[arm]}),encoding='utf-8')
    controls={}
    fixed=dict(expected,new_visitor_queries=sum(not q.visitor_seen for q,_ in queries),
        multi_item_current_queries=sum(q.current_size>1 for q,_ in queries),multi_item_target_queries=sum(len(q.targets)>1 for q,_ in queries),
        target_model_query_counts={g:sum(ref['slices']['target_model']==g for ref in refs) for g in p.GROUPS['target_model']})
    for arm in ('P0','C1','D1'):
        folds={'main':p.Aggregate(cat),'conditional':p.Aggregate(cat)}
        groups={f:{g:p.Aggregate(cat) for g in names} for f,names in p.GROUPS.items()}
        for (q,_),ref in zip(queries,refs):
            args=(q,ref['predictions'][arm],ref['terms'][arm],q.reachable_count)
            folds['main'].add(*args)
            if q.all_reachable:folds['conditional'].add(*args)
            for f,g in ref['slices'].items():groups[f][g].add(*args)
        control=dict(folds['main'].result(),conditional=folds['conditional'].result(),support_floor_queries=50,slices={})
        for f,buckets in groups.items():
            control['slices'][f]={}
            for g,fold in buckets.items():
                value=fold.result();control['slices'][f][g]=dict(value,support='empty' if not value['queries'] else 'descriptive_only')
        controls[arm]=control
    cost={key:cm.audit[key] for key in ('train_sessions','singleton_sessions','train_baskets','basket_item_memberships','distinct_session_item_memberships','positive_support_items')}
    cost.update(maximum_session_items=max(len(r['items']) for r in lineage),maximum_posting_size=max(support.values()))
    config={'schemas':schemas,'train_window_ms':[10*factor,100*factor],
        'validation_window_ms':[100*factor,1000*factor],
        'validation_window_utc':[datetime.fromtimestamp(t*factor/1000,timezone.utc).isoformat() for t in (100,1000)],
        'role_windows_ms':{'warmup':[0,10*factor],'train':[10*factor,100*factor],'validation':[100*factor,1000*factor]},
        'control_fit_ids':fits,'fixed_validation':fixed,'expected_controls':controls,'train_cost_audit':cost}
    (root/'configuration.json').write_text(adapter.dump(config)+'\n',encoding='utf-8')
    return root,paths,config


def binding(root):
    return [entry.descriptor(p.relative_to(entry.ROOT).as_posix()) for p in sorted(root.rglob('*')) if p.is_file()]


def run_case(base=None,boundary=False):
    root,paths,config=make_fixture(base,boundary)
    result=entry.execute_once(root/'execution',paths,config,binding(root),lambda:None)
    return root,result


class FileAcceptanceTests(unittest.TestCase):
    def test_full_file_pipeline_and_complete_readback(self):
        root,result=run_case()
        self.assertEqual(result['readback']['queries_checked'],7)
        self.assertEqual(result['readback']['all_session_visits'],49)
        self.assertGreater(result['readback']['candidate_scores_checked'],0)
        self.assertEqual(result['readback']['bootstrap_replicates'],2000)
        self.assertFalse(result['readback']['production_K1_helpers_imported'])
        self.assertFalse(result['readback']['sampled_oracle'])
        self.assertEqual(entry.verify_run(root/'execution')['research_recomputed'],False)

    def test_501_neighbors_full_pool_and_boundary(self):
        root,result=run_case(boundary=True)
        row=next(adapter.jsonlines(root/'execution/queries.jsonl'))['predictions']['K1']
        self.assertEqual(row['eligible_neighbors'],501);self.assertEqual(row['selected_neighbor_count'],500)
        self.assertEqual(row['boundary_ties_excluded'],1)
        self.assertEqual(result['readback']['all_session_visits'],501)

    def test_fit_loader_does_not_decode_validation_or_test_items(self):
        root,paths,config=make_fixture();header,values=csv_rows(paths['dataset']/'baskets.csv')
        for row in values:
            if row['role']!='train': row['items']='POISON'
        write_csv(paths['dataset']/'baskets.csv',header,values)
        self.assertEqual(len(list(adapter.baskets(paths['dataset'],config,('train',)))),11)

    def test_test_roles_cannot_be_requested(self):
        root,paths,config=make_fixture()
        for roles in [('reserved_test',),('train','validation'),('tail',)]:
            with self.subTest(roles=roles),self.assertRaises(ValueError):list(adapter.baskets(paths['dataset'],config,roles))

    def test_missing_extra_duplicate_control_queries_stop(self):
        for mutation in ('missing','extra','duplicate'):
            root,paths,config=make_fixture();values=list(adapter.jsonlines(paths['D1']/'queries.jsonl'))
            if mutation=='missing':values.pop(0)
            elif mutation=='extra':values.append(values[-1])
            else:values.insert(1,values[0])
            write_lines(paths['D1']/'queries.jsonl',values);out=root/'out';out.mkdir()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):adapter.build(out,paths,config)

    def test_control_provenance_and_copied_values_stop(self):
        for field in ('fit','score','metric','history','target','slice'):
            root,paths,config=make_fixture();values=list(adapter.jsonlines(paths['D1']/'queries.jsonl'));r=values[0]
            if field=='fit':r['predictions']['D1']['fit_id']='wrong'
            elif field=='score':r['predictions']['C1']['scores'][0][0]+=1
            elif field=='metric':r['terms']['P0']['ndcg']+=.1
            elif field=='history':r['history'].append('999')
            elif field=='target':r['targets']=['999']
            else:r['slices']['visitor_history']='wrong'
            write_lines(paths['D1']/'queries.jsonl',values);out=root/'out';out.mkdir()
            with self.subTest(field=field),self.assertRaises(ValueError):adapter.build(out,paths,config)

    def test_P0_original_fit_scores_and_denominator_stop(self):
        for name,field,value in [('ranked_queries.csv','fit_id','wrong'),('ranked_queries.csv','top10_scores','[0]'),
                                 ('query_metrics.csv','reachable_target_count','999')]:
            root,paths,config=make_fixture();header,values=csv_rows(paths['P0']/name);values[0][field]=value
            write_csv(paths['P0']/name,header,values);out=root/'out';out.mkdir()
            with self.subTest(field=field),self.assertRaises(ValueError):adapter.build(out,paths,config)

    def test_schema_width_and_future_role_clock_rejected(self):
        for field,value in [('role','train'),('query_ms','999999999'),('basket_index','0')]:
            root,paths,config=make_fixture();header,values=csv_rows(paths['dataset']/'baskets.csv');values[0][field]=value
            if field=='role':values[0]['role']='validation' # train timestamp outside validation role
            write_csv(paths['dataset']/'baskets.csv',header,values)
            with self.subTest(field=field),self.assertRaises(ValueError):list(adapter.baskets(paths['dataset'],config,('warmup','train','validation')))
        root,paths,config=make_fixture();path=paths['dataset']/'queries.csv'
        path.write_text('wrong,header\na,b\n',encoding='utf-8')
        with self.assertRaises(ValueError):list(adapter.queries(paths['dataset'],config))

    def test_missing_current_basket_rejected(self):
        root,paths,config=make_fixture();header,values=csv_rows(paths['dataset']/'baskets.csv')
        values=[r for r in values if not (r['role']=='validation' and r['visitorid']=='90' and r['basket_index']=='1')]
        write_csv(paths['dataset']/'baskets.csv',header,values);out=root/'out';out.mkdir()
        with self.assertRaises(ValueError):adapter.build(out,paths,config)

    def test_lineage_and_support_mismatch_rejected(self):
        for field in ('lineage','support'):
            root,paths,config=make_fixture();out=root/'out';out.mkdir()
            if field=='lineage':
                values=list(adapter.jsonlines(paths['C1']/'train_sessions.jsonl'));values[0]['baskets']+=1
                write_lines(paths['C1']/'train_sessions.jsonl',values)
            else:
                header,values=csv_rows(paths['C1']/'support.csv');values[0]['support']='999'
                write_csv(paths['C1']/'support.csv',header,values)
            with self.subTest(field=field),self.assertRaises(ValueError):adapter.build(out,paths,config)

    def test_fixed_counts_and_reference_aggregates_rejected(self):
        for field in ('fixed','aggregate'):
            root,paths,config=make_fixture();out=root/'out';out.mkdir()
            if field=='fixed':config['fixed_validation']['new_visitor_queries']+=1
            else:config['expected_controls']['D1']['metrics']['ndcg']+=.1
            with self.subTest(field=field),self.assertRaises(ValueError):adapter.build(out,paths,config)

    def test_oracle_rejects_every_artifact_family(self):
        for name in adapter.ARTIFACTS:
            root,paths,config=make_fixture();out=root/'out';out.mkdir();adapter.build(out,paths,config)
            path=out/name
            if name=='aggregate.json':
                value=json.loads(path.read_text());value['diagnostics']['eligible_neighbors']['999']=1
                path.write_text(adapter.dump(value),encoding='utf-8')
            elif name=='fit_audit.json':
                value=json.loads(path.read_text());value['fit_id']='wrong';path.write_text(adapter.dump(value),encoding='utf-8')
            else:
                values=list(adapter.jsonlines(path))
                if name=='sessions.jsonl':values[0]['items'].append('999')
                elif name=='postings.jsonl':values[0]['sessions'].pop()
                elif name=='train_sessions.jsonl':values[0]['basket_memberships']+=1
                elif name=='queries.jsonl':values[0]['predictions']['K1']['selected_neighbors'][0]['union']+=1
                else:values[0]['query_denominator']+=1
                write_lines(path,values)
            with self.subTest(name=name),self.assertRaises(ValueError):oracle.verify(out,paths,config)

    def test_oracle_detects_next_basket_target_corruption(self):
        root,paths,config=make_fixture();out=root/'out';out.mkdir();adapter.build(out,paths,config)
        header,values=csv_rows(paths['dataset']/'baskets.csv')
        for row in values:
            if row['visitorid']=='1' and row['role']=='validation' and row['basket_index']=='5':row['items']='["999"]'
        write_csv(paths['dataset']/'baskets.csv',header,values)
        with self.assertRaises(ValueError):oracle.verify(out,paths,config)

    def test_oracle_rejects_nonfloat_or_nonfinite_metrics(self):
        for value in (0,float('nan')):
            root,paths,config=make_fixture();out=root/'out';out.mkdir();adapter.build(out,paths,config)
            values=list(adapter.jsonlines(out/'queries.jsonl'));values[0]['terms']['K1']['ndcg']=value
            (out/'queries.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in values),encoding='utf-8')
            with self.subTest(value=value),self.assertRaises(ValueError):oracle.verify(out,paths,config)

    def test_oracle_has_no_production_helper_dependency(self):
        root,paths,config=make_fixture();out=root/'out';out.mkdir();adapter.build(out,paths,config)
        with patch.object(adapter,'baskets',side_effect=AssertionError('production used')), \
             patch.object(adapter.k.Ranker,'rank',side_effect=AssertionError('production used')), \
             patch.object(adapter.evaluation,'evaluate',side_effect=AssertionError('production used')):
            result=oracle.verify(out,paths,config)
        self.assertEqual(result['queries_checked'],7)

    def test_watch_interrupts_full_session_and_candidate_enumeration(self):
        def stop():raise RuntimeError('budget stop')
        with self.assertRaisesRegex(RuntimeError,'budget stop'):
            oracle.predict({('1',1):{'1'}},{'1':1},'id',{'1':1},{'1':1},100,['1'],('2',2),stop)


if __name__=='__main__':unittest.main()
