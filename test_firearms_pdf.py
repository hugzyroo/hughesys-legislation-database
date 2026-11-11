#!/usr/bin/env python3
"""Standalone, read-only diagnostic for the official Firearms Act PDF endpoint."""
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import requests

URL = 'https://legislation.nt.gov.au/api/sitecore/Act/PDF?id=11817'
REPORT = Path('firearms_pdf_test_report.json')


def main():
    result = {'url': URL, 'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'success': False}
    try:
        response = requests.get(URL, timeout=60, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; NTActsHub-UpdateCheck/1.0)',
            'Accept': 'application/pdf,*/*',
        })
        result.update(http_status=response.status_code,
                      content_type=response.headers.get('Content-Type', ''),
                      final_url=response.url,
                      size_bytes=len(response.content))
        response.raise_for_status()
        if not response.content.startswith(b'%PDF-'):
            raise ValueError('Response is not a PDF (missing %PDF- signature)')
        if len(response.content) < 10000:
            raise ValueError('PDF unexpectedly small')
        result.update(success=True, sha256=hashlib.sha256(response.content).hexdigest())
        print('SUCCESS: Official Firearms Act PDF downloaded and validated.')
        print('Size:', len(response.content), 'bytes')
        print('SHA-256:', result['sha256'])
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        print('FAILED:', result['error'], file=sys.stderr)
    finally:
        REPORT.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print('Report:', REPORT)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
