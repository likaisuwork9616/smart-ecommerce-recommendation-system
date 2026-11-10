"""Post-exit log recovery checks over small artificial files; no scientific runs."""
from copy import deepcopy
from contextlib import ExitStack
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import psutil

from scripts import release_retailrocket_session_knn_v32 as release
from scripts import run_retailrocket_session_knn_v2 as io
from scripts.retailrocket_session_knn_checkpoint_v2 import encoded
from scripts.retailrocket_session_knn_cost_window_v5 import LIMITS
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.retailrocket_session_knn_snapshot_v30 import SCHEME


def record(path,data):
    return dict(path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())


def fixture_json(path,value):
    Path(path).write_bytes(encoded(value))


class Files(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='knn-v32-release-unit-',dir=io.ROOT/'shop-mysql-runtime/verification')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.path=release.NAMESPACE+'/stdout_stderr.log';self.log=self.root/self.path;self.log.parent.mkdir(parents=True)
        self.tail=release.EXPECTED_TAIL;self.log.write_bytes(self.tail)
        self.old=record(self.path,b'');self.final=record(self.path,self.tail)
        self.other_path='existing/scientific-payload.json';self.other=self.root/self.other_path
        self.other.parent.mkdir()
        self.other.write_bytes(b'{"proof":"bound"}\n');self.other_record=record(self.other_path,self.other.read_bytes())
        self.strict=_clone(io.verify_bindings,ROOT=self.root,describe=_clone(io.describe,ROOT=self.root))


