"""Read-only UCI workbook intake audit; private SQLite, public aggregates only."""
import argparse
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, getcontext
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

getcontext().prec = 50
ROOT = Path(__file__).resolve().parents[1]
RAW = 'data/raw/online_retail_ii'
PRIVATE = 'shop-mysql-runtime/uci_retail_ii_intake_v1'
REPORT = 'reports/stage6/uci_retail_ii_intake.json'
HEADERS = ['Invoice','StockCode','Description','Quantity','InvoiceDate','Price','Customer ID','Country']
FIELDS = ['invoice','stock','description','quantity','ts','price','customer','country']
PROBES = ('2010-12-01', '2011-06-01')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def descriptor(path):
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':sha(path)}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_new(path, value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')


def text_value(value):
    if value is None or (isinstance(value,str) and not value.strip()):
        return None
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        number=Decimal(str(value))
        return format(number.normalize(),'f') if number.is_finite() else str(value)
    return str(value)  # Preserve case and nonblank whitespace for duplicate detection.


def number(value):
    if value is None or isinstance(value,bool):return None
    try:
        d=Decimal(str(value))
        return d if d.is_finite() else None
    except InvalidOperation:return None


class DecimalSum:
    def __init__(self):self.total=Decimal(0)
    def step(self,value):
        if value is not None:self.total+=Decimal(value)
    def finalize(self):return format(self.total,'f')


def connect(path=':memory:'):
    db=sqlite3.connect(path)
    db.execute('PRAGMA temp_store=MEMORY')
    db.create_aggregate('DECIMAL_SUM',1,DecimalSum)
    return db


def schema(db):
    db.execute('CREATE TABLE rows(sheet TEXT, excel_row INTEGER, invoice TEXT, stock TEXT, description TEXT, '
               'quantity TEXT, ts TEXT, price TEXT, customer TEXT, country TEXT, amount TEXT, '
               'signature TEXT, canceled INTEGER, numeric_invoice INTEGER, qty_sign INTEGER, price_sign INTEGER, '
               'qty_integral INTEGER, price_dp INTEGER, standard_stock_shape INTEGER, candidate INTEGER, invalid_clock INTEGER)')


