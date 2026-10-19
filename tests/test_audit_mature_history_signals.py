"""Integration guards for the read-only mature-history audit runner."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pandas as pd

from scripts import audit_mature_history_signals as audit
from scripts import delay_four_model_boundary as boundary
from tests.test_delay_history_features import tiny_tables
from tests.test_delay_mature_history_audit import queries, events, sellers
from tests.test_diagnose_age_colsample import four_fixture


def enriched_fixture():
    query = queries([('q','2018-02-01',20.,'RJ','SP')])
    event = events([('h','2018-01-01','2018-01-11',1,'RJ','SP')])
    enriched = audit.signals.build_signals(query,event,sellers(query,event))
    original = enriched.drop(columns=audit.signals.CANDIDATE_FEATURES+audit.signals.AUDIT_ONLY_FEATURES)
    return original,enriched


class MatureSignalRunnerTests(unittest.TestCase):
    def test_existing_values_and_other_original_columns_cannot_drift(self):
        before,after = enriched_fixture()
        self.assertEqual(audit.validate_cache(before,after),20)
        changed = after.copy()
        changed.loc[0,'route_completed_90d'] += 1
        with self.assertRaises(AssertionError):
            audit.validate_cache(before,changed)
        changed = after.copy()
        changed.loc[0,'estimated_delivery_days'] += 1
        with self.assertRaises(AssertionError):
            audit.validate_cache(before,changed)
        changed = after.copy()
        changed.index = [99]
        with self.assertRaises(ValueError):
            audit.validate_cache(before,changed)

    def test_maturity_population_excludes_post_may_before_feature_construction(self):
        tables = tiny_tables()
        mask = tables['orders'].order_id.eq('current')
        tables['orders'].loc[mask,'order_purchase_timestamp'] = pd.Timestamp('2018-05-01')
        tables['orders'].loc[mask,'order_approved_at'] = '2018-05-01 01:00'
        tables['orders'].loc[mask,'order_delivered_customer_date'] = '2018-05-05'
        tables['orders'].loc[mask,'order_estimated_delivery_date'] = '2018-05-10'
        build = audit.build_order_features
        with patch.object(audit,'load_olist_tables',return_value=tables), patch.object(audit,'build_order_features',wraps=build) as constructor:
            event,primary,quality = audit.mature_events(Path('unused'))
        selected = constructor.call_args.args[0]['orders']
        self.assertNotIn('current',set(selected.order_id))
        self.assertEqual(set(event.order_id),{'history'})
        self.assertEqual(quality['mature_eligible_delivery_events_before_may'],1)
        self.assertEqual(primary.loc[primary.order_id.eq('history'),'primary_seller_id'].iloc[0],'seller_a')

    def test_delivery_at_may_boundary_is_excluded_even_if_approval_is_earlier(self):
        tables = tiny_tables()
        tables['orders'].loc[tables['orders'].order_id.eq('current'),'order_delivered_customer_date'] = '2018-05-01 00:00'
        with patch.object(audit,'load_olist_tables',return_value=tables):
            event,_,quality = audit.mature_events(Path('unused'))
        self.assertEqual(set(event.order_id),{'history'})
        self.assertEqual(quality['legacy_eligible_but_delivered_at_or_after_may'],1)

    def test_common_misses_reconcile_by_identity_and_original_groups(self):
        frame,scores,known = four_fixture()
        public,private = boundary.diagnose_phase(frame,scores,known)
        common = np.isin(frame.order_id,list(private['common_missed']['overall:ALL']))
        common4 = {seed:common.copy() for seed in audit.frozen.SEEDS}
        preceding = {'persistent_misses':{'phase':{'groups':[
            {'kind':row['kind'],'key':row['key'],
             'known_delayed_rows':row['denominators']['positive_rows'],
             'all20_missed':row['common_missed_delays']} for row in public['groups']]}},
            'seed_phases':{str(seed):{'phase':public} for seed in audit.frozen.SEEDS}}
        self.assertGreater(audit.verify_common_counts(frame,known,common,common4,preceding,'phase'),10)
        changed = deepcopy(preceding)
        changed['persistent_misses']['phase']['groups'][0]['all20_missed'] += 1
        with self.assertRaises(ValueError):
            audit.verify_common_counts(frame,known,common,common4,changed,'phase')

    def test_public_output_cannot_replace_existing_report_or_write_into_data(self):
        path = audit.ROOT/'.runtime'/f'mature-audit-test-{uuid4().hex}.json'
        try:
            audit.fixed_json(path,{'actual':3})
            audit.fixed_json(path,{'actual':3})
            with self.assertRaises(ValueError):
                audit.fixed_json(path,{'actual':4})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'actual':3})
        finally:
            path.unlink(missing_ok=True)
        with self.assertRaises(ValueError):
            audit.fixed_json(audit.ROOT/'data'/'forbidden.json',{})

    def test_private_cache_must_be_an_ignored_csv_and_cannot_be_replaced(self):
        with self.assertRaises(ValueError):
            audit.write_private_cache(audit.ROOT/'reports'/'private.csv',pd.DataFrame({'a':[1]}))
        path = audit.ROOT/'data/processed'/f'mature-audit-test-{uuid4().hex}.csv'
        try:
            first = audit.write_private_cache(path,pd.DataFrame({'a':[1]}))
            self.assertEqual(first['rows'],1)
            self.assertEqual(audit.write_private_cache(path,pd.DataFrame({'a':[1]})),first)
            with self.assertRaises(ValueError):
                audit.write_private_cache(path,pd.DataFrame({'a':[2]}))
        finally:
            path.unlink(missing_ok=True)


if __name__=='__main__':
    unittest.main()
