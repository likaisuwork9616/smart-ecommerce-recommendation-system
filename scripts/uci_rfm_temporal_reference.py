"""Independent pandas/numpy/scipy/sklearn evaluation of frozen customer tables."""
from itertools import product
import json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import adjusted_rand_score

AXES={'R':'R_seconds','F':'F_invoices','M':'M_milli_GBP'}
STATES=['active_complete','inactive_complete','observed_no_eligible_history','active_with_quarantine','inactive_with_quarantine']
PROBS=[0,.25,.5,.75,.95,.99,1]


def load(path):
    frame=pd.read_csv(path,dtype='string',keep_default_na=False)
    frame['rfm_usable']=frame['rfm_usable'].eq('true')
    for f in AXES.values():frame[f]=pd.Series([int(v) if v else None for v in frame[f]],index=frame.index,dtype=object)
    return frame


def value(v):
    if v is None or pd.isna(v):return None
    return v.item() if isinstance(v,np.generic) else v


def quantiles(values,probs=PROBS):
    values=list(values)
    if not values:return {'n':0,'quantiles':{str(p):None for p in probs}}
    array=np.asarray(values)
    return {'n':len(values),'quantiles':{str(p):value(v) for p,v in zip(probs,np.quantile(array,probs,method='inverted_cdf'))}}


def cutpoints(frame):
    active=frame.loc[frame.rfm_usable]
    if len(active)<200:return {'reference':'main/T1','n':len(active),'status':'insufficient_reference','axes':{}}
    result={}
    for axis,field in AXES.items():
        data=np.asarray(active[field].tolist(),dtype=np.int64)
        raw=np.quantile(data,[.2,.4,.6,.8],method='inverted_cdf').astype(np.int64).tolist()
        cuts=sorted(set(v for v in raw if v<int(data.max())))
        result[axis]={'unit':'seconds' if axis=='R' else 'invoices' if axis=='F' else '0.001_GBP','raw_P20_P40_P60_P80':raw,
                      'cutpoints':cuts,'levels':len(cuts)+1,'constant_reference':bool(data.min()==data.max())}
    return {'reference':'main/T1','n':len(active),'status':'fitted_once','axes':result}


def scored(frame,cuts):
    out=frame.copy()
    for axis,field in AXES.items():
        out[axis+'_score']=pd.Series([None]*len(out),dtype=object,index=out.index)
        if cuts['status']=='fitted_once':
            mask=out.rfm_usable;arr=np.asarray(out.loc[mask,field].tolist(),dtype=np.int64)
            bins=np.searchsorted(cuts['axes'][axis]['cutpoints'],arr,side='left')
            scores=cuts['axes'][axis]['levels']-bins if axis=='R' else bins+1
            out.loc[mask,axis+'_score']=scores.astype(object)
    out['joint_tuple']=[([int(row.R_score),int(row.F_score),int(row.M_score)] if row.R_score is not None else None) for row in out.itertuples()]
    return out


def fraction(a,b):return a/b if b else None


def joint(v):return f'R{v[0]}-F{v[1]}-M{v[2]}'


def all_joint(cuts):
    return [joint(v) for v in product(*(range(1,cuts['axes'][a]['levels']+1) for a in AXES))] if cuts['status']=='fitted_once' else []


def table(x,y,labels):
    counts=pd.crosstab(pd.Series(list(x),dtype='str',name='a'),pd.Series(list(y),dtype='str',name='b')).reindex(index=labels,columns=labels,fill_value=0)
    totals={k:int(counts.loc[k].sum()) for k in labels}
    return {'labels':labels,'source_totals':totals,'cells':[{'from':a,'to':b,'n':int(counts.at[a,b]),'row_rate':int(counts.at[a,b])/totals[a]} for a,b in product(labels,repeat=2) if counts.at[a,b]],
            'empty_source_rows':[k for k in labels if not totals[k]],'unlisted_cells':0}


def support(frame,cuts):
    active=frame.loc[frame.rfm_usable];n=len(active);minimum=max(50,int(np.ceil(n*.01)))
    if cuts['status']!='fitted_once':return {'n':n,'minimum':minimum,'status':'no_reference_cutpoints'}
    def group(values,levels):
        freq=pd.Series(list(values),dtype=object).value_counts().reindex(levels,fill_value=0)
        under=freq[(freq>0)&(freq<minimum)];nonempty=freq[freq>0]
        return {'counts':{str(k):int(freq[k]) for k in levels},'empty_groups':int((freq==0).sum()),'nonempty_groups':len(nonempty),
                'under_supported_groups':len(under),'people_in_under_supported_groups':int(under.sum()),
                'minimum_nonempty_group':int(nonempty.min()) if len(nonempty) else None}
    return {'n':n,'minimum':minimum,'status':'checked','axes':{a:group(active[a+'_score'].tolist(),list(range(1,cuts['axes'][a]['levels']+1))) for a in AXES},
            'joint':group([joint(v) for v in active.joint_tuple],all_joint(cuts))}


