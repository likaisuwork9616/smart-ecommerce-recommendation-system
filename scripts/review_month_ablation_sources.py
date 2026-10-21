"""Prepare frozen month-ablation sources and complete control rosters; never fit."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from scripts import freeze_review_dataset as files
from scripts import freeze_review_month_ablation as method
from scripts import review_baseline_evaluation as evaluation
from scripts import review_baseline_pipeline as control_pipeline
from scripts import review_baseline_sources as baseline_sources
from scripts import review_month_ablation_pipeline as treatment_pipeline
from scripts import run_review_baseline as control_training

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PROOF = 'reports/stage5/review_month_ablation_pipeline_verification.json'
PINNED = {
    method.SPEC: '5ac404e3d66463a571d726f57f9af9d3774d30d7f3d90b4d4e86308f4c2ec9f1',
    method.REPORT: '995ab67ebd04d1e677c49c53d663f207782086db51d6d6abe28b38c92c97e094',
    PIPELINE_PROOF: 'a3adfc0f39777fa8c73df9c9bca2db400f751d7255797cdff7f52cfcd6bf012d',
}
CONTROL_SCORE_FILES = ('inner_scores.csv', 'outer_scores.csv')


@contextmanager
def forbid_model_execution():
    """Guard preparation against feature/model execution and metric selection."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    counters = {'forbidden_calls': 0}

    def forbidden(*args, **kwargs):
        counters['forbidden_calls'] += 1
        raise RuntimeError('Preparation forbids feature building, models, metrics and selection')

    with ExitStack() as stack:
        for module in (control_pipeline, treatment_pipeline):
            stack.enter_context(patch.object(module, 'build_primary_features', forbidden))
        classes = (
            (control_pipeline.GuardedReviewBaseline,
             ('__init__', 'fit_orders', 'transform_orders', 'predict_orders')),
            (treatment_pipeline.GuardedReviewMonthAblation,
             ('__init__', 'fit_orders', 'transform_orders', 'predict_orders')),
            (LogisticRegression, ('__init__', 'fit', 'predict', 'predict_proba')),
            (StandardScaler, ('__init__', 'fit', 'partial_fit', 'fit_transform', 'transform')),
            (OneHotEncoder, ('__init__', 'fit', 'fit_transform', 'transform')),
        )
        for cls, names in classes:
            for name in names:
                stack.enter_context(patch.object(cls, name, forbidden))
        for name in ('evaluate_role', 'select_candidate', 'macro_average_precision'):
            stack.enter_context(patch.object(evaluation, name, forbidden))
        for name in ('execute_training', '_execute_training'):
            stack.enter_context(patch.object(control_training, name, forbidden))
        yield counters
        # A caller cannot swallow a forbidden call and then report success.
        if counters['forbidden_calls']:
            raise RuntimeError('A forbidden execution was attempted during preparation')


def _verify_pipeline_proof(proof, method_spec):
    tests = proof['tests']
    modules = ['tests.test_review_baseline_pipeline', 'tests.test_review_month_ablation_pipeline']
    if (proof['status'] != 'passed_synthetic_month_ablation_pipeline_verification'
            or tests['modules'] != modules
            or tests['counts_by_module'] != dict(zip(modules, (32, 43)))
            or tests['tests_run'] != 75 or len(tests['test_ids']) != 75
            or len(set(tests['test_ids'])) != 75
            or any(tests[key] for key in ('failures', 'errors', 'skips',
                                         'expected_failures', 'unexpected_successes'))):
        raise ValueError('Frozen three-feature synthetic verification is incomplete')
    versions = method.baseline.software_versions()
    if proof['software_versions'] != versions or method_spec['software_versions_unchanged'] != versions:
        raise ValueError('Ablation pipeline and current software versions differ')
    implementation = proof['implementation']
    if (implementation['primary_order'] != ['purchase_dayofweek', 'purchase_hour', 'approval_wait_hours']
            or implementation['one_hot_columns'] != 31 or implementation['output_columns'] != 32
            or implementation['control_output_columns'] != 44
            or implementation['frozen_control_code_unchanged'] is not True):
        raise ValueError('Frozen three-feature verification structure differs')


