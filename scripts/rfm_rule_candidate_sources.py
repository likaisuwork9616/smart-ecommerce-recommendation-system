"""Frozen G2 input provenance and complete source-ID/G1 readback wiring.

Preparation calls only ``metadata_snapshot`` (JSON metadata and binary hashes).
``read_inputs`` is a future execution operation, exercised on synthetic inputs
only in this preparation round; it never rebuilds RFM or reruns the G1 core.
"""
from __future__ import annotations

from pathlib import Path

from scripts import verify_rfm_rule_candidate as prior

base, artifacts, same = prior.base, prior.typed, prior.same
description_entry = prior.prior
description_sources = description_entry.sources
description_outputs = description_entry.outputs
ROOT = Path(__file__).resolve().parents[1]


def _require(condition, message):
    if condition is not True:
        raise ValueError(message)


def metadata_snapshot(root=ROOT):
    """Bind all 51 prior public sources and complete private provenance.

    The synthetic implementation must already exist and verify unchanged.  This
    calls no prior ``run`` action, CSV parser, individual reader or core; private
    fingerprints in this returned object are for private guards only.
    """
    root = Path(root)
    before = prior._prior_snapshot(root)
    prior._check_existing(root, before)
    bindings = [*before['source_bindings'], *[
        base.descriptor(root / relative, root) for relative in (prior.SPEC, prior.OUTPUT)]]
    _require(len(bindings) == 51 and len({item['path'] for item in bindings}) == 51,
             'Complete fifty-one prior public source bindings required')
    inherited = before['private_provenance']
    old_snapshot = inherited['prepared_state']['input_snapshot']
    snapshot = {
        'format_version': 1,
        'public_sources': bindings,
        'private_inputs': {
            'implementation_input_guard': base.descriptor(root / prior.GUARD, root),
            'implementation_test_log': base.descriptor(root / prior.LOG, root),
            'prior_G0_G1_provenance': inherited,
        },
        'accepted_rows': old_snapshot['accepted_rows'],
        'metadata_checks': before['metadata_checks'],
        'description_input_snapshot': old_snapshot,
        'G1_readback_acceptance': inherited['completed_guard']['readback_acceptance'],
    }
    after = prior._prior_snapshot(root)
    _require(same(before, after), 'Prior sources changed during G2 input snapshot')
    prior._check_existing(root, after)
    return snapshot


def read_inputs(root, expected_snapshot):
    """Future load: full source-derived rosters plus accepted G1 typed readback.

    The independent customer universe, all pre-T orders, window order IDs and
    every order mapping/event proof come from the original frozen source loader.
    G1's existing four files and public aggregate are verified using that already
    loaded dataset, without rerunning its core or loading the RFM bundle twice.
    """
    root = Path(root)
    before = metadata_snapshot(root)
    _require(same(before, expected_snapshot), 'Frozen G2 input snapshot differs before parsing')
    data = description_sources.read_inputs(root, before['description_input_snapshot'])
    _require(same({'customers.csv': len(data['dataset']['customers']),
                   'order_decisions.csv': len(data['dataset']['orders'])}, before['accepted_rows']),
             'Accepted G2 dataset row counts differ')
    provenance = {
        'execution_specification': base.descriptor(root / description_entry.SPEC, root),
        'source_bindings': base.read_json(root / description_entry.SPEC)['sources'],
    }
    completed_guard = before['private_inputs']['prior_G0_G1_provenance']['completed_guard']
    public = base.read_json(root / description_entry.PUBLIC)
    receipt = description_outputs.verify_outputs(
        root / description_entry.DATASET, data, public['description'], provenance,
        expected_guard=completed_guard['private_bundle_guard'])
    expected_public = description_outputs.public_report(public['description'], provenance, receipt)
    _require(same(receipt, before['G1_readback_acceptance'])
             and same(receipt, completed_guard['readback_acceptance'])
             and (root / description_entry.PUBLIC).read_bytes() == artifacts.json_bytes(expected_public),
             'Existing G1 full readback or public aggregate differs')
    gates = public['description']['gate_status']
    _require(gates['G0'] == 'passed' and gates['G1'] == 'ready_for_aggregate_review'
             and gates['G2'] == gates['G3'] == 'not_executed',
             'Existing G1 review preconditions differ')
    after = metadata_snapshot(root)
    _require(same(before, after), 'Frozen G2 inputs changed during source/G1 readback')
    return {
        'dataset': data['dataset'], 'evaluation_spec': data['evaluation_spec'],
        'customer_ids': data['customer_ids'], 'order_ids': data['order_ids'],
        'window_order_ids': data['window_order_ids'], 'snapshot': after,
        'g1_accepted': True, 'g1_readback_acceptance': receipt,
    }
