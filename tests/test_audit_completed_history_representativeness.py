"""Input-clock and legacy reconstruction regression checks for the audit CLI."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import audit_completed_history_representativeness as runner


def fixture():
    rows=[('q','2018-02-10','2018-02-09','2018-05-15','2018-05-02','2018-02-20','delivered'),
          ('h','2018-01-01','2017-12-31','2018-01-05',None,'2018-01-10','canceled'),
          ('future','2018-05-10','2018-05-09',None,None,'2018-06-01','processing'),
          ('reversed','2018-01-06','2018-01-07',None,None,'2018-01-20','processing'),
          ('missing','2018-01-08',None,None,None,None,'unavailable')]
    orders=pd.DataFrame(rows,columns=['order_id','order_approved_at','order_purchase_timestamp',
        'order_delivered_customer_date','order_delivered_carrier_date','order_estimated_delivery_date','order_status'])
    orders['customer_id']='c'
    tables={'orders':orders,'order_items':pd.DataFrame({'order_id':orders.order_id,'order_item_id':1,'price':10.,'seller_id':'s'}),
            'customers':pd.DataFrame({'customer_id':['c'],'customer_state':['RJ']}),
            'sellers':pd.DataFrame({'seller_id':['s'],'seller_state':['SP']})}
    queries=pd.DataFrame({'order_id':['q'],'prediction_time':[pd.Timestamp('2018-02-10')],
                          'primary_seller_id':['s'],'state_route':['SP->RJ']})
    return tables,queries


class RepresentationRunnerTests(unittest.TestCase):
    def test_status_free_population_and_post_cutoff_censoring(self):
        tables,queries=fixture()
        before={name:value.copy(deep=True) for name,value in tables.items()}
        result,quality=runner.prepare_history(tables,queries)
        self.assertEqual(result.order_id.tolist(),['q','h'])
        self.assertEqual(result.legacy_eligible.tolist(),[True,False])
        self.assertTrue(pd.isna(result.loc[0,'delivery_time']))
        self.assertTrue(pd.isna(result.loc[0,'carrier_time']))
        self.assertEqual(quality['raw_pre_may_approval_rows'],4)
        self.assertEqual(quality['missing_purchase_rows_excluded'],1)
        self.assertEqual(quality['purchase_after_approval_rows_excluded'],1)
        for name in tables:
            pd.testing.assert_frame_equal(tables[name],before[name],check_exact=True)

    def test_final_status_changes_only_retrospective_quality(self):
        tables,queries=fixture()
        left,first=runner.prepare_history(tables,queries)
        tables['orders']['order_status']='unavailable'
        right,second=runner.prepare_history(tables,queries)
        pd.testing.assert_frame_equal(left,right,check_exact=True)
        self.assertNotEqual(first['final_status_retrospective_only'],second['final_status_retrospective_only'])

    def test_static_query_keys_and_clocks_cannot_silently_change(self):
        for name,value in (('prediction_time',pd.Timestamp('2018-02-11')),
                           ('primary_seller_id','other'),('state_route','SP->SC')):
            with self.subTest(name=name):
                tables,queries=fixture()
                queries.loc[0,name]=value
                with self.assertRaisesRegex(ValueError,'Frozen query raw'):
                    runner.prepare_history(tables,queries)

    def test_lookup_duplicates_are_rejected(self):
        tables,queries=fixture()
        tables['customers']=pd.concat([tables['customers'],tables['customers']],ignore_index=True)
        with self.assertRaisesRegex(ValueError,'lookup keys'):
            runner.prepare_history(tables,queries)

    def test_legacy_overdue_reconstruction_retains_negative_promise_difference(self):
        columns={}
        old={}
        for basis,col in (('seller90','seller_completed_90d'),('route90','route_completed_90d'),
                          ('joint90','audit_seller_route_completed_90d'),('route30','audit_route_completed_30d')):
            columns[f'audit_{basis}_legacy_delivery_window']=[12.,np.nan]
            old[col]=[12.,0.]
        for basis,suffix in (('seller90','seller'),('route90','route'),('route30','route')):
            window='30d' if basis=='route30' else '90d'
            columns[f'audit_{basis}_pending']=[5.,np.nan]
            columns[f'audit_{basis}_pending_overdue']=[2.,np.nan]
            columns[f'audit_{basis}_pending_negative_promise']=[1.,np.nan]
            old[f'{suffix}_pending_{window}']=[5.,0.]
            old[f'{suffix}_pending_overdue_{window}']=[3.,0.]
        audit,frame=pd.DataFrame(columns),pd.DataFrame(old)
        result=runner.verify_reconstruction(frame,audit)
        self.assertEqual(result['existing_counter_fields_reconstructed'],10)
        self.assertEqual(result['existing_counter_cells_verified'],20)
        broken=frame.copy()
        broken.loc[0,'seller_pending_overdue_90d']=2.
        with self.assertRaises(AssertionError):
            runner.verify_reconstruction(broken,audit)

    def test_six_metrics_only_compare_original101_numeric_white_list(self):
        values={}
        for basis in runner.profiles.COMPARISON_BASES:
            for name,data in (('approved',[2.,4.,0.]),('pending',[1.,3.,0.]),
                              ('pending_overdue',[0.,1.,0.]),('key_known',[1.,1.,1.])):
                values[f'audit_{basis}_{name}']=data
        frame=pd.DataFrame({'x':[.5,.75,np.nan],'y':[1.,0.,0.],
                            'delayed':[object(),object(),object()]})
        with patch.object(runner.preceding,'feature_names',return_value=(['x','y'],[])):
            result=runner.label_free_redundancy(frame,pd.DataFrame(values))
        self.assertEqual(result['original_numeric_feature_count'],2)
        self.assertEqual(len(result['audit_ratios']),6)
        for basis in runner.profiles.COMPARISON_BASES:
            row=result['audit_ratios'][f'{basis}.pending_share']
            self.assertEqual(row['exact_original101_duplicates'],['x'])
            self.assertEqual(row['finite_queries'],2)
            self.assertEqual({x['feature'] for x in row['top_absolute_spearman']},{'x','y'})


if __name__=='__main__':
    unittest.main()
