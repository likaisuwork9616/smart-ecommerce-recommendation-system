"""Independent stdlib XML -> SQL/window-function reference, without builder imports."""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

from scripts.verify_uci_retail_ii import read_xml_rows, NS

NAMES=['Year 2009-2010','Year 2010-2011']
COLS='invoice,stock,description,quantity,ts,price,customer,country'


def integer_amount(q,p):
    try:
        quantity=Decimal(q) if q is not None else Decimal('NaN')
        price=Decimal(p) if p is not None else Decimal('NaN')
    except InvalidOperation:
        return None,None,None
    qi=int(quantity) if quantity.is_finite() and quantity==quantity.to_integral_value() else None
    if price.is_finite():
        if price.as_tuple().exponent < -3 and price*1000 != (price*1000).to_integral_value():raise ValueError('Precision')
        pi=int(price*1000)
    else:pi=None
    amount=qi*pi if qi is not None and pi is not None else None
    for n in (qi,pi,amount):
        if n is not None and not -2**63<=n<2**63:raise OverflowError('Reference integer range')
    return qi,pi,amount


def database(path):
    db=sqlite3.connect(path)
    db.execute('PRAGMA temp_store=MEMORY')
    db.execute('CREATE TABLE source(si INTEGER,excel_row INTEGER,invoice TEXT,stock TEXT,description TEXT,quantity TEXT,ts TEXT,price TEXT,customer TEXT,country TEXT,gid TEXT,qi INTEGER,pi INTEGER,amount INTEGER,numeric INTEGER,cancel INTEGER,bad INTEGER,standard INTEGER)')
    return db


