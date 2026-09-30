#!/usr/bin/env python3
import json
import os
import tempfile
from pathlib import Path

import app


def main():
 original_root, original_data = app.ROOT, app.DATA
 try:
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); app.ROOT=root; app.DATA=root/'data'; app.DATA.mkdir()
   doc=root/'resume.docx'; pdf=root/'resume.pdf'; doc.write_bytes(b'docx'); pdf.write_bytes(b'pdf')
   record={'application_id':'app_unicode','company_name':'Café — AI‑ML','job_title':'Python Engineer – ML','selected_projects':['AI‑ML project']}
   cases=[None,'','   ','{}','{"documents": "invalid"}','not json']
   for content in cases:
    path=app.DATA/'document_history.json'
    if content is None:
     if path.exists(): path.unlink()
    else: path.write_text(content,encoding='utf-8')
    assert app.load_document_history()=={'documents':[]}, content
    app.save_history(record,'resume',doc,pdf)
    raw=path.read_bytes(); assert raw.decode('utf-8')
    history=json.loads(raw.decode('utf-8')); assert len(history['documents'])==1
    assert history['documents'][0]['company']=='Café — AI‑ML'
    assert history['documents'][0]['selected_projects']==['AI‑ML project']
   existing={'documents':[{'application_id':'existing','company':'Existing','role':'Role'}]}
   app.save_document_history(existing)
   app.save_history(record,'resume',doc,pdf)
   history=app.load_document_history(); assert [x['application_id'] for x in history['documents']]==['existing','app_unicode']
   path=app.DATA/'document_history.json'; before=path.read_bytes(); original_replace=os.replace
   def failing_replace(src,dst): raise OSError('simulated atomic replacement failure')
   os.replace=failing_replace
   try:
    try: app.save_document_history({'documents':[{'application_id':'should_not_replace'}]})
    except OSError: pass
    else: raise AssertionError('atomic replacement failure was not propagated')
   finally: os.replace=original_replace
   assert path.read_bytes()==before, 'canonical history changed after failed replacement'
 finally:
  app.ROOT, app.DATA = original_root, original_data
 print('PASS document history missing/empty/whitespace/invalid recovery, UTF-8 Unicode, preservation, and atomic replacement')


if __name__=='__main__': main()
