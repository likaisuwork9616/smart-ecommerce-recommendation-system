"""Archive accepted UCI v1 lineage and handoff snapshots locally, without research reruns."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import time
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
REPORT='reports/stage6/uci_rfm_v1_research_release.json'
PRIVATE='shop-mysql-runtime/uci_rfm_release_v1'
VERIFY='shop-mysql-runtime/verification/uci-rfm-release-v1'
ARCHIVE='shop-mysql-runtime/backups/uci_rfm_v1_research_release_v1.zip'
TOP_GUARD='shop-mysql-runtime/uci_rfm_temporal_v1/output_guard.json'
MANIFEST_MEMBER='uci_rfm_v1_archive_manifest.json'
HANDOFF='docs/STAGE6_RFM_RESEARCH_HANDOFF.md'
CODE='scripts/archive_uci_rfm_v1.py'
TEST='tests/test_archive_uci_rfm_v1.py'
SNAPSHOTS=['.gitattributes','.gitignore','README.md','data/README.md','docs/README.md','docs/PROJECT_PROGRESS.md','reports/README.md','scripts/README.md','tests/README.md','requirements.txt','requirements-lock.txt','scripts/__init__.py']
EXTRAS=[HANDOFF,'docs/STAGE6_UCI_RETAIL_II_INTAKE.md','docs/STAGE6_UCI_RFM_BUILD_V1.md','docs/STAGE6_UCI_RFM_TEMPORAL_V1.md',
        'requirements.txt','requirements-lock.txt','scripts/__init__.py',CODE,TEST,
        'shop-mysql-runtime/uci_rfm_contract_v1/tests.log',
        'shop-mysql-runtime/verification/uci-rfm-build-v1/tests.log','shop-mysql-runtime/verification/uci-rfm-build-v1/prepared_guard.json',
        'shop-mysql-runtime/verification/uci-rfm-temporal-v1/tests.log','shop-mysql-runtime/verification/uci-rfm-temporal-v1/prepared_guard.json',
        VERIFY+'/tests.log']


def safe_name(name):
    path=PurePosixPath(name)
    if not name or name.startswith('/') or '\\' in name or ':' in name or any(p in ('','.','..') for p in name.split('/')) or path.as_posix()!=name:
        raise ValueError('Unsafe archive member')
    return path.as_posix()


def inside(root,name):
    path=Path(root)/safe_name(name)
    if not path.resolve().is_relative_to(Path(root).resolve()):raise ValueError('Path leaves shop')
    return path


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def descriptor(root,name):
    path=inside(root,name)
    return {'path':name,'bytes':path.stat().st_size,'sha256':digest(path)}


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')


def write_new(path,value):
    with Path(path).open('xb') as output:output.write(encoded(value))


def assert_descriptor(root,item):
    if descriptor(root,item['path'])!={k:item[k] for k in ('path','bytes','sha256')}:raise ValueError('Source bytes differ: '+item['path'])


def normalize(items):
    unique={}
    for item in items:
        name=safe_name(item['path']);d={k:item[k] for k in ('path','bytes','sha256')}
        if name in unique and unique[name]!=d:raise ValueError('Conflicting source descriptors')
        unique[name]=d
    return [unique[name] for name in sorted(unique)]


def collect(root):
    guard=read(inside(root,TOP_GUARD))
    items=normalize([*guard['sources'],guard['execution_specification'],guard['cutpoints'],guard['result'],guard['acceptance'],guard['manifest'],*guard['files']])
    for d in items:assert_descriptor(root,d)
    declared={d['path']:d for d in items}
    for name in [TOP_GUARD,*EXTRAS,*SNAPSHOTS]:
        d=descriptor(root,name)
        if name in declared and declared[name]!=d:raise ValueError('Conflicting current source')
        declared[name]=d
    return [dict(declared[name],live_role='mutable_context_snapshot' if name in SNAPSHOTS else 'frozen_research_source') for name in sorted(declared)]


def pack(root,path,manifest):
    """No extraction, no overwrite; every source remains in place."""
    with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
        archive.writestr(MANIFEST_MEMBER,encoded(manifest))
        for item in manifest['files']:
            name=safe_name(item['path']);source=inside(root,name);sha=hashlib.sha256();size=0
            with source.open('rb') as stream,archive.open(name,'w',force_zip64=True) as output:
                while chunk:=stream.read(1024*1024):output.write(chunk);sha.update(chunk);size+=len(chunk)
            if size!=item['bytes'] or sha.hexdigest()!=item['sha256']:raise ValueError('Source changed while archiving: '+name)


def inspect_archive(path,expected_manifest_sha=None):
    checked=total=0
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate ZIP members')
        for name in names:safe_name(name)
        manifest_bytes=archive.read(MANIFEST_MEMBER)
        manifest_sha=hashlib.sha256(manifest_bytes).hexdigest()
        if expected_manifest_sha and manifest_sha!=expected_manifest_sha:raise ValueError('Archive manifest changed')
        manifest=json.loads(manifest_bytes)
        expected=[d['path'] for d in manifest['files']]
        if len(expected)!=len(set(expected)) or set(names)!={MANIFEST_MEMBER,*expected}:raise ValueError('ZIP inventory differs')
        for item in manifest['files']:
            sha=hashlib.sha256();size=0
            with archive.open(item['path']) as stream:
                while chunk:=stream.read(1024*1024):sha.update(chunk);size+=len(chunk)
            # ZipExtFile verifies CRC when its stream reaches EOF.
            if size!=item['bytes'] or sha.hexdigest()!=item['sha256']:raise ValueError('Archived payload differs: '+item['path'])
            checked+=1;total+=size
    return manifest,{'payload_files':checked,'zip_members':checked+1,'payload_bytes':total,'all_payload_CRC_and_SHA256_passed':True,'manifest_sha256':manifest_sha}


def facts(root):
    r=read(inside(root,'reports/stage6/uci_rfm_temporal_v1.json'));a=read(inside(root,'reports/stage6/uci_rfm_temporal_v1_acceptance.json'))
    if r['status']!='completed_retrospective_temporal_description' or a['status']!='passed_independent_scores_and_aggregates':raise ValueError('Temporal acceptance unavailable')
    s=r['results'];main=s['temporal']['main']
    if r['primary_fit_calls']!=1 or r['T2_cutpoint_fits']!=0:raise ValueError('Unexpected reference fit role')
    return {'reference_customers':r['cutpoints']['n'],'primary_fit_calls':1,'T2_cutpoint_fits':0,'paired_active_customers':main['paired']['n'],
            'paired_over_U1':main['paired_coverage']['over_U1'],'joint_exact_rate':main['paired']['joint']['exact_rate'],'ARI':main['paired']['joint']['ARI'],
            'joint_support':{t:{k:v for k,v in s['snapshots']['main/'+t]['support']['joint'].items() if k!='counts'} for t in ['T1','T2']},
            'missing_customer_raw_row_share':{t:s['window_raw_ledgers'][t]['unknown_customer_row_share'] for t in ['T1','T2']},
            'provenance':'copied_from_accepted_report_not_new_metric_recalculation'}


def archive_release(root=ROOT):
    root=Path(root)
    if inside(root,REPORT).exists():return verify(root)
    private=inside(root,PRIVATE);target=inside(root,ARCHIVE);partial=target.with_suffix('.zip.partial')
    if private.exists() or target.exists() or partial.exists():raise FileExistsError('Preserve existing or partial release; do not replay')
    # Run archive-specific synthetic I/O tests, without any research runner import.
    import sys
    if str(root) not in sys.path:sys.path.insert(0,str(root))
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_archive_uci_rfm_v1');log=io.StringIO();start=time.perf_counter()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite);test_seconds=round(time.perf_counter()-start,6)
    if not result.wasSuccessful() or result.skipped:print(log.getvalue());raise ValueError('Archive tests failed')
    inside(root,VERIFY).mkdir(parents=True,exist_ok=True)
    inside(root,VERIFY+'/tests.log').write_text(log.getvalue(),encoding='utf-8',newline='\n')
    sources=collect(root);summary=facts(root)
    manifest={'release_id':'uci_rfm_v1_research_release_v1','scope':'UCI accepted lineage, raw source and local results; study handoff; selected public-code and mutable-index snapshots',
              'files':sources,'research_facts':summary,
              'operational_status':'offline_research_only_small_groups_and_retrospective_limits_retained',
              'snapshot_policy':'Archive bytes are fixed. Mutable indexes may evolve after release; frozen research inputs must remain byte-identical.',
              'restore':'Preserve ZIP and detached public release receipt. Verify archive before extraction into a clean project directory; restore dependencies separately.',
              'excluded':'No MySQL database/credentials, .venv, .git history, models or Olist private datasets; old Olist backups remain separate.',
              'attribution':'Chen, D. (2012). Online Retail II. UCI Machine Learning Repository. DOI 10.24432/C5CG6D. Official page CC BY 4.0; page snapshot included.'}
    private.mkdir();target.parent.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    try:
        write_new(private/'archive_manifest.json',manifest)
        pack(root,partial,manifest)
        restored,verification=inspect_archive(partial,digest(private/'archive_manifest.json'))
        if restored!=manifest:raise ValueError('Archive manifest readback differs')
        for item in sources:assert_descriptor(root,item)
        partial.rename(target)
        receipt={'status':'research_handoff_archived_and_verified','release_id':manifest['release_id'],'archive':descriptor(root,ARCHIVE),
                 'archive_manifest':descriptor(root,PRIVATE+'/archive_manifest.json'),'verification':verification,
                 'frozen_research_sources':sum(d['live_role']=='frozen_research_source' for d in sources),
                 'context_snapshots':sum(d['live_role']=='mutable_context_snapshot' for d in sources),
                 'research_facts':summary,'sources':sources,
                 'archive_tests':{'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'elapsed_seconds':test_seconds},
                 'elapsed_seconds':round(time.perf_counter()-started,3),
                 'scope_this_turn':{'RFM_rebuilds':0,'cutpoint_fits':0,'metric_recalculations':0,'new_models':0,'research_tests_rerun':False},
                 'backup_limit':'Same shop drive only; no remote/offsite backup or GitHub publication performed.'}
        write_new(inside(root,REPORT),receipt)
        write_new(private/'output_guard.json',{'receipt':descriptor(root,REPORT),'archive':receipt['archive'],'manifest':receipt['archive_manifest']})
        return {'status':receipt['status'],'archive_bytes':receipt['archive']['bytes'],**verification,'archive_tests':result.testsRun,'elapsed_seconds':receipt['elapsed_seconds']}
    except Exception as error:
        write_new(private/'failure.json',{'status':'partial_archive_preserved_no_replay','error_type':type(error).__name__});raise


def verify(root=ROOT,archive_only=False):
    root=Path(root);receipt=read(inside(root,REPORT));assert_descriptor(root,receipt['archive'])
    manifest,checked=inspect_archive(inside(root,receipt['archive']['path']),receipt['verification']['manifest_sha256'])
    if manifest['files']!=receipt['sources'] or checked!=receipt['verification']:raise ValueError('Release inventory mismatch')
    verified=0
    if not archive_only:
        assert_descriptor(root,receipt['archive_manifest'])
        for item in manifest['files']:
            if item['live_role']=='frozen_research_source':assert_descriptor(root,item);verified+=1
        guard=read(inside(root,PRIVATE+'/output_guard.json'))
        for d in guard.values():assert_descriptor(root,d)
    return {'status':'archive_only_verified' if archive_only else 'archive_and_live_frozen_sources_verified',
            **checked,'live_frozen_sources_verified':verified,'research_recomputed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--archive',action='store_true');actions.add_argument('--verify',action='store_true');actions.add_argument('--verify-archive-only',action='store_true')
    args=parser.parse_args();print(json.dumps(archive_release() if args.archive else verify(archive_only=args.verify_archive_only),ensure_ascii=False))