def record(sheet, excel_row, values):
    if len(values)!=8:raise ValueError('Unexpected row width')
    vals=[text_value(v) for v in values]
    q,p=number(values[3]),number(values[5])
    date=values[4]
    ts=date.isoformat(sep=' ') if isinstance(date,datetime) and date.tzinfo is None else None
    vals[3]=format(q.normalize(),'f') if q is not None else vals[3]
    vals[5]=format(p.normalize(),'f') if p is not None else vals[5]
    vals[4]=ts if ts is not None else vals[4]
    sig=hashlib.sha256(json.dumps(vals,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    invoice,stock,_,_,_,_,customer,_=vals
    canceled=bool(invoice and invoice.upper().startswith('C'))
    numeric=bool(invoice and re.fullmatch(r'\d{6}',invoice))
    q_sign=None if q is None else (q>0)-(q<0)
    p_sign=None if p is None else (p>0)-(p<0)
    integral=q is not None and q==q.to_integral_value()
    dp=None if p is None else max(0,-p.normalize().as_tuple().exponent)
    candidate=bool(numeric and not canceled and customer and ts and integral and q>0 and p is not None and p>0)
    return (sheet,excel_row,*vals[:4],ts,*vals[5:],None if q is None or p is None else format(q*p,'f'),
            sig,int(canceled),int(numeric),q_sign,p_sign,int(integral),dp,
            int(bool(stock and re.fullmatch(r'\d{5}[A-Za-z]*',stock))),int(candidate),int(ts is None))


def insert(db, records):
    db.executemany('INSERT INTO rows VALUES ('+','.join(['?']*21)+')',records)


def build_views(db):
    db.execute('CREATE INDEX ix_signature ON rows(signature)')
    db.execute('CREATE INDEX ix_invoice ON rows(invoice)')
    db.execute('CREATE VIEW unique_rows AS SELECT * FROM rows WHERE rowid IN (SELECT MIN(rowid) FROM rows GROUP BY signature)')
    db.execute('CREATE TABLE invoice_headers AS SELECT invoice,COUNT(*) n,COUNT(DISTINCT customer) customers, '
               'COUNT(DISTINCT ts) clocks,COUNT(DISTINCT country) countries,SUM(customer IS NULL) missing_customer '
               'FROM rows WHERE invoice IS NOT NULL GROUP BY invoice')
    db.execute('CREATE INDEX ix_header_invoice ON invoice_headers(invoice)')
    db.execute('CREATE VIEW bad_invoices AS SELECT invoice FROM invoice_headers WHERE customers>1 OR clocks>1 OR countries>1')
    db.execute('CREATE VIEW coherent_candidates AS SELECT * FROM unique_rows WHERE candidate=1 '
               'AND invoice NOT IN (SELECT invoice FROM bad_invoices)')
    db.commit()


def scalar(db,sql,args=()):
    return db.execute(sql,args).fetchone()[0]


def counts(db,table='rows',where='1',args=()):
    n,invoices,customers,amount= db.execute(
        f'SELECT COUNT(*),COUNT(DISTINCT invoice),COUNT(DISTINCT customer),DECIMAL_SUM(amount) FROM {table} WHERE {where}',args).fetchone()
    return {'rows':n,'invoices':invoices,'known_customers':customers,'signed_line_amount_GBP':amount or '0'}


def duplicate_stats(db,table='rows'):
    n=scalar(db,f'SELECT COUNT(*) FROM {table}')
    unique=scalar(db,f'SELECT COUNT(DISTINCT signature) FROM {table}')
    groups=scalar(db,f'SELECT COUNT(*) FROM (SELECT signature FROM {table} GROUP BY signature HAVING COUNT(*)>1)')
    return {'rows':n,'distinct_eight_field_rows':unique,'duplicate_excess_rows':n-unique,'duplicate_groups':groups}


def analyze(db):
    total=counts(db)
    missing={key:scalar(db,f'SELECT COUNT(*) FROM rows WHERE {key} IS NULL') for key in FIELDS}
    sheets=[]
    for sheet,n,lo,hi in db.execute('SELECT sheet,COUNT(*),MIN(ts),MAX(ts) FROM rows GROUP BY sheet ORDER BY sheet'):
        unique=scalar(db,'SELECT COUNT(DISTINCT signature) FROM rows WHERE sheet=?',(sheet,))
        sheets.append({'sheet':sheet,'headers':HEADERS,'rows':n,'minimum':lo,'maximum':hi,'distinct_eight_field_rows':unique,
                       'within_sheet_duplicate_excess':n-unique,'missing_customer_rows':scalar(db,'SELECT COUNT(*) FROM rows WHERE sheet=? AND customer IS NULL',(sheet,))})
    duplicates=duplicate_stats(db)
    duplicates['within_sheet_duplicate_excess']=sum(s['within_sheet_duplicate_excess'] for s in sheets)
    duplicates['cross_sheet_duplicate_excess_after_within_sheet_dedup']=sum(s['distinct_eight_field_rows'] for s in sheets)-duplicates['distinct_eight_field_rows']
    duplicates['invoice_keys_in_multiple_sheets']=scalar(db,'SELECT COUNT(*) FROM (SELECT invoice FROM rows WHERE invoice IS NOT NULL GROUP BY invoice HAVING COUNT(DISTINCT sheet)>1)')
    duplicates['raw_rows_in_cross_sheet_signatures']=scalar(db,'SELECT COUNT(*) FROM rows WHERE signature IN (SELECT signature FROM rows GROUP BY signature HAVING COUNT(DISTINCT sheet)>1)')
    duplicates['cross_sheet_duplicate_min_date'],duplicates['cross_sheet_duplicate_max_date']=db.execute(
        'SELECT MIN(ts),MAX(ts) FROM rows WHERE signature IN (SELECT signature FROM rows GROUP BY signature HAVING COUNT(DISTINCT sheet)>1)').fetchone()
    invoices={
        'multiple_detail_rows_is_not_itself_an_error':True,
        'invoices_with_multiple_rows':scalar(db,'SELECT COUNT(*) FROM invoice_headers WHERE n>1'),
        'multiple_known_customers':scalar(db,'SELECT COUNT(*) FROM invoice_headers WHERE customers>1'),
        'multiple_timestamps':scalar(db,'SELECT COUNT(*) FROM invoice_headers WHERE clocks>1'),
        'multiple_countries':scalar(db,'SELECT COUNT(*) FROM invoice_headers WHERE countries>1'),
        'mixed_missing_and_known_customer':scalar(db,'SELECT COUNT(*) FROM invoice_headers WHERE missing_customer>0 AND customers>0'),
        'ambiguous_header_union':scalar(db,'SELECT COUNT(*) FROM bad_invoices'),
        'distinct_rows_on_ambiguous_invoices':scalar(db,'SELECT COUNT(*) FROM unique_rows WHERE invoice IN (SELECT invoice FROM bad_invoices)'),
        'invoice_stock_pairs_with_multiple_distinct_rows':scalar(db,'SELECT COUNT(*) FROM (SELECT invoice,stock FROM unique_rows GROUP BY invoice,stock HAVING COUNT(*)>1)')}
    sign_matrix=[]
    for c,q,p,n,amount in db.execute('SELECT canceled,qty_sign,price_sign,COUNT(*),DECIMAL_SUM(amount) FROM rows GROUP BY canceled,qty_sign,price_sign ORDER BY canceled,qty_sign,price_sign'):
        sign_matrix.append({'cancellation_prefix':bool(c),'quantity_sign':q,'price_sign':p,'rows':n,'signed_line_amount_GBP':amount})
    issues={
        'cancellation_prefix':counts(db,where='canceled=1'),
        'negative_quantity_without_cancellation_prefix':counts(db,where='canceled=0 AND qty_sign=-1'),
        'cancellation_prefix_with_nonnegative_quantity':counts(db,where='canceled=1 AND qty_sign>=0'),
        'zero_quantity':counts(db,where='qty_sign=0'),
        'negative_price':counts(db,where='price_sign=-1'),
        'zero_price':counts(db,where='price_sign=0'),
        'missing_customer':counts(db,where='customer IS NULL'),
        'known_customer_non_five_digit_format':counts(db,where="customer IS NOT NULL AND (length(customer)!=5 OR customer GLOB '*[^0-9]*')"),
        'non_six_digit_non_cancellation_invoice':counts(db,where='numeric_invoice=0 AND canceled=0'),
        'invalid_timestamp_rows':scalar(db,'SELECT COUNT(*) FROM rows WHERE invalid_clock=1'),
        'invalid_quantity_rows':scalar(db,'SELECT COUNT(*) FROM rows WHERE qty_sign IS NULL'),
        'nonintegral_quantity_rows':scalar(db,'SELECT COUNT(*) FROM rows WHERE qty_integral=0 AND qty_sign IS NOT NULL'),
        'invalid_price_rows':scalar(db,'SELECT COUNT(*) FROM rows WHERE price_sign IS NULL'),
        'price_more_than_two_decimal_places_rows':scalar(db,'SELECT COUNT(*) FROM rows WHERE price_dp>2'),
        'maximum_price_decimal_places':scalar(db,'SELECT MAX(price_dp) FROM rows'),
        'quantity_min_max':list(db.execute('SELECT MIN(CAST(quantity AS REAL)),MAX(CAST(quantity AS REAL)) FROM rows').fetchone()),
        'price_min_max':list(db.execute('SELECT MIN(CAST(price AS REAL)),MAX(CAST(price AS REAL)) FROM rows').fetchone())}
    views={'raw':total,'eight_field_distinct_sensitivity':counts(db,'unique_rows'),
           'raw_positive_known_customer_candidate':counts(db,where='candidate=1'),
           'distinct_positive_known_customer_candidate':counts(db,'unique_rows','candidate=1'),
           'distinct_positive_header_coherent_candidate':counts(db,'coherent_candidates')}
    views['coherent_candidate_nonstandard_stock_shape']=counts(db,'coherent_candidates','standard_stock_shape=0')
    month=[]
    for m in [r[0] for r in db.execute('SELECT DISTINCT substr(ts,1,7) FROM rows WHERE ts IS NOT NULL ORDER BY 1')]:
        raw=counts(db,where='substr(ts,1,7)=?',args=(m,))
        clean=counts(db,'coherent_candidates','substr(ts,1,7)=?',(m,))
        first,last,days=db.execute('SELECT MIN(ts),MAX(ts),COUNT(DISTINCT substr(ts,1,10)) FROM rows WHERE substr(ts,1,7)=?',(m,)).fetchone()
        month.append({'month':m,'raw':raw,'coherent_candidate':clean,'missing_customer_rows':scalar(db,'SELECT COUNT(*) FROM rows WHERE substr(ts,1,7)=? AND customer IS NULL',(m,)),
                      'cancellation_rows':scalar(db,'SELECT COUNT(*) FROM rows WHERE substr(ts,1,7)=? AND canceled=1',(m,)),
                      'first_event':first,'last_event':last,'observed_calendar_days':days,'upstream_complete':None})
    probes=[];sets=[]
    for cutoff in PROBES:
        end=datetime.fromisoformat(cutoff);start=end-timedelta(days=365)
        lo,hi=start.isoformat(sep=' '),end.isoformat(sep=' ')
        scope=counts(db,'coherent_candidates','ts>=? AND ts<?',(lo,hi))
        sets.append({r[0] for r in db.execute('SELECT DISTINCT customer FROM coherent_candidates WHERE ts>=? AND ts<?',(lo,hi))})
        probes.append({'start_inclusive':lo,'cutoff_exclusive':hi,'days':365,'coherent_candidate_support':scope,
                       'selected_research_cutoff':False,'as_of_complete':None})
    overlap={'both_windows':len(sets[0]&sets[1]),'first_only':len(sets[0]-sets[1]),'second_only':len(sets[1]-sets[0]),
             'union':len(sets[0]|sets[1]),'meaning':'Observed positive-purchase keys in exploratory windows, not retailer entry/exit or clean holdout.'}
    waterfall=[];where='1';last=scalar(db,'SELECT COUNT(*) FROM unique_rows')
    for label,condition in [('six_digit_invoice','numeric_invoice=1'),('valid_naive_timestamp','invalid_clock=0'),
                            ('known_customer','customer IS NOT NULL'),('positive_integral_quantity','qty_sign=1 AND qty_integral=1'),
                            ('positive_price','price_sign=1'),('unambiguous_invoice_header','invoice NOT IN (SELECT invoice FROM bad_invoices)')]:
        where+=' AND '+condition
        n=scalar(db,'SELECT COUNT(*) FROM unique_rows WHERE '+where)
        waterfall.append({'step':label,'removed_at_this_step':last-n,'remaining':n});last=n
    assert last==views['distinct_positive_header_coherent_candidate']['rows']
    assert duplicates['duplicate_excess_rows']==duplicates['within_sheet_duplicate_excess']+duplicates['cross_sheet_duplicate_excess_after_within_sheet_dedup']
    assert sum(m['raw']['rows'] for m in month)+issues['invalid_timestamp_rows']==total['rows']
    assert sum(Decimal(m['raw']['signed_line_amount_GBP']) for m in month)==Decimal(total['signed_line_amount_GBP'])
    return {'tables':sheets,'raw':total,'missing_cells':missing,'duplicates':duplicates,'invoice_integrity':invoices,
            'quality_issues':issues,'cancellation_quantity_price_sign_matrix':sign_matrix,'sensitivity_views':views,
            'sequential_candidate_exclusions':waterfall,'monthly_coverage':month,'exploratory_365_day_windows':probes,
            'exploratory_customer_overlap':overlap,
            'reconciliation':{'row_counts':True,'duplicate_decomposition':True,'monthly_signed_amount':True,'candidate_waterfall':True}}


def run():
    import openpyxl
    private=ROOT/PRIVATE
    assert private.resolve().is_relative_to(ROOT.resolve())
    if private.exists() or (ROOT/REPORT).exists():raise FileExistsError('Existing audit; preserve and use --verify')
    manifest=read_json(ROOT/RAW/'source_manifest.json')
    for desc in manifest['files']:
        if descriptor(ROOT/desc['path'])!=desc:raise ValueError('Intake source changed')
    private.mkdir()
    dbpath=private/'inventory.sqlite'
    db=connect(dbpath);schema(db)
    workbook=openpyxl.load_workbook(ROOT/RAW/'online_retail_II.xlsx',read_only=True,data_only=False)
    formula_cells=0
    for sheet in workbook:
        iterator=sheet.iter_rows()
        headers=[c.value for c in next(iterator)]
        if headers!=HEADERS:raise ValueError('Workbook schema differs')
        batch=[];n=0
        for row_no,cells in enumerate(iterator,start=2):
            formula_cells+=sum(c.data_type=='f' for c in cells)
            if any(c.data_type=='f' for c in cells):raise ValueError('Unexpected source formulas require review')
            batch.append(record(sheet.title,row_no,[c.value for c in cells]));n+=1
            if len(batch)==10000:insert(db,batch);db.commit();batch=[]
            if n%200000==0:print(json.dumps({'sheet':sheet.title,'rows_read':n}),flush=True)
        insert(db,batch);db.commit()
        print(json.dumps({'sheet':sheet.title,'rows_read':n,'complete':True}),flush=True)
    workbook.close();build_views(db)
    result=analyze(db);db.close()
    sources=[descriptor(ROOT/RAW/'source_manifest.json'),*manifest['files'],
             descriptor(Path(__file__)),descriptor(ROOT/'tests/test_uci_retail_ii.py')]
    output={'format_version':1,'status':'intake_audited_retrospective_study_feasible_with_unresolved_policy',
            'source':{'url':manifest['source_url'],'doi':manifest['doi'],'license':manifest['license_on_source_page'],
                      'attribution':manifest['attribution'],'download_completed_utc':manifest['download_completed_utc'],
                      'package_crc_passed':manifest['outer_zip_crc_passed'],'xlsx_crc_passed':manifest['xlsx_container_crc_passed'],
                      'published_rows':1067371,'published_rows_match':result['raw']['rows']==1067371,'files':sources},
            'method':{'reader':'openpyxl read_only / data_only=False','reader_version':openpyxl.__version__,'python':sys.version.split()[0],
                      'formula_cells':formula_cells,'duplicates':'Exact decoded eight-column values across both sheets; numeric scalar formatting normalized. Dedup is sensitivity, not final cleaning.',
                      'money':'Decimal(str(decoded cell value)); Quantity * Price, preserve sub-penny precision, no FX or line rounding. Signed arithmetic is not verified net revenue.',
                      'candidate':'Six-digit invoice, known customer, valid naive clock, positive integral quantity and positive price; exact-value distinct view, then exclude invoices with conflicting known customer/time/country.',
                      'source_mutations':0,'new_RFM_or_cutpoints':0,'models_or_holdout_scores':0,
                      'exposure':'Full-file quality/monthly amounts and exploratory window support inspected; later periods are not pristine unseen data.'},
            'results':result,
            'limitations':['No original visibility/revision timestamps or certified completion watermark; event-proxy retrospective only.',
                           'No canonical original-sale linkage for cancellations; do not mechanically strip C and match invoice suffixes.',
                           'Repeated exact lines may be source duplicates or genuine identical lines; no line-level key, sensitivity is not truth.',
                           'Known-customer positive candidates exclude unknown IDs and adjustments; retain excluded ledgers when building any future dataset.',
                           'Nonstandard stock-code shape may represent fees/adjustments or valid products; monetary eligibility requires a new explicit policy.',
                           'Workbook sheets overlap; future ingestion cannot concatenate and assume distinct periods.',
                           'Original Olist small-group limitation and Stage4 daily 10 percent budget remain; Dashboard deferred.']}
    for desc in sources:
        if descriptor(ROOT/desc['path'])!=desc:raise ValueError('Source changed during audit')
    write_new(ROOT/REPORT,output)
    write_new(private/'output_guard.json',{'report':descriptor(ROOT/REPORT),'database':descriptor(dbpath),'sources':sources})
    print(json.dumps({'status':output['status'],'raw':result['raw'],'duplicates':result['duplicates'],'candidate':result['sensitivity_views']['distinct_positive_header_coherent_candidate']}),flush=True)


def verify():
    guard=read_json(ROOT/PRIVATE/'output_guard.json')
    for desc in [guard['report'],guard['database'],*guard['sources']]:
        if descriptor(ROOT/desc['path'])!=desc:raise ValueError('Saved audit bytes changed')
    print(json.dumps({'status':'source_and_saved_audit_bytes_verified','recomputed_rows':False}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--run',action='store_true');actions.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    run() if args.run else verify()