class LogTests(Files):
    def test_exact_frozen_tail_and_original_empty_descriptor_accepted(self):
        witness=release.validate_log(self.old,self.final,self.tail,self.tail)
        self.assertIsInstance(witness,dict);self.assertEqual(len(self.tail),450)
        self.assertEqual(self.final['sha256'],release.EXPECTED_FINAL_SHA)

    def test_caller_cannot_authorize_arbitrary_expected_tail(self):
        evil=b'arbitrary text\r\n'
        with self.assertRaises(ValueError):release.validate_log(self.old,record(self.path,evil),evil,evil)

    def test_old_prefix_content_or_nonempty_shape_is_never_exempt(self):
        for old in (record(self.path,b'prefix'),dict(self.old,sha256='0'*64),dict(self.old,bytes=1),dict(self.old,bytes=False)):
            with self.subTest(old=old),self.assertRaises(ValueError):release.validate_log(old,self.final,self.tail,self.tail)

    def test_actual_log_prefix_truncation_or_tail_change_rejected(self):
        for data in (self.tail[:-1],self.tail[1:],b'X'+self.tail[1:],self.tail+b'\r\n',self.tail+self.tail):
            with self.subTest(data_bytes=len(data)),self.assertRaises(ValueError):
                release.validate_log(self.old,record(self.path,data),data,self.tail)

    def test_lf_rewrite_and_same_size_arbitrary_tail_rejected(self):
        for data in (self.tail.replace(b'\r\n',b'\n'),b'X'*len(self.tail)):
            with self.subTest(data_bytes=len(data)),self.assertRaises(ValueError):
                release.validate_log(self.old,record(self.path,data),data,self.tail)

    def test_final_descriptor_path_size_and_sha_must_match(self):
        for change in (dict(path='different/stdout_stderr.log'),dict(bytes=449),dict(sha256='0'*64),dict(bytes=True)):
            with self.subTest(change=change),self.assertRaises(ValueError):
                release.validate_log(self.old,dict(self.final,**change),self.tail,self.tail)

    def test_only_exact_outer_log_basename_can_receive_exception(self):
        for name in ('existing/worker.log','existing/stdout_stderr.log.extra','stdout_stderr.log'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                release.validate_log(dict(self.old,path=name),dict(self.final,path=name),self.tail,self.tail)


class VerifierTests(Files):
    def verifier(self):return release.make_verifier(self.old,self.final,self.tail,root=self.root)

    def test_old_stdout_exception_preserves_strict_verification_of_all_other_sources(self):
        with patch.object(release,'verify_bindings',side_effect=self.strict) as strict:
            self.verifier()([self.other_record,self.old])
        passed=[r for call in strict.call_args_list for r in call.args[0]]
        self.assertIn(self.other_record,passed);self.assertNotIn(self.old,passed)

    def test_new_log_descriptor_is_strictly_verified(self):
        with patch.object(release,'verify_bindings',side_effect=self.strict) as strict:
            self.verifier()([self.final])
        passed=[r for call in strict.call_args_list for r in call.args[0]]
        self.assertIn(self.final,passed)

    def test_unknown_descriptor_for_same_log_path_rejected(self):
        with patch.object(release,'verify_bindings',side_effect=self.strict),self.assertRaises(ValueError):
            self.verifier()([dict(self.old,bytes=12,sha256='0'*64)])

    def test_other_file_tampering_is_not_covered_by_log_exception(self):
        self.other.write_bytes(b'{"proof":"changed"}\n')
        with patch.object(release,'verify_bindings',side_effect=self.strict),self.assertRaises(ValueError):
            self.verifier()([self.old,self.other_record])

    def test_same_basename_from_another_context_is_strictly_rejected(self):
        other='another-window/stdout_stderr.log';path=self.root/other;path.parent.mkdir();path.write_bytes(self.tail)
        with patch.object(release,'verify_bindings',side_effect=self.strict),self.assertRaises(ValueError):
            self.verifier()([record(other,b'')])

    def test_every_old_descriptor_use_rereads_log_and_detects_late_append(self):
        verify=self.verifier()
        with patch.object(release,'verify_bindings',side_effect=self.strict):
            verify([self.old]);self.log.write_bytes(self.tail+b'late write')
            with self.assertRaises(ValueError):verify([self.old])

    def test_invocation_local_exception_does_not_replace_frozen_global_verifier(self):
        original=io.verify_bindings
        with patch.object(release,'verify_bindings',side_effect=self.strict):self.verifier()([self.old,self.other_record])
        self.assertIs(io.verify_bindings,original)
        with self.assertRaises(ValueError):self.strict([self.old])


class StoppedTests(Files):
    def setUp(self):
        super().setUp();self.folder=self.root/'window';self.folder.mkdir()
        self.request=dict(created_utc='2026-11-10T00:00:00+00:00',deadline_utc='2026-11-10T00:30:00+00:00',
            budget_seconds=1800,limits=LIMITS,operation='joint_tail',full_readback_enabled=False,reserved_test='locked',T_plan=None,
            metadata=dict(fingerprint_scheme=SCHEME))
        self.completion=dict(exit_code=0,stop_reason=None,supervisor_error=None,tracked_processes_alive_after_cleanup=0,
            actual_exit_observed_utc='2026-11-10T00:20:00+00:00',operation='joint_tail',full_readback_started=False,
            reserved_test='locked',T_plan=None,seconds=1200,peak_sampled_tree_and_supervisor_rss_bytes=1,peak_sampled_execution_bytes=1)
        self.exits={kind:dict(kind=kind,returncode=0,pid=900001+i,create_time=100+i,
            started_utc=f'2026-11-10T00:{i*10:02d}:00+00:00',ended_utc=f'2026-11-10T00:{(i+1)*10:02d}:00+00:00',seconds=600)
            for i,kind in enumerate(('worker','publisher'))}
        fixture_json(self.folder/'pipeline_done.json',dict(completed=True));self.save()
        fixture_json(self.folder/'tracked_process_identities.json',dict(identities=[dict(pid=900003,create_time=103)],live_after_cleanup=0,
            coverage='Identities observed at monitor samples, not an OS job-object guarantee.'))

    def save(self):
        fixture_json(self.folder/'supervisor_completion.json',self.completion)
        for kind,value in self.exits.items():fixture_json(self.folder/(kind+'_exit.json'),value)

    def stopped(self):
        with patch.object(release.psutil,'Process',side_effect=psutil.NoSuchProcess(900000)):
            return release.assert_stopped(self.folder,self.request)

    def test_normal_supervisor_children_and_tracked_identities_must_all_be_stopped(self):
        completion,exits=self.stopped();self.assertEqual(completion,self.completion);self.assertEqual(exits,self.exits)

    def test_supervisor_failure_stop_and_live_cleanup_rejected(self):
        for change in (dict(exit_code=1),dict(stop_reason='deadline'),dict(supervisor_error='RuntimeError'),dict(tracked_processes_alive_after_cleanup=1)):
            with self.subTest(change=change):
                fixture_json(self.folder/'supervisor_completion.json',dict(self.completion,**change))
                with self.assertRaises(ValueError):self.stopped()

    def test_outer_deadline_and_resource_limits_rejected(self):
        for change in (dict(actual_exit_observed_utc='2026-11-10T00:31:00+00:00'),dict(seconds=1801),
                       dict(peak_sampled_tree_and_supervisor_rss_bytes=LIMITS['rss_bytes']+1)):
            with self.subTest(change=change):
                fixture_json(self.folder/'supervisor_completion.json',dict(self.completion,**change))
                with self.assertRaises(ValueError):self.stopped()

    def test_incomplete_pipeline_rejected(self):
        fixture_json(self.folder/'pipeline_done.json',dict(completed=False))
        with self.assertRaises(ValueError):self.stopped()

    def test_failed_child_and_wrong_child_identity_rejected(self):
        for kind in ('worker','publisher'):
            for change in (dict(returncode=1),dict(kind='another-context'),dict(ended_utc='2026-11-10T00:31:00+00:00')):
                with self.subTest(kind=kind,change=change):
                    fixture_json(self.folder/(kind+'_exit.json'),dict(self.exits[kind],**change))
                    with self.assertRaises(ValueError):self.stopped()
                    fixture_json(self.folder/(kind+'_exit.json'),self.exits[kind])

    def test_overlapping_worker_and_publisher_rejected(self):
        value=dict(self.exits['publisher'],started_utc='2026-11-10T00:09:59+00:00')
        fixture_json(self.folder/'publisher_exit.json',value)
        with self.assertRaises(ValueError):self.stopped()

    def test_matching_live_tracked_process_identity_rejected(self):
        class Alive:
            def is_running(self):return True
            def create_time(self):return 103
        def process(pid):
            if pid==900003:return Alive()
            raise psutil.NoSuchProcess(pid)
        with patch.object(release.psutil,'Process',side_effect=process),self.assertRaises(ValueError):
            release.assert_stopped(self.folder,self.request)

    def test_reused_pid_with_different_creation_identity_is_not_original_live_process(self):
        class Reused:
            def is_running(self):return True
            def create_time(self):return 999
        def process(pid):
            if pid==900003:return Reused()
            raise psutil.NoSuchProcess(pid)
        with patch.object(release.psutil,'Process',side_effect=process):
            self.assertEqual(release.assert_stopped(self.folder,self.request)[0],self.completion)


class AuditTests(Files):
    def setUp(self):
        super().setUp();self.folder=self.root/release.NAMESPACE
        self.request=dict(metadata=dict(fingerprint_scheme=SCHEME))
        self.witness=release.validate_log(self.old,self.final,self.tail,self.tail)
        self.frames=[f'{{"artificial_ordinal":{i}}}\n'.encode() for i in range(48)]
        payload=b''.join(self.frames)
        self.reference=dict(actual_committed_bytes=len(payload),actual_committed_payload_sha256=hashlib.sha256(payload).hexdigest())
        self.result=dict(status='v31_C1_S1_independent_real_audit_complete',cache=dict(fingerprint_scheme=SCHEME),
            runs={f'artificial_{i}':{} for i in range(14)})
        self.audited=(self.result,{}, {},{},{});self.meta=dict(cohort=dict(old_run='reference/run.json'));self.delegate_calls=0

    def auditing(self,late_append=False):
        stack=ExitStack();maker=release.make_verifier
        def original_audit(folder,request):
            # The real invocation-local _clone must inject its strict exception
            # here; the test does not replace _clone or its global lookup.
            verify_bindings([self.old,self.other_record])
            self.delegate_calls+=1
            if late_append:self.log.write_bytes(self.tail+b'late append')
            return self.audited
        def contract(request):
            sys.stdout.write(self.tail.decode('ascii').replace('\r\n','\n'))
            return self.meta
        stack.enter_context(patch.object(release,'ROOT',self.root))
        self.stop_check=stack.enter_context(patch.object(release,'assert_stopped',return_value=({},{})))
        stack.enter_context(patch.object(release,'expected_diagnostic',return_value=self.tail))
        stack.enter_context(patch.object(release.entry,'contract',side_effect=contract))
        stack.enter_context(patch.object(release.entry,'specification',return_value=dict(original48_reference=self.reference)))
        stack.enter_context(patch.object(release.previous,'audit_completed',original_audit))
        stack.enter_context(patch.object(release,'make_verifier',side_effect=lambda *a,**kw:maker(*a,root=self.root)))
        self.strict_check=stack.enter_context(patch.object(release,'verify_bindings',side_effect=self.strict))
        self.frame_check=stack.enter_context(patch.object(release,'_physical_frames',side_effect=lambda path:iter(self.frames)))
        return stack

    def test_complete_post_exit_delegate_and_all14_scientific_frame_checks_preserved(self):
        with self.auditing():
            self.assertEqual(release.audit_existing(self.folder,self.request,self.witness),self.audited)
            self.assertEqual(self.delegate_calls,1);self.assertEqual(self.frame_check.call_count,15)
            self.assertEqual(self.stop_check.call_count,2)
            strict=[r for call in self.strict_check.call_args_list for r in call.args[0]]
            self.assertIn(self.other_record,strict);self.assertIn(self.final,strict)

    def test_mixed_namespace_request_scheme_and_publisher_status_or_scheme_rejected(self):
        with self.auditing():
            with self.subTest(namespace=True),self.assertRaises(ValueError):
                release.audit_existing(self.folder.parent/'another-window',self.request,self.witness)
            wrong=deepcopy(self.request);wrong['metadata']['fingerprint_scheme']='wrong-S1-scheme'
            with self.subTest(request_scheme=True),self.assertRaises(ValueError):release.audit_existing(self.folder,wrong,self.witness)
            saved=self.result['status'];self.result['status']='v30-synthetic-or-another-context'
            with self.subTest(status=True),self.assertRaises(ValueError):release.audit_existing(self.folder,self.request,self.witness)
            self.result['status']=saved;self.result['cache']['fingerprint_scheme']='wrong-S1-scheme'
            with self.subTest(publisher_scheme=True),self.assertRaises(ValueError):release.audit_existing(self.folder,self.request,self.witness)

    def test_toctou_append_after_original_audit_cannot_receive_new_final_seal(self):
        with self.auditing(late_append=True),self.assertRaisesRegex(ValueError,'Frozen source identity changed'):
            release.audit_existing(self.folder,self.request,self.witness)
        self.assertEqual(self.delegate_calls,1)


class ManifestTests(Files):
    def test_sorted_complete_manifest_rejects_added_files_and_changed_contents_before_publication(self):
        folder=self.log.parent
        for name in ('z-last.txt','a-first.txt'):(folder/name).write_bytes(name.encode())
        frozen=release.window_manifest(folder)
        self.assertEqual([x['path'] for x in frozen],sorted(x['path'] for x in frozen))
        self.assertEqual(release.window_manifest(folder),frozen)
        extra=folder/'unexpected-new-file.log';extra.write_bytes(b'unsealed addition')
        with patch.object(release,'read',return_value=dict(window_evidence=frozen)):
            with self.subTest(new_file=True),self.assertRaisesRegex(ValueError,'frozen complete final window manifest'):
                release.report_for(folder,dict(metadata={}),({},{},{},{},{}),{})
            extra.unlink();self.log.write_bytes(self.tail+b'changed')
            with self.subTest(changed_content=True),self.assertRaisesRegex(ValueError,'frozen complete final window manifest'):
                release.report_for(folder,dict(metadata={}),({},{},{},{},{}),{})


if __name__=='__main__':unittest.main()
