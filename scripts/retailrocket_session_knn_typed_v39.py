"""Complete passive late typed comparison against a worker-local source authority.

Public reference construction reconstructs and checks the unchanged canonical
oracle (one additional canonical call at this builder's actual stack depth).
The private builder is a TRUSTED SEALED ADAPTER boundary: it accepts a recorded
successful original early call, not a generally unforgeable public capability.
Neither comparison entry point invokes a clock, observer, watch or user hook.
"""
import hashlib
import json
import math
import sys
from threading import local
from types import MappingProxyType
from weakref import WeakValueDictionary

from scripts import retailrocket_session_knn_reuse_v27 as original

SCHEME='K1-C1-LATE-TYPED-REFERENCE-v1'
ORIGINAL_CANONICAL=original.canonical
class _Lease:
    __slots__=('_factory_slots','__weakref__')
    def __init__(self,slots):object.__setattr__(self,'_factory_slots',slots)
    def __setattr__(self,name,value):raise TypeError('Factory admission is immutable')
_ADMITTED=WeakValueDictionary()
_MISSING=object()
_BUSY=local()
_TAGS=('none','bool','int','float','str','list','tuple','map')
_RUNTIME_KEYS={'recursion_limit','int_max_str_digits','frame_depth'}


class Reference(tuple):
    """Immutable tuple-only source authority. Construct only through the builders."""
    __slots__=()
    def __new__(cls,*args,**kwargs):raise TypeError('Use a reference builder')
    def __reduce_ex__(self,protocol):raise TypeError('References cannot cross a process boundary')
    @property
    def scheme(self):return tuple.__getitem__(self,0)
    @property
    def root(self):return tuple.__getitem__(self,1)
    @property
    def source_bytes(self):return tuple.__getitem__(self,2)
    @property
    def source_length(self):return tuple.__getitem__(self,3)
    @property
    def source_sha256(self):return tuple.__getitem__(self,4)
    @property
    def source_descriptor(self):return dict(scheme=self.scheme,bytes=self.source_length,sha256=self.source_sha256)
    @property
    def provenance(self):return dict(tuple.__getitem__(self,6))
    def statistics(self):return dict(tuple.__getitem__(self,5))


def capture_runtime(*,skip=0):
    """Capture the caller's expected original-oracle callsite, excluding this helper."""
    if type(skip) is not int or skip<0:raise ValueError('Nonnegative exact frame skip required')
    frame=sys._getframe(1+skip);depth=0
    try:
        while frame is not None:depth+=1;frame=frame.f_back
    finally:del frame
    digits=sys.get_int_max_str_digits() if hasattr(sys,'get_int_max_str_digits') else None
    return dict(recursion_limit=sys.getrecursionlimit(),int_max_str_digits=digits,frame_depth=depth)


def _runtime(value):
    if type(value) is not dict or set(value)!=_RUNTIME_KEYS:
        raise ValueError('Exact passive runtime metadata required')
    if (type(value['recursion_limit']) is not int or value['recursion_limit']<1
            or type(value['frame_depth']) is not int or value['frame_depth']<1
            or value['int_max_str_digits'] is not None and
               (type(value['int_max_str_digits']) is not int or value['int_max_str_digits']<0)):
        raise ValueError('Invalid original-oracle runtime budget')
    return dict(value)


def _text(value):
    # Validation of a leaf, not emission of a complete canonical preimage.
    value.encode('utf-8')


def _string(text,start):
    """Decode one string; require exactly ensure_ascii=False canonical escaping."""
    i=start+1
    while i<len(text):
        char=text[i]
        if char=='"':
            value,end=json.decoder.scanstring(text,start+1,True)
            if end!=i+1:raise ValueError('String boundary differs')
            return value,end
        if char=='\\':
            if i+1>=len(text):raise ValueError('Truncated JSON escape')
            escaped=text[i+1]
            if escaped in ('"','\\','b','f','n','r','t'):i+=2;continue
            if escaped!='u' or i+6>len(text):raise ValueError('Noncanonical JSON escape')
            digits=text[i+2:i+6]
            if any(c not in '0123456789abcdef' for c in digits):raise ValueError('Canonical lowercase control escape required')
            value=int(digits,16)
            if value>31 or value in (8,9,10,12,13):raise ValueError('Only canonical long control escapes are allowed')
            i+=6;continue
        if ord(char)<32 or 0xD800<=ord(char)<=0xDFFF:raise ValueError('Unencodable or unescaped JSON character')
        i+=1
    raise ValueError('Unterminated JSON string')


