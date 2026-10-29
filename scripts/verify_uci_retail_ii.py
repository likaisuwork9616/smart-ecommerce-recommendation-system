"""Independently decode XLSX XML and reconcile the saved intake; no openpyxl import."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile

getcontext().prec = 50
ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / 'data/raw/online_retail_ii/online_retail_II.xlsx'
DATABASE = ROOT / 'shop-mysql-runtime/uci_retail_ii_intake_v1/inventory.sqlite'
REPORT = ROOT / 'reports/stage6/uci_retail_ii_intake.json'
OUTPUT = ROOT / 'reports/stage6/uci_retail_ii_verification.json'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
FIELDS = ['invoice', 'stock', 'description', 'quantity', 'ts', 'price', 'customer', 'country']
HEADERS = ['Invoice', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID', 'Country']


def descriptor(path):
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest}


def normalized(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (int, float)):
        return format(Decimal(str(value)).normalize(), 'f')
    return str(value)


def read_xml_rows(archive, member, strings):
    with archive.open(member) as source:
        context = ET.iterparse(source, events=('start', 'end'))
        _, root = next(context)
        for event, element in context:
            if event != 'end' or element.tag != '{' + NS['s'] + '}row':
                continue
            values = [None] * 8
            row_number = int(element.attrib['r'])
            for cell in element.findall('s:c', NS):
                reference = cell.attrib['r']
                letters = ''.join(c for c in reference if c.isalpha())
                assert letters in 'ABCDEFGH' and len(letters) == 1, 'Unexpected column'
                column = ord(letters) - ord('A')
                assert cell.find('s:f', NS) is None, 'Formula requires explicit review'
                value = cell.find('s:v', NS)
                kind = cell.get('t', 'n')
                if kind == 'inlineStr':
                    decoded = ''.join(t.text or '' for t in cell.findall('.//s:t', NS))
                elif value is None or value.text is None:
                    decoded = None
                elif kind == 's':
                    decoded = strings[int(value.text)]
                elif kind == 'n':
                    raw = value.text
                    decoded = float(raw) if any(c in raw for c in '.eE') else int(raw)
                else:
                    raise ValueError('Unsupported source cell type: ' + kind)
                if row_number > 1 and column == 4 and isinstance(decoded, (int, float)):
                    # All source dates use the workbook's default 1900 date system.
                    days, fraction = divmod(decoded, 1)
                    decoded = (datetime(1899, 12, 30) + timedelta(days=days,
                               milliseconds=round(fraction * 86_400_000))).isoformat(sep=' ')
                values[column] = normalized(decoded)
            yield row_number, values
            element.clear()
            root.clear()


def run():
    started = time.perf_counter()
    if OUTPUT.exists():
        raise FileExistsError('Preserve the existing independent verification receipt')
    sources = [descriptor(p) for p in (WORKBOOK, DATABASE, REPORT, Path(__file__))]
    report = json.loads(REPORT.read_text(encoding='utf-8'))['results']
    db = sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA temp_store=MEMORY')
    checks = []

    def equal(label, actual, expected):
        if actual != expected:
            raise AssertionError(label + ' differs')
        checks.append(label)

    counts = Counter()
    missing = Counter()
    monthly = defaultdict(lambda: {'rows': 0, 'amount': Decimal(0), 'missing': 0, 'cancel': 0,
                                   'days': set(), 'min': None, 'max': None})
    signs = defaultdict(lambda: [0, Decimal(0)])
    total = Decimal(0)
    cells = 0
    with zipfile.ZipFile(WORKBOOK) as archive:
        strings = [''.join(t.text or '' for t in item.findall('.//s:t', NS))
                   for item in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        properties = book.find('s:workbookPr', NS)
        assert properties is None or properties.get('date1904', '0') in ('0', 'false')
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        for sheet in book.findall('s:sheets/s:sheet', NS):
            name = sheet.get('name')
            relation = sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target = rels[relation]
            member = target.lstrip('/') if target.startswith('/') else str(PurePosixPath('xl') / target)
            source_rows = read_xml_rows(archive, member, strings)
            header_row, header = next(source_rows)
            equal(name + ': physical header row', header_row, 1)
            equal(name + ': headers', header, HEADERS)
            saved = db.execute('SELECT excel_row,' + ','.join(FIELDS) + ' FROM rows WHERE sheet=? ORDER BY excel_row', (name,))
            n = 0
            for row_number, values in source_rows:
                stored = saved.fetchone()
                if stored is None or stored != (row_number, *values):
                    raise AssertionError(f'Source/SQLite mismatch: {name}, row {row_number}')
                cells += 8
                n += 1
                for field, value in zip(FIELDS, values):
                    missing[field] += value is None
                invoice, stock, description, quantity, timestamp, price, customer, country = values
                q, p = Decimal(quantity), Decimal(price)
                amount = q * p
                total += amount
                cancel = invoice.upper().startswith('C')
                qsign, psign = (q > 0) - (q < 0), (p > 0) - (p < 0)
                signs[(cancel, qsign, psign)][0] += 1
                signs[(cancel, qsign, psign)][1] += amount
                counts['cancel'] += cancel
                counts['negative_without_c'] += q < 0 and not cancel
                counts['zero_price'] += p == 0
                counts['negative_price'] += p < 0
                counts['zero_quantity'] += q == 0
                counts['sub_penny_price'] += p.normalize().as_tuple().exponent < -2
                month = monthly[timestamp[:7]]
                month['rows'] += 1
                month['amount'] += amount
                month['missing'] += customer is None
                month['cancel'] += cancel
                month['days'].add(timestamp[:10])
                month['min'] = timestamp if month['min'] is None else min(month['min'], timestamp)
                month['max'] = timestamp if month['max'] is None else max(month['max'], timestamp)
                if n % 250000 == 0:
                    print(json.dumps({'independent_xml_sheet': name, 'rows_checked': n}), flush=True)
            equal(name + ': no extra saved rows', saved.fetchone(), None)
            equal(name + ': row count', n, next(t['rows'] for t in report['tables'] if t['sheet'] == name))
            counts['rows'] += n
    equal('raw rows', counts['rows'], report['raw']['rows'])
    equal('raw signed amount', total, Decimal(report['raw']['signed_line_amount_GBP']))
    equal('missing cells', dict(missing), report['missing_cells'])
    for counter, issue in [('cancel', 'cancellation_prefix'), ('negative_without_c', 'negative_quantity_without_cancellation_prefix'),
                           ('zero_price', 'zero_price'), ('negative_price', 'negative_price'), ('zero_quantity', 'zero_quantity')]:
        equal(issue, counts[counter], report['quality_issues'][issue]['rows'])
    equal('sub-penny prices', counts['sub_penny_price'], report['quality_issues']['price_more_than_two_decimal_places_rows'])
    equal('monthly coverage length', len(monthly), len(report['monthly_coverage']))
    for month in report['monthly_coverage']:
        key = month['month']
        actual = monthly[key]
        for label, a, b in [('rows', actual['rows'], month['raw']['rows']),
                            ('amount', actual['amount'], Decimal(month['raw']['signed_line_amount_GBP'])),
                            ('missing', actual['missing'], month['missing_customer_rows']),
                            ('cancel', actual['cancel'], month['cancellation_rows']),
                            ('days', len(actual['days']), month['observed_calendar_days']),
                            ('min', actual['min'], month['first_event']), ('max', actual['max'], month['last_event'])]:
            equal(key + ': ' + label, a, b)
    equal('sign matrix length', len(signs), len(report['cancellation_quantity_price_sign_matrix']))
    for entry in report['cancellation_quantity_price_sign_matrix']:
        key = entry['cancellation_prefix'], entry['quantity_sign'], entry['price_sign']
        equal('sign matrix rows ' + str(key), signs[key][0], entry['rows'])
        equal('sign matrix amount ' + str(key), signs[key][1], Decimal(entry['signed_line_amount_GBP']))
    # Group original decoded columns, independently of the audit's SHA-256 row signatures.
    field_group = ','.join(FIELDS)
    distinct, groups, excess, cross = db.execute(
        'SELECT COUNT(*),SUM(n>1),SUM(n-1),SUM(sheets-1) FROM '
        '(SELECT COUNT(*) n,COUNT(DISTINCT sheet) sheets FROM rows GROUP BY ' + field_group + ')').fetchone()
    duplicates = report['duplicates']
    for key, actual in [('distinct_eight_field_rows', distinct), ('duplicate_groups', groups),
                        ('duplicate_excess_rows', excess), ('cross_sheet_duplicate_excess_after_within_sheet_dedup', cross),
                        ('within_sheet_duplicate_excess', excess-cross)]:
        equal('column grouping: ' + key, actual, duplicates[key])
    db.close()
    for source in sources:
        equal('unchanged bytes: ' + source['path'], descriptor(ROOT / source['path']), source)
    receipt = {'status': 'passed', 'method': 'stdlib ZIP/XML decode, all eight fields against SQLite; independent Decimal monthly/sign aggregates; SQL group by actual eight fields, not row signature',
               'source_rows_compared': counts['rows'], 'source_cells_compared': cells,
               'aggregate_and_integrity_checks': len(checks), 'checks': checks,
               'raw_signed_line_amount_GBP': format(total, 'f'), 'sources': sources,
               'elapsed_seconds': round(time.perf_counter()-started, 3),
               'limits': 'Verifies intake extraction and listed aggregates, not historical visibility, transaction truth or a finalized RFM dataset.'}
    with OUTPUT.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(receipt, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('sources', 'checks')}), flush=True)


if __name__ == '__main__':
    run()
