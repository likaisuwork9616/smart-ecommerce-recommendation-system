"""Download the official UCI 502 package inside this project, without overwriting."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data/raw/online_retail_ii'
URL = 'https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip'
PAGE = 'https://archive.ics.uci.edu/dataset/502/online+retail+ii'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    assert DEST.resolve().is_relative_to(ROOT.resolve())
    DEST.mkdir(parents=True, exist_ok=True)
    archive = DEST / 'online_retail_ii_official.zip'
    workbook = DEST / 'online_retail_II.xlsx'
    partial = archive.with_suffix('.zip.partial')
    manifest = DEST / 'source_manifest.json'
    if any(p.exists() for p in (archive, workbook, partial, manifest, DEST/'source_page.html')):
        raise FileExistsError('Existing intake files: preserve them; use the audit for verification')
    started = datetime.now(timezone.utc).isoformat()
    headers = {'User-Agent':'Mozilla/5.0', 'Accept-Encoding':'identity'}
    with urllib.request.urlopen(urllib.request.Request(URL, headers=headers), timeout=60) as response:
        if response.status != 200:
            raise ValueError('Full download requires HTTP 200')
        expected_length = response.headers.get('Content-Length')
        total = 0
        with partial.open('xb') as stream:
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > 100*1024*1024:
                    raise ValueError('Unexpected package larger than 100 MiB')
                stream.write(chunk)
        if expected_length is not None and total != int(expected_length):
            raise ValueError('Truncated HTTP body')
    with zipfile.ZipFile(partial) as package:
        if package.testzip() is not None:
            raise ValueError('Official package CRC failed')
        files = [x for x in package.infolist() if not x.is_dir()]
        if len(files) != 1 or files[0].filename != workbook.name:
            raise ValueError('Unexpected archive members; inspect without extracting')
        with package.open(files[0]) as source, workbook.open('xb') as output:
            shutil.copyfileobj(source, output)
    with zipfile.ZipFile(workbook) as inner:
        if inner.testzip() is not None:
            raise ValueError('Workbook container CRC failed')
        if 'xl/workbook.xml' not in inner.namelist():
            raise ValueError('Not an XLSX workbook')
    partial.rename(archive)
    with urllib.request.urlopen(urllib.request.Request(PAGE, headers=headers), timeout=45) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('Unexpectedly large source page')
    (DEST/'source_page.html').write_bytes(body)
    result = {'dataset':'UCI Online Retail II (502)', 'doi':'10.24432/C5CG6D',
              'attribution':'Chen, D. (2012). Online Retail II. UCI Machine Learning Repository.',
              'source_url':URL,'source_page':PAGE,'license_on_source_page':'CC BY 4.0',
              'download_started_utc':started,'download_completed_utc':datetime.now(timezone.utc).isoformat(),
              'http_content_length':expected_length,'complete_download_bytes':total,
              'outer_zip_crc_passed':True,'xlsx_container_crc_passed':True,
              'sha256_role':'Locally computed version pins, not a separately published UCI checksum.',
              'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
                       for p in (archive,workbook,DEST/'source_page.html')]}
    with manifest.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
