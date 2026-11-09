"""Read-only NT Acts source monitor. Never edits index.html or declares its text verified.

Reports official PDF SHA-256 and whether it differs from a reviewed baseline.
A successful source check is NOT verification of the app's stored provisions.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = 'https://legislation.nt.gov.au'
PORTAL = BASE + '/en/LegislationPortal/Acts/By-Title?status=inforce'
HERE = Path(__file__).resolve().parent
HEADERS = {'User-Agent': 'NTActsHubReferenceChecker/1.1 (official NT legislation only)'}

def fetch(session, url):
    if urlparse(url).hostname != 'legislation.nt.gov.au':
        raise ValueError('Refusing non-official URL: ' + url)
    response = session.get(url, timeout=65, headers=HEADERS)
    response.raise_for_status()
    if urlparse(response.url).hostname != 'legislation.nt.gov.au':
        raise ValueError('Redirected outside official portal')
    return response

def normalise(name):
    return re.sub(r'\s+', ' ', name).strip().casefold()

def catalog(session):
    soup = BeautifulSoup(fetch(session, PORTAL).text, 'html.parser')
    found = {}
    for a in soup.select('a[href]'):
        name = ' '.join(a.get_text(' ', strip=True).split())
        url = urljoin(PORTAL, a['href'])
        if re.search(r'\bAct\s+\d{4}\b', name, re.I) and urlparse(url).hostname == 'legislation.nt.gov.au':
            if '/Legislation/' in url and '/Acts/By-Title' not in url:
                found.setdefault(normalise(name), {'name': name, 'url': url})
    if len(found) < 100:
        raise RuntimeError(f'Official catalogue parser found only {len(found)} Acts; investigate site format before trusting results')
    return found

def pdf_link(session, detail_url):
    response = fetch(session, detail_url)
    if response.content.startswith(b'%PDF'):
        return response.url, response.content
    soup = BeautifulSoup(response.text, 'html.parser')
    candidates = []
    for a in soup.select('a[href]'):
        url = urljoin(detail_url, a['href'])
        label = a.get_text(' ', strip=True).lower()
        if urlparse(url).hostname != 'legislation.nt.gov.au':
            continue
        if '.pdf' in url.lower() or 'pdfversion' in label or 'pdf' == label:
            score = (3 if 'current' in label or 'in force' in label else 0) + (2 if 'consolidat' in label else 0) + (1 if '.pdf' in url.lower() else 0)
            candidates.append((score, url))
    if not candidates:
        raise RuntimeError('No official PDF candidate found; check detail page')
    candidates.sort(reverse=True)
    # Ambiguous links must be reviewed; do not silently choose a historical reprint.
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise RuntimeError('Multiple equally plausible PDFs; manual source selection required')
    pdf_url = candidates[0][1]
    return pdf_url, fetch(session, pdf_url).content

def run():
    parser = argparse.ArgumentParser(description='Read-only NT legislation source monitor')
    parser.add_argument('--act', action='append', help='Only check this exact Act title (repeatable)')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--baseline', default='verified_source_baseline.json', help='Previously reviewed official PDF digests')
    args = parser.parse_args()
    names = args.act or json.loads((HERE / 'tracked_acts.json').read_text(encoding='utf-8'))
    if args.limit: names = names[:args.limit]
    baseline_path = HERE / args.baseline
    baseline = json.loads(baseline_path.read_text(encoding='utf-8')) if baseline_path.exists() else {}
    if not isinstance(baseline, dict):
        raise ValueError('Baseline must be a JSON object mapping exact Act names to approved PDF SHA-256 digests')
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    results = []
    session = requests.Session()
    try:
        acts = catalog(session)
        for name in names:
            record = {'name': name, 'checked_utc': now, 'app_text_verified': False}
            try:
                item = acts.get(normalise(name))
                if not item:
                    raise RuntimeError('Act title not found in official catalogue')
                url, pdf = pdf_link(session, item['url'])
                if not pdf.startswith(b'%PDF') or len(pdf) < 1000:
                    raise RuntimeError('Downloaded content is not a valid-looking PDF')
                digest = hashlib.sha256(pdf).hexdigest()
                expected = baseline.get(name)
                if expected and not re.fullmatch(r'[a-fA-F0-9]{64}', expected):
                    raise RuntimeError('Invalid baseline SHA-256 for this Act')
                record.update(source_page=item['url'], pdf_url=url, sha256=digest, pdf_bytes=len(pdf))
                record['status'] = ('baseline_missing' if not expected else 'source_unchanged' if digest == expected else 'source_changed')
            except Exception as exc:
                record.update(status='check_failed', reason=str(exc))
            print(f"{name}: {record['status']}")
            results.append(record)
    except Exception as exc:
        print('Official catalogue unavailable:', exc, file=sys.stderr)
        results = [{'name': name, 'checked_utc': now, 'status': 'check_failed', 'reason': 'Catalogue error: ' + str(exc), 'app_text_verified': False} for name in names]
    report = {'checked_utc': now, 'monitor_type': 'official_pdf_change_detection_only', 'warning': 'No stored app legislation has been verified by this monitor. Do not auto-publish or mark Acts current.', 'results': results}
    output = HERE / 'candidate_report.json'
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('Report saved:', output)
    return 1 if any(r['status'] == 'check_failed' for r in results) else 0

if __name__ == '__main__':
    sys.exit(run())