def paired(a,b,cuts):
    n=len(a);result={'n':n,'axes':{}}
    for axis,field in AXES.items():
        x=np.asarray(a[field].tolist(),dtype=np.int64);y=np.asarray(b[field].tolist(),dtype=np.int64);delta=y-x
        reason='insufficient_n' if n<200 else 'constant_axis' if len(np.unique(x))<2 or len(np.unique(y))<2 else None
        correlation=None if reason else float(spearmanr(x,y).statistic)
        result['axes'][axis]={'delta_T2_minus_T1':quantiles(delta),'absolute_delta':quantiles(np.abs(delta),[.5,.9]),'spearman':correlation,'spearman_null_reason':reason}
    if cuts['status']!='fitted_once':result['score_status']='no_reference_cutpoints';return result
    result['score_status']='fixed_T1_cutpoints';result['score_axes']={}
    for axis in AXES:
        x=np.asarray(a[axis+'_score'].tolist(),dtype=np.int64);y=np.asarray(b[axis+'_score'].tolist(),dtype=np.int64)
        exact=int(np.sum(x==y));within=int(np.sum(np.abs(x-y)<=1))
        result['score_axes'][axis]={'exact_n':exact,'exact_rate':fraction(exact,n),'within_one_n':within,'within_one_rate':fraction(within,n),
                                  'transition':table([str(v) for v in x],[str(v) for v in y],[str(v) for v in range(1,cuts['axes'][axis]['levels']+1)])}
    x=[joint(v) for v in a.joint_tuple];y=[joint(v) for v in b.joint_tuple]
    reason='insufficient_n' if n<200 else 'degenerate_partition' if (len(set(x))==len(set(y))==1 or len(set(x))==len(set(y))==n) else None
    exact=int(np.sum(np.array(x)==np.array(y)))
    result['joint']={'exact_n':exact,'exact_rate':fraction(exact,n),'ARI':None if reason else float(adjusted_rand_score(x,y)),
                     'ARI_null_reason':reason,'transition':table(x,y,all_joint(cuts))}
    return result


def snapshot(frame,cuts):
    active=frame.loc[frame.rfm_usable];n=len(active);repeat=int(active.F_invoices.ge(2).sum())
    return {'universe':len(frame),'states':{s:int(frame.state.eq(s).sum()) for s in STATES},'active_complete':n,
            'RFM':{axis:quantiles(active[field]) for axis,field in AXES.items()},'F_ge_2':{'n':repeat,'denominator':n,'rate':fraction(repeat,n)},
            'support':support(frame,cuts)}


def temporal(first,second,cuts):
    a=first.set_index('customer_key',drop=False);b=second.set_index('customer_key',drop=False)
    if not a.index.isin(b.index).all():raise ValueError('Reference U1 not subset')
    base=b.loc[a.index];both=a.rfm_usable & base.rfm_usable;keys=a.index[both]
    new=b.loc[~b.index.isin(a.index)];excluded=pd.DataFrame({'T1':a.loc[~both].state,'T2':base.loc[~both].state}).groupby(['T1','T2']).size()
    return {'U1':len(a),'U2':len(b),'new_observed_keys':len(new),'new_observed_states':{s:int(new.state.eq(s).sum()) for s in STATES},
            'state_transition_on_U1':table(a.state,base.state,STATES),'paired_coverage':{'n':len(keys),'over_U1':fraction(len(keys),len(a)),
                'over_T1_active':fraction(len(keys),int(a.rfm_usable.sum())),'over_T2_active':fraction(len(keys),int(b.rfm_usable.sum()))},
            'excluded_U1_state_pairs':[{'T1':x,'T2':y,'n':int(n)} for (x,y),n in excluded.items()],
            'paired':paired(a.loc[keys],b.loc[keys],cuts)}


