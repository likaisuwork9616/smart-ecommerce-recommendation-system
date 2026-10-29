"""Frozen-v1 retrospective RFM description and scoring, integer reference quantiles."""
from collections import Counter, defaultdict
import csv
from fractions import Fraction
from itertools import product
import math

AXES={'R':'R_seconds','F':'F_invoices','M':'M_milli_GBP'}
STATES=['active_complete','inactive_complete','observed_no_eligible_history','active_with_quarantine','inactive_with_quarantine']
PROBS=[0,.25,.5,.75,.95,.99,1]
SCORE_HEADER=['customer_key','arm','T_id','state','rfm_usable','R_seconds','F_invoices','M_milli_GBP','R_score','F_score','M_score','joint_tuple']
PANEL_HEADER=['customer_key','in_U1','in_U2','T1_state','T2_state','both_active_complete','new_observed_key']


def load_customers(path):
    rows=[];seen=set()
    with path.open(encoding='utf-8',newline='') as source:
        for raw in csv.DictReader(source):
            key=raw['customer_key']
            if key in seen:raise ValueError('Duplicate customer in frozen dataset')
            seen.add(key)
            row={k:raw[k] for k in ('customer_key','arm','T_id','state')}
            row['rfm_usable']=raw['rfm_usable']=='true'
            for field in AXES.values():row[field]=int(raw[field]) if raw[field]!='' else None
            if row['state'] not in STATES or row['rfm_usable']!=(row['state']=='active_complete'):raise ValueError('Invalid active state')
            if row['rfm_usable'] and any(row[f] is None for f in AXES.values()):raise ValueError('Missing active RFM')
            rows.append(row)
    if [r['customer_key'] for r in rows]!=sorted(seen):raise ValueError('Unsorted customer file')
    return rows


def quantile(values,p):
    if not values:return None
    ordered=sorted(values)
    if p==0:return ordered[0]
    probability=Fraction(str(p));index=(len(ordered)*probability.numerator+probability.denominator-1)//probability.denominator-1
    return ordered[index]


def describe(values,probs=PROBS):
    return {'n':len(values),'quantiles':{str(p):quantile(values,p) for p in probs}}


def fit_reference(rows,source_id):
    if source_id!='main/T1':raise ValueError('Cutpoints may only be fitted on main/T1')
    active=[r for r in rows if r['rfm_usable']]
    if len(active)<200:return {'reference':source_id,'n':len(active),'status':'insufficient_reference','axes':{}}
    axes={}
    for axis,field in AXES.items():
        values=[r[field] for r in active]
        raw=[quantile(values,p) for p in [.2,.4,.6,.8]]
        cuts=sorted({c for c in raw if c<max(values)})
        axes[axis]={'unit':'seconds' if axis=='R' else 'invoices' if axis=='F' else '0.001_GBP',
                    'raw_P20_P40_P60_P80':raw,'cutpoints':cuts,'levels':len(cuts)+1,'constant_reference':min(values)==max(values)}
    return {'reference':source_id,'n':len(active),'status':'fitted_once','axes':axes}


def apply(rows,cutpoints):
    result=[]
    for row in rows:
        r=dict(row);joint=[]
        for axis,field in AXES.items():
            value=None
            if r['rfm_usable'] and cutpoints['status']=='fitted_once':
                thresholds=cutpoints['axes'][axis]['cutpoints']
                j=sum(r[field]>c for c in thresholds)
                value=len(thresholds)+1-j if axis=='R' else j+1
            r[axis+'_score']=value;joint.append(value)
        r['joint_tuple']=joint if all(v is not None for v in joint) else None
        result.append(r)
    return result


def score_record(r):return [r[k] for k in SCORE_HEADER]


def ratio(n,d):return n/d if d else None


def transition(before,after,labels):
    count=Counter(zip(before,after));totals=Counter(before)
    return {'labels':labels,'source_totals':{label:totals[label] for label in labels},
            'cells':[{'from':a,'to':b,'n':count[a,b],'row_rate':ratio(count[a,b],totals[a])}
                     for a,b in product(labels,repeat=2) if count[a,b]],
            'empty_source_rows':[label for label in labels if not totals[label]],'unlisted_cells':0}


def joint_label(values):return '-'.join(f'{axis}{value}' for axis,value in zip(AXES,values))


def labels(cuts):
    if cuts['status']!='fitted_once':return []
    return [joint_label(v) for v in product(*(range(1,cuts['axes'][axis]['levels']+1) for axis in AXES))]


