"""Independent raw ZIP -> pandas vectorized partitions -> full CSV readback.

Does not import the production builder or read its SQLite tables.
"""
from __future__ import annotations
import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd


def text(v):
    if v is None:return ''
    if isinstance(v,(bool,np.bool_)):return '1' if v else '0'
    if isinstance(v,(list,dict)):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
    return str(v)


class Compare:
    def __init__(self,folder,schemas):
        self.files={};self.readers={};self.counts={};self.schemas=schemas
        for name,header in schemas.items():
            f=(folder/name).open(encoding='utf-8',newline='');self.files[name]=f
            reader=csv.reader(f)
            if next(reader,None)!=header:raise ValueError('Independent header mismatch: '+name)
            self.readers[name]=reader;self.counts[name]=0
    def row(self,name,expected):
        actual=next(self.readers[name],None);wanted=[text(v) for v in expected]
        if actual!=wanted:
            col=next((j for j,(x,y) in enumerate(zip(actual or [],wanted)) if x!=y),-1)
            raise ValueError(f'Independent cell mismatch {name}, record {self.counts[name]+1}, column {col}; values remain private')
        self.counts[name]+=1
    def finish(self):
        for name,reader in self.readers.items():
            if next(reader,None) is not None:raise ValueError('Unexpected extra CSV record: '+name)
        return {name:{'rows':n,'cells':n*len(self.schemas[name])} for name,n in self.counts.items()}
    def close(self):
        for f in self.files.values():f.close()


