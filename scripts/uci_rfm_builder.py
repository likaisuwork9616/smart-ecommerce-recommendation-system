"""UCI frozen-v1 invoice/row decisions and integer RFM; no scoring or fitting."""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

LIMIT = 2**63-1
SHEETS = ['Year 2009-2010','Year 2010-2011']
REASONS = ['cancellation_document','other_adjustment_document','missing_invoice','header_conflict',
           'unknown_customer','invalid_purchase_numeric_or_missing_stock','duplicate_excess','zero_price_free_line','eligible_paid_line']


def checked(n):
    if not -LIMIT-1 <= n <= LIMIT:raise OverflowError('Integer outside signed int64')
    return n


def decimal(value):
    try:
        d = Decimal(value) if value is not None else None
        return d if d is not None and d.is_finite() else None
    except InvalidOperation:return None


def clock(text):
    value = datetime.strptime(text,'%Y-%m-%d %H:%M:%S')
    if value.strftime('%Y-%m-%d %H:%M:%S') != text or value < datetime(2009,12,1):
        raise ValueError('Invalid source event clock')
    return value


def decode(source):
    """Source tuple: sheet,row,Invoice,StockCode,Description,Quantity,date,Price,Customer,Country."""
    sheet,row,*v = source
    if sheet not in SHEETS or type(row) is not int or row < 2:raise ValueError('Invalid source row key')
    if len(v)!=8:raise ValueError('Wrong source width')
    invoice,stock,desc,q,ts,p,customer,country = v
    clock(ts)
    if customer is not None and re.fullmatch('[0-9]{5}',customer) is None:raise ValueError('Malformed known customer')
    quantity,price = decimal(q),decimal(p)
    integral = quantity is not None and quantity == quantity.to_integral_value()
    qi = checked(int(quantity)) if integral else None
    if price is not None and max(0,-price.normalize().as_tuple().exponent)>3:
        raise ValueError('Price precision exceeds v1')
    pi = checked(int(price*1000)) if price is not None else None
    amount = checked(qi*pi) if qi is not None and pi is not None else None
    numeric = bool(invoice and re.fullmatch('[0-9]{6}',invoice))
    cancel = bool(invoice and invoice.upper().startswith('C'))
    bad = qi is None or qi<=0 or pi is None or pi<0 or stock is None
    gid = hashlib.sha256(json.dumps(v,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    return {'source':source,'values':v,'invoice':invoice,'customer':customer,'ts':ts,'q':qi,'p':pi,'amount':amount,
            'numeric':numeric,'cancel':cancel,'bad':bad,'gid':gid,
            'standard':bool(stock and re.fullmatch('[0-9]{5}[A-Za-z]*',stock))}


def prepare(sources, window):
    cutoff = window['cutoff_exclusive']
    rows = [decode(r) for r in sources if r[6] < cutoff]
    rows.sort(key=lambda r:(SHEETS.index(r['source'][0]),r['source'][1]))
    headers = {}
    groups = defaultdict(list)
    universe = set()
    for i,r in enumerate(rows):
        groups[r['gid']].append(i)
        if r['customer'] is not None:universe.add(r['customer'])
        inv = r['invoice']
        if inv is not None:
            h = headers.setdefault(inv,{'indices':[],'customers':set(),'times':set(),'countries':set(),'missing':False,'bad':False})
            h['indices'].append(i);h['times'].add(r['ts']);h['countries'].add(r['values'][7])
            if r['customer'] is not None:h['customers'].add(r['customer'])
            else:h['missing']=True
            h['bad'] |= r['bad']
    for inv,h in headers.items():
        flags=[]
        if len(h['times'])>1:flags.append('multiple_distinct_timestamps')
        if len(h['customers'])>1:flags.append('multiple_distinct_known_customer_keys')
        if h['missing'] and h['customers']:flags.append('mixed_missing_and_known_customer')
        if len(h['countries'])>1:flags.append('multiple_distinct_countries_including_missing')
        h['conflict']=bool(flags)
        if None in h['countries']:flags.append('country_missing')
        h['flags']=sorted(flags)
        h['numeric']=bool(re.fullmatch('[0-9]{6}',inv))
        h['quarantined']=h['numeric'] and (h['conflict'] or h['bad'])
        h['in_window']=any(rows[i]['ts']>=window['start_inclusive'] for i in h['indices'])
    main_rep={};sensitivity_rep={};selected=set()
    for gid,indices in groups.items():
        indices.sort(key=lambda i:(SHEETS.index(rows[i]['source'][0]),rows[i]['source'][1]))
        main_rep[gid]=indices[0]
        per_sheet=Counter(rows[i]['source'][0] for i in indices)
        chosen=min(per_sheet,key=lambda s:(-per_sheet[s],SHEETS.index(s)))
        kept=[i for i in indices if rows[i]['source'][0]==chosen]
        sensitivity_rep[gid]=kept[0];selected.update(kept)
    return {'rows':rows,'headers':headers,'universe':sorted(universe),'main_rep':main_rep,
            'sensitivity_rep':sensitivity_rep,'sensitivity_kept':selected,'window':window}


def decisions(prepared, arm):
    rows=prepared['rows'];headers=prepared['headers']
    multiplicity=arm['duplicates'].startswith('max_')
    representatives=prepared['sensitivity_rep'] if multiplicity else prepared['main_rep']
    keep=prepared['sensitivity_kept'] if multiplicity else set(representatives.values())
    invoice_amount=defaultdict(int);paid_count=Counter();free_count=Counter()
    primary=Counter();raw_sum=0;included_sum=0;window_sum=0;duplicates=0;unknown_rows=0
    S=prepared['window']['start_inclusive'];T=prepared['window']['cutoff_exclusive'];tid=prepared['window']['id']
    qcounts=Counter()
    for inv,h in headers.items():
        if h['quarantined'] and h['in_window']:
            qcounts.update(h['customers'])
    for i,r in enumerate(rows):
        if r['invoice'] is None and r['customer'] is not None and r['ts']>=S:qcounts[r['customer']]+=1

    def row_outputs():
        nonlocal raw_sum,included_sum,window_sum,duplicates,unknown_rows
        for i,r in enumerate(rows):
            h=headers.get(r['invoice'])
            flags=[]
            if r['cancel']:flags.append(REASONS[0])
            if r['invoice'] is not None and not r['numeric'] and not r['cancel']:flags.append(REASONS[1])
            if r['invoice'] is None:flags.append(REASONS[2])
            if r['numeric'] and h['conflict']:flags.append(REASONS[3])
            if r['customer'] is None:flags.append(REASONS[4]);unknown_rows+=1
            if r['numeric'] and h['bad']:flags.append(REASONS[5])
            retained=i in keep
            if not retained:flags.append(REASONS[6]);duplicates+=1
            good=bool(r['numeric'] and not h['quarantined'] and r['customer'] is not None)
            if good and r['p']==0:flags.append(REASONS[7])
            paid=good and r['p']>0 and retained
            if paid:flags.append(REASONS[8])
            if r['values'][2] is None:flags.append('description_missing')
            if r['values'][7] is None:flags.append('country_missing')
            reason=next(reason for reason in REASONS if reason in flags)
            primary[reason]+=1
            included=0
            if paid:
                paid_count[r['invoice']]+=1
                if arm['money']=='all_paid_codes' or r['standard']:included=r['amount']
                invoice_amount[r['invoice']]=checked(invoice_amount[r['invoice']]+included)
            if good and r['p']==0 and retained:free_count[r['invoice']]+=1
            raw_sum=checked(raw_sum+(r['amount'] or 0));included_sum=checked(included_sum+included)
            if r['ts']>=S:window_sum=checked(window_sum+included)
            row=[*r['source'][:2],arm['id'],tid,r['invoice'],r['customer'],r['ts'],r['gid'],reason,sorted(flags),r['amount'],included]
            rep=rows[representatives[r['gid']]]['source']
            mapping=[*r['source'][:2],arm['id'],tid,r['gid'],rep[0],rep[1],retained]
            yield row,mapping

    def invoices():
        for inv in sorted(headers):
            h=headers[inv];first=rows[h['indices'][0]]
            if first['cancel']:reason='cancellation_document'
            elif not h['numeric']:reason='other_adjustment_document'
            elif h['conflict']:reason='header_conflict'
            elif not h['customers']:reason='unknown_customer'
            elif h['bad']:reason='invalid_purchase_numeric_or_missing_stock'
            elif not paid_count[inv]:reason='no_paid_lines'
            else:reason='eligible_purchase_invoice'
            eligible=reason=='eligible_purchase_invoice'
            yield [inv,arm['id'],tid,sorted(h['customers']),next(iter(h['times'])) if len(h['times'])==1 else None,
                   h['flags'],eligible,h['in_window'],h['quarantined'],reason,paid_count[inv],free_count[inv],invoice_amount[inv] if eligible else None]

    def customers():
        history=Counter();frequency=Counter();money=defaultdict(int);last={}
        for inv,h in headers.items():
            if paid_count[inv] and not h['quarantined']:
                customer=next(iter(h['customers']));history[customer]+=1
                if h['in_window']:
                    frequency[customer]+=1;money[customer]=checked(money[customer]+invoice_amount[inv])
                    last[customer]=max(last.get(customer,''),next(iter(h['times'])))
        for customer in prepared['universe']:
            f=frequency[customer];m=money[customer];q=qcounts[customer]
            r=int((clock(T)-clock(last[customer])).total_seconds()) if f else None
            if q:state='active_with_quarantine' if f else 'inactive_with_quarantine'
            elif f:state='active_complete'
            elif history[customer]:state='inactive_complete'
            else:state='observed_no_eligible_history'
            yield [customer,arm['id'],tid,S,T,state,state=='active_complete',history[customer],q,
                   None if q else r,None if q else f,None if q else m,last.get(customer),r,f,m]

    def summary(customer_rows,invoice_rows):
        states=Counter(r[5] for r in customer_rows)
        assert sum(primary.values())==len(rows)
        assert included_sum==sum(r[12] or 0 for r in invoice_rows)
        assert window_sum==sum(r[15] for r in customer_rows)
        return {'prefix_rows':len(rows),'distinct_groups':len(prepared['main_rep']),'duplicate_excess_rows':duplicates,
                'universe':len(customer_rows),'states':dict(sorted(states.items())),'primary_reasons':dict(sorted(primary.items())),
                'prefix_unknown_customer_rows':unknown_rows,'prefix_signed_amount_milli_GBP':raw_sum,
                'history_eligible_invoices':sum(r[6] for r in invoice_rows),'window_eligible_invoices':sum(r[6] and r[7] for r in invoice_rows),
                'quarantined_invoices':sum(r[8] for r in invoice_rows),'window_quarantined_invoices':sum(r[8] and r[7] for r in invoice_rows),
                'window_partial_M_milli_GBP':sum(r[15] for r in customer_rows),
                'window_complete_active_M_milli_GBP':sum(r[11] for r in customer_rows if r[6]),
                'row_invoice_customer_history_amount_reconciled':True}
    return row_outputs,invoices,customers,summary