def support(rows,cuts):
    active=[r for r in rows if r['rfm_usable']];n=len(active);floor=max(50,(n+99)//100)
    if cuts['status']!='fitted_once':return {'n':n,'minimum':floor,'status':'no_reference_cutpoints'}
    result={'n':n,'minimum':floor,'status':'checked','axes':{}}
    def counts(values,levels):
        counter=Counter(values);under=[x for x in levels if 0<counter[x]<floor]
        nonempty=[counter[x] for x in levels if counter[x]]
        return {'counts':{str(x):counter[x] for x in levels},'empty_groups':sum(not counter[x] for x in levels),
                'nonempty_groups':len(nonempty),'under_supported_groups':len(under),
                'people_in_under_supported_groups':sum(counter[x] for x in under),
                'minimum_nonempty_group':min(nonempty) if nonempty else None}
    for axis in AXES:result['axes'][axis]=counts([r[axis+'_score'] for r in active],list(range(1,cuts['axes'][axis]['levels']+1)))
    result['joint']=counts([joint_label(r['joint_tuple']) for r in active],labels(cuts))
    return result


def ranks_twice(values):
    ordered=sorted(range(len(values)),key=values.__getitem__);result=[0]*len(values);start=0
    while start<len(values):
        end=start+1
        while end<len(values) and values[ordered[end]]==values[ordered[start]]:end+=1
        rank=start+1+end
        for i in ordered[start:end]:result[i]=rank
        start=end
    return result


def spearman(x,y):
    if not x:return None
    a,b=ranks_twice(x),ranks_twice(y);n=len(a)
    cross=n*sum(i*j for i,j in zip(a,b))-sum(a)*sum(b)
    va=n*sum(i*i for i in a)-sum(a)**2;vb=n*sum(i*i for i in b)-sum(b)**2
    return cross/math.sqrt(va*vb) if va and vb else None


def ari(x,y):
    n=len(x)
    if n<2:return None
    choose=lambda v:v*(v-1)//2
    pairs=choose(n);a=sum(choose(v) for v in Counter(zip(x,y)).values())
    b=sum(choose(v) for v in Counter(x).values());c=sum(choose(v) for v in Counter(y).values())
    expected=Fraction(b*c,pairs);denominator=Fraction(b+c,2)-expected
    return float((a-expected)/denominator) if denominator else None


def paired_numeric(first,second,cuts):
    n=len(first);result={'n':n,'axes':{}}
    for axis,field in AXES.items():
        x=[r[field] for r in first];y=[r[field] for r in second];delta=[b-a for a,b in zip(x,y)]
        correlation=spearman(x,y) if n>=200 else None
        reason='insufficient_n' if n<200 else 'constant_axis' if correlation is None else None
        result['axes'][axis]={'delta_T2_minus_T1':describe(delta),'absolute_delta':describe([abs(v) for v in delta],[.5,.9]),
                              'spearman':correlation,'spearman_null_reason':reason}
    if cuts['status']!='fitted_once':result['score_status']='no_reference_cutpoints';return result
    result['score_status']='fixed_T1_cutpoints';result['score_axes']={}
    for axis in AXES:
        x=[r[axis+'_score'] for r in first];y=[r[axis+'_score'] for r in second]
        result['score_axes'][axis]={'exact_n':sum(a==b for a,b in zip(x,y)),'exact_rate':ratio(sum(a==b for a,b in zip(x,y)),n),
            'within_one_n':sum(abs(a-b)<=1 for a,b in zip(x,y)),'within_one_rate':ratio(sum(abs(a-b)<=1 for a,b in zip(x,y)),n),
            'transition':transition([str(v) for v in x],[str(v) for v in y],[str(v) for v in range(1,cuts['axes'][axis]['levels']+1)])}
    x=[joint_label(r['joint_tuple']) for r in first];y=[joint_label(r['joint_tuple']) for r in second]
    value=ari(x,y) if n>=200 else None
    result['joint']={'exact_n':sum(a==b for a,b in zip(x,y)),'exact_rate':ratio(sum(a==b for a,b in zip(x,y)),n),
                     'ARI':value,'ARI_null_reason':'insufficient_n' if n<200 else 'degenerate_partition' if value is None else None,
                     'transition':transition(x,y,labels(cuts))}
    return result


def snapshot(rows,cuts):
    active=[r for r in rows if r['rfm_usable']]
    return {'universe':len(rows),'states':{s:sum(r['state']==s for r in rows) for s in STATES},
            'active_complete':len(active),'RFM':{axis:describe([r[field] for r in active]) for axis,field in AXES.items()},
            'F_ge_2':{'n':sum(r['F_invoices']>=2 for r in active),'denominator':len(active),'rate':ratio(sum(r['F_invoices']>=2 for r in active),len(active))},
            'support':support(rows,cuts)}


def temporal(first,second,cuts):
    a={r['customer_key']:r for r in first};b={r['customer_key']:r for r in second}
    if not set(a)<=set(b):raise ValueError('U1 not subset U2')
    keys=sorted(k for k in a if a[k]['rfm_usable'] and b[k]['rfm_usable'])
    paired_keys=set(keys)
    new=[b[k] for k in sorted(set(b)-set(a))]
    out={'U1':len(a),'U2':len(b),'new_observed_keys':len(new),'new_observed_states':{s:sum(r['state']==s for r in new) for s in STATES},
         'state_transition_on_U1':transition([a[k]['state'] for k in sorted(a)],[b[k]['state'] for k in sorted(a)],STATES),
         'paired_coverage':{'n':len(keys),'over_U1':ratio(len(keys),len(a)),
                            'over_T1_active':ratio(len(keys),sum(r['rfm_usable'] for r in first)),
                            'over_T2_active':ratio(len(keys),sum(r['rfm_usable'] for r in second))},
         'excluded_U1_state_pairs':[{'T1':x,'T2':y,'n':n} for (x,y),n in sorted(Counter((a[k]['state'],b[k]['state']) for k in a if k not in paired_keys).items())]}
    out['paired']=paired_numeric([a[k] for k in keys],[b[k] for k in keys],cuts)
    return out


def sensitivity(main,other,cuts):
    a={r['customer_key']:r for r in main};b={r['customer_key']:r for r in other}
    if set(a)!=set(b):raise ValueError('Sensitivity universe mismatch')
    for k in a:
        if any(a[k][field]!=b[k][field] for field in ['state','rfm_usable','R_seconds','F_invoices']):raise ValueError('Sensitivity changed state/R/F')
    keys=sorted(k for k in a if a[k]['rfm_usable'])
    first=[a[k] for k in keys];second=[b[k] for k in keys]
    x=[r['M_milli_GBP'] for r in first];y=[r['M_milli_GBP'] for r in second]
    delta=[v-u for u,v in zip(x,y)];relative=[(v-u)/u for u,v in zip(x,y) if u]
    out={'same_universe_states_R_F':True,'n':len(keys),'main_M_total_milli_GBP':sum(x),'other_M_total_milli_GBP':sum(y),
         'M_total_delta_milli_GBP':sum(y)-sum(x),'M_total_relative_delta':ratio(sum(y)-sum(x),sum(x)),
         'M_delta_milli_GBP':describe(delta),'M_customer_relative_delta':describe(relative),
         'relative_delta_excluded_zero_main':sum(not v for v in x)}
    if cuts['status']=='fitted_once':
        out['score_agreement']={'M_exact_n':sum(a['M_score']==b['M_score'] for a,b in zip(first,second)),
             'M_exact_rate':ratio(sum(a['M_score']==b['M_score'] for a,b in zip(first,second)),len(keys)),
             'joint_exact_rate':ratio(sum(a['joint_tuple']==b['joint_tuple'] for a,b in zip(first,second)),len(keys))}
    else:out['score_agreement']=None
    return out


def ledger(path,start,cutoff):
    n=missing=amount=missing_amount=positive=missing_positive=unknown=0;reasons=Counter()
    with path.open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            if not start<=row['timestamp']<cutoff:continue
            n+=1;is_missing=row['customer_key']=='';missing+=is_missing;reasons[row['primary_reason']]+=1
            if row['signed_raw_amount_milli_GBP']=='':unknown+=1;continue
            value=int(row['signed_raw_amount_milli_GBP']);amount+=value;missing_amount+=value if is_missing else 0
            if value>0:positive+=value;missing_positive+=value if is_missing else 0
    return {'scope':'original_rows_in_window_before_dedup_signed_arithmetic_not_net_revenue','rows':n,'unknown_customer_rows':missing,
            'unknown_customer_row_share':ratio(missing,n),'signed_amount_milli_GBP':amount,'unknown_customer_signed_amount_milli_GBP':missing_amount,
            'unknown_customer_signed_amount_share':ratio(missing_amount,amount),'positive_amount_milli_GBP':positive,
            'unknown_customer_positive_amount_milli_GBP':missing_positive,'unknown_customer_positive_amount_share':ratio(missing_positive,positive),
            'raw_amount_unknown_rows':unknown,'primary_reasons':dict(sorted(reasons.items()))}


def report(datasets,cuts,ledgers,build_summaries,arms):
    return {'snapshots':{name:snapshot(rows,cuts) for name,rows in datasets.items()},
            'temporal':{arm:temporal(datasets[arm+'/T1'],datasets[arm+'/T2'],cuts) for arm in arms},
            'sensitivity':{arm+'/'+tid:sensitivity(datasets['main/'+tid],datasets[arm+'/'+tid],cuts) for arm in arms if arm!='main' for tid in ['T1','T2']},
            'window_raw_ledgers':ledgers,'accepted_build_exclusion_and_duplicate_summaries':build_summaries}


def panel(datasets):
    a={r['customer_key']:r for r in datasets['main/T1']};b={r['customer_key']:r for r in datasets['main/T2']}
    return [[k,k in a,True,a[k]['state'] if k in a else None,b[k]['state'],bool(k in a and a[k]['rfm_usable'] and b[k]['rfm_usable']),k not in a] for k in sorted(b)]
