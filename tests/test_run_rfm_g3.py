"""Synthetic G3 provenance, persistence, completion and failure handling."""
import copy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import run_rfm_g3 as entry
from tests.test_rfm_g3 import fixture


class G3EntryTests(unittest.TestCase):
    def setUp(self):
        scratch=entry.ROOT/'.runtime/rfm_g3_synthetic'
        scratch.mkdir(parents=True,exist_ok=True)
        self.root=scratch/uuid.uuid4().hex;self.root.mkdir()
        def cleanup():
            target,parent=self.root.resolve(),scratch.resolve()
            if target==parent or not target.is_relative_to(parent): raise ValueError('Unsafe scratch cleanup')
            shutil.rmtree(target)
        self.addCleanup(cleanup)
        source=self.root/'synthetic_source.txt';source.write_text('fixture only',encoding='utf-8')
        self.inputs=fixture()
        self.state=lambda root:{'sources':[entry.base.descriptor(source,root)],
            'prior_private_evidence':{'synthetic_fixture':True},
            'actual_input_verification_receipt':{'synthetic_fixture':True},'environment':{'fixture_only':True}}
        for mocker in (patch.object(entry,'state',side_effect=self.state),
                       patch.object(entry.sources,'load_reference',side_effect=lambda root:copy.deepcopy(self.inputs))):
            mocker.start();self.addCleanup(mocker.stop)
        spec={'format_version':1,'policy':entry.policy(),'sources':self.state(self.root)['sources'],
              'environment':{'fixture_only':True},'synthetic_verification':{'fixture_only':True}}
        entry.base.immutable_write(self.root/entry.SPEC,spec)
        log=self.root/entry.LOG;log.parent.mkdir(parents=True,exist_ok=True)
        log.write_text('synthetic setup; not an actual execution receipt',encoding='utf-8')
        entry.base.immutable_write(self.root/entry.INPUT,{'specification':entry.base.descriptor(self.root/entry.SPEC,self.root),
            'test_log':entry.base.descriptor(log,self.root),'state':self.state(self.root)})

    def test_complete_run_readback_and_no_G3_core_on_verify(self):
        result=entry.run(self.root)
        self.assertEqual(result['G3'],'passed')
        with patch.object(entry.core,'evaluate',side_effect=AssertionError):
            self.assertEqual(entry.verify(self.root),result)
        with self.assertRaises(ValueError): entry.run(self.root)
        with self.assertRaises(ValueError): entry.prepare(self.root)

    def test_ineligible_is_saved_as_completed_diagnostic(self):
        self.inputs=fixture(frequency=[1]*200+[2]*800)
        result=entry.run(self.root)
        self.assertEqual(result['G3'],'ineligible')
        self.assertFalse((self.root/entry.FAILURE).exists())
        self.assertTrue((self.root/entry.GUARD).is_file())

    def test_source_change_and_changed_test_log_rejected_before_execution(self):
        (self.root/'synthetic_source.txt').write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError): entry.run(self.root)
        self.assertFalse((self.root/entry.EXECUTION).exists())
        (self.root/'synthetic_source.txt').write_text('fixture only',encoding='utf-8')
        (self.root/entry.LOG).write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError): entry.run(self.root)

    def test_partial_namespace_rejected(self):
        (self.root/entry.EXECUTION).mkdir()
        with self.assertRaises(ValueError): entry.run(self.root)

    def test_public_report_tampering_rejected(self):
        entry.run(self.root)
        path=self.root/entry.REPORT
        path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaises(ValueError): entry.verify(self.root)

    def test_assignment_tampering_rejected(self):
        entry.run(self.root)
        path=self.root/entry.BUNDLE/'assignments.csv'
        path.write_bytes(path.read_bytes().replace(b'customer00000',b'customerXXXXX',1))
        with self.assertRaises(ValueError): entry.verify(self.root)

    def test_late_guard_failure_keeps_evidence_and_blocks_replay(self):
        original=entry.base.immutable_write
        def write(path,payload):
            if path==self.root/entry.GUARD: raise OSError('synthetic late failure')
            return original(path,payload)
        with patch.object(entry.base,'immutable_write',side_effect=write):
            with self.assertRaises(OSError): entry.run(self.root)
        self.assertTrue((self.root/entry.REPORT).exists())
        self.assertTrue((self.root/entry.FAILURE).exists())
        with self.assertRaises(ValueError): entry.verify(self.root)
        with self.assertRaises(ValueError): entry.run(self.root)

    def test_source_change_after_core_prevents_publication(self):
        evaluate=entry.core.evaluate
        def changing(*args):
            result=evaluate(*args)
            (self.root/'synthetic_source.txt').write_text('changed mid-execution',encoding='utf-8')
            return result
        with patch.object(entry.core,'evaluate',side_effect=changing):
            with self.assertRaises(ValueError): entry.run(self.root)
        self.assertFalse((self.root/entry.REPORT).exists())
        self.assertTrue((self.root/entry.FAILURE).exists())


class G3SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        scratch=entry.ROOT/'.runtime/rfm_g3_source_synthetic'
        scratch.mkdir(parents=True,exist_ok=True)
        self.root=scratch/uuid.uuid4().hex;self.root.mkdir()
        def cleanup():
            target,parent=self.root.resolve(),scratch.resolve()
            if target==parent or not target.is_relative_to(parent): raise ValueError('Unsafe cleanup')
            shutil.rmtree(target)
        self.addCleanup(cleanup)

    def test_actual_verification_receipt_binds_before_after_and_cannot_overwrite(self):
        state={'fixture':'same'}
        result={'G2':'passed','status':'synthetic_verified'}
        with patch.object(entry.sources,'snapshot',return_value=state), \
             patch.object(entry.sources.v2,'verify',return_value=result) as verify:
            entry.sources.verify_v2(self.root)
            verify.assert_called_once_with(self.root)
            self.assertEqual(entry.sources.accepted_snapshot(self.root),state)
            with self.assertRaises(ValueError): entry.sources.verify_v2(self.root)
        with patch.object(entry.sources,'snapshot',return_value={'fixture':'changed'}):
            with self.assertRaises(ValueError): entry.sources.accepted_snapshot(self.root)

    def test_changed_source_during_input_verify_does_not_create_receipt(self):
        with patch.object(entry.sources,'snapshot',side_effect=[{'v':1},{'v':2}]), \
             patch.object(entry.sources.v2,'verify',return_value={'G2':'passed'}):
            with self.assertRaises(ValueError): entry.sources.verify_v2(self.root)
        self.assertFalse((self.root/entry.sources.RECEIPT).exists())


if __name__=='__main__': unittest.main()
