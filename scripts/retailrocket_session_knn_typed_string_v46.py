"""Candidate string check for the V39 canonical decoder."""
from json.decoder import scanstring
import re

from scripts import retailrocket_session_knn_typed_v39 as original
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


# Find the first quote, escape, raw control character, or surrogate. All
# intervening characters have the same acceptance rule in the original loop.
_SPECIAL = re.compile(r'["\\\x00-\x1f\ud800-\udfff]')
_SHORT_ESCAPES = frozenset(('"', '\\', 'b', 'f', 'n', 'r', 't'))
_LOWER_HEX = frozenset('0123456789abcdef')
_SHORT_CONTROL_CODES = frozenset((8, 9, 10, 12, 13))


def scan_string(text, start):
    """Decode one token starting at the decoder's opening quote."""
    index = start + 1
    length = len(text)
    while True:
        match = _SPECIAL.search(text, index)
        if match is None:
            raise ValueError('Unterminated JSON string')
        index = match.start()
        special = text[index]
        if special == '"':
            value, end = scanstring(text, start + 1, True)
            if end != index + 1:
                raise ValueError('String boundary differs')
            return value, end
        if special != '\\':
            raise ValueError('Unencodable or unescaped JSON character')
        if index + 1 >= length:
            raise ValueError('Truncated JSON escape')
        escaped = text[index + 1]
        if escaped in _SHORT_ESCAPES:
            index += 2
            continue
        if escaped != 'u' or index + 6 > length:
            raise ValueError('Noncanonical JSON escape')
        digits = text[index + 2:index + 6]
        if not all(digit in _LOWER_HEX for digit in digits):
            raise ValueError('Canonical lowercase control escape required')
        value = int(digits, 16)
        if value > 31 or value in _SHORT_CONTROL_CODES:
            raise ValueError('Only canonical long control escapes are allowed')
        index += 6


decode = _clone(original._decode, _string=scan_string)
