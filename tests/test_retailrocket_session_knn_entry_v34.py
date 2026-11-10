"""Actual top-level contracts and buffered child logs under the common lifecycle."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import retailrocket_session_knn_entry_v34 as common
from scripts import run_retailrocket_session_knn_sources_v25 as old
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,write,describe,verify_bindings,environment
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS

MODULE='tests.test_retailrocket_session_knn_entry_v34'
SEEDS=('scripts/retailrocket_session_knn_entry_v34.py','tests/test_retailrocket_session_knn_entry_v34.py')


def noisy_contract(request):
    print('parent audit diagnostic stdout')
    print('parent audit diagnostic stderr',file=sys.stderr)
    if request['metadata'].get('synthetic_only') is not True:raise ValueError('Only an artificial lifecycle fixture')
    common.require_direct_sources(request['metadata']['direct_methods'],request['sources'])
    verify_bindings(request['sources'])
    return request['metadata']


def child(folder,kind):
    folder=Path(folder).resolve()
    if folder.parent!=PRIVATE.resolve() or not folder.name.startswith('knn-v34-synthetic-'):
        raise ValueError('Artificial common-entry namespace only')
    request=read(folder/'request.json')
    meta,diagnostic=common.quiet_contract(noisy_contract,request)
    write(folder/(kind+'_contract.json'),dict(diagnostic=diagnostic,synthetic_only=True))
    if kind=='pipeline':
        # This output deliberately remains buffered through publisher sealing.
        print('late pipeline stdout after publisher snapshot')
        print('pipeline stderr before shutdown',file=sys.stderr)
        for role in ('worker','publisher'):
            old.run_child(folder,request,role,[sys.executable,'-B','-m',MODULE,'--'+role,str(folder)])
        write(folder/'pipeline_done.json',dict(completed=True));return
    if kind=='worker':
        print('worker buffered output')
        write(folder/'worker_done.json',dict(synthetic_only=True));return
    print('publisher buffered output')
    (folder/'publisher').mkdir()
    # Generic lifecycle receipt, not scientific query/SQL evidence.
    write(folder/'audited_result.json',dict(status='artificial_lifecycle_only',evidence=common.publisher_evidence(folder)))
    for name in ('events.json','observation.json','entry_span.json','telemetry_records.json'):
        write(folder/'publisher'/name,dict(synthetic_only=True))


def run_artificial():
    folder=PRIVATE/('knn-v34-synthetic-'+uuid4().hex)
    direct=common.source_inventory(SEEDS,dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],direct,'joint_tail',
        metadata=dict(synthetic_only=True,direct_methods=direct,environment=environment()),budget_seconds=1800,limits=LIMITS,poll_seconds=.05)
    completion=read(folder/'supervisor_completion.json')
    if completion['exit_code']!=0:
        raise AssertionError('\n'.join(p.read_text(encoding='utf-8',errors='replace')[-5000:] for p in folder.glob('*.log')))
    request=read(folder/'request.json');exits={k:old.child_exit(folder,request,k) for k in ('worker','publisher')}
    seal=common.closed_log_manifest(folder,request,completion,exits)
    return folder,seal


class UnitTests(unittest.TestCase):
    def test_quiet_contract_retains_diagnostics_and_exceptions(self):
        from io import StringIO
        from contextlib import redirect_stdout,redirect_stderr
        outer=StringIO()
        def contract():print('out');print('err',file=sys.stderr);return {'checked':True}
        with redirect_stdout(outer),redirect_stderr(outer):value,text=common.quiet_contract(contract)
        self.assertEqual(value,{'checked':True});self.assertIn('out',text);self.assertIn('err',text);self.assertEqual(outer.getvalue(),'')
        def fail():print('before failure');raise ValueError('guard')
        with redirect_stdout(outer),self.assertRaisesRegex(ValueError,'guard'):common.quiet_contract(fail)

    def test_merge_only_adds_and_rejects_conflicts(self):
        a=dict(path='scripts/a.py',bytes=1,sha256='a'*64);b=dict(path='scripts/b.py',bytes=2,sha256='b'*64)
        result=common.merge_methods([a],[a,b]);self.assertEqual({x['path']:x for x in result},{a['path']:a,b['path']:b})
        with self.assertRaises(ValueError):common.merge_methods([a],[dict(a,sha256='c'*64)])

    def test_real_inventory_directly_contains_priority_and_transitive_helpers(self):
        result=common.source_inventory(SEEDS,dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
        paths={r['path'] for r in result}
        for name in ('scripts/retailrocket_session_knn_priority_v23.py','scripts/retailrocket_session_knn_checkpoint_v2.py'):
            self.assertIn(name,paths)
        common.require_direct_sources(result,result)
        for removed in ('scripts/retailrocket_session_knn_priority_v23.py','scripts/retailrocket_session_knn_checkpoint_v2.py'):
            with self.subTest(removed=removed),self.assertRaises(ValueError):
                common.require_direct_sources(result,[r for r in result if r['path']!=removed])

    def test_same_size_changed_content_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'x.py';p.write_bytes(b'x=1\n');(root/'scripts').mkdir()
            priority=root/common.PRIORITY_SOURCE;priority.write_bytes(b'pass\n')
            required=dict(path=common.PRIORITY_SOURCE,bytes=5,sha256=hashlib.sha256(priority.read_bytes()).hexdigest())
            record=dict(path='x.py',bytes=4,sha256=hashlib.sha256(p.read_bytes()).hexdigest());p.write_bytes(b'x=2\n')
            with self.assertRaisesRegex(ValueError,'bytes changed'):common.require_direct_sources([required,record],[required,record],root=root)

    @contextmanager
    def source_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'scripts').mkdir()
            (root/'scripts/__init__.py').write_bytes(b'')
            (root/common.PRIORITY_SOURCE).write_bytes(b'pass\n')
            yield root

    def test_function_relative_and_package_imports_resolve_from_bytes(self):
        with self.source_fixture() as root:
            (root/'scripts/a.py').write_text('def f():\n from scripts import b\n',encoding='utf-8')
            (root/'scripts/b.py').write_text('from .c import value\n',encoding='utf-8')
            (root/'scripts/c.py').write_text('value=1\n',encoding='utf-8')
            paths={r['path'] for r in common.source_inventory(['scripts/a.py'],root=root)}
            self.assertTrue({'scripts/a.py','scripts/b.py','scripts/c.py','scripts/__init__.py'}<=paths)

    def test_loaded_module_cannot_hide_missing_direct_source(self):
        with self.source_fixture() as root:
            (root/'scripts/a.py').write_text('import scripts.missing\n',encoding='utf-8')
            with patch.dict(sys.modules,{'scripts.missing':object()}),self.assertRaisesRegex(ValueError,'Missing direct'):
                common.source_inventory(['scripts/a.py'],root=root)

    def test_nonliteral_dynamic_import_needs_sealed_explicit_targets(self):
        with self.source_fixture() as root:
            (root/'scripts/a.py').write_text('import importlib\ndef f(name): return importlib.import_module(name)\n',encoding='utf-8')
            (root/'scripts/b.py').write_text('value=1\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'explicit source seeds'):common.source_inventory(['scripts/a.py'],root=root)
            paths={r['path'] for r in common.source_inventory(['scripts/a.py'],dynamic_seeds=['scripts/b.py'],root=root)}
            self.assertIn('scripts/b.py',paths)

    def test_project_star_import_is_not_silently_omitted(self):
        with self.source_fixture() as root:
            (root/'scripts/pkg').mkdir();(root/'scripts/pkg/__init__.py').write_bytes(b'')
            (root/'scripts/a.py').write_text('from scripts.pkg import *\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'star imports'):common.source_inventory(['scripts/a.py'],root=root)

    def test_relative_dynamic_import_is_not_silently_omitted(self):
        with self.source_fixture() as root:
            (root/'scripts/a.py').write_text("import importlib\nimportlib.import_module('.child', package='scripts.pkg')\n",encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Relative dynamic'):common.source_inventory(['scripts/a.py'],root=root)

    def test_duplicate_or_noncanonical_descriptors_rejected(self):
        record=dict(path='scripts/a.py',bytes=1,sha256='a'*64)
        for records in ([record,record],[dict(record,bytes=True)],[dict(record,path='../a.py')]):
            with self.subTest(records=records),self.assertRaises(ValueError):common.merge_methods([],records)

    def test_source_paths_cannot_escape_root(self):
        with self.assertRaises((ValueError,FileNotFoundError)):common.source_inventory(['../outside.py'])

    def test_publisher_excludes_only_exact_active_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'window';(folder/'nested').mkdir(parents=True)
            for name in ('stdout_stderr.log','publisher.log','worker.log','nested/stdout_stderr.log','nested/publisher.log'):
                (folder/name).write_text(name,encoding='utf-8')
            result=common.publisher_evidence(folder,root=root);paths={x['path'] for x in result}
            self.assertNotIn('window/stdout_stderr.log',paths);self.assertNotIn('window/publisher.log',paths)
            self.assertIn('window/worker.log',paths);self.assertIn('window/nested/stdout_stderr.log',paths);self.assertIn('window/nested/publisher.log',paths)


class IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.folder,cls.seal=run_artificial()
    def check(self,completion=None):
        request=read(self.folder/'request.json')
        return common.closed_log_manifest(self.folder,request,completion or read(self.folder/'supervisor_completion.json'),
            {k:old.child_exit(self.folder,request,k) for k in ('worker','publisher')},expected=self.seal)

    def test_true_top_level_contract_and_late_log_flush_complete(self):
        self.assertEqual(self.check(),self.seal)
        result=read(self.folder/'audited_result.json');paths={x['path'] for x in result['evidence']}
        for name in ('stdout_stderr.log','publisher.log'):
            self.assertNotIn((self.folder/name).relative_to(ROOT).as_posix(),paths)
            self.assertGreater((self.folder/name).stat().st_size,0)
        self.assertIn('late pipeline stdout',(self.folder/'stdout_stderr.log').read_text(encoding='utf-8'))
        for kind in ('pipeline','worker','publisher'):
            self.assertIn('parent audit diagnostic',read(self.folder/(kind+'_contract.json'))['diagnostic'])

    def test_any_final_log_append_or_sealed_file_mutation_rejected(self):
        for name in ('stdout_stderr.log','publisher.log','worker.log','worker_done.json','audited_result.json'):
            p=self.folder/name;before=p.read_bytes();p.write_bytes(before+b'changed')
            try:
                with self.subTest(name=name),self.assertRaises((ValueError,AssertionError)):self.check()
            finally:p.write_bytes(before)

    def test_new_file_and_live_completion_rejected(self):
        p=self.folder/'unexpected.txt';p.write_text('late file',encoding='utf-8')
        try:
            with self.assertRaises(ValueError):self.check()
        finally:p.unlink()
        completion=read(self.folder/'supervisor_completion.json')
        for change in (dict(exit_code=1),dict(tracked_processes_alive_after_cleanup=1),dict(stop_reason='deadline')):
            with self.subTest(change=change),self.assertRaises(ValueError):self.check(dict(completion,**change))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1] in ('--pipeline','--worker','--publisher'):child(sys.argv[2],sys.argv[1][2:])
    else:unittest.main()
