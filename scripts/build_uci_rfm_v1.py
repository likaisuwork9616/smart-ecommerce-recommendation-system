"""Prepare once, build eight UCI RFM datasets, independently read back every cell."""
import argparse
from collections import Counter
import csv
import gc
import io
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import freeze_uci_rfm_contract as frozen
from scripts import uci_rfm_builder as builder
from scripts import uci_rfm_reference as reference

PRIVATE='shop-mysql-runtime/uci_rfm_dataset_v1'
VERIFY='shop-mysql-runtime/verification/uci-rfm-build-v1'
SPEC='reports/stage6/uci_rfm_build_v1_specification.json'
RESULT='reports/stage6/uci_rfm_build_v1.json'
ACCEPT='reports/stage6/uci_rfm_build_v1_acceptance.json'
CODE=['scripts/uci_rfm_builder.py','scripts/uci_rfm_reference.py','scripts/build_uci_rfm_v1.py','tests/test_uci_rfm_builder.py']
FILES={'customers.csv':'customers_fields','invoice_decisions.csv':'invoice_decisions_fields',
       'row_decisions.csv':'row_decisions_fields','duplicate_map.csv':'duplicate_map_fields'}


def cell(value):
    if value is None:return ''
    if type(value) is bool:return 'true' if value else 'false'
    if isinstance(value,list):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return str(value)


def write_csv(path,header,rows):
    n=0
    with path.open('x',encoding='utf-8',newline='') as output:
        writer=csv.writer(output,lineterminator='\n');writer.writerow(header)
        for row in rows:writer.writerow([cell(v) for v in row]);n+=1
    return n


def compare_csv(path,header,expected):
    n=0
    with path.open(encoding='utf-8',newline='') as source:
        reader=csv.reader(source)
        if next(reader)!=header:raise ValueError('Readback schema mismatch: '+path.name)
        for n,row in enumerate(expected,1):
            actual=next(reader,None)
            if actual != [cell(v) for v in row]:
                column=next((i for i,(a,b) in enumerate(zip(actual or [],[cell(v) for v in row])) if a!=b),-1)
                raise ValueError(f'Independent readback differs in {path.name}, record {n}, column {column}; values kept private')
        if next(reader,None) is not None:raise ValueError('Extra output row: '+path.name)
    return {'rows':n,'cells':n*len(header)}


def source_bindings():
    frozen.verify()
    old=frozen.read_json(ROOT/frozen.SPEC)
    descriptors={d['path']:d for d in old['sources']}
    for name in [frozen.SPEC,frozen.REPORT,frozen.PRIVATE+'/output_guard.json',*CODE]:
        descriptors[name]=frozen.descriptor(ROOT,name)
    return [descriptors[name] for name in sorted(descriptors)]


