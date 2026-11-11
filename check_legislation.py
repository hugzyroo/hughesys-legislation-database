#!/usr/bin/env python3
"""Monitor official NT consolidated Act PDFs; never update the app's legal text."""
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE = 'https://legislation.nt.gov.au'
ROOT = Path(__file__).resolve().parent
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; NTActsHubChecker/2.0)', 'Accept': 'text/html,application/pdf,*/*'}


def slugs(name):
    # Official portal titles sometimes omit year or punctuation.
    variants = [name, re.sub(r'\s+\d{4}$', '', name)]
    if name == 'Evidence (National Uniform Legislation) Act 2011':
        variants.append('Evidence National Uniform Legislation Act 2011')
    if name == 'Sexual Offences (Evidence and Procedure) Act 1983':
        variants.append('Sexual Offences Evidence and Procedure Act 1983')
    return list(dict.fromkeys(re.sub(r'[^A-Z0-9]+', '-', n.upper()).strip('-') for n in variants))


def fetch(session, url):
    response = session.get(url, headers=HEADERS, timeout=45)
    response.raise_for_status()
    return response


def discover_pdf_urls(html, page_url):
    """Find official Sitecore API downloads even though URLs don't end in .pdf."""
    soup = BeautifulSoup(html, 'html.parser')
    urls = []
    for a in soup.select('a[href], [data-url], [data-href]'):
        raw = a.get('href') or a.get('data-url') or a.get('data-href')
        if not raw:
            continue
        url = urljoin(page_url, raw.replace('&amp;', '&'))
        label = a.get_text(' ', strip=True).lower()
        low = url.lower()
        if ('/api/sitecore/act/pdf?' in low or '.pdf' in low or
                ('pdf' in label and ('/api/' in low or 'download' in low))):
            urls.append(url)
    # Also catch PDF API URLs embedded in attributes or inline page scripts.
    for match in re.findall(r'(?:https?://legislation\.nt\.gov\.au)?/api/sitecore/Act/PDF\?id=\d+', html, flags=re.I):
        urls.append(urljoin(BASE, match))
    # Only download PDFs from the official legislation host.
    return list(dict.fromkeys(u for u in urls if urlparse(u).hostname in ('legislation.nt.gov.au', 'www.legislation.nt.gov.au')))


def check(session, name):
    failures = []
    for slug in slugs(name):
        page = f'{BASE}/en/Legislation/{slug}'
        try:
            r = fetch(session, page)
            soup = BeautifulSoup(r.text, 'html.parser')
            # Guard against an unrelated page being accepted as this Act.
            title = soup.get_text(' ', strip=True).upper()
            if slug.replace('-', ' ') not in title and name.upper() not in title:
                raise ValueError('Page does not clearly identify the requested Act')
            pdf_urls = discover_pdf_urls(r.text, r.url)
            if not pdf_urls:
                raise ValueError('No official PDF download endpoint found')
            for pdf_url in pdf_urls:
                try:
                    pdf = fetch(session, pdf_url)
                    if not pdf.content.startswith(b'%PDF-') or len(pdf.content) < 1000:
                        raise ValueError('Response is not a valid-sized PDF')
                    return {'name': name, 'official_page': r.url, 'pdf_url': pdf.url,
                            'sha256': hashlib.sha256(pdf.content).hexdigest(),
                            'pdf_bytes': len(pdf.content)}
                except Exception as exc:
                    failures.append(f'{pdf_url}: {exc}')
        except Exception as exc:
            failures.append(f'{page}: {exc}')
    raise ValueError('Could not verify official consolidated PDF; ' + ' | '.join(failures[:4]))


def main():
    names = json.loads((ROOT / 'tracked_acts.json').read_text(encoding='utf-8'))
    versions = ROOT / 'legislation_versions.json'
    old = json.loads(versions.read_text(encoding='utf-8')) if versions.exists() else {}
    new = dict(old)
    changes, errors, verified = [], [], []
    session = requests.Session()
    for name in names:
        try:
            result = check(session, name)
            previous = old.get(name)
            new[name] = result
            verified.append(name)
            if previous and previous.get('sha256') != result['sha256']:
                changes.append({'name': name, 'previous_sha256': previous.get('sha256'), **result})
            print('CHANGED' if changes and changes[-1]['name'] == name else 'CHECKED', name, flush=True)
        except Exception as exc:
            errors.append({'name': name, 'error': str(exc)})
            print('ERROR', name, str(exc), flush=True)
        time.sleep(0.4)
    report = {'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'checked': len(verified), 'tracked': len(names), 'changes': changes,
              'errors': errors, 'baseline_created': not bool(old)}
    (ROOT / 'legislation_check_report.json').write_text(json.dumps(report, indent=2) + '\n')
    versions.write_text(json.dumps(new, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'checked': len(verified), 'changed': len(changes), 'errors': len(errors)}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
