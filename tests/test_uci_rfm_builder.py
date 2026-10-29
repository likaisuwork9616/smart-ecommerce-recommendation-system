"""Hand-counted RFM cases, future invariance, independent SQL parity and I/O guards."""
from copy import deepcopy
from pathlib import Path
import unittest
import uuid

from scripts import uci_rfm_builder as b
from scripts import uci_rfm_reference as r
from scripts import build_uci_rfm_v1 as run
from scripts import freeze_uci_rfm_contract as frozen

P=frozen.read_json(frozen.ROOT/frozen.POLICY)


def line(row=2,invoice='123456',q='2',price='1.25',customer='12345',ts='2010-06-01 12:00:00',stock='12345',country='United Kingdom',desc='item',sheet=b.SHEETS[0]):
    return (sheet,row,invoice,stock,desc,q,ts,price,customer,country)


def calculate(sources,window=None,arm=None):
    p=b.prepare(sources,window or P['windows'][0]);a=arm or P['arms'][0]
    rows,inv,cust,summary=b.decisions(p,a)
    pairs=list(rows());invoices=list(inv());customers=list(cust())
    return pairs,invoices,customers,summary(customers,invoices)


class BuilderTests(unittest.TestCase):
    def test_hand_counted_invoice_not_line_frequency(self):
        _,inv,cust,s=calculate([line(),line(row=3,stock='54321',q='3',price='0.001')])
        self.assertEqual(cust[0][10],1)
        self.assertEqual(cust[0][11],2503)
        self.assertEqual(cust[0][9],15768000)
        self.assertEqual(inv[0][10],2)

    def test_sub_penny_exactness(self):
        self.assertEqual(calculate([line(q='3',price='0.001')])[2][0][11],3)

    def test_start_included_T_excluded(self):
        _,_,customers,_=calculate([line(ts='2009-12-01 00:00:00'),line(row=3,invoice='123457',ts='2010-12-01 00:00:00',customer='54321')])
        self.assertEqual([c[0] for c in customers],['12345'])
        self.assertEqual(customers[0][9],31536000)

    def test_future_conflicting_rows_cannot_change_T1(self):
        initial=[line()]
        future=[line(row=3,ts='2010-12-01 00:00:00',customer='54321',country='France',price='9.99'),line(row=4,invoice='C123456',q='-2',ts='2011-01-01 00:00:00')]
        self.assertEqual(calculate(initial),calculate(initial+future))
        self.assertEqual(calculate(initial+future,P['windows'][1])[2][0][5],'inactive_with_quarantine')

    def test_time_conflict_masks_whole_customer_but_preserves_partial(self):
        data=[line(),line(row=3,ts='2010-06-02 12:00:00'),line(row=4,invoice='123457',price='2')]
        _,_,cust,_=calculate(data)
        self.assertEqual(cust[0][5],'active_with_quarantine')
        self.assertEqual(cust[0][9:12],[None,None,None])
        self.assertEqual(cust[0][14:16],[1,4000])

    def test_customer_conflict_links_both_keys(self):
        _,_,cust,_=calculate([line(),line(row=3,customer='54321')])
        self.assertEqual([c[5] for c in cust],['inactive_with_quarantine']*2)

    def test_mixed_known_missing_customer_quarantines_known(self):
        _,_,cust,_=calculate([line(),line(row=3,customer=None)])
        self.assertEqual(cust[0][5],'inactive_with_quarantine')

    def test_country_conflict_includes_missing(self):
        _,_,cust,_=calculate([line(),line(row=3,country=None)])
        self.assertEqual(cust[0][5],'inactive_with_quarantine')

    def test_consistently_missing_country_description_nonblocking(self):
        _,_,cust,_=calculate([line(country=None,desc=None)])
        self.assertEqual(cust[0][5],'active_complete')

    def test_unknown_customer_kept_only_in_row_ledger(self):
        rows,inv,cust,s=calculate([line(customer=None)])
        self.assertEqual(cust,[])
        self.assertEqual(rows[0][0][8],'unknown_customer')
        self.assertEqual(s['prefix_unknown_customer_rows'],1)

    def test_C_positive_and_negative_excluded_without_suffix_matching(self):
        _,_,cust,_=calculate([line(),line(row=3,invoice='C123456',q='-2'),line(row=4,invoice='c123457',customer='54321')])
        self.assertEqual(cust[0][11],2500)
        self.assertEqual(cust[1][5],'observed_no_eligible_history')

    def test_negative_purchase_quantity_quarantines_entire_invoice(self):
        _,_,cust,_=calculate([line(),line(row=3,q='-1',price='0')])
        self.assertEqual(cust[0][5],'inactive_with_quarantine')

    def test_negative_or_missing_price_not_silent_partial_total(self):
        for value in ['-1',None,'NaN']:
            _,_,cust,_=calculate([line(),line(row=3,price=value)])
            self.assertIsNone(cust[0][11])

    def test_missing_stock_quarantines_purchase(self):
        self.assertEqual(calculate([line(stock=None)])[2][0][5],'inactive_with_quarantine')

    def test_zero_price_does_not_add_activity_or_quarantine(self):
        _,inv,cust,_=calculate([line(price='0')])
        self.assertEqual(cust[0][5],'observed_no_eligible_history')
        self.assertEqual(cust[0][9:12],[None,0,0])
        self.assertEqual(inv[0][11],1)

    def test_free_and_paid_invoice_counted_once(self):
        _,_,cust,_=calculate([line(),line(row=3,price='0')])
        self.assertEqual(cust[0][10:12],[1,2500])

    def test_code_only_changes_money_and_can_give_zero_active(self):
        data=[line(stock='POST')]
        main=calculate(data)[2][0];other=calculate(data,arm=P['arms'][2])[2][0]
        self.assertEqual(other[5],'active_complete')
        self.assertEqual(other[9:11],main[9:11])
        self.assertEqual(other[11],0)

    def test_cross_sheet_multiplicity_is_max_not_sum(self):
        data=[line(row=2),line(row=3),line(row=4),line(row=2,sheet=b.SHEETS[1]),line(row=3,sheet=b.SHEETS[1])]
        self.assertEqual(calculate(data)[2][0][11],2500)
        self.assertEqual(calculate(data,arm=P['arms'][1])[2][0][11],7500)
        self.assertEqual(calculate(data,arm=P['arms'][1])[3]['duplicate_excess_rows'],2)

    def test_larger_second_sheet_is_selected(self):
        data=[line(),line(sheet=b.SHEETS[1]),line(row=3,sheet=b.SHEETS[1])]
        maps=[pair[1] for pair in calculate(data,arm=P['arms'][1])[0]]
        self.assertEqual([m[7] for m in maps],[False,True,True])
        self.assertTrue(all(m[5]==b.SHEETS[1] for m in maps))

    def test_nonidentical_same_stock_retained(self):
        self.assertEqual(calculate([line(),line(row=3,price='2')])[2][0][11],6500)

    def test_past_only_quarantine_does_not_mask_current_window(self):
        data=[line(ts='2010-01-01 00:00:00'),line(row=3,ts='2010-01-02 00:00:00'),line(row=4,invoice='123457',ts='2011-01-01 00:00:00')]
        self.assertEqual(calculate(data,P['windows'][1])[2][0][5],'active_complete')

    def test_history_customer_retained_clean_inactive(self):
        c=calculate([line()],P['windows'][1])[2][0]
        self.assertEqual(c[5],'inactive_complete')
        self.assertEqual(c[9:12],[None,0,0])

    def test_missing_invoice_rows_do_not_invent_one_shared_document(self):
        rows,inv,cust,_=calculate([line(invoice=None),line(row=3,invoice=None,customer='54321')])
        self.assertEqual(inv,[])
        self.assertEqual([c[8] for c in cust],[1,1])
        self.assertTrue(all(p[0][8]=='missing_invoice' for p in rows))

    def test_amount_overflow_and_extra_precision_stop(self):
        for row in [line(q=str(2**63)),line(price='0.0001'),line(q=str(2**62),price='2')]:
            with self.assertRaises((ValueError,OverflowError)):b.decode(row)

    def test_invalid_clock_and_customer_stop(self):
        for row in [line(ts='bad'),line(ts='2009-11-30 00:00:00'),line(ts='2010-01-01 00:00:00.100'),line(customer='1234')]:
            with self.assertRaises(ValueError):b.decode(row)

    def test_independent_SQL_all_arms_and_windows_full_ledger_parity(self):
        data=[line(),line(row=3),line(sheet=b.SHEETS[1]),line(row=4,invoice='123457',stock='POST',price='0.001'),
              line(row=5,invoice='C123456',q='-1'),line(row=6,invoice='123458',customer=None),
              line(row=7,invoice='123459',country=None),line(row=8,invoice='123459'),
              line(row=9,invoice=None,customer='54321'),line(row=10,invoice='123460',price='0'),
              line(row=11,invoice='123461',q='-1'),line(row=12,ts='2011-01-01 00:00:00'),
              line(row=13,invoice='A123456',price='-1'),line(row=14,invoice='123462',stock=None),
              line(row=15,invoice='123463',customer='54321',ts='2011-02-01 00:00:00')]
        db=r.database(':memory:');self.addCleanup(db.close);r.insert_sources(db,data)
        for w in P['windows']:
            ref=r.prepare(db,w)
            for a in P['arms']:
                expected_rows,expected_inv,expected_cust=r.expected(ref,a)
                pairs=list(expected_rows());invoices=list(expected_inv());customers=list(expected_cust())
                actual=calculate(data,w,a)
                self.assertEqual(actual[:3],(pairs,invoices,customers))

    def test_readback_catches_same_total_customer_swap(self):
        folder=frozen.within(frozen.ROOT,'shop-mysql-runtime/verification/uci-rfm-build-v1/synthetic/'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        path=folder/'test.csv'
        run.write_csv(path,['key','M'],[['12345',10],['54321',20]])
        with self.assertRaises(ValueError):run.compare_csv(path,['key','M'],[['12345',20],['54321',10]])

    def test_readback_catches_extra_row_and_schema(self):
        folder=frozen.within(frozen.ROOT,'shop-mysql-runtime/verification/uci-rfm-build-v1/synthetic/'+uuid.uuid4().hex)
        folder.mkdir(parents=True);path=folder/'test.csv';run.write_csv(path,['x'],[[1],[2]])
        with self.assertRaises(ValueError):run.compare_csv(path,['x'],[[1]])
        with self.assertRaises(ValueError):run.compare_csv(path,['other'],[[1],[2]])

    def test_csv_exclusive_create_and_null_zero_boolean(self):
        self.assertEqual([run.cell(v) for v in [None,0,False,True,[]]],['','0','false','true','[]'])
        folder=frozen.within(frozen.ROOT,'shop-mysql-runtime/verification/uci-rfm-build-v1/synthetic/'+uuid.uuid4().hex)
        folder.mkdir(parents=True);path=folder/'test.csv';run.write_csv(path,['x'],[[0]])
        with self.assertRaises(FileExistsError):run.write_csv(path,['x'],[[1]])

    def test_input_rows_unchanged(self):
        data=[line(),line(row=3)];before=deepcopy(data);calculate(data)
        self.assertEqual(data,before)


if __name__=='__main__':unittest.main()