def verify(package,policy,audit,folder,schemas):
    comparison=Compare(folder,schemas)
    starts={name:pd.Timestamp(policy['time_roles'][name][0]).value//1000000 for name in ('warmup','train','validation','reserved_test')}
    ends={name:pd.Timestamp(policy['time_roles'][name][1]).value//1000000 for name in starts}
    event_sha=next(r['sha256'] for r in audit['files'] if r['name']=='events.csv')
    aggregates={role:{'baskets':0,'sessions_starting':0,'statuses':Counter(),'labelled_visitors':set(),'labelled_targets':0,
        'reachable_targets':0,'all_targets_reachable_queries':0,'new_visitor_queries':0,'new_to_fit_targets':0,
        'multi_item_context_queries':0,'multi_item_target_queries':0,'min_candidate_count':None,
        'available_unknown_basket_items':0,'category_unknown_basket_items':0} for role in starts}
    try:
        with zipfile.ZipFile(package) as z:
            with z.open('events.csv') as f:raw=pd.read_csv(f,dtype=str,keep_default_na=False)
            raw.insert(0,'n',np.arange(2,len(raw)+2,dtype='int64'))
            signatures=list(zip(*(raw[c].tolist() for c in policy['schemas']['events.csv'])))
            hashes=[hashlib.sha256(json.dumps(list(r),ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest() for r in signatures]
            canonical=raw.groupby(policy['schemas']['events.csv'],sort=False)['n'].transform('min').to_numpy()
            # The actual bound source is fully canonical and has no malformed fields;
            # format counterexamples are covered separately in synthetic tests.
            for c in ('timestamp','visitorid','itemid'):
                if not raw[c].str.fullmatch(r'(0|[1-9][0-9]*)').all():raise ValueError('Unexpected malformed independent source')
            if not raw['event'].isin(['view','addtocart','transaction']).all():raise ValueError('Unexpected event')
            tx=raw['event'].eq('transaction')
            if not raw.loc[tx,'transactionid'].str.fullmatch(r'(0|[1-9][0-9]*)').all() or raw.loc[~tx,'transactionid'].ne('').any():raise ValueError('Unexpected transaction key')
            raw['t']=raw['timestamp'].astype('int64')
            raw['role']=np.select([raw['t'].ge(starts[r])&raw['t'].lt(ends[r]) for r in starts],list(starts),default='outside_v1')
            raw['canonical']=canonical
            valid=raw['n'].eq(raw['canonical'])&raw['role'].ne('outside_v1')
            for pos,r in enumerate(raw.itertuples(index=False,name=None)):
                n,rt,v,e,i,x,t,role,anchor=r
                decision='duplicate' if anchor!=n else 'excluded' if role=='outside_v1' else 'canonical'
                reason={'duplicate':'exact_content_duplicate','excluded':'outside_v1_time','canonical':'qualified'}[decision]
                row=[n,event_sha,rt,v,e,i,x,hashes[pos],role,anchor,decision,reason]
                comparison.row('row_decisions.csv',row)
                if decision=='canonical':comparison.row('qualified_events.csv',row[:9])
                elif decision=='excluded':comparison.row('exclusions.csv',row)
                else:comparison.row('duplicate_map.csv',[n,anchor,event_sha,hashes[pos],role])
            del signatures,hashes
            qualified=raw.loc[valid].copy()
            item_first=qualified.loc[qualified['event'].eq('view')].groupby('itemid')['t'].min().to_dict()
            visitor_first=qualified.groupby('visitorid')['t'].min().to_dict()
            train_counts=qualified.loc[qualified['event'].eq('view')&qualified['role'].eq('train')].groupby('visitorid').size().to_dict()
            for item in sorted(item_first):comparison.row('catalog.csv',[item,item_first[item]])
            for visitor in sorted(visitor_first):comparison.row('visitor_history.csv',[visitor,visitor_first[visitor],train_counts.get(visitor,0)])
            views=qualified.loc[qualified['event'].eq('view'),['n','t','visitorid','itemid','role']].copy()
            del raw,qualified
            grouped=views.groupby(['visitorid','t'],sort=True).agg(items=('itemid',lambda a:sorted(set(a),key=int)),records=('n',lambda a:sorted(a.tolist())),role=('role','first')).reset_index()
            prev=grouped.groupby('visitorid')['t'].shift(1)
            is_new=prev.isna()|grouped['t'].sub(prev).gt(1800000)
            grouped['s']=grouped['t'].where(is_new).groupby(grouped['visitorid']).ffill().astype('int64')
            grouped['idx']=grouped.groupby(['visitorid','s']).cumcount()+1
            grouped['occ']=grouped['items'].str.len().groupby([grouped['visitorid'],grouped['s']]).cumsum()
            grouped['next_t']=grouped.groupby('visitorid')['t'].shift(-1).astype('Int64')
            grouped['next_role']=grouped.groupby('visitorid')['role'].shift(-1)
            grouped['next_items']=grouped.groupby('visitorid')['items'].shift(-1)
            sessions=grouped.groupby(['visitorid','s'],sort=True).agg(last=('t','max'),n=('t','size'),occ=('occ','max'),first_role=('role','first'),last_role=('role','last')).reset_index()
            for v,s,t,n,occ,first,last in sessions.itertuples(index=False,name=None):
                comparison.row('sessions.csv',[v,s,t,n,occ,first,last]);aggregates[first]['sessions_starting']+=1
            del sessions,views
            first_sorted=np.sort(np.asarray(list(item_first.values()),dtype='int64'))
            # Read all raw property records independently; retain only the two
            # contracted diagnostic properties with physical source lineage.
            props=[]
            for part in ('item_properties_part1.csv','item_properties_part2.csv'):
                offset=2
                with z.open(part) as f:
                    for chunk in pd.read_csv(f,dtype=str,keep_default_na=False,chunksize=500000):
                        chunk['n']=np.arange(offset,offset+len(chunk),dtype='int64');offset+=len(chunk)
                        chunk['part']=part
                        bad=~chunk['timestamp'].str.fullmatch(r'(0|[1-9][0-9]*)')|~chunk['itemid'].str.fullmatch(r'(0|[1-9][0-9]*)')|chunk['property'].eq('')|chunk['value'].eq('')
                        for rt,i,p,value,n,part_ in chunk.loc[bad].itertuples(index=False,name=None):comparison.row('property_exclusions.csv',[part_,n,rt,i,p,value,'invalid_property_row'])
                        props.append(chunk.loc[~bad&chunk['property'].isin(['available','categoryid'])].copy())
                print('reference property source read: '+part,flush=True)
            props=pd.concat(props,ignore_index=True);props['t']=props['timestamp'].astype('int64')
            with z.open('category_tree.csv') as f:tree=pd.read_csv(f,dtype=str,keep_default_na=False)
        parent_sets=tree.groupby('categoryid')['parentid'].agg(set).to_dict()
        for no,(c,p) in enumerate(tree.itertuples(index=False,name=None),2):
            flags=[]
            if len(parent_sets[c])>1:flags.append('conflicting_parent')
            if p and p not in parent_sets:flags.append('missing_parent')
            visited=set();node=c
            while node in parent_sets and len(parent_sets[node])==1:
                if node in visited:flags.append('cycle');break
                visited.add(node);node=next(iter(parent_sets[node]))
                if not node:break
            comparison.row('category_tree_diagnostics.csv',[no,c,p,sorted(set(flags))])
        versions=[];orphan_counts={}
        props.sort_values(['itemid','property','t','part','n'],inplace=True)
        if not props.duplicated(['itemid','property','t'],keep=False).any():
            groups=((item,prop,t,[value],[[part,int(n)]]) for item,prop,t,value,part,n in props[['itemid','property','t','value','part','n']].itertuples(index=False,name=None))
        else:
            groups=((item,prop,t,g['value'].unique().tolist(),[[p,int(n)] for p,n in zip(g['part'],g['n'])]) for (item,prop,t),g in props.groupby(['itemid','property','t'],sort=True))
        for item,prop,t,distinct,locators in groups:
            value=distinct[0] if len(distinct)==1 else None
            state='conflict' if len(distinct)>1 else 'known'
            if value is not None and ((prop=='available' and value not in ('0','1')) or (prop=='categoryid' and not str(value).isascii()) or (prop=='categoryid' and not str(value).isdecimal()) or (prop=='categoryid' and str(value)!=str(int(value)))):
                state='invalid_value';value=None
            orphan=bool(prop=='categoryid' and value is not None and value not in parent_sets)
            comparison.row('property_versions.csv',[item,prop,t,state,value,locators,orphan])
            versions.append((item,prop,t,state,value,int(orphan)))
            if orphan:orphan_counts[value]=orphan_counts.get(value,0)+1
        del props
        for c in sorted(orphan_counts):comparison.row('orphan_categories.csv',[c,orphan_counts[c]])
        version_frame=pd.DataFrame(versions,columns=['itemid','property','pt','state','value','orphan'])
        del versions
        # Causal as-of joins use a library algorithm independent of production's
        # per-item SQLite predecessor search. Same-clock matches are forbidden.
        diag=grouped[['visitorid','s','t','items','role']].explode('items').rename(columns={'items':'itemid'})
        diag['itemid']=diag['itemid'].astype('object')
        diag['order']=np.arange(len(diag),dtype='int64');diag.sort_values('t',inplace=True)
        for prop,prefix in [('available','a'),('categoryid','c')]:
            right=version_frame.loc[version_frame['property'].eq(prop),['itemid','pt','state','value','orphan']].sort_values('pt')
            right['itemid']=right['itemid'].astype('object')
            merged=pd.merge_asof(diag[['itemid','t','order']],right,left_on='t',right_on='pt',by='itemid',allow_exact_matches=False,direction='backward').set_index('order')
            ordered=merged.reindex(diag['order'])
            for col in ('pt','state','value','orphan'):diag[prefix+'_'+col]=ordered[col].to_numpy()
        diag.sort_values('order',inplace=True)
        del version_frame
        for v,s,t,i,role,_,at,ast,av,ao,ct,cst,cv,co in diag.itertuples(index=False,name=None):
            a_missing=pd.isna(at);c_missing=pd.isna(ct)
            a=[None,'no_prior_version',None,None] if a_missing else [int(at),ast,None if pd.isna(av) else av,t-int(at)]
            c=[None,'no_prior_version',None,None] if c_missing else [int(ct),cst,None if pd.isna(cv) else cv,t-int(ct)]
            comparison.row('view_property_diagnostics.csv',[v,s,t,i,*a,*c,False if c_missing else bool(co)])
            aggregates[role]['available_unknown_basket_items']+=int(a_missing or ast!='known')
            aggregates[role]['category_unknown_basket_items']+=int(c_missing or cst!='known')
        del diag
        for pos,r in enumerate(grouped.itertuples(index=False,name=None),1):
            v,t,items,records,role,s,idx,occ,nt,nr,ni=r
            comparison.row('baskets.csv',[v,s,t,role,idx,items,records,occ])
            has_next=not pd.isna(nt);next_t=int(nt) if has_next else None;next_role=nr if has_next else None
            same=has_next and next_t-t<=1800000
            mature=t<=ends[role]-1800000
            cross=bool(same and nr!=role)
            if role=='warmup':status='warmup_context_only'
            elif t>ends[role]-1800000:status='right_censored'
            elif not same:status='no_observed_continuation'
            elif cross:status='cross_role_target'
            else:status='labelled'
            targets=ni if status=='labelled' else []
            reachable=sum(item_first[i]<t for i in targets)
            fit=starts['reserved_test'] if role=='reserved_test' else starts['validation']
            n=train_counts.get(v,0)
            activity='0' if n==0 else '1' if n==1 else '2-5' if n<6 else '6+'
            candidate_n=int(np.searchsorted(first_sorted,t,side='left'))
            q=[v,s,t,role,idx,occ,next_t,next_role,same,mature,cross,status,candidate_n,targets,len(targets),reachable,
               reachable==len(targets) if targets else None,visitor_first[v]<fit,sum(item_first[i]<fit for i in targets),n,activity]
            comparison.row('query_decisions.csv',q)
            agg=aggregates[role];agg['baskets']+=1;agg['statuses'][status]+=1
            if status=='labelled':
                comparison.row('queries.csv',q)
                agg['labelled_visitors'].add(v);agg['labelled_targets']+=len(targets);agg['reachable_targets']+=reachable
                agg['all_targets_reachable_queries']+=int(reachable==len(targets));agg['new_visitor_queries']+=int(not q[17])
                agg['new_to_fit_targets']+=len(targets)-q[18]
                agg['multi_item_context_queries']+=int(len(items)>1);agg['multi_item_target_queries']+=int(len(targets)>1)
                agg['min_candidate_count']=candidate_n if agg['min_candidate_count'] is None else min(agg['min_candidate_count'],candidate_n)
            if not mature or cross:comparison.row('boundary_ledger.csv',[v,s,t,role,next_t,next_role,mature,cross,status])
            if pos%500000==0:print(f'independent baskets/queries compared: {pos}',flush=True)
        files=comparison.finish()
        for role,agg in aggregates.items():
            agg['labelled_visitors']=len(agg['labelled_visitors']);agg['statuses']=dict(agg['statuses'])
            agg['support_floor_queries']=max(50,(agg['statuses'].get('labelled',0)+99)//100)
        return {'status':'independent_raw_zip_to_every_csv_cell_passed','files':files,
                'rows':sum(r['rows'] for r in files.values()),'cells':sum(r['cells'] for r in files.values()),
                'roles':aggregates,
                'independent_algorithm':'raw ZIP pandas partitions/diff/cumulative groups/shift/numpy searchsorted/merge_asof',
                'pandas_version':pd.__version__,'numpy_version':np.__version__}
    finally:comparison.close()
