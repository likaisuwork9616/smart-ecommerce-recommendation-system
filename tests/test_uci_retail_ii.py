"""Hand-counted intake fixtures; no real customer IDs or performance claims."""
from datetime import datetime
from decimal import Decimal
import unittest
from scripts import audit_uci_retail_ii as audit


def line(invoice='123456',stock='12345',quantity=2,price=1.25,customer=12345,
         date=datetime(2010,6,1),description='item',country='United Kingdom'):
    return [invoice,stock,description,quantity,date,price,customer,country]


class IntakeTests(unittest.TestCase):
    def database(self, entries):
        db=audit.connect();self.addCleanup(db.close);audit.schema(db)
        audit.insert(db,[audit.record(sheet,i+2,row) for i,(sheet,row) in enumerate(entries)])
        audit.build_views(db)
        return db

    def test_repeated_invoice_is_not_duplicate_line(self):
        db=self.database([('A',line()),('A',line(stock='54321'))])
        self.assertEqual(audit.duplicate_stats(db)['duplicate_excess_rows'],0)
        self.assertEqual(audit.counts(db)['invoices'],1)

    def test_exact_duplicate_excess_not_all_members(self):
        db=self.database([('A',line())]*3)
        self.assertEqual(audit.duplicate_stats(db)['duplicate_excess_rows'],2)
        self.assertEqual(audit.counts(db,'unique_rows')['rows'],1)

    def test_cross_sheet_overlap_separate_from_within_sheet(self):
        db=self.database([('A',line()),('A',line()),('B',line())])
        result=audit.analyze(db)['duplicates']
        self.assertEqual(result['within_sheet_duplicate_excess'],1)
        self.assertEqual(result['cross_sheet_duplicate_excess_after_within_sheet_dedup'],1)

    def test_sub_penny_not_rounded(self):
        db=self.database([('A',line(quantity=3,price=0.001))])
        self.assertEqual(Decimal(audit.counts(db)['signed_line_amount_GBP']),Decimal('0.003'))

    def test_missing_customer_retained_but_not_candidate(self):
        db=self.database([('A',line(customer=None))])
        self.assertEqual(audit.counts(db)['rows'],1)
        self.assertEqual(audit.counts(db,'coherent_candidates')['rows'],0)

    def test_lowercase_cancellation_and_negative_quantity(self):
        db=self.database([('A',line(invoice='c123456',quantity=-2))])
        self.assertEqual(audit.scalar(db,'SELECT canceled FROM rows'),1)
        self.assertEqual(audit.counts(db,'coherent_candidates')['rows'],0)

    def test_negative_without_c_is_separate(self):
        db=self.database([('A',line(quantity=-2))])
        self.assertEqual(audit.scalar(db,'SELECT canceled FROM rows'),0)
        self.assertEqual(audit.counts(db,'coherent_candidates')['rows'],0)

    def test_zero_price_not_a_missing_price(self):
        db=self.database([('A',line(price=0))])
        self.assertEqual(audit.scalar(db,'SELECT price_sign FROM rows'),0)
        self.assertEqual(audit.counts(db,'coherent_candidates')['rows'],0)

    def test_multiple_known_customers_is_ambiguous(self):
        db=self.database([('A',line()),('A',line(customer=54321))])
        self.assertEqual(audit.scalar(db,'SELECT COUNT(*) FROM bad_invoices'),1)
        self.assertEqual(audit.counts(db,'coherent_candidates')['rows'],0)

    def test_different_timestamps_not_silently_collapsed(self):
        db=self.database([('A',line()),('A',line(date=datetime(2010,6,2)))])
        self.assertEqual(audit.scalar(db,'SELECT COUNT(*) FROM bad_invoices'),1)

    def test_same_product_different_price_not_duplicate(self):
        db=self.database([('A',line()),('A',line(price=2))])
        self.assertEqual(audit.duplicate_stats(db)['distinct_eight_field_rows'],2)

    def test_window_left_inclusive_right_exclusive(self):
        db=self.database([('A',line(invoice='123451',date=datetime(2009,12,1))),
                          ('A',line(invoice='123452',date=datetime(2010,12,1)))])
        result=audit.analyze(db)
        self.assertEqual(result['exploratory_365_day_windows'][0]['coherent_candidate_support']['rows'],1)
        self.assertEqual(result['exploratory_customer_overlap']['both_windows'],1)

    def test_decimal_signed_sum_reconciles(self):
        db=self.database([('A',line()),('A',line(invoice='C123457',quantity=-1))])
        result=audit.analyze(db)
        self.assertEqual(Decimal(result['raw']['signed_line_amount_GBP']),Decimal('1.25'))
        self.assertTrue(all(result['reconciliation'].values()))

    def test_input_values_unchanged(self):
        row=line();before=row[:]
        audit.record('A',2,row)
        self.assertEqual(row,before)


if __name__=='__main__':unittest.main()
