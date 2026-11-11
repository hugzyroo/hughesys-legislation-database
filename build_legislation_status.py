#!/usr/bin/env python3
"""Publish transparent, conservative status; never certify app content."""
import json
from pathlib import Path
p=Path(__file__).resolve().parent
report=json.loads((p/'legislation_check_report.json').read_text())
pending_path=p/'legislation_pending_review.json'
pending=json.loads(pending_path.read_text()) if pending_path.exists() else {}
if not isinstance(pending,dict):raise ValueError('Pending review must be an object')
for item in report['changes']:
 name=item['name']
 pending[name]={'detected_at_utc':report['checked_at_utc'],'pdf_sha256':item['sha256'],'official_page':item['official_page']}
# Never auto-clear pending changes. Human review is required.
pending_path.write_text(json.dumps(pending,indent=2,sort_keys=True)+'\n')
status={'checked_at_utc':report['checked_at_utc'],'checked':report['checked'],'tracked':report['tracked'], 'errors':len(report['errors']),'pending_count':len(pending),'pending_acts':sorted(pending),'source':'Official PDF fingerprint comparison; not a legal-text audit'}
(p/'legislation_status.json').write_text(json.dumps(status,indent=2)+'\n')
print('Status:',json.dumps(status))