def insert_sources(db,sources):
    batch=[]
    for sheet,row,*v in sources:
        inv,stock,desc,q,ts,p,customer,country=v
        parsed=datetime.strptime(ts,'%Y-%m-%d %H:%M:%S')
        if parsed.strftime('%Y-%m-%d %H:%M:%S')!=ts or ts<'2009-12-01 00:00:00':raise ValueError('Reference source date')
        if customer is not None and not re.fullmatch('[0-9]{5}',customer):raise ValueError('Reference key')
        qi,pi,amount=integer_amount(q,p)
        numeric=int(bool(inv and re.fullmatch('[0-9]{6}',inv)))
        cancel=int(bool(inv and inv[:1].lower()=='c'))
        bad=int(qi is None or qi<=0 or pi is None or pi<0 or stock is None)
        gid=hashlib.sha256(json.dumps(v,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
        batch.append((NAMES.index(sheet),row,*v,gid,qi,pi,amount,numeric,cancel,bad,int(bool(stock and re.fullmatch('[0-9]{5}[A-Za-z]*',stock)))))
        if len(batch)==10000:
            db.executemany('INSERT INTO source VALUES ('+','.join(['?']*18)+')',batch);db.commit();batch=[]
    db.executemany('INSERT INTO source VALUES ('+','.join(['?']*18)+')',batch);db.commit()


def load_workbook(db,workbook):
    with zipfile.ZipFile(workbook) as z:
        strings=[''.join(t.text or '' for t in item.findall('.//s:t',NS)) for item in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        book=ET.fromstring(z.read('xl/workbook.xml'))
        sheets=book.findall('s:sheets/s:sheet',NS)
        rels={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        assert [s.get('name') for s in sheets]==NAMES
        for s in sheets:
            target=rels[s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
            member=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            iterator=read_xml_rows(z,member,strings)
            _,headers=next(iterator)
            assert headers==['Invoice','StockCode','Description','Quantity','InvoiceDate','Price','Customer ID','Country']
            insert_sources(db,((s.get('name'),row,*v) for row,v in iterator))
            print(json.dumps({'independent_XML_sheet_loaded':s.get('name')}),flush=True)


def prepare(db,window):
    # Explicit eight-column SQL partition is independent of the builder's group dictionary.
    for table in ['prefix','ranked','chosen']:
        db.execute('DROP TABLE IF EXISTS '+table)
    db.execute('CREATE TABLE prefix AS SELECT * FROM source WHERE ts>=? AND ts<?',('2009-12-01 00:00:00',window['cutoff_exclusive']))
    db.execute('CREATE TABLE ranked AS SELECT *,ROW_NUMBER() OVER (PARTITION BY '+COLS+' ORDER BY si,excel_row) exact_rank,COUNT(*) OVER (PARTITION BY '+COLS+',si) sheet_n FROM prefix')
    db.execute('CREATE TABLE chosen AS SELECT *,FIRST_VALUE(si) OVER (PARTITION BY '+COLS+' ORDER BY sheet_n DESC,si,excel_row) chosen_si,FIRST_VALUE(excel_row) OVER (PARTITION BY '+COLS+' ORDER BY sheet_n DESC,si,excel_row) chosen_row,FIRST_VALUE(si) OVER (PARTITION BY '+COLS+' ORDER BY si,excel_row) first_si,FIRST_VALUE(excel_row) OVER (PARTITION BY '+COLS+' ORDER BY si,excel_row) first_row FROM ranked')
    db.execute('CREATE INDEX ix_chosen_invoice ON chosen(invoice)')
    headers={}
    for inv,nt,nc,missing,ncountries,nullcountry,bad,lo,hi in db.execute(
        'SELECT invoice,COUNT(DISTINCT ts),COUNT(DISTINCT customer),MAX(customer IS NULL),COUNT(DISTINCT country),MAX(country IS NULL),MAX(bad),MIN(ts),MAX(ts) FROM prefix WHERE invoice IS NOT NULL GROUP BY invoice'):
        customers=[r[0] for r in db.execute('SELECT DISTINCT customer FROM chosen WHERE invoice=? AND customer IS NOT NULL ORDER BY customer',(inv,))]
        flags=[]
        if nt>1:flags.append('multiple_distinct_timestamps')
        if nc>1:flags.append('multiple_distinct_known_customer_keys')
        if missing and nc:flags.append('mixed_missing_and_known_customer')
        if ncountries+nullcountry>1:flags.append('multiple_distinct_countries_including_missing')
        conflict=bool(flags)
        if nullcountry:flags.append('country_missing')
        numeric=bool(re.fullmatch('[0-9]{6}',inv))
        headers[inv]=(customers,lo if nt==1 else None,sorted(flags),numeric and (conflict or bool(bad)),hi>=window['start_inclusive'],conflict,bool(bad),numeric)
    universe=[r[0] for r in db.execute('SELECT DISTINCT customer FROM prefix WHERE customer IS NOT NULL ORDER BY customer')]
    return {'db':db,'window':window,'headers':headers,'universe':universe}


def expected(prepared,arm):
    db=prepared['db'];headers=prepared['headers'];w=prepared['window']
    multi=arm['duplicates'].startswith('max_');allcodes=arm['money']=='all_paid_codes'
    paid=Counter();free=Counter();amounts=defaultdict(int);quarantine=Counter()
    history=Counter();freq=Counter();money=defaultdict(int);last={}
    for inv,h in headers.items():
        if h[3] and h[4]:quarantine.update(h[0])
    for customer,n in db.execute('SELECT customer,COUNT(*) FROM prefix WHERE invoice IS NULL AND customer IS NOT NULL AND ts>=? GROUP BY customer',(w['start_inclusive'],)):
        quarantine[customer]+=n

    def rows():
        for record in db.execute('SELECT * FROM chosen ORDER BY si,excel_row'):
            si,row,inv,stock,desc,q,ts,p,customer,country,gid,qi,pi,raw,numeric,cancel,bad,standard,rank,sheet_n,chosen_si,chosen_row,first_si,first_row=record
            h=headers.get(inv)
            retained=si==chosen_si if multi else rank==1
            good=bool(numeric and not h[3] and customer is not None)
            flags=set()
            if cancel:flags.add('cancellation_document')
            elif inv is not None and not numeric:flags.add('other_adjustment_document')
            if inv is None:flags.add('missing_invoice')
            if numeric and h[5]:flags.add('header_conflict')
            if customer is None:flags.add('unknown_customer')
            if numeric and h[6]:flags.add('invalid_purchase_numeric_or_missing_stock')
            if not retained:flags.add('duplicate_excess')
            if good and pi==0:flags.add('zero_price_free_line')
            is_paid=good and pi>0 and retained
            if is_paid:flags.add('eligible_paid_line')
            if desc is None:flags.add('description_missing')
            if country is None:flags.add('country_missing')
            order=['cancellation_document','other_adjustment_document','missing_invoice','header_conflict','unknown_customer','invalid_purchase_numeric_or_missing_stock','duplicate_excess','zero_price_free_line','eligible_paid_line']
            reason=next(k for k in order if k in flags)
            included=raw if is_paid and (allcodes or standard) else 0
            if is_paid:paid[inv]+=1;amounts[inv]+=included
            if good and pi==0 and retained:free[inv]+=1
            if any(not -2**63<=n<2**63 for n in (included,amounts[inv])):raise OverflowError('Reference sum')
            yield ([NAMES[si],row,arm['id'],w['id'],inv,customer,ts,gid,reason,sorted(flags),raw,included],
                   [NAMES[si],row,arm['id'],w['id'],gid,NAMES[chosen_si if multi else first_si],chosen_row if multi else first_row,bool(retained)])

    def invoices():
        for inv in sorted(headers):
            customers,ts,flags,q,in_window,conflict,bad,numeric=headers[inv]
            if inv[:1].lower()=='c':reason='cancellation_document'
            elif not numeric:reason='other_adjustment_document'
            elif conflict:reason='header_conflict'
            elif not customers:reason='unknown_customer'
            elif bad:reason='invalid_purchase_numeric_or_missing_stock'
            elif not paid[inv]:reason='no_paid_lines'
            else:reason='eligible_purchase_invoice'
            eligible=reason=='eligible_purchase_invoice'
            if eligible:
                customer=customers[0];history[customer]+=1
                if in_window:
                    freq[customer]+=1;money[customer]+=amounts[inv];last[customer]=max(last.get(customer,''),ts)
            yield [inv,arm['id'],w['id'],customers,ts,flags,eligible,in_window,q,reason,paid[inv],free[inv],amounts[inv] if eligible else None]

    def customers():
        for customer in prepared['universe']:
            f=freq[customer];q=quarantine[customer];m=money[customer]
            r=int((datetime.fromisoformat(w['cutoff_exclusive'])-datetime.fromisoformat(last[customer])).total_seconds()) if f else None
            state=('active_with_quarantine' if f else 'inactive_with_quarantine') if q else ('active_complete' if f else ('inactive_complete' if history[customer] else 'observed_no_eligible_history'))
            yield [customer,arm['id'],w['id'],w['start_inclusive'],w['cutoff_exclusive'],state,state=='active_complete',history[customer],q,None if q else r,None if q else f,None if q else m,last.get(customer),r,f,m]
    return rows,invoices,customers
