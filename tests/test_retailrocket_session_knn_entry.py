"""Preparation-only entry, resource and write guards; synthetic fixtures only."""
from copy import deepcopy
import contextlib
import io
import unittest

from scripts import prepare_retailrocket_session_knn_v1 as entry
from tests.test_retailrocket_session_knn import folder


class EntryTests(unittest.TestCase):
    def test_only_prepare_and_verify_flags(self):
        for flag in ('--run-validation','--run','--final-refit','--test','--reserved-test'):
            with self.subTest(flag=flag),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc: entry.parser().parse_args([flag])
                self.assertEqual(exc.exception.code,2)
        self.assertTrue(entry.parser().parse_args(['--prepare']).prepare)
        self.assertTrue(entry.parser().parse_args(['--verify']).verify)

    def test_partial_state_and_failure_not_completed(self):
        root=folder()
        self.assertEqual(entry.state(root/'absent'),'absent')
        self.assertEqual(entry.state(root),'partial')
        (root/'output_guard.json').write_text('{}',encoding='utf-8')
        self.assertEqual(entry.state(root),'complete')
        (root/'failure.json').write_text('{}',encoding='utf-8')
        self.assertEqual(entry.state(root),'partial')

    def test_each_resource_limit_stops(self):
        values={'RSS':1,'disk':1,'free_disk':entry.LIMITS['minimum_free_disk_bytes'],
                'available_memory':entry.LIMITS['minimum_available_memory_bytes'],'elapsed':0}
        entry.validate_measurements(values)
        for field,value in [('RSS',entry.LIMITS['maximum_process_RSS_bytes']+1),
                            ('disk',entry.LIMITS['maximum_execution_disk_bytes']+1),
                            ('free_disk',entry.LIMITS['minimum_free_disk_bytes']-1),
                            ('available_memory',entry.LIMITS['minimum_available_memory_bytes']-1),
                            ('elapsed',entry.LIMITS['maximum_elapsed_seconds']+1)]:
            with self.subTest(field=field):
                changed=dict(values);changed[field]=value
                with self.assertRaises(RuntimeError):entry.validate_measurements(changed)

    def test_resource_limits_cannot_be_changed(self):
        policy=entry.read(entry.frozen.POLICY);implementation=entry.read(entry.CONTRACT)
        entry.validate_policy(policy,implementation)
        policy['resources']['limits']['maximum_elapsed_seconds']=1
        with self.assertRaises(ValueError):entry.validate_policy(policy,implementation)

    def test_real_index_validation_final_test_all_disabled(self):
        policy=entry.read(entry.frozen.POLICY);original=entry.read(entry.CONTRACT)
        for key in ('real_validation_enabled','real_K1_index_build_enabled','final_refit_enabled','reserved_test_enabled'):
            changed=deepcopy(original);changed[key]=True
            with self.assertRaises(ValueError):entry.validate_policy(policy,changed)

    def test_guard_detects_mutation_and_no_overwrite(self):
        root=folder()
        entry.frozen.write_new(root,'file.json',{'x':1})
        record=entry.frozen.describe(root,'file.json')
        entry.frozen.check(root,record)
        with self.assertRaises(FileExistsError):entry.frozen.write_new(root,'file.json',{'x':2})
        (root/'file.json').write_text('{"x":2}',encoding='utf-8')
        with self.assertRaises(ValueError):entry.frozen.check(root,record)


if __name__=='__main__':unittest.main()
