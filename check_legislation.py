#!/usr/bin/env python3
"""Check official NT legislation pages for changes; never alter legal text."""
import datetime as dt, hashlib, json, os, re, sys, time
from pathlib import Path
from urllib.parse import quote, urljoin
import requests
from bs4 import BeautifulSoup

BASE='https://legislation.nt.gov.au'
ROOT=Path(__file__).resolve().parent
HEADERS={'User-Agent':'HughesysLegislationUpdateChecker/1.0','Accept':'text/html,application/pdf'}

def fetch(session,url):
    r=session.get(url,headers=HEADERS,timeout=45);r.raise_for_status();return r

def check(session,name):
    slug=name.upper().replace(' ','-')
    url=f'{BASE}/en/Legislation/{quote(slug)}'
    r=fetch(session,url)
    soup=BeautifulSoup(r.text,'html.parser')
    text=' '.join(soup.stripped_strings)
    if len(text)<250 or ('legislation' not in text.lower() and 'firearms' not in text.lower()):
        raise ValueError('Official Act page appears empty or invalid')
    # Extract only explicit consolidated/reprint PDF links. Never hash whole HTML,
    # since page chrome, banners and timestamps can change without amending an Act.
    links=[]
    for a in soup.select('a[href]'):
        href=urljoin(r.url,a['href']);label=' '.join(a.stripped_strings)
        if '.pdf' in href.lower() or ('pdf' in label.lower() and 'version' in label.lower()):
            links.append((href,label))
    if not links:
        raise ValueError('No PDF link found: portal may have changed; manual check required')
    # Prefer the current consolidated PDF shown first by the portal.
    pdf_url=links[0][0]
    p=fetch(session,pdf_url)
    if not p.content.startswith(b'%PDF'):
        raise ValueError('Linked resource is not a PDF')
    if len(p.content)<1000:raise ValueError('Suspiciously short PDF')
    return {'name':name,'official_page':r.url,'pdf_url':p.url,
            'sha256':hashlib.sha256(p.content).hexdigest(),
            'pdf_bytes':len(p.content)}

def main():
    names=json.loads((ROOT/'tracked_acts.json').read_text())
    path=ROOT/'legislation_versions.json'
    old=json.loads(path.read_text()) if path.exists() else {}
    new=dict(old);changes=[];errors=[];verified=[]
    session=requests.Session()
    for name in names:
        try:
            result=check(session,name)
            previous=old.get(name)
            new[name]=result
            verified.append(name)
            if previous and previous.get('sha256')!=result['sha256']:
                changes.append({'name':name,'previous_sha256':previous['sha256'],**result})
            print('CHANGED' if changes and changes[-1]['name']==name else 'CHECKED',name,flush=True)
        except Exception as e:
            errors.append({'name':name,'error':str(e)})
            print('ERROR',name,str(e),flush=True)
        time.sleep(0.4)
    report={'checked_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'checked':len(verified),'tracked':len(names),'changes':changes,'errors':errors,
            'baseline_created':not bool(old)}
    (ROOT/'legislation_check_report.json').write_text(json.dumps(report,indent=2)+'\n')
    path.write_text(json.dumps(new,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'checked':len(verified),'changed':len(changes),'errors':len(errors)},indent=2))
    # Fail when any Act cannot be verified, to surface errors in Actions.
    return 1 if errors else 0
if __name__=='__main__':sys.exit(main())
