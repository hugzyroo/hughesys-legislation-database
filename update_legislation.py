"""Download NT official consolidated PDF reprints and rebuild Hughesy's offline reader.
Run on a computer with internet. No scraping of non-official sources.
"""
import argparse, datetime as dt, hashlib, html, json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import fitz

BASE='https://legislation.nt.gov.au'
PORTAL=BASE+'/en/LegislationPortal/Acts/By-Title?status=inforce'
HERE=Path(__file__).resolve().parent
DEFAULT=['Police Administration Act 1978','Criminal Code Act 1983','Mental Health and Related Services Act 1998','Trespass Act 2023','Traffic Act 1987','Domestic and Family Violence Act 2007','Liquor Act 2019','Weapons Control Act 2001','Firearms Act 1997']
HEADERS={'User-Agent':'HughesysLegislationPersonalReference/1.0 (official documents only)'}

def get(session,url):
    r=session.get(url,timeout=60,headers=HEADERS);r.raise_for_status();return r

def catalog(session):
    soup=BeautifulSoup(get(session,PORTAL).text,'html.parser')
    acts={}
    for a in soup.select('a[href]'):
        name=' '.join(a.get_text(' ',strip=True).split())
        href=urljoin(PORTAL,a['href'])
        if re.search(r'\bACT\s+\d{4}\b',name,re.I) and '/Legislation/' in href and '/Acts/' not in href:
            acts[name.casefold()]=(name,href)
    if len(acts)<100:raise RuntimeError(f'Official catalogue returned only {len(acts)} Acts; site format may have changed')
    return acts

def pdf_for_act(session,url):
    soup=BeautifulSoup(get(session,url).text,'html.parser')
    candidates=[]
    for a in soup.select('a[href]'):
        href=urljoin(url,a['href']);label=a.get_text(' ',strip=True).lower()
        if '.pdf' in href.lower() or 'pdfversion' in label:
            candidates.append(href)
    if not candidates:raise RuntimeError('No official PDF link found on Act details page')
    return candidates[0]

def extract_sections(pdf_bytes):
    doc=fitz.open(stream=pdf_bytes,filetype='pdf')
    if len(doc)<2:raise RuntimeError('PDF has fewer than two pages')
    pages=[p.get_text(sort=True) for p in doc]
    if sum(map(len,pages))<1200:raise RuntimeError('PDF text extraction empty (possibly scanned)')
    # Locate main body, skipping front matter headed Table of provisions.
    first=next((i for i,t in enumerate(pages) if re.search(r'(?im)^\s*1\s*\n\s*Short title\s*$',t) and 'Table of provisions' not in t),None)
    if first is None:
        first=next((i for i,t in enumerate(pages) if re.search(r'(?im)^\s*1\s*\n\s*(?:Short title|Citation|Definitions)\s*$',t) and 'Table of provisions' not in t),None)
    if first is None:raise RuntimeError('Could not reliably identify beginning of provisions; leaving existing Act unchanged')
    text='\n'.join(pages[first:]); lines=text.splitlines()
    # Official NT PDFs commonly place the section number on its own line, followed by heading.
    # Exclude common non-section lines and avoid accepting repeated page headers.
    candidates=[]
    for i in range(len(lines)-1):
        n=lines[i].strip();title=lines[i+1].strip()
        if not re.fullmatch(r'\d{1,3}[A-Z]{0,3}',n):continue
        if not (3<=len(title)<=125) or not re.match(r'^[A-Z]',title):continue
        if re.search(r'^(Part |Division |Subdivision |Schedule |Chapter |Northern Territory|As in force|Table of)',title,re.I):continue
        if title.endswith('.') or re.fullmatch(r'\d+',title):continue
        candidates.append((i,n,title))
    # Monotonic section ordering; retain alphanumeric insertions (e.g. 43AB).
    sections=[];lastnum=0
    for k,(i,n,title) in enumerate(candidates):
        num=int(re.match(r'\d+',n).group())
        if num<lastnum or num>lastnum+60:continue
        if sections and sections[-1]['id']==n:continue
        if num==1 and title.lower() not in ('short title','citation'):continue
        if num==lastnum and not re.search('[A-Z]',n):continue
        end=candidates[k+1][0] if k+1<len(candidates) else len(lines)
        body='\n'.join(lines[i+2:end]).strip()
        if len(body)<12:continue
        sections.append({'id':n,'title':title,'text':body});lastnum=num
    if len(sections)<3 or sections[0]['id']!='1':raise RuntimeError('Section extraction did not pass basic validation')
    # For larger Acts, reject suspiciously short extraction to prevent corrupt imports.
    if len(text)>50000 and len(sections)<15:raise RuntimeError('Large PDF yielded too few sections; manual review needed')
    return sections,len(doc)