def _decode(source):
    """Iterative array/string/bool parser; no recursive JSON DOM/depth cutoff."""
    if type(source) is not bytes:raise ValueError('Exact canonical bytes required')
    text=source.decode('utf-8');stack=[];root=_MISSING;i=0;max_depth=0
    def append(value):
        nonlocal root
        if stack:
            frame=stack[-1]
            if not frame[1]:raise ValueError('Missing canonical comma')
            frame[0].append(value);frame[1]=False;frame[2]=False
        elif root is _MISSING:root=value
        else:raise ValueError('Extra canonical root')
    while i<len(text):
        char=text[i]
        if char==',':
            if not stack or stack[-1][1]:raise ValueError('Unexpected canonical comma')
            stack[-1][1]=True;stack[-1][2]=False;i+=1;continue
        if char==']':
            if not stack or stack[-1][1] and not stack[-1][2]:raise ValueError('Unexpected or trailing array end')
            value=tuple(stack.pop()[0]);append(value);i+=1;continue
        if root is not _MISSING and not stack:raise ValueError('Extra canonical bytes')
        if stack and not stack[-1][1]:raise ValueError('Missing canonical comma')
        if char=='[':
            stack.append([[],True,True]);max_depth=max(max_depth,len(stack));i+=1;continue
        if char=='"':value,i=_string(text,i);append(value);continue
        if text.startswith('true',i):append(True);i+=4;continue
        if text.startswith('false',i):append(False);i+=5;continue
        raise ValueError('Only compact canonical arrays, strings and booleans are allowed')
    if stack or root is _MISSING:raise ValueError('Incomplete canonical root')
    return root,max_depth


def _grammar(root):
    stats=dict(nodes=0,maps=0,sequences=0,scalars=0,max_depth=0)
    pending=[(root,0)]
    while pending:
        node,depth=pending.pop();stats['nodes']+=1;stats['max_depth']=max(stats['max_depth'],depth)
        if type(node) is not tuple or not node or type(node[0]) is not str or node[0] not in _TAGS:
            raise ValueError('Exact typed node/tag required')
        tag=node[0]
        if len(node)!=(1 if tag=='none' else 2):raise ValueError('Exact typed node arity required')
        if tag=='none':stats['scalars']+=1;continue
        payload=node[1]
        if tag=='bool':
            if type(payload) is not bool:raise ValueError('Exact bool reference payload required')
        elif tag=='int':
            if type(payload) is not str or str(int(payload))!=payload:raise ValueError('Canonical decimal integer payload required')
        elif tag=='float':
            if type(payload) is not str:raise ValueError('Exact float.hex payload required')
            value=float.fromhex(payload)
            if not math.isfinite(value) or value.hex()!=payload:raise ValueError('Canonical finite float.hex payload required')
        elif tag=='str':
            if type(payload) is not str:raise ValueError('Exact string reference payload required')
            _text(payload)
        elif tag in ('list','tuple'):
            if type(payload) is not tuple:raise ValueError('Immutable sequence child tuple required')
            stats['sequences']+=1
            pending.extend((child,depth+1) for child in reversed(payload));continue
        else:
            if type(payload) is not tuple:raise ValueError('Immutable map pair tuple required')
            previous=None;children=[]
            for pair in payload:
                if type(pair) is not tuple or len(pair)!=2 or type(pair[0]) is not str:raise ValueError('Exact immutable map pair required')
                key,child=pair;_text(key)
                if previous is not None and not previous<key:raise ValueError('Strictly sorted unique map keys required')
                previous=key;children.append(child)
            stats['maps']+=1;pending.extend((child,depth+1) for child in reversed(children));continue
        stats['scalars']+=1
    return stats


def _materialize(root):
    """Reconstruct only for the public independent original-oracle validation."""
    pending=[('visit',root)];values=[]
    while pending:
        action,node=pending.pop()
        if action!='visit':
            tag,count,keys=node;children=values[-count:] if count else []
            if count:del values[-count:]
            values.append(dict(zip(keys,children)) if tag=='map' else tuple(children) if tag=='tuple' else list(children));continue
        tag=node[0]
        if tag=='none':values.append(None)
        elif tag=='bool' or tag=='str':values.append(node[1])
        elif tag=='int':values.append(int(node[1]))
        elif tag=='float':values.append(float.fromhex(node[1]))
        else:
            children=node[1];keys=tuple(pair[0] for pair in children) if tag=='map' else ()
            pending.append(('finish',(tag,len(children),keys)))
            pending.extend(('visit',pair[1] if tag=='map' else pair) for pair in reversed(children))
    if len(values)!=1:raise ValueError('Malformed source materialization')
    return values[0]