def prepare():
    if (ROOT/SPEC).exists():
        guard=frozen.read_json(ROOT/VERIFY/'prepared_guard.json')
        frozen.verify_descriptors(ROOT,[guard['specification'],guard['tests'],*guard['sources']])
        return {'status':'existing_execution_spec_verified','tests_rerun':False}
    if (ROOT/PRIVATE).exists() or (ROOT/RESULT).exists() or (ROOT/ACCEPT).exists():raise FileExistsError('Unexpected existing build outputs')
    sources=source_bindings()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_uci_rfm_builder')
    ids=frozen.test_ids(suite);log=io.StringIO();started=time.perf_counter()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    elapsed=round(time.perf_counter()-started,6)
    if not result.wasSuccessful() or result.skipped:
        print(log.getvalue());raise ValueError('Builder tests failed; no execution specification written')
    frozen.verify_descriptors(ROOT,sources)
    spec={'status':'prepared_before_real_build','contract':frozen.descriptor(ROOT,frozen.POLICY),'sources':sources,
          'schemas':frozen.read_json(ROOT/frozen.POLICY)['planned_outputs'],
          'implementation_details':{
              'invoice_ledger':'nonblank_invoice_keys_only; missing-invoice rows stay in row decisions and affect own known key',
              'quarantine_count':'distinct numeric invoice per linked customer plus each missing-invoice source row in window',
              'invoice_in_window':'any prefix member in window; eligible invoices have one timestamp',
              'invoice_header_flags':'four conflict flags plus country_missing diagnostic; numeric_bad separately recorded in row flags and primary reason',
              'paid_and_free_counts':'retained eligible paid/free rows, regardless of the monetary code sensitivity',
              'included_paid_amount':'history qualified amount per row; quarantine customer primary M is null while partial amount stays in diagnostics',
              'last_window_invoice_at':'latest eligible subset time also retained for quarantined customers as a diagnostic',
              'duplicate_representative':'group anchor; multiplicity arm may retain multiple rows from the chosen sheet',
              'flag_order':'lexicographic; primary reason uses frozen precedence',
              'independent_path':'original XLSX XML reader -> separate SQLite; full-eight-column SQL partitions, independent header/row/invoice/customer calculations',
              'execution_limit':'dataset build/readback only, no cutpoint fitting or temporal scores'},
          'synthetic_tests':{'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'elapsed_seconds':elapsed,'test_ids':ids}}
    (ROOT/VERIFY).mkdir(parents=True,exist_ok=True)
    (ROOT/VERIFY/'tests.log').write_text(log.getvalue(),encoding='utf-8',newline='\n')
    frozen.write_new(ROOT/SPEC,spec)
    frozen.write_new(ROOT/VERIFY/'prepared_guard.json',{'specification':frozen.descriptor(ROOT,SPEC),'tests':frozen.descriptor(ROOT,VERIFY+'/tests.log'),'sources':sources})
    return {'status':'prepared','tests':result.testsRun,'seconds':elapsed,'sources':len(sources)}


def build():
    if (ROOT/PRIVATE).exists():return verify()
    prepare()
    spec=frozen.read_json(ROOT/SPEC);policy=frozen.read_json(ROOT/frozen.POLICY)
    frozen.verify_descriptors(ROOT,spec['sources'])
    private=frozen.within(ROOT,PRIVATE)
    if (ROOT/RESULT).exists() or (ROOT/ACCEPT).exists():raise FileExistsError('Existing public results')
    private.mkdir()
    started=time.perf_counter()
    try:
        source=sqlite3.connect((ROOT/'shop-mysql-runtime/uci_retail_ii_intake_v1/inventory.sqlite').as_uri()+'?mode=ro',uri=True)
        sources=source.execute("SELECT sheet,excel_row,invoice,stock,description,quantity,ts,price,customer,country FROM rows ORDER BY CASE sheet WHEN 'Year 2009-2010' THEN 0 ELSE 1 END,excel_row").fetchall()
        source.close()
        seen=set()
        for row in sources:
            builder.decode(row)
            key=row[:2]
            if key in seen:raise ValueError('Duplicate source row key')
            seen.add(key)
        del seen
        summary={};file_records=[];universes={};checks={}
        for window in policy['windows']:
            prepared=builder.prepare(sources,window)
            universes[window['id']]=set(prepared['universe'])
            for arm in policy['arms']:
                folder=private/arm['id']/window['id'];folder.mkdir(parents=True)
                rowgen,invgen,custgen,summarize=builder.decisions(prepared,arm)
                paths={name:folder/name for name in FILES}
                counts={}
                with paths['row_decisions.csv'].open('x',encoding='utf-8',newline='') as rf,paths['duplicate_map.csv'].open('x',encoding='utf-8',newline='') as df:
                    rw=csv.writer(rf,lineterminator='\n');dw=csv.writer(df,lineterminator='\n')
                    rw.writerow(policy['planned_outputs']['row_decisions_fields']);dw.writerow(policy['planned_outputs']['duplicate_map_fields']);n=0
                    for row,mapping in rowgen():
                        rw.writerow([cell(v) for v in row]);dw.writerow([cell(v) for v in mapping]);n+=1
                counts['row_decisions.csv']=counts['duplicate_map.csv']=n
                invoices=list(invgen());customers=list(custgen())
                counts['invoice_decisions.csv']=write_csv(paths['invoice_decisions.csv'],policy['planned_outputs']['invoice_decisions_fields'],invoices)
                counts['customers.csv']=write_csv(paths['customers.csv'],policy['planned_outputs']['customers_fields'],customers)
                identifier=arm['id']+'/'+window['id'];summary[identifier]=summarize(customers,invoices)
                signature=[(r[0],r[5],r[7],r[8],r[9],r[10],r[12],r[13],r[14]) for r in customers]
                if arm['id']=='main':checks[window['id']]=signature
                elif checks[window['id']]!=signature:raise ValueError('Arms differ in universe/state/R/F')
                for name in FILES:
                    relative=paths[name].relative_to(ROOT).as_posix()
                    file_records.append(dict(frozen.descriptor(ROOT,relative),rows=counts[name],columns=len(policy['planned_outputs'][FILES[name]])))
                print(json.dumps({'built':identifier,'universe':len(customers),'states':summary[identifier]['states']}),flush=True)
            del prepared;gc.collect()
        assert universes['T1']<=universes['T2']
        del sources;gc.collect()
        # Original-XLSX independent path. It imports no primary builder functions.
        refpath=ROOT/VERIFY/'reference.sqlite'
        if refpath.exists():raise FileExistsError('Preserve existing reference work')
        refdb=reference.database(refpath)
        reference.load_workbook(refdb,ROOT/policy['source']['workbook'])
        comparisons={};aggregate_checks=0
        for window in policy['windows']:
            ref=reference.prepare(refdb,window)
            for arm in policy['arms']:
                folder=private/arm['id']/window['id'];rowgen,invgen,custgen=reference.expected(ref,arm)
                # Two saved row files checked simultaneously from one reference pass.
                paths=[folder/'row_decisions.csv',folder/'duplicate_map.csv']
                handles=[p.open(encoding='utf-8',newline='') for p in paths]
                try:
                    readers=[csv.reader(h) for h in handles]
                    for reader,path in zip(readers,paths):
                        if next(reader)!=policy['planned_outputs'][FILES[path.name]]:raise ValueError('Row schema')
                    n=0
                    for n,pair in enumerate(rowgen(),1):
                        for reader,expected,path in zip(readers,pair,paths):
                            if next(reader,None)!=[cell(v) for v in expected]:raise ValueError(f'Independent {arm["id"]}/{window["id"]}/{path.name} mismatch at record {n}; values private')
                    for reader,path in zip(readers,paths):
                        if next(reader,None) is not None:raise ValueError('Extra rows')
                        comparisons[f'{arm["id"]}/{window["id"]}/{path.name}']={'rows':n,'cells':n*len(policy['planned_outputs'][FILES[path.name]])}
                finally:
                    for handle in handles:handle.close()
                invrows=list(invgen());custrows=list(custgen())
                for name,expected in [('invoice_decisions.csv',invrows),('customers.csv',custrows)]:
                    comparisons[f'{arm["id"]}/{window["id"]}/{name}']=compare_csv(folder/name,policy['planned_outputs'][FILES[name]],expected)
                stats=summary[arm['id']+'/'+window['id']]
                assert len(custrows)==stats['universe']
                assert dict(sorted(Counter(r[5] for r in custrows).items()))==stats['states']
                assert sum(r[15] for r in custrows)==stats['window_partial_M_milli_GBP']
                assert sum(r[11] for r in custrows if r[6])==stats['window_complete_active_M_milli_GBP']
                aggregate_checks+=4
                print(json.dumps({'independent_readback_passed':arm['id']+'/'+window['id']}),flush=True)
        refdb.close()
        # Check every written byte after semantic readback, including all CSV schemas/counts.
        for record in file_records:
            if frozen.descriptor(ROOT,record['path'])!={k:record[k] for k in ('path','bytes','sha256')}:raise ValueError('Output changed during independent readback')
        frozen.verify_descriptors(ROOT,spec['sources'])
        manifest={'contract':spec['contract'],'execution_specification':frozen.descriptor(ROOT,SPEC),'files':file_records,
                  'schemas':{name:policy['planned_outputs'][field] for name,field in FILES.items()},
                  'source_bindings':spec['sources'],'summaries':summary,'independent_readback':comparisons}
        frozen.write_new(private/'root_manifest.json',manifest)
        result={'status':'built_and_independently_accepted','contract':spec['contract'],'execution_specification':frozen.descriptor(ROOT,SPEC),
                'datasets':summary,'universe_relation':{'T1_subset_T2':True,'new_observed_T2_keys':len(universes['T2']-universes['T1'])},
                'scope':{'snapshots':2,'arms':4,'cutpoints':0,'temporal_scores':0,'models_fitted':0},
                'limits':['Retrospective event-time proxy; no visibility/revision clock or completion watermark.',
                          'Customer key non-reuse is an assumption; missing identities remain unlinked.',
                          'Money is positive line gross proxy, not product/net revenue.',
                          'Olist 25 under-supported groups retained; Stage4 daily10 percent; Dashboard deferred.']}
        frozen.write_new(ROOT/RESULT,result)
        acceptance={'status':'passed_full_independent_cell_readback','execution_specification':frozen.descriptor(ROOT,SPEC),
                    'synthetic_tests':spec['synthetic_tests'],'source_files':len(spec['sources']),
                    'files_compared':len(comparisons),'data_records_compared':sum(v['rows'] for v in comparisons.values()),
                    'data_cells_compared':sum(v['cells'] for v in comparisons.values()),'per_file':comparisons,
                    'independent_aggregate_checks':aggregate_checks,'source_and_output_bytes_unchanged':True,
                    'elapsed_seconds':round(time.perf_counter()-started,3),'transaction_source':'original XLSX XML; eight-column SQL partitions; separate integer invoice/customer calculation',
                    'no_cutpoints_or_temporal_scores':True}
        frozen.write_new(ROOT/ACCEPT,acceptance)
        frozen.write_new(private/'output_guard.json',{'sources':spec['sources'],'specification':frozen.descriptor(ROOT,SPEC),
                         'result':frozen.descriptor(ROOT,RESULT),'acceptance':frozen.descriptor(ROOT,ACCEPT),
                         'manifest':frozen.descriptor(ROOT,PRIVATE+'/root_manifest.json'),'files':file_records})
        return {k:acceptance[k] for k in ['status','files_compared','data_records_compared','data_cells_compared','elapsed_seconds']}
    except Exception as error:
        frozen.write_new(private/'failure.json',{'status':'partial_build_preserved_no_replay','error_type':type(error).__name__})
        raise


def verify():
    guard=frozen.read_json(ROOT/PRIVATE/'output_guard.json')
    allfiles=[*guard['sources'],guard['specification'],guard['result'],guard['acceptance'],guard['manifest']]
    frozen.verify_descriptors(ROOT,allfiles)
    for file in guard['files']:
        frozen.verify_descriptors(ROOT,[{k:file[k] for k in ('path','bytes','sha256')}])
    manifest=frozen.read_json(ROOT/PRIVATE/'root_manifest.json')
    if manifest['files']!=guard['files']:raise ValueError('Manifest differs')
    return {'status':'saved_complete_bundle_bytes_verified','CSV_files':len(guard['files']),'recomputed_values':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare',action='store_true');action.add_argument('--run',action='store_true');action.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    print(json.dumps(prepare() if args.prepare else build() if args.run else verify(),ensure_ascii=False))
