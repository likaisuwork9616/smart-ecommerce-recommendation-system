"""Single T1 reference fit, fixed applications and independent temporal acceptance."""
import argparse
import csv
import io
import json
import math
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import freeze_uci_rfm_contract as frozen
from scripts import build_uci_rfm_v1 as build
from scripts import uci_rfm_temporal as core
from scripts import uci_rfm_temporal_reference as independent

PRIVATE='shop-mysql-runtime/uci_rfm_temporal_v1'
VERIFY='shop-mysql-runtime/verification/uci-rfm-temporal-v1'
SPEC='reports/stage6/uci_rfm_temporal_v1_specification.json'
RESULT='reports/stage6/uci_rfm_temporal_v1.json'
ACCEPT='reports/stage6/uci_rfm_temporal_v1_acceptance.json'
CODE=['scripts/uci_rfm_temporal.py','scripts/uci_rfm_temporal_reference.py','scripts/run_uci_rfm_temporal_v1.py','tests/test_uci_rfm_temporal.py']


def compare_tree(actual,expected,path='root'):
    """Every JSON leaf checked; integer counts exact, derived floats 1e-12 tolerance."""
    if isinstance(actual,dict) and isinstance(expected,dict):
        if set(actual)!=set(expected):raise ValueError('Independent keys differ: '+path)
        return sum(compare_tree(actual[k],expected[k],path+'/'+k) for k in actual)
    if isinstance(actual,list) and isinstance(expected,list):
        if len(actual)!=len(expected):raise ValueError('Independent list length differs: '+path)
        return sum(compare_tree(a,b,path+'/'+str(i)) for i,(a,b) in enumerate(zip(actual,expected)))
    if type(actual) is bool or type(expected) is bool:
        ok=type(actual) is type(expected) and actual==expected
    elif isinstance(actual,(int,float)) and isinstance(expected,(int,float)):
        ok=actual==expected if isinstance(actual,int) and isinstance(expected,int) else math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-12)
    else:ok=actual==expected
    if not ok:raise ValueError('Independent value differs: '+path)
    return 1


