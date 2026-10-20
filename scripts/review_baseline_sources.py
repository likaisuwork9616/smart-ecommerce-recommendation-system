"""Load the frozen review sources and guarded role inputs without fitting."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

try:
    from scripts import audit_review_baseline_contract as baseline
    from scripts import freeze_review_dataset as dataset
    from scripts import review_baseline_pipeline as pipeline
except ModuleNotFoundError:
    import audit_review_baseline_contract as baseline
    import freeze_review_dataset as dataset
    import review_baseline_pipeline as pipeline

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PROOF = 'reports/stage5/review_pipeline_verification.json'
PARENT_SHAS = {
    baseline.SPEC: '202de6045b7dcee7b00c068670fff44b5cac813a838d3d5ad15d620e18e721aa',
    baseline.REPORT: '204c8d2b09327848fe9367e75efae5b37093a39164ccdb4b69f34ef396e4c16a',
    PIPELINE_PROOF: '75e62c8c2862b5e0c9af505a165209610375ecba5bcaee7ca71e07481161e050',
}
ROLES = ('inner_train_pool', 'inner_validation', 'outer_train_pool', 'outer_evaluation')
QUERY_ROLES = ('inner_validation', 'outer_evaluation')
FUTURE_QUERY_COLUMNS = ('window_deadline', 'observation_cutoff', 'horizon_complete',
                        'label_state', 'role_label_usable', 'y', 'first_visible_answer_at')


def merge_sources(*groups):
    """Deduplicate exact descriptors, rejecting conflicting claims for one path."""
    result = {}
    for group in groups:
        for item in group:
            entry = {key: item[key] for key in ('path', 'bytes', 'sha256')}
            path = entry['path']
            if path in result and result[path] != entry:
                raise ValueError('Conflicting frozen source descriptor: ' + path)
            result[path] = entry
    return [result[path] for path in sorted(result)]


def _frozen_provenance(root):
    """Follow existing public/private guards, without rerunning an old audit."""
    root = Path(root).resolve()
    parents = [dataset.descriptor(root / path, root) for path in PARENT_SHAS]
    for item in parents:
        if item['sha256'] != PARENT_SHAS[item['path']]:
            raise ValueError('Frozen review ancestor changed: ' + item['path'])
    spec = dataset.read_json(root / baseline.SPEC)
    audit = dataset.read_json(root / baseline.REPORT)
    spec_source, guard = baseline.verify_contract(
        spec, root / baseline.SPEC, root / baseline.GUARD, root)
    if audit['specification'] != spec_source or audit['protocol'] != spec['protocol']:
        raise ValueError('Frozen baseline audit does not bind the baseline specification')
    if audit['status'] != 'passed_baseline_contract_metadata_only':
        raise ValueError('Frozen baseline metadata audit did not pass')
    proof = dataset.read_json(root / PIPELINE_PROOF)
    tests = proof['tests']
    if (proof['status'] != 'passed_synthetic_pipeline_contract_verification'
            or tests['tests_run'] <= 0 or len(tests['test_ids']) != tests['tests_run']
            or len(set(tests['test_ids'])) != tests['tests_run']
            or any(tests[key] for key in ('failures', 'errors', 'skips',
                                         'expected_failures', 'unexpected_successes'))):
        raise ValueError('Frozen synthetic pipeline verification did not fully pass')
    if (proof['software_versions'] != baseline.software_versions()
            or proof['software_versions'] != spec['software_versions']):
        raise ValueError('Frozen pipeline and baseline software versions differ')
    public = merge_sources(spec['sources'], parents, proof['sources'])
    private = merge_sources(guard['private_inputs'],
                            [dataset.descriptor(root / baseline.GUARD, root)])
    if {item['path'] for item in public} & {item['path'] for item in private}:
        raise ValueError('Public and private source bindings overlap')
    dataset.verify_sources(public + private, root)
    oldspec = dataset.read_json(root / dataset.SPEC)
    oldaudit = dataset.read_json(root / dataset.REPORT)
    return spec, oldspec, oldaudit, public, private


def _validate_loaded_frames(raw_orders, labels, membership, oldspec, oldaudit):
    """Audit complete denominators, role masks, and event-proxy label cutoffs."""
    if list(raw_orders.columns) != list(pipeline.RAW_COLUMNS):
        raise ValueError('Only raw IDs and purchase/approval clocks may be loaded')
    if (len(raw_orders) != oldaudit['order_quality']['source_orders']
            or len(labels) != oldspec['expected_existing_cohort_orders']):
        raise ValueError('Frozen raw or global label denominator changed')
    roster = baseline.raw_clock_roster(raw_orders)
    if len(roster) != oldspec['expected_existing_cohort_orders']:
        raise ValueError('Raw primary cohort differs from the frozen H60 cohort')
    global_metadata, folds = baseline.metadata_audit(roster, labels, membership, oldaudit)
    if len(folds) != 3 or sum(len(fold['roles']) for fold in folds) != 12:
        raise ValueError('Expected all three folds and twelve complete role blocks')
    if list(oldspec['calendar_split_plan']) != [fold['calendar'] for fold in folds]:
        raise ValueError('Frozen dataset calendar changed')
    if any(fold['support'] != 'supported_for_future_offline_baseline_only' for fold in folds):
        raise ValueError('A required training or inner-validation class is missing')
    expected_roster = roster[['order_id', 'prediction_time']].copy()
    context = pipeline.ApprovalRosterContext(
        expected_roster, context_version='stage5-h60-' + baseline.OLD_SPEC_SHA)
    summary = {'raw_order_rows': len(raw_orders), 'cohort_order_rows': len(roster),
               'membership_rows': len(membership), 'folds': len(folds), 'role_blocks': 12,
               'global_known_labels': global_metadata['usable_labels'],
               'global_unknown_labels': global_metadata['unknown_or_ineligible_labels'],
               'required_both_class_contexts': 9,
               'scope': 'source_and_label_metadata_checks_only_no_feature_or_model_fit',
               'historical_ingestion_verified': False}
    return context, summary


@dataclass(frozen=True, slots=True)
class VerifiedReviewSources:
    """Verified snapshots; frame/descriptor properties return defensive copies."""

    _root: Path
    _raw_orders: pd.DataFrame = field(repr=False)
    _membership: pd.DataFrame = field(repr=False)
    context: pipeline.ApprovalRosterContext = field(repr=False)
    _public_sources: tuple = field(repr=False)
    _private_sources: tuple = field(repr=False)
    _baseline_spec: dict = field(repr=False)
    _dataset_audit: dict = field(repr=False)
    _summary: dict = field(repr=False)

    @property
    def raw_orders(self):
        return self._raw_orders.copy(deep=True)

    @property
    def membership(self):
        return self._membership.copy(deep=True)

    @property
    def public_sources(self):
        return deepcopy(list(self._public_sources))

    @property
    def private_sources(self):
        return deepcopy(list(self._private_sources))

    @property
    def baseline_spec(self):
        return deepcopy(self._baseline_spec)

    @property
    def dataset_audit(self):
        return deepcopy(self._dataset_audit)

    @property
    def summary(self):
        return deepcopy(self._summary)

    def verify_stable(self):
        dataset.verify_sources(list(self._public_sources) + list(self._private_sources), self._root)
        return {'public_bound_files': len(self._public_sources),
                'private_bound_files': len(self._private_sources), 'unchanged': True}

    def role_block(self, fold, role, *, labelled=True):
        if fold not in pipeline.INNER_MONTHS or role not in ROLES:
            raise ValueError('Requested fold or role is outside the frozen calendar')
        block = self._membership.loc[(self._membership.outer_fold == fold)
                                     & (self._membership.role == role)].copy(deep=True)
        if block.empty:
            raise ValueError('Frozen role is missing or empty')
        block = block.reset_index(drop=True)
        if not labelled:
            for name in FUTURE_QUERY_COLUMNS:
                block[name] = pd.NA
        return block

    def prediction_block(self, fold, role):
        if role not in QUERY_ROLES:
            raise ValueError('Only a frozen query role can provide prediction inputs')
        return self.role_block(fold, role, labelled=False)


def load_verified_sources(root=ROOT):
    """Read frozen clock/label snapshots, verify before/after, and never fit."""
    root = Path(root).resolve()
    spec, oldspec, oldaudit, public, private = _frozen_provenance(root)
    dataset.verify_sources(public + private, root)
    raw = pd.read_csv(root / dataset.ORDERS, usecols=list(pipeline.RAW_COLUMNS), dtype='string')
    raw = raw.loc[:, list(pipeline.RAW_COLUMNS)]
    labels = dataset.read_private_csv((root / dataset.PRIVATE / 'order_labels.csv').read_bytes(),
                                      dataset.LABEL_COLUMNS)
    membership = dataset.read_private_csv((root / dataset.PRIVATE / 'split_membership.csv').read_bytes(),
                                          dataset.MEMBERSHIP_COLUMNS)
    context, summary = _validate_loaded_frames(raw, labels, membership, oldspec, oldaudit)
    dataset.verify_sources(public + private, root)
    bundle = VerifiedReviewSources(root, raw.copy(deep=True), membership.copy(deep=True), context,
                                   tuple(deepcopy(public)), tuple(deepcopy(private)),
                                   deepcopy(spec), deepcopy(oldaudit), summary)
    bundle.verify_stable()
    return bundle