def _reference(source,root,stats,runtime,authority,source_role):
    provenance=dict(authority=authority,oracle='scripts.retailrocket_session_knn_reuse_v27.canonical',
        recursion_limit=runtime['recursion_limit'],int_max_str_digits=runtime['int_max_str_digits'],
        observed_source_callstack_depth=runtime['frame_depth'],source_role=source_role)
    slots=(SCHEME,root,source,len(source),hashlib.sha256(source).hexdigest(),
        tuple(sorted(stats.items())),tuple(sorted(provenance.items())))
    lease=_Lease(slots)
    result=tuple.__new__(Reference,(*slots,lease))
    # Weak admission metadata holds no reference/tree/encoded-buffer cache.
    # Copying a factory tuple with tuple.__new__ is not factory admission.
    _ADMITTED[id(result)]=lease
    return result


def build_reference(canonical_bytes):
    """Public safe builder: one EXTRA unchanged canonical call verifies exact bytes.

    Approval is at this builder's actual oracle callstack, not a claim that
    resource limits are identical at every possible shallower caller location.
    Worker code must instead use the explicitly trusted private adapter path.
    """
    root,encoded_depth=_decode(canonical_bytes);stats=_grammar(root);stats['encoded_depth']=encoded_depth
    value=_materialize(root);before=capture_runtime()
    if original.canonical is not ORIGINAL_CANONICAL:raise ValueError('Original canonical function identity changed')
    actual=ORIGINAL_CANONICAL(value);after=capture_runtime()
    if before!=after or actual!=canonical_bytes:raise ValueError('Reference is not the exact original canonical preimage')
    return _reference(canonical_bytes,root,stats,before,'public_original_oracle_validation','public')


def _build_verified_reference(canonical_bytes,*,runtime_before,runtime_after,oracle=ORIGINAL_CANONICAL,source_role):
    """PRIVATE trusted sealed-adapter success attestation; NOT public proof issuance.

    The adapter must have just successfully called the unchanged oracle at its
    recorded callsite on the exact verified source and completed ALL four early
    live/source comparisons. This function intentionally does not repeat that
    serialization. Python callers able to invoke private internals are trusted;
    this is not an unforgeable capability or an attestation from bytes alone.
    """
    before=_runtime(runtime_before);after=_runtime(runtime_after)
    if (before!=after or oracle is not ORIGINAL_CANONICAL or original.canonical is not ORIGINAL_CANONICAL
            or source_role not in ('config','model')):raise ValueError('Exact successful original source-oracle attestation required')
    root,encoded_depth=_decode(canonical_bytes);stats=_grammar(root);stats['encoded_depth']=encoded_depth
    current=capture_runtime()
    if any(current[k]!=before[k] for k in ('recursion_limit','int_max_str_digits')):
        raise ValueError('Oracle runtime changed before reference publication')
    return _reference(canonical_bytes,root,stats,before,'trusted_sealed_adapter_success_attestation',source_role)


def _approved(ref,runtime):
    if (type(ref) is not Reference or tuple.__len__(ref)!=8 or type(tuple.__getitem__(ref,7)) is not _Lease
            or _ADMITTED.get(id(ref)) is not tuple.__getitem__(ref,7)
            or tuple.__getitem__(ref,0)!=SCHEME or type(tuple.__getitem__(ref,2)) is not bytes):
        raise ValueError('Exact factory-built immutable reference authority required')
    lease=tuple.__getitem__(ref,7)
    if any(tuple.__getitem__(ref,index) is not lease._factory_slots[index] for index in range(7)):
        raise ValueError('Reference slots differ from the immutable factory admission')
    provenance=dict(tuple.__getitem__(ref,6))
    if (runtime['recursion_limit']!=provenance['recursion_limit']
            or runtime['int_max_str_digits']!=provenance['int_max_str_digits']
            or runtime['frame_depth']>provenance['observed_source_callstack_depth']):
        raise ValueError('Original-oracle limits/callstack budget changed before late comparison')
    return tuple.__getitem__(ref,1)


