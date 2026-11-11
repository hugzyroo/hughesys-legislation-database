#!/usr/bin/env python3
"""Check official NT consolidated legislation PDFs; never modify the published app."""
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = 'https://legislation.nt.gov.au'
ROOT = Path(__file__).resolve().parent
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; NTActsHubVersionChecker/1.1)',
           'Accept': 'text/html,application/pdf,*/*'}

# The portal sometimes uses different titles/paths than the Act's formal name.
# Keep these aliases conservative: never silently substitute a different Act.
ALIASES = {
    'Evidence (National Uniform Legislation) Act 2011': ['Evidence (National Uniform Legislation) Act', 'Evidence National Uniform Legislation Act 2011'],
    'Sexual Offences (Evidence and Procedure) Act 1983': ['Sexual Offences (Evidence and Procedure) Act', 'Sexual Offences Evidence and Procedure Act 1983'],
}

def fetch(session, url):
    response = session.get(url, headers=HEADERS, timeout=45)
    response.raise_for_status()
    return response

def slugs(name):
    names = [name] + ALIASES.get(name, [])
    # Different NT portal entries can omit the year or the word 'Act'.
    names += [re.sub(r'\s+\d{4}$', '', name)]
    found = []
    for title in names:
        slug = re.sub(r'[^A-Z0-9]+', '-', title.upper()).strip('-')
        if slug and slug not in found:
            found.append(slug)
    return found

def candidates(name):
    return [f'{BASE}/en/Legislation/{quote(s)}' for s in slugs(name)]

def pdf_links(soup, page_url):
    links = []
    for tag in soup.select('[href], [data-href], [data-url]'):
        href = tag.get('href') or tag.get('data-href') or tag.get('data-url')
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            continue
        url = urljoin(page_url, href)
        if urlparse(url).netloc.lower() not in ('legislation.nt.gov.au', 'www.legislation.nt.gov.au'):
            continue
        label = ' '.join(tag.stripped_strings).lower()
        target = (url + ' ' + label).lower()
        if '.pdf' in target or '/media/' in target or 'download' in target or 'reprint' in target:
            score = (5 if 'current' in target or 'in force' in target else 0) + (3 if 'consolidat' in target or 'reprint' in target else 0) + (2 if '.pdf' in target else 0)
            links.append((score, url))
    # Prefer explicit current/reprint links, but never pretend the first link is verified.
    return [u for _, u in sorted(dict((u, score) for score, u in links).items(), key=lambda pair: -pair[1])]

def check(session, name):
    failures = []
    for page in candidates(name):
        try:
            response = fetch(session, page)
            if 'pdf' in response.headers.get('Content-Type', '').lower():
                raise ValueError('Act landing page unexpectedly returned a PDF')
            soup = BeautifulSoup(response.text, 'html.parser')
            if len(' '.join(soup.stripped_strings)) < 250:
                raise ValueError('Act page appears empty')
            links = pdf_links(soup, response.url)
            if not links:
                raise ValueError('No downloadable PDF link identified')
            for pdf_url in links[:12]:
                try:
                    pdf = fetch(session, pdf_url)
                    if not pdf.content.startswith(b'%PDF-') or len(pdf.content) < 1000:
                        continue
                    # Check document content, not unrelated HTML or site chrome.
                    return {'name': name, 'official_page': response.url,
                            'pdf_url': pdf.url, 'sha256': hashlib.sha256(pdf.content).hexdigest(),
                            'pdf_bytes': len(pdf.content)}
                except (requests.RequestException, ValueError):
                    continue
            raise ValueError('Page found but none of its PDF candidates was downloadable')
        except (requests.RequestException, ValueError) as exc:
            failures.append(f'{page}: {exc}')
    raise ValueError('Could not verify official consolidated PDF; attempted URLs: ' + ' | '.join(failures))

def main():
    names = json.loads((ROOT / 'tracked_acts.json').read_text(encoding='utf-8'))
    versions_path = ROOT / 'legislation_versions.json'
    old = json.loads(versions_path.read_text(encoding='utf-8')) if versions_path.exists() else {}
    new = dict(old)
    changes, errors, verified = [], [], []
    with requests.Session() as session:
        for name in names:
            try:
                result = check(session, name)
                previous = old.get(name)
                new[name] = result
                verified.append(name)
                if previous and previous.get('sha256') != result['sha256']:
                    changes.append({'name': name, 'previous_sha256': previous['sha256'], **result})
                print('CHANGED' if previous and previous.get('sha256') != result['sha256'] else 'CHECKED', name, flush=True)
            except Exception as exc:
                errors.append({'name': name, 'error': str(exc)})
                print('ERROR', name, str(exc), flush=True)
            time.sleep(0.4)
    report = {'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'checked': len(verified), 'tracked': len(names), 'changes': changes,
              'errors': errors, 'baseline_created': not bool(old)}
    (ROOT / 'legislation_check_report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    versions_path.write_text(json.dumps(new, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'checked': len(verified), 'changed': len(changes), 'errors': len(errors)}, indent=2))
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