def _frozen_provenance(root=ROOT):
    """Follow pinned receipts and guards without rerunning historical audits."""
    root = Path(root).resolve()
    parents = [files.descriptor(root / path, root) for path in PINNED]
    if any(item['sha256'] != PINNED[item['path']] for item in parents):
        raise ValueError('Frozen ablation method, audit or implementation proof changed')
    provenance = method.load_provenance(root)
    method_spec, method_source, _ = method.verify_specification(provenance, root)
    audit = files.read_json(root / method.REPORT)
    if (audit['status'] != 'passed_month_ablation_contract_metadata_only'
            or audit['specification'] != method_source
            or audit['sources'] != method_spec['sources']
            or audit['protocol'] != method_spec['protocol']
            or audit['allowed_protocol_changes'] != method_spec['allowed_protocol_changes']):
        raise ValueError('Frozen ablation metadata audit does not bind the method')
    proof = files.read_json(root / PIPELINE_PROOF)
    _verify_pipeline_proof(proof, method_spec)
    public = baseline_sources.merge_sources(method_spec['sources'], parents, proof['sources'])
    private = baseline_sources.merge_sources(provenance[4],
                                             [files.descriptor(root / method.GUARD, root)])
    if {item['path'] for item in public} & {item['path'] for item in private}:
        raise ValueError('Public and private source bindings overlap')
    files.verify_sources(public + private, root)
    return method_spec, public, private


@dataclass(frozen=True, slots=True)
class PreparedMonthAblationSources:
    """Defensive snapshots of complete roles and already frozen control scores."""

    _root: Path
    _base: baseline_sources.VerifiedReviewSources = field(repr=False)
    _method_spec: dict = field(repr=False)
    _control_report: dict = field(repr=False)
    _control_scores: dict = field(repr=False)
    _public_sources: tuple = field(repr=False)
    _private_sources: tuple = field(repr=False)
    _summary: dict = field(repr=False)

    @property
    def raw_orders(self):
        return self._base.raw_orders

    @property
    def membership(self):
        return self._base.membership

    @property
    def context(self):
        return self._base.context

    @property
    def method_spec(self):
        return deepcopy(self._method_spec)

    @property
    def control_report(self):
        return deepcopy(self._control_report)

    @property
    def control_scores(self):
        return {name: frame.copy(deep=True) for name, frame in self._control_scores.items()}

    @property
    def public_sources(self):
        return deepcopy(list(self._public_sources))

    @property
    def private_sources(self):
        return deepcopy(list(self._private_sources))

    @property
    def summary(self):
        return deepcopy(self._summary)

    def role_block(self, fold, role, *, labelled=True):
        return self._base.role_block(fold, role, labelled=labelled)

    def prediction_block(self, fold, role):
        return self._base.prediction_block(fold, role)

    def verify_stable(self):
        bound = list(self._public_sources) + list(self._private_sources)
        files.verify_sources(bound, self._root)
        return {'public_bound_files': len(self._public_sources),
                'private_bound_files': len(self._private_sources), 'unchanged': True}


def load_prepared_sources(root=ROOT):
    """Validate full H60 roles and existing score metadata under a no-fit guard."""
    from scripts import review_month_ablation_pairing as pairing
    root = Path(root).resolve()
    with forbid_model_execution() as counters:
        method_spec, public, private = _frozen_provenance(root)
        base = baseline_sources.load_verified_sources(root)
        public = baseline_sources.merge_sources(public, base.public_sources)
        private = baseline_sources.merge_sources(private, base.private_sources)
        if {item['path'] for item in public} & {item['path'] for item in private}:
            raise ValueError('Public and private source bindings overlap')
        bound = public + private
        files.verify_sources(bound, root)
        report = files.read_json(root / control_training.REPORT)
        if report['status'] != 'completed_real_offline_minimal_baseline':
            raise ValueError('Frozen control training report did not complete')
        score_paths = [control_training.PRIVATE + '/' + name for name in CONTROL_SCORE_FILES]
        if not set(score_paths).issubset({item['path'] for item in private}):
            raise ValueError('Frozen control score files lack private source bindings')
        scores = {name: control_training.read_score_csv((root / path).read_bytes())
                  for name, path in zip(CONTROL_SCORE_FILES, score_paths)}
        score_summary = pairing.validate_frozen_control(
            base, report, scores['inner_scores.csv'], scores['outer_scores.csv'])
        files.verify_sources(bound, root)
        summary = {'source_bundle': base.summary,
                   'frozen_control': score_summary,
                   'future_query_fields_masked': list(baseline_sources.FUTURE_QUERY_COLUMNS),
                   'training_authorized_this_run': False,
                   'historical_ingestion_verified': False,
                   'feature_builds': 0, 'model_instantiations': 0, 'model_fits': 0,
                   'transforms': 0, 'predictions': 0, 'metrics_computed': 0,
                   'candidate_selections': 0, 'forbidden_execution_attempts': counters['forbidden_calls']}
        prepared = PreparedMonthAblationSources(
            root, base, deepcopy(method_spec), deepcopy(report),
            {name: frame.copy(deep=True) for name, frame in scores.items()},
            tuple(deepcopy(public)), tuple(deepcopy(private)), summary)
        prepared.verify_stable()
        return prepared
