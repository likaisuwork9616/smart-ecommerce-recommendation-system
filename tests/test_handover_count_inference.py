"""Saved count-model contract dispatch, raw reconstruction and geographic CLI."""
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import delay_handover_count_training as training
from scripts import predict_delay
from scripts.delay_handover_features import build_handover_order_features
from tests.test_delay_budget_features import tiny_tables


class HandoverCountInferenceTests(unittest.TestCase):
    def test_saved_count_contract_dispatches_raw_builder_with_geolocation(self):
        tables = {'orders': pd.DataFrame()}
        geo = pd.DataFrame({'geolocation_zip_code_prefix': ['00123']})
        expected = pd.DataFrame({'order_id': ['example']})
        with patch.object(training, 'build_count_order_features', return_value=expected) as builder:
            actual = predict_delay.build_inference_features({'feature_set': training.FEATURE_SET}, tables, geo)
        builder.assert_called_once_with(tables, geo)
        self.assertIs(actual, expected)

    def test_unknown_count_contract_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported feature set'):
            predict_delay.build_inference_features({'feature_set': training.FEATURE_SET+'_unknown'}, {})

    def test_real_raw_builder_preserves_frozen_count_values_and_drops_duration_quantiles(self):
        tables = tiny_tables()
        tables['orders']['order_delivered_carrier_date'] = (
            pd.to_datetime(tables['orders'].order_approved_at) + pd.Timedelta(hours=6))
        tables['customers']['customer_zip_code_prefix'] = 1040
        tables['sellers']['seller_zip_code_prefix'] = 1040
        geo = pd.DataFrame({'geolocation_zip_code_prefix': [1040],
                            'geolocation_lat': [-23.], 'geolocation_lng': [-46.]})
        full = build_handover_order_features(tables, geo)
        numeric, categorical = training.feature_names(training.NEW_CANDIDATE)
        actual = predict_delay.build_inference_features({'feature_set': training.FEATURE_SET}, tables, geo)
        pd.testing.assert_frame_equal(actual, full[
            ['order_id', 'order_purchase_timestamp', 'prediction_time']+numeric+categorical])
        self.assertEqual(len(actual.columns), 105)
        self.assertNotIn('seller_handover_p50_hours_90d', actual)
        self.assertNotIn('seller_handover_p90_hours_90d', actual)
        with self.assertRaises(ValueError):
            training.build_count_order_features(tables)

    def test_raw_cli_loads_geolocation_for_count_contract(self):
        tables, geo = {}, pd.DataFrame({'geolocation_zip_code_prefix': [1040]})
        features = pd.DataFrame({'order_id': ['example'], 'order_purchase_timestamp': [pd.Timestamp('2018-01-01')],
                                 'prediction_time': [pd.Timestamp('2018-01-02')], 'estimated_delivery_days': [10.]})
        artifact = {'feature_set': training.FEATURE_SET, 'selected_model': training.NEW_CANDIDATE}
        predictions = pd.DataFrame({'order_id': ['example'], 'predicted_delayed': [0]})
        with patch('sys.argv', ['predict_delay', '--model', 'example.joblib', '--order-id', 'example']), \
                patch.object(predict_delay.joblib, 'load', return_value=artifact), \
                patch.object(predict_delay, 'load_olist_tables', return_value=tables), \
                patch.object(predict_delay.pd, 'read_csv', return_value=geo) as read_geo, \
                patch.object(predict_delay, 'build_inference_features', return_value=features) as build, \
                patch.object(predict_delay, 'predict_features', return_value=predictions), \
                patch('sys.stdout', new_callable=io.StringIO):
            predict_delay.main()
        build.assert_called_once_with(artifact, tables, geo)
        self.assertEqual(Path(read_geo.call_args.args[0]).name, 'olist_geolocation_dataset.csv')


if __name__ == '__main__':
    unittest.main()
