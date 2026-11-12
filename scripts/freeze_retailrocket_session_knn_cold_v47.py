"""Bind the original fixed48 inputs and the V46 decoder evidence."""
from scripts import compare_retailrocket_session_knn_string_v46 as decoder
from scripts import retailrocket_session_knn_cold_v47 as cold
from scripts import run_retailrocket_session_knn_compare_v41 as prior


ROOT, describe, read = prior.ROOT, prior.describe, prior.read
BASE = 'reports/stage12/retailrocket_session_knn_v47_cold_'
SPEC = BASE + 'specification_20261112.json'
SEAL = BASE + 'seal_20261112.json'
METHOD = 'scripts/freeze_retailrocket_session_knn_cold_v47.py'
WINDOW_PREFIX = 'knn-v47-cold-real-'
V41_SHA = '3912ac1ffb443a14c52da75b4dd9e51fd828429424c860ba81e40a0adb119647'
V46_SHA = 'ed5fd6adb4a11eab95a07eb547eb3519f7f548dc856151570d54ec9c5ccbe3a2'
REQUIREMENTS = ('decoder_worker_isolation', 'all_cold_fixed48_output_and_proof', 'stopped_release', 'cost_accounting')
verify_original_reference = prior.frozen.verify_original_reference


def specification_value():
    original = prior.frozen.specification()
    v41, v46 = (describe(ROOT / path) for path in (prior.REPORT, decoder.REPORT))
    if v41['sha256'] != V41_SHA or v46['sha256'] != V46_SHA:
        raise ValueError('Expected original V41 and V46 reports')
    authority = read(ROOT / prior.REPORT)['typed_validation']['authority']
    evidence = read(ROOT / decoder.REPORT)['evidence']
    if (authority['raw_sources']['model'] != evidence['V45_inputs']['V44_inputs']['V43']['raw_model']
            or authority['canonical']['model'] != evidence['V45_inputs']['V44_inputs']['V43']['model']
            or describe(ROOT / 'scripts/retailrocket_session_knn_typed_string_v46.py') not in evidence['methods']):
        raise ValueError('Expected the same model and tested V46 decoder')
    fields = ('cohort', 'dependencies', 'original_binding', 'reference', 'scope', 'gates', 'environment',
              'budget_seconds', 'limits', 'fingerprint_scheme', 'typed_reference_policy', 'typed_reference_scheme')
    return dict({key: original[key] for key in fields}, status='v47_fresh_context_comparison_frozen',
        predecessors=[v41, v46], canonical=authority['canonical'], arms=cold.ARMS, schedule=cold.SCHEDULE,
        namespace_prefix=WINDOW_PREFIX, requirements=list(REQUIREMENTS), real_runs=0,
        timing=dict(entry='Fixed48 V39 full entry with a fresh pool and fresh ledger for every scheduled run.',
                    reference='Original V39 passive two-root build interval inside each cold entry.',
                    decode='Matched model-only no-sampling replays after the cold entries.',
                    comparison='Two warmups then six alternating formal pairs. Aggregate by paired signed differences.'))


def seal_value():
    return dict(status='v47_fresh_context_comparison_sealed', specification=describe(ROOT / SPEC),
                method=describe(ROOT / METHOD), real_runs=0)


def specification():
    value = read(ROOT / SPEC)
    if read(ROOT / SEAL) != seal_value() or value != specification_value():
        raise ValueError('Sealed V47 protocol changed')
    return value


def freeze():
    if any((ROOT / path).exists() for path in (SPEC, SEAL)):
        raise FileExistsError('Immutable V47 specification already exists')
    value = specification_value()
    verify_original_reference(value)
    prior.public_json(ROOT / SPEC, value, exclusive=True)
    prior.public_json(ROOT / SEAL, seal_value(), exclusive=True)
    return value


if __name__ == '__main__':
    with prior.entry.exclusive():
        print(dict(status=freeze()['status'], real_runs=0))
