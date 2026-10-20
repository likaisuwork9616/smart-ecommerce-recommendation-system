"""Small leakage, censoring, key and source-immutability contract examples."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts import audit_review_prediction_feasibility as audit


def cohort():
    data = {'order_id': ['one'], 'customer_id': ['customer'], 'order_status': ['canceled'],
            'order_purchase_timestamp': ['2018-01-01 00:00:00'],
            'order_approved_at': ['2018-01-02 00:00:00'],
            'order_delivered_carrier_date': [None], 'order_delivered_customer_date': [None],
            'order_estimated_delivery_date': ['2018-01-08 00:00:00']}
    return audit.approval_cohort(pd.DataFrame(data))[0]


def reviews(answers=('2018-01-03 00:00:00',), scores=('1',)):
    return pd.DataFrame({'review_id': [f'review-{i}' for i in range(len(answers))],
                         'order_id': ['one'] * len(answers), 'review_score': scores,
                         'review_creation_date': ['2018-01-02 00:00:00'] * len(answers),
                         'review_answer_timestamp': answers})


def states(data):
    return audit.first_answer_profile(cohort(), data)[2]


class ReviewFeasibilityTest(unittest.TestCase):
    def test_no_review_unknown_not_negative(self):
        summary = states(reviews().iloc[:0])
        self.assertEqual(summary['exclusive_label_states'], {'no_review': 1})
        self.assertEqual(summary['descriptive_low_1_2'], 0)
        self.assertFalse(summary['no_review_is_negative'])

    def test_earliest_answer_chosen_before_t_no_late_repick(self):
        data = reviews(('2018-01-01 20:00:00', '2018-01-04 00:00:00'), ('5', '1'))
        data.loc[0, 'review_creation_date'] = '2018-01-01 00:00:00'
        self.assertEqual(states(data)['exclusive_label_states'], {'first_answer_not_after_approval': 1})

    def test_equal_approval_answer_excluded(self):
        self.assertEqual(states(reviews(('2018-01-02 00:00:00',)))['exclusive_label_states'],
                         {'first_answer_not_after_approval': 1})

    def test_conflicting_earliest_tie_quarantined(self):
        data = reviews(('2018-01-03 00:00:00',) * 2, ('1', '5'))
        self.assertEqual(states(data)['exclusive_label_states'], {'ambiguous_first_answer_tie': 1})

    def test_missing_answer_anywhere_blocks_entire_order(self):
        data = reviews(('2018-01-03 00:00:00', None), ('1', '5'))
        self.assertEqual(states(data)['exclusive_label_states'], {'missing_answer_prevents_first': 1})

    def test_later_invalid_score_cannot_be_silently_dropped(self):
        data = reviews(('2018-01-03 00:00:00', '2018-01-04 00:00:00'), ('1', 'invalid'))
        self.assertEqual(states(data)['exclusive_label_states'], {'invalid_review_score': 1})

    def test_missing_creation_and_reversed_creation_block(self):
        for value, state in ((None, 'invalid_review_creation_clock'),
                             ('2018-01-05 00:00:00', 'review_creation_after_its_answer')):
            with self.subTest(value=value):
                data = reviews()
                data.loc[0, 'review_creation_date'] = value
                self.assertEqual(states(data)['exclusive_label_states'], {state: 1})

    def test_review_id_reuse_across_orders_allowed_pair_duplicate_blocked(self):
        data = reviews()
        other = data.assign(order_id='another')
        self.assertEqual(states(pd.concat([data, other]))['descriptive_low_1_2'], 1)
        self.assertEqual(states(pd.concat([data, data]))['exclusive_label_states'],
                         {'duplicate_or_missing_review_key': 1})

    def test_target_ordinal_values_and_inputs_unchanged(self):
        data = reviews(scores=('5',))
        original = deepcopy(data)
        self.assertEqual(states(data)['descriptive_other_3_5'], 1)
        pd.testing.assert_frame_equal(data, original)

    def test_history_requires_answer_strictly_before_fit(self):
        data = reviews(('2018-02-01 00:00:00',))
        joined, *_ = audit.first_answer_profile(cohort(), data)
        support = audit.temporal_support(joined)
        self.assertEqual(support[1]['historical_label_event_before_fit'], 0)
        self.assertEqual(support[1]['historical_future_label_not_yet_before_fit'], 1)
        self.assertEqual(support[2]['historical_label_event_before_fit'], 1)

    def test_canceled_status_retained_and_may_cutoff_exclusive(self):
        data = cohort()
        result, _ = audit.approval_cohort(data)
        self.assertEqual(len(result), 1)
        data.loc[0, 'order_approved_at'] = pd.Timestamp('2018-05-01')
        self.assertEqual(len(audit.approval_cohort(data)[0]), 0)

    def test_source_mutation_and_immutable_json_fail_closed(self):
        runtime = audit.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            root = Path(directory)
            source = root / 'source'
            source.write_bytes(b'first')
            bound = audit.descriptor(source, root)
            self.assertEqual(audit.verify_sources([bound], root), 1)
            source.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                audit.verify_sources([bound], root)
            output = root / 'output.json'
            audit.immutable_write(output, {'count': 1})
            before = output.read_bytes()
            audit.immutable_write(output, {'count': 1})
            self.assertEqual(before, output.read_bytes())
            with self.assertRaises(ValueError):
                audit.immutable_write(output, {'count': 2})


if __name__ == '__main__':
    unittest.main()
