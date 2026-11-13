"""Seal a second load window while preserving the exact V47 protocol."""
from scripts import freeze_retailrocket_session_knn_cold_v47 as inherited
from scripts import run_retailrocket_session_knn_cold_v47 as previous
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


ROOT, read, describe = previous.ROOT, previous.read, previous.describe
BASE = 'reports/stage12/retailrocket_session_knn_v48_cold_'
SPEC = BASE + 'specification_20261113.json'
SEAL = BASE + 'seal_20261113.json'
METHOD = 'scripts/freeze_retailrocket_session_knn_cold_v48.py'
WINDOW_PREFIX = 'knn-v48-cold-real-'
BASELINE_SHA = '3ff9aa0eceb8e2ae79c02549953aad91f95fe8a3a3c9d5785a095b5d02a84ecd'
REQUIREMENTS = (*inherited.REQUIREMENTS, 'unchanged_repeat_protocol', 'isolated_repeat_window')
verify_original_reference = inherited.verify_original_reference


def specification_value():
    original = inherited.specification()
    baseline = describe(ROOT / previous.REPORT)
    if baseline['sha256'] != BASELINE_SHA:
        raise ValueError('Expected the sealed first V47 window')
    result = read(ROOT / previous.REPORT)
    if (result['specification'] != describe(ROOT / inherited.SPEC)
            or result['authority']['canonical'] != original['canonical']
            or result['schedule'] != original['schedule'] or result['arms'] != original['arms']):
        raise ValueError('First window differs from the inherited protocol')
    evidence = [describe(ROOT / name) for name in
                (inherited.SPEC, inherited.SEAL, previous.ACCEPTANCE, previous.ACCEPTANCE_SEAL, previous.REPORT)]
    return dict(original, status='v48_second_cold_window_frozen',
        predecessors=[*original['predecessors'], *evidence], namespace_prefix=WINDOW_PREFIX,
        requirements=list(REQUIREMENTS), repeat=dict(baseline=baseline,
            unchanged_fields=['cohort', 'dependencies', 'original_binding', 'canonical', 'arms', 'schedule',
                              'timing', 'scope', 'gates', 'environment', 'budget_seconds', 'limits'],
            assessment='Report each window, all signed pairs, regressions, order groups and entry totals. '
                       'Use existing system observations only; no causal decoder-retention percentage. '
                       'Adoption is an engineering assessment, not an automatic default change.'))


def seal_value():
    return dict(status='v48_second_cold_window_sealed', specification=describe(ROOT / SPEC),
                method=describe(ROOT / METHOD), real_runs=0)


def specification():
    value = read(ROOT / SPEC)
    if read(ROOT / SEAL) != seal_value() or value != specification_value():
        raise ValueError('Sealed V48 repeat protocol changed')
    return value


freeze = _clone(inherited.freeze, SPEC=SPEC, SEAL=SEAL, specification_value=specification_value,
                seal_value=seal_value)


if __name__ == '__main__':
    with previous.entry.exclusive():
        print(dict(status=freeze()['status'], real_runs=0))
