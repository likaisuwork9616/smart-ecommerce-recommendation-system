"""Development entry scope, immutable evidence and path/phase guards."""
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from scripts import run_retailrocket_popularity_v1 as entry

ROOT=Path(__file__).resolve().parents[1]


def scratch():
    p=ROOT/'shop-mysql-runtime/verification/retailrocket-popularity-implementation-v1/entry-synthetic'/uuid.uuid4().hex
    p.mkdir(parents=True);return p


class EntryTests(unittest.TestCase):
    def test_development_flag_only(self):self.assertTrue(entry.parser().parse_args(['--run-development']).run_development)
    def test_reserved_test_flag_does_not_exist(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):entry.parser().parse_args(['--run-reserved-test'])
    def test_final_refit_flag_does_not_exist(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):entry.parser().parse_args(['--final-refit'])
    def test_prepare_and_run_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):entry.parser().parse_args(['--prepare','--run-development'])
    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):entry.within(scratch(),'../outside')
    def test_new_json_is_exclusive(self):
        root=scratch();entry.write_new(root,'proof.json',{'original':True})
        with self.assertRaises(FileExistsError):entry.write_new(root,'proof.json',{'original':False})
        self.assertEqual(json.loads((root/'proof.json').read_text(encoding='utf-8')),{'original':True})
    def test_source_hash_drift_stops(self):
        root=scratch();path=root/'value';path.write_bytes(b'original');bound=entry.descriptor(root,'value');path.write_bytes(b'changed')
        with self.assertRaises(ValueError):entry.check(root,[bound])
    def test_partial_directory_is_not_complete(self):
        root=scratch();self.assertEqual(entry.state(root/'dev'),'absent');(root/'dev').mkdir();self.assertEqual(entry.state(root/'dev'),'partial')
    def test_verify_cannot_mask_partial_development(self):
        root=scratch();(root/entry.DEV).mkdir(parents=True)
        with patch.object(entry,'ROOT',root),self.assertRaises(FileExistsError):entry.verify()
    def test_initial_gate_must_stay_locked(self):
        with self.assertRaises(ValueError):entry.require_locked({'status':'used','test_ranking_started':True,'logical_tests_consumed':1},scratch())
    def test_later_test_usage_prevents_new_development(self):
        root=scratch();(root/'test_usage.jsonl').write_text('{}\n',encoding='utf-8')
        with self.assertRaises(ValueError):entry.require_locked({'status':'locked_at_specification_freeze','test_ranking_started':False,'logical_tests_consumed':0},root)
    def test_later_refit_prevents_new_development(self):
        root=scratch();(root/'final_refit').mkdir()
        with self.assertRaises(ValueError):entry.require_locked({'status':'locked_at_specification_freeze','test_ranking_started':False,'logical_tests_consumed':0},root)
    def test_locked_empty_execution_namespace_allowed(self):
        entry.require_locked({'status':'locked_at_specification_freeze','test_ranking_started':False,'logical_tests_consumed':0},scratch())


if __name__=='__main__':unittest.main()
