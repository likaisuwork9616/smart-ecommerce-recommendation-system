"""Inference must dispatch the saved handover contract with its geography."""
import unittest
from unittest.mock import patch

import pandas as pd

from scripts.delay_handover_features import FEATURE_SET
from scripts.predict_delay import build_inference_features


class HandoverInferenceTests(unittest.TestCase):
    def test_saved_feature_set_dispatches_raw_builder_with_geolocation(self):
        tables = {'orders': pd.DataFrame()}
        geo = pd.DataFrame({'geolocation_zip_code_prefix': ['00123']})
        expected = pd.DataFrame({'order_id': ['example']})
        with patch('scripts.delay_handover_features.build_handover_order_features', return_value=expected) as builder:
            result = build_inference_features({'feature_set': FEATURE_SET}, tables, geo)
        builder.assert_called_once_with(tables, geo)
        self.assertIs(result, expected)

    def test_unknown_handover_contract_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported feature set'):
            build_inference_features({'feature_set': FEATURE_SET + '_unknown'}, {})


if __name__ == '__main__':
    unittest.main()