def prepare():
    if (ROOT/SPEC).exists():
        guard=frozen.read_json(ROOT/VERIFY/'prepared_guard.json')
        frozen.verify_descriptors(ROOT,[guard['specification'],guard['tests'],*guard['sources']])
        return {'status':'prepared_specification_verified','tests_rerun':False}
    if (ROOT/PRIVATE).exists() or (ROOT/RESULT).exists() or (ROOT/ACCEPT).exists():raise FileExistsError('Existing temporal namespace')
    build.verify()
    guard=frozen.read_json(ROOT/build.PRIVATE/'output_guard.json')
    sources={d['path']:{k:d[k] for k in ('path','bytes','sha256')} for d in [*guard['sources'],guard['specification'],guard['result'],guard['acceptance'],guard['manifest'],*guard['files']]}
    for name in [build.PRIVATE+'/output_guard.json',*CODE]:sources[name]=frozen.descriptor(ROOT,name)
    sources=[sources[name] for name in sorted(sources)]
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_uci_rfm_temporal');ids=frozen.test_ids(suite)
    log=io.StringIO();started=time.perf_counter();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite);elapsed=round(time.perf_counter()-started,6)
    if not result.wasSuccessful() or result.skipped:
        print(log.getvalue());raise ValueError('Temporal tests failed; no real cutpoints estimated')
    frozen.verify_descriptors(ROOT,sources)
    policy=frozen.read_json(ROOT/frozen.POLICY)
    import numpy,scipy,sklearn,pandas
    spec={'status':'prepared_before_real_cutpoint_estimation','contract':frozen.descriptor(ROOT,frozen.POLICY),'sources':sources,
          'windows':policy['windows'],'evaluation':policy['evaluation'],
          'details':{'fit':'main/T1 active_complete only, one primary fit call; independent quantile recomputation is acceptance, not candidate selection',
                     'applications':'same saved cuts on all eight arm/snapshot customer files; no T2 refit',
                     'paired':'U1 members active_complete both snapshots; all four arms compared separately',
                     'raw_ledger':'main row decisions original raw rows restricted to each S,T; signed and positive amount missing-ID shares reported separately',
                     'accepted_build_summaries':'reuse byte-bound accepted exclusion/duplicate summaries for all arms, do not rebuild prior RFM',
                     'transitions':'sparse positive cells, full label and source denominator list, unlisted cells zero; empty row rates undefined',
                     'relative_M':'total relative difference and nearest-rank per-customer relative changes excluding main M=0',
                     'verification':'independent pandas/numpy inverted-CDF and searchsorted; scipy average-rank Spearman; sklearn ARI; own support/transitions/ledger calculations',
                     'float_tolerance':{'relative':1e-12,'absolute':1e-12},'counts_and_integer_money':'exact',
                     'hypothesis_role':'descriptive retrospective, no temporal pass/fail or business performance claim',
                     'serialization':'same UTF8 LF CSV null-empty booleans and compact JSON arrays as accepted builder'},
          'independent_libraries':{'numpy':numpy.__version__,'scipy':scipy.__version__,'sklearn':sklearn.__version__,'pandas':pandas.__version__},
          'synthetic_tests':{'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'elapsed_seconds':elapsed,'test_ids':ids}}
    (ROOT/VERIFY/'tests.log').write_text(log.getvalue(),encoding='utf-8',newline='\n')
    frozen.write_new(ROOT/SPEC,spec)
    frozen.write_new(ROOT/VERIFY/'prepared_guard.json',{'specification':frozen.descriptor(ROOT,SPEC),'tests':frozen.descriptor(ROOT,VERIFY+'/tests.log'),'sources':sources})
    return {'status':'prepared','tests':result.testsRun,'seconds':elapsed,'sources':len(sources)}


def reference_records(frame,header):
    for row in frame.to_dict(orient='records'):
        result=[]
        for field in header:
            v=row[field]
            result.append(independent.value(v) if not isinstance(v,list) else [int(x) for x in v])
        yield result


def run():
    if (ROOT/PRIVATE).exists():return verify()
    prepare();spec=frozen.read_json(ROOT/SPEC);policy=frozen.read_json(ROOT/frozen.POLICY)
    frozen.verify_descriptors(ROOT,spec['sources'])
    if (ROOT/RESULT).exists() or (ROOT/ACCEPT).exists():raise FileExistsError('Public temporal result already exists')
    private=frozen.within(ROOT,PRIVATE);private.mkdir();started=time.perf_counter()
    try:
        arms=[a['id'] for a in policy['arms']];paths={a+'/'+w['id']:ROOT/build.PRIVATE/a/w['id']/'customers.csv' for a in arms for w in policy['windows']}
        original={name:core.load_customers(path) for name,path in paths.items()}
        cuts=core.fit_reference(original['main/T1'],'main/T1');fit_calls=1
        cut_file=private/'cutpoints.json'
        frozen.write_new(cut_file,{'reference_customer_file':frozen.descriptor(ROOT,paths['main/T1'].relative_to(ROOT).as_posix()),'execution_specification':frozen.descriptor(ROOT,SPEC),'primary_fit_calls':fit_calls,'cutpoints':cuts})
        datasets={name:core.apply(rows,cuts) for name,rows in original.items()}
        files=[]
        for name,rows in datasets.items():
            path=private/name/'scores.csv';path.parent.mkdir(parents=True)
            n=build.write_csv(path,core.SCORE_HEADER,(core.score_record(r) for r in rows))
            files.append(dict(frozen.descriptor(ROOT,path.relative_to(ROOT).as_posix()),rows=n,columns=len(core.SCORE_HEADER)))
        panel_path=private/'panel.csv';n=build.write_csv(panel_path,core.PANEL_HEADER,core.panel(datasets))
        files.append(dict(frozen.descriptor(ROOT,panel_path.relative_to(ROOT).as_posix()),rows=n,columns=len(core.PANEL_HEADER)))
        ledgers={w['id']:core.ledger(ROOT/build.PRIVATE/'main'/w['id']/'row_decisions.csv',w['start_inclusive'],w['cutoff_exclusive']) for w in policy['windows']}
        build_summaries=frozen.read_json(ROOT/build.RESULT)['datasets']
        analytics=core.report(datasets,cuts,ledgers,build_summaries,arms)
        print(json.dumps({'phase':'primary_reference_and_report_complete','primary_fit_calls':fit_calls,'levels':{a:v['levels'] for a,v in cuts['axes'].items()}}),flush=True)
        # Independent read and numerical path; no production metric/cutpoint function is called.
        ref_original={name:independent.load(path) for name,path in paths.items()}
        ref_cuts=independent.cutpoints(ref_original['main/T1'])
        leaf_checks=compare_tree(cuts,ref_cuts,'cutpoints')
        ref_data={name:independent.scored(frame,ref_cuts) for name,frame in ref_original.items()}
        compared={}
        for name,frame in ref_data.items():
            compared[name+'/scores.csv']=build.compare_csv(private/name/'scores.csv',core.SCORE_HEADER,reference_records(frame,core.SCORE_HEADER))
        compared['panel.csv']=build.compare_csv(panel_path,core.PANEL_HEADER,independent.panel(ref_data))
        ref_ledgers={w['id']:independent.ledger(ROOT/build.PRIVATE/'main'/w['id']/'row_decisions.csv',w['start_inclusive'],w['cutoff_exclusive']) for w in policy['windows']}
        ref_analytics=independent.report(ref_data,ref_cuts,ref_ledgers,frozen.read_json(ROOT/build.RESULT)['datasets'],arms)
        leaf_checks+=compare_tree(analytics,ref_analytics,'analytics')
        # Save then read all JSON/CSV bytes. The guard is written only after full semantic checks.
        payload={'status':'completed_retrospective_temporal_description','contract':spec['contract'],'execution_specification':frozen.descriptor(ROOT,SPEC),
                 'cutpoints':cuts,'primary_fit_calls':fit_calls,'results':analytics,
                 'limits':['T2 already exposed to intake quality/monthly aggregate inspection; not pristine holdout.',
                           'No original visibility/revision clock or certified completeness watermark; same customer key non-reuse unverified.',
                           'M is positive line gross proxy including possible fees, not net/product revenue or LTV.',
                           'Paired active customers exclude inactivity/quarantine and new observed keys; report coverage and state transitions.',
                           'Under-supported groups retain flags; no merging, retuning or group business claim.',
                           'Natural temporal change is descriptive, without a pass/fail stability threshold.',
                           'Olist 25 small groups, Stage4 daily10 percent and Dashboard deferral retained.'],
                 'models_fitted':0,'T2_cutpoint_fits':0,'arm_selection':False}
        frozen.write_new(ROOT/RESULT,payload)
        leaf_checks+=compare_tree(frozen.read_json(ROOT/RESULT),payload,'saved_public_JSON')
        cut_saved=frozen.read_json(cut_file)
        leaf_checks+=compare_tree(cut_saved['cutpoints'],ref_cuts,'saved_cutpoints')
        frozen.verify_descriptors(ROOT,spec['sources'])
        for file in files:
            if frozen.descriptor(ROOT,file['path'])!={k:file[k] for k in ('path','bytes','sha256')}:raise ValueError('Saved score file changed')
        acceptance={'status':'passed_independent_scores_and_aggregates','source_files':len(spec['sources']),'synthetic_tests':spec['synthetic_tests'],
                    'primary_fit_calls':fit_calls,'T2_cutpoint_fits':0,'independent_reference_recomputation':'audit only, not an alternate fitted candidate',
                    'score_and_panel_files':len(compared),'per_file':compared,'data_records_compared':sum(v['rows'] for v in compared.values()),
                    'data_cells_compared':sum(v['cells'] for v in compared.values()),'JSON_leaf_checks':leaf_checks,
                    'independent_libraries':spec['independent_libraries'],'integer_counts_and_money_exact':True,
                    'derived_float_tolerance':spec['details']['float_tolerance'],'prior_sources_and_new_outputs_unchanged':True,
                    'elapsed_seconds':round(time.perf_counter()-started,3),'existing_RFM_rebuilt':False,'models_fitted':0}
        frozen.write_new(ROOT/ACCEPT,acceptance)
        manifest={'execution_specification':frozen.descriptor(ROOT,SPEC),'sources':spec['sources'],'files':files,
                  'cutpoints':frozen.descriptor(ROOT,cut_file.relative_to(ROOT).as_posix()),'result':frozen.descriptor(ROOT,RESULT),'acceptance':frozen.descriptor(ROOT,ACCEPT)}
        frozen.write_new(private/'manifest.json',manifest)
        frozen.write_new(private/'output_guard.json',dict(manifest,manifest=frozen.descriptor(ROOT,PRIVATE+'/manifest.json')))
        return {k:acceptance[k] for k in ['status','primary_fit_calls','T2_cutpoint_fits','score_and_panel_files','data_cells_compared','JSON_leaf_checks','elapsed_seconds']}
    except Exception as error:
        frozen.write_new(private/'failure.json',{'status':'partial_execution_preserved_no_replay','error_type':type(error).__name__})
        raise


def verify():
    guard=frozen.read_json(ROOT/PRIVATE/'output_guard.json')
    frozen.verify_descriptors(ROOT,[*guard['sources'],guard['execution_specification'],guard['cutpoints'],guard['result'],guard['acceptance'],guard['manifest']])
    for file in guard['files']:frozen.verify_descriptors(ROOT,[{k:file[k] for k in ('path','bytes','sha256')}])
    if frozen.read_json(ROOT/PRIVATE/'manifest.json')!={k:v for k,v in guard.items() if k!='manifest'}:raise ValueError('Temporal manifest mismatch')
    return {'status':'saved_temporal_bundle_bytes_verified','CSV_files':len(guard['files']),'cutpoints_refitted':False,'metrics_recomputed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);action=parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare','run','verify'):action.add_argument('--'+name,action='store_true')
    args=parser.parse_args();print(json.dumps(prepare() if args.prepare else run() if args.run else verify(),ensure_ascii=False))