def _compare(live,ref,runtime):
    _deny_reentry()
    root=_approved(ref,runtime)
    _BUSY.active=True;_BUSY.reentered=False
    stats=dict(nodes=0,maps=0,sequences=0,scalars=0,mapping_keys_checked=0,mapping_lookups=0,
        sequence_items=0,max_depth=0,ordinary_mismatches=0)
    equal=True;active=set();pending=[('visit',live,root,0)]
    def mismatch():
        nonlocal equal
        equal=False;stats['ordinary_mismatches']+=1
    try:
        while pending:
            action,*args=pending.pop()
            if action=='leave':active.remove(args[0]);continue
            if action=='next_sequence':
                iterator,expected,index,depth=args
                try:child=next(iterator)
                except StopIteration:
                    if index!=len(expected):mismatch()
                    continue
                stats['sequence_items']+=1
                pending.append(('next_sequence',iterator,expected,index+1,depth))
                pending.append(('visit',child,expected[index] if index<len(expected) else _MISSING,depth+1));continue
            if action=='next_map':
                value,keys,expected,index,depth=args
                try:raw_key=next(keys)
                except StopIteration:
                    if index!=len(expected):mismatch()
                    continue
                # The original first scan checked exact strings, but an active
                # proxy can yield a str subclass on its second iteration.
                # JSON uses its underlying Unicode, not overloaded equality,
                # __str__ or encode. Keep the original key for the lookup.
                key=str.__str__(raw_key);_text(key)
                child=value[raw_key];stats['mapping_lookups']+=1
                match=index<len(expected) and key==expected[index][0]
                if not match:mismatch()
                pending.append(('next_map',value,keys,expected,index+1,depth))
                pending.append(('visit',child,expected[index][1] if match else _MISSING,depth+1));continue
            value,expected,depth=args;stats['nodes']+=1;stats['max_depth']=max(stats['max_depth'],depth)
            # A dynamic proxy may manufacture infinitely many fresh containers.
            # This ceiling is looser than original recursive canonical permits;
            # matching trees additionally require same-call oracle approval.
            if depth>runtime['recursion_limit']:raise RecursionError('Live typed traversal exceeds original runtime budget')
            kind=type(value)
            if value is None:tag='none';payload=None
            elif kind is bool:tag='bool';payload=value
            elif kind is int:tag='int';payload=str(value)
            elif kind is float:
                if not math.isfinite(value):raise ValueError('Nonfinite semantic value')
                tag='float';payload=value.hex()
            elif kind is str:_text(value);tag='str';payload=value
            elif kind is list or kind is tuple:tag=kind.__name__;payload=None
            elif kind is dict or kind is MappingProxyType:tag='map';payload=None
            else:raise ValueError('Unsupported mutable or custom semantic value')
            matches=expected is not _MISSING and expected[0]==tag
            if not matches:mismatch()
            if tag not in ('map','list','tuple'):
                stats['scalars']+=1
                if matches and tag!='none' and payload!=expected[1]:mismatch()
                continue
            identity=id(value)
            if identity in active:raise ValueError('Cyclic semantic graph')
            active.add(identity);pending.append(('leave',identity))
            if tag in ('list','tuple'):
                stats['sequences']+=1
                pending.append(('next_sequence',iter(value),expected[1] if matches else (),0,depth))
            else:
                stats['maps']+=1
                def key_ok(key):
                    stats['mapping_keys_checked']+=1;return type(key) is str
                # Deliberately the original protocol: all-key scan, sorted(v),
                # then v[k] in sorted order. NO extra live len()/items() call.
                if not all(key_ok(key) for key in value):raise ValueError('Non-string semantic key')
                keys=sorted(value)
                pending.append(('next_map',value,iter(keys),expected[1] if matches else (),0,depth))
        if _BUSY.reentered:raise RuntimeError('A caught nested comparison invalidated the outer comparison')
        return equal,stats
    finally:
        _BUSY.active=False;_BUSY.reentered=False


def _deny_reentry():
    if getattr(_BUSY,'active',False):
        _BUSY.reentered=True
        raise RuntimeError('Reentrant late comparison is forbidden')


def compare_with_stats(live,ref,*,runtime=None):
    """Full selected-root traversal; False only after every supported live tail."""
    _deny_reentry();current=capture_runtime(skip=1)
    if runtime is not None and _runtime(runtime)!=current:raise ValueError('Late callsite attestation differs from current runtime')
    result=_compare(live,ref,current)
    if capture_runtime(skip=1)!=current:raise ValueError('Original-oracle runtime changed during complete late comparison')
    return result


def compare_full(live,ref,*,runtime=None):
    """Same engine as compare_with_stats; no wrapper call changes the budget."""
    _deny_reentry();current=capture_runtime(skip=1)
    if runtime is not None and _runtime(runtime)!=current:raise ValueError('Late callsite attestation differs from current runtime')
    result=_compare(live,ref,current)[0]
    if capture_runtime(skip=1)!=current:raise ValueError('Original-oracle runtime changed during complete late comparison')
    return result