def sensitivity(main,other,cuts):
    a=main.set_index('customer_key',drop=False);b=other.set_index('customer_key',drop=False).loc[a.index]
    if not a[['state','rfm_usable','R_seconds','F_invoices']].equals(b[['state','rfm_usable','R_seconds','F_invoices']]):raise ValueError('Reference sensitivity R/F state differs')
    a=a.loc[a.rfm_usable];b=b.loc[a.index];x=np.asarray(a.M_milli_GBP.tolist(),dtype=np.int64);y=np.asarray(b.M_milli_GBP.tolist(),dtype=np.int64)
    delta=y-x;relative=delta[x!=0]/x[x!=0]
    out={'same_universe_states_R_F':True,'n':len(a),'main_M_total_milli_GBP':int(x.sum()),'other_M_total_milli_GBP':int(y.sum()),
         'M_total_delta_milli_GBP':int(delta.sum()),'M_total_relative_delta':fraction(int(delta.sum()),int(x.sum())),
         'M_delta_milli_GBP':quantiles(delta),'M_customer_relative_delta':quantiles(relative),'relative_delta_excluded_zero_main':int(np.sum(x==0))}
    if cuts['status']=='fitted_once':
        exact=int(np.sum(a.M_score.to_numpy()==b.M_score.to_numpy()))
        jt=sum(x==y for x,y in zip(a.joint_tuple,b.joint_tuple))
        out['score_agreement']={'M_exact_n':exact,'M_exact_rate':fraction(exact,len(a)),'joint_exact_rate':fraction(jt,len(a))}
    else:out['score_agreement']=None
    return out


def ledger(path,start,end):
    totals={k:0 for k in ['rows','missing','amount','missing_amount','positive','missing_positive','unknown']};reasons={}
    for chunk in pd.read_csv(path,dtype='string',keep_default_na=False,chunksize=100000,usecols=['timestamp','customer_key','primary_reason','signed_raw_amount_milli_GBP']):
        chunk=chunk.loc[(chunk.timestamp>=start)&(chunk.timestamp<end)]
        missing=chunk.customer_key.eq('');known_amount=chunk.signed_raw_amount_milli_GBP.ne('')
        vals=pd.to_numeric(chunk.loc[known_amount,'signed_raw_amount_milli_GBP'])
        linked_missing=missing.loc[vals.index];positive=vals.gt(0)
        totals['rows']+=len(chunk);totals['missing']+=int(missing.sum());totals['unknown']+=int((~known_amount).sum())
        totals['amount']+=int(vals.sum());totals['missing_amount']+=int(vals.loc[linked_missing].sum())
        totals['positive']+=int(vals.loc[positive].sum());totals['missing_positive']+=int(vals.loc[positive & linked_missing].sum())
        for k,n in chunk.primary_reason.value_counts().items():reasons[k]=reasons.get(k,0)+int(n)
    t=totals
    return {'scope':'original_rows_in_window_before_dedup_signed_arithmetic_not_net_revenue','rows':t['rows'],'unknown_customer_rows':t['missing'],
            'unknown_customer_row_share':fraction(t['missing'],t['rows']),'signed_amount_milli_GBP':t['amount'],
            'unknown_customer_signed_amount_milli_GBP':t['missing_amount'],'unknown_customer_signed_amount_share':fraction(t['missing_amount'],t['amount']),
            'positive_amount_milli_GBP':t['positive'],'unknown_customer_positive_amount_milli_GBP':t['missing_positive'],
            'unknown_customer_positive_amount_share':fraction(t['missing_positive'],t['positive']),'raw_amount_unknown_rows':t['unknown'],'primary_reasons':dict(sorted(reasons.items()))}


def report(datasets,cuts,ledgers,build_summaries,arms):
    return {'snapshots':{name:snapshot(frame,cuts) for name,frame in datasets.items()},
            'temporal':{a:temporal(datasets[a+'/T1'],datasets[a+'/T2'],cuts) for a in arms},
            'sensitivity':{a+'/'+t:sensitivity(datasets['main/'+t],datasets[a+'/'+t],cuts) for a in arms if a!='main' for t in ['T1','T2']},
            'window_raw_ledgers':ledgers,'accepted_build_exclusion_and_duplicate_summaries':build_summaries}


def panel(datasets):
    a=datasets['main/T1'].set_index('customer_key');b=datasets['main/T2'].set_index('customer_key')
    return [[k,k in a.index,True,a.at[k,'state'] if k in a.index else None,b.at[k,'state'],
             bool(k in a.index and a.at[k,'rfm_usable'] and b.at[k,'rfm_usable']),k not in a.index] for k in b.index]
