"""Versioned complete C1-S1 snapshot encoding; no source checks or rankings are replaced."""
from contextlib import nullcontext
import hashlib
import json
import re
from types import MappingProxyType

from scripts.retailrocket_session_knn_sql_v2 import FrozenCatalog

SCHEME='K1-C1-S1-SNAPSHOT-v1'
PREFIX=(SCHEME+'\n').encode('utf-8')
_ID=re.compile(r'(?:0|[1-9][0-9]*)',re.ASCII)


def _span(observer,name):
    return observer.span(name,scheme=SCHEME) if observer is not None else nullcontext()


def _identifier(value):
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError('Expected a canonical ASCII nonnegative decimal string ID')


def _integer(value):
    if type(value) is not int or value<0:
        raise ValueError('Expected an exact nonnegative integer; bool/float are forbidden')


def _rows(prepared,watch):
    if type(prepared) is not FrozenCatalog:
        raise ValueError('Exact accepted FrozenCatalog required')
    try:first,counts,times,fallback=(prepared.first,prepared.counts,prepared.first_times,prepared.fallback)
    except AttributeError as error:raise ValueError('All four snapshot fields required') from error
    if (type(first) is not MappingProxyType or type(counts) is not MappingProxyType
            or type(times) is not tuple or type(fallback) is not tuple):
        raise ValueError('Exact read-only mappings and tuple fields required')
    result=[]
    for name,mapping in (('first',first),('counts',counts)):
        rows=[]
        for item,value in mapping.items():
            watch();_identifier(item);_integer(value);rows.append((item,value))
        rows.sort(key=lambda row:row[0])
        result.append((name,rows))
    copied_times=[]
    for value in times:
        watch();_integer(value);copied_times.append(value)
    copied_fallback=[]
    for item in fallback:
        watch();_identifier(item);copied_fallback.append(item)
    # These sequences intentionally preserve every value and position, including repeats.
    result.extend((('first_times',copied_times),('fallback',copied_fallback)))
    watch()
    return result


def _encode(prepared,observer,watch):
    with _span(observer,'snapshot.validation'):values=_rows(prepared,watch)
    with _span(observer,'snapshot.json'):
        watch();text=json.dumps(values,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    with _span(observer,'snapshot.utf8'):
        watch();data=PREFIX+text.encode('utf-8')
    with _span(observer,'snapshot.release'):
        del text,values
    return data


def encode_snapshot(prepared,observer=None,watch=lambda:None):
    """Return exact complete prefixed preimage bytes for diagnostics and equivalence tests."""
    with _span(observer,'snapshot.encode'):
        return _encode(prepared,observer,watch)


def fingerprint(prepared,observer=None,watch=lambda:None):
    """Validate and encode the current live object every time; never reuse encoded bytes."""
    with _span(observer,'snapshot.fingerprint'):
        data=_encode(prepared,observer,watch)
        with _span(observer,'snapshot.sha256'):
            watch();result=hashlib.sha256(data).hexdigest()
        with _span(observer,'snapshot.release'):
            del data
        return result
