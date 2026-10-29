"""Source binding, exclusive lifecycle, gates and resource checks on artificial files."""
import contextlib
import io
import json
import unittest
from unittest.mock import Mock,patch

from scripts import run_retailrocket_session_knn_v1 as entry
from tests.test_retailrocket_session_knn_validation import make_fixture,binding,run_case


class EntryTests(unittest.TestCase):
    def test_only_three_modes_and_no_parameter_overrides(self):
        for flag in ('--prepare','--verify','--run-validation'):entry.parser().parse_args([flag])
        for args in ([],['--prepare','--run-validation'],['--test'],['--final-refit'],['--reserved-test'],
                     ['--run-validation','--k','10'],['--run-validation','--source','x'],['--retry']):
            with self.subTest(args=args),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                entry.parser().parse_args(args)

    def test_unprepared_real_entry_does_not_build(self):
        root,_,_=make_fixture()
        with patch.object(entry,'ROOT',root),patch.object(entry.adapter,'build') as build,self.assertRaises(ValueError):
            entry.run_validation()
        build.assert_not_called()

    def test_partial_run_never_replays(self):
        root,paths,config=make_fixture();folder=root/'execution';folder.mkdir()
        with patch.object(entry.adapter,'build') as build,self.assertRaises(FileExistsError):
            entry.execute_once(folder,paths,config,[],lambda:None)
        build.assert_not_called()

    def test_completed_run_only_checks_bytes(self):
        root,result=run_case()
        with patch.object(entry.adapter,'build') as build,patch.object(entry.oracle,'verify') as oracle:
            receipt=entry.execute_once(root/'execution',{},None,[],lambda:None)
        self.assertFalse(receipt['research_recomputed']);build.assert_not_called();oracle.assert_not_called()

    def test_changed_source_same_size_stops_before_build(self):
        root,paths,config=make_fixture();sources=binding(root);path=paths['C1']/'support.csv'
        content=path.read_text();path.write_text(content.replace(',1\n',',9\n',1),encoding='utf-8',newline='\n')
        with patch.object(entry.adapter,'build') as build,self.assertRaises(ValueError):
            entry.execute_once(root/'execution',paths,config,sources,lambda:None)
        build.assert_not_called();self.assertTrue((root/'execution/failure.json').exists())

    def test_failure_and_budget_stop_preserve_started_no_retry(self):
        root,paths,config=make_fixture();stop=Mock(side_effect=RuntimeError('budget exceeded'))
        with patch.object(entry.adapter,'build') as build,self.assertRaisesRegex(RuntimeError,'budget exceeded'):
            entry.execute_once(root/'execution',paths,config,binding(root),lambda:None,budget_factory=lambda _:stop)
        build.assert_not_called()
        self.assertTrue((root/'execution/started.json').exists());self.assertTrue((root/'execution/failure.json').exists())
        with self.assertRaises(FileExistsError):entry.execute_once(root/'execution',paths,config,[],lambda:None)

    def test_interruption_is_partial_not_complete(self):
        root,paths,config=make_fixture()
        with patch.object(entry.adapter,'build',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            entry.execute_once(root/'execution',paths,config,binding(root),lambda:None)
        self.assertEqual(entry.state(root/'execution'),'partial')

    def test_post_execution_input_mutation_cannot_publish(self):
        root,paths,config=make_fixture();actual=entry.adapter.build
        def altered(*args):
            result=actual(*args)
            with (root/'configuration.json').open('a',encoding='utf-8') as stream:stream.write(' ')
            return result
        publish=Mock()
        with patch.object(entry.adapter,'build',side_effect=altered),self.assertRaises(ValueError):
            entry.execute_once(root/'execution',paths,config,binding(root),lambda:None,publish=publish)
        publish.assert_not_called();self.assertFalse((root/'execution/output_guard.json').exists())

    def test_completed_output_tamper_rejected_without_replay(self):
        root,_=run_case();path=root/'execution/queries.jsonl'
        with path.open('a',encoding='utf-8') as stream:stream.write('{}\n')
        with patch.object(entry.adapter,'build') as build,self.assertRaises(ValueError):
            entry.execute_once(root/'execution',{},None,[],lambda:None)
        build.assert_not_called()

    def test_gate_failure_prevents_namespace_creation(self):
        root,paths,config=make_fixture();gate=Mock(side_effect=ValueError('test gate'))
        with self.assertRaises(ValueError):entry.execute_once(root/'execution',paths,config,[],gate)
        self.assertFalse((root/'execution').exists())

    def test_unexpected_completed_file_rejected(self):
        root,_=run_case();(root/'execution/extra.json').write_text('{}')
        with self.assertRaises(ValueError):entry.verify_run(root/'execution')

    def test_partial_preparation_not_overwritten(self):
        root,_,_=make_fixture();(root/entry.PRIVATE).mkdir(parents=True)
        with patch.object(entry,'ROOT',root),self.assertRaises(FileExistsError):entry.prepare()

    def test_configuration_is_metadata_only(self):
        original=entry.Path.open
        def limited(path,*args,**kwargs):
            if path.suffix in ('.csv','.jsonl'):raise AssertionError('Real row decoder used')
            return original(path,*args,**kwargs)
        with patch.object(entry.Path,'open',limited):config=entry.configuration()
        self.assertEqual(config['fixed_validation']['queries'],166897)
        self.assertEqual(set(config['control_fit_ids']),{'P0','C1','D1'})

    def test_preparation_blocks_real_semantic_open(self):
        with entry.synthetic_only_reads():
            for group,names in entry.INPUTS.items():
                for name in names:
                    if name.endswith(('.csv','.jsonl')):
                        with self.subTest(name=name),self.assertRaises(PermissionError):
                            entry.inside(entry.DIRECTORIES[group]+'/'+name).open('r',encoding='utf-8')

    def test_post_run_gate_failure_preserves_partial_evidence(self):
        root,paths,config=make_fixture();gate=Mock(side_effect=[None,ValueError('changed gate')])
        with self.assertRaisesRegex(ValueError,'changed gate'):
            entry.execute_once(root/'execution',paths,config,binding(root),gate)
        self.assertTrue((root/'execution/failure.json').exists())
        self.assertFalse((root/'execution/output_guard.json').exists())

    def test_limits_and_contract_changes_rejected(self):
        entry.validate_contract();original=entry.read
        def changed(name):
            value=original(name)
            if name==entry.CONTRACT:value['limits']['maximum_elapsed_seconds']=999
            return value
        with patch.object(entry,'read',changed),self.assertRaises(ValueError):entry.validate_contract()

    def test_failure_marker_overrides_complete_guard(self):
        root,_,_=make_fixture();(root/'output_guard.json').write_text('{}');(root/'failure.json').write_text('{}')
        self.assertEqual(entry.state(root),'partial')

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):entry.inside('../outside')


if __name__=='__main__':unittest.main()
