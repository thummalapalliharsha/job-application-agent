#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import app
import application_assistant as aa


def main():
 original_root, original_data = app.ROOT, app.DATA
 original_aa_root, original_aa_data = aa.ROOT, aa.DATA
 try:
  with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'CAREER_OS_STORAGE_BACKEND':'file'}, clear=False):
   root=Path(td); app.ROOT=root; app.DATA=root/'data'; app.DATA.mkdir()
   aa.ROOT=root; aa.DATA=app.DATA
   doc=root/'resume.docx'; pdf=root/'resume.pdf'; doc.write_bytes(b'docx'); pdf.write_bytes(b'pdf')
   record={'application_id':'app_unicode','company_name':'Café — AI‑ML','job_title':'Python Engineer – ML','selected_projects':['AI‑ML project']}
   path=app.DATA/'document_history.json'
   assert app.load_document_history()=={'documents':[]}
   saved=app.save_history(record,'resume',doc,pdf)
   history=app.load_document_history()
   assert len(history['documents'])==1
   assert history['documents'][0]['document_id']==saved['document_id']
   assert history['documents'][0]['company']=='Café — AI‑ML'
   assert history['documents'][0]['selected_projects']==['AI‑ML project']
   for content in ('', '   ', '{}', '{"documents": "invalid"}', 'not json'):
    path.write_text(content,encoding='utf-8')
    original=path.read_bytes()
    try:
     app.load_document_history()
    except RuntimeError:
     pass
    else:
     raise AssertionError(f'malformed history was silently accepted: {content!r}')
    try:
     app.save_history(record,'resume',doc,pdf)
    except RuntimeError:
     pass
    else:
     raise AssertionError(f'malformed history was overwritten: {content!r}')
    try:
     app.save_document_history({'documents':[]})
    except RuntimeError:
     pass
    else:
     raise AssertionError(f'malformed history was replaced: {content!r}')
    assert path.read_bytes()==original
   existing={'documents':[{'application_id':'existing','company':'Existing','role':'Role'}]}
   path.unlink()
   app.save_document_history(existing)
   initial_id=app.load_document_history()['documents'][0]['document_id']
   app.save_history(record,'resume',doc,pdf)
   history=app.load_document_history(); assert [x['application_id'] for x in history['documents']]==['existing','app_unicode']
   assert history['documents'][0]['document_id']==initial_id
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
  aa.ROOT, aa.DATA = original_aa_root, original_aa_data
 print('PASS document history CRUD append, Unicode, stable IDs, malformed-file safety, and atomic replacement')


if __name__=='__main__': main()