def main():
    ap=argparse.ArgumentParser(description='Import official NT Acts and rebuild offline legislation database')
    ap.add_argument('--all',action='store_true',help='Attempt every Act on official portal (may take a long time)')
    ap.add_argument('--act',action='append',help='Import a particular Act by its official title (repeatable)')
    ap.add_argument('--limit',type=int,default=0,help='Limit number of Acts processed (useful for testing)')
    args=ap.parse_args()
    session=requests.Session();print('Checking official NT Acts catalogue...')
    try:listing=catalog(session)
    except Exception as e:print('FAILED:',e);return 1
    requested=sorted(x[0] for x in listing.values()) if args.all else (args.act or json.loads((HERE/'tracked_acts.json').read_text(encoding='utf8')))
    if args.limit:requested=requested[:args.limit]
    source=(HERE/'index.html').read_text(encoding='utf8');start=source.index('const ACTS=')+len('const ACTS=')
    old,end=json.JSONDecoder().raw_decode(source[start:]);byname={x['name'].casefold():x for x in old}
    manifest=[];success=0
    previous={}
    previous_path=HERE/'version_manifest.json'
    if previous_path.exists():
        try: previous={item['name'].casefold():item for item in json.loads(previous_path.read_text()).get('results',[]) if item.get('status') in ('imported','unchanged')}
        except Exception: previous={}
    for index,name in enumerate(requested,1):
        key=name.casefold();match=listing.get(key)
        if not match:
            print(f'[{index}/{len(requested)}] NOT FOUND: {name}');manifest.append({'name':name,'status':'not_found'});continue
        realname,url=match
        print(f'[{index}/{len(requested)}] {realname} ... ',end='',flush=True)
        try:
            pdfurl=pdf_for_act(session,url)
            raw=get(session,pdfurl).content
            if not raw.startswith(b'%PDF'):raise RuntimeError('Downloaded document is not a PDF')
            digest=hashlib.sha256(raw).hexdigest()
            if previous.get(key,{}).get('sha256')==digest and key in byname:
                manifest.append({**previous[key],'status':'unchanged','checked_utc':dt.datetime.now(dt.timezone.utc).isoformat()})
                print('UNCHANGED');continue
            sections,pages=extract_sections(raw)
            old_count=len(byname.get(key,{}).get('sections',[]))
            if old_count>=20 and len(sections)<old_count*0.6:
                raise RuntimeError(f'Extraction only yielded {len(sections)} sections versus {old_count} previously; manual review required')
            record={'name':realname.title(),'date':'Official NT portal retrieval '+dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d UTC'), 'sections':sections}
            byname[key]=record
            manifest.append({'name':realname,'status':'imported','sections':len(sections),'pages':pages,'sha256':digest,'source_page':url,'pdf_url':pdfurl,'retrieved_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'validation':'automated extraction; verify against official PDF'})
            success+=1;print(f'OK: {len(sections)} sections')
        except Exception as e:
            manifest.append({'name':realname,'status':'failed','reason':str(e),'source_page':url});print('FAILED:',e)
        time.sleep(0.2)
    updated=list(byname.values());updated.sort(key=lambda x:x['name'].casefold())
    result=source[:start]+json.dumps(updated,ensure_ascii=False,separators=(',',':'))+source[start+end:]
    out=HERE/'candidate_index.html'
    out.write_text(result,encoding='utf8')
    report={'catalogue_count':len(listing),'successful_imports':success,'checked_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'results':manifest}
    (HERE/'candidate_report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(f'\nSaved {out.name}: {len(updated)} Acts ({success} imported from official PDFs this run).')
    print('IMPORTANT: This is a CANDIDATE only. Review extracted sections against official PDFs before publishing.')
    return 0

if __name__=='__main__':sys.exit(main())
