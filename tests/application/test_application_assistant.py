#!/usr/bin/env python3
import json, shutil, tempfile, hashlib, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT)); import application_assistant as a

def main():
 td=tempfile.TemporaryDirectory(); r=Path(td.name); (r/'data').mkdir(); (r/'job_descriptions').mkdir(); (r/'output/reports').mkdir(parents=True); (r/'output/cover_letters').mkdir(parents=True); (r/'output/resumes').mkdir(parents=True)
 for p in (ROOT/'data').glob('*.json'): shutil.copy2(p,r/'data'/p.name)
 old=(a.ROOT,a.DATA,a.JOBS,a.OUT,a.REPORTS,a.LETTERS,a.RESUMES); a.ROOT=r; a.DATA=r/'data'; a.JOBS=r/'job_descriptions'; a.OUT=r/'output'; a.REPORTS=r/'output/reports'; a.LETTERS=r/'output/cover_letters'; a.RESUMES=r/'output/resumes'
 results=[]
 def ck(n,v,d=''): results.append({'test':n,'passed':bool(v),'detail':d})
 jd='Junior Generative AI RAG Engineer\nRequired Skills:\n- Python\n- RAG\n- vector database\nPreferred Skills:\n- LangChain\nResponsibilities:\n- Build retrieval pipelines.'
 try:
  x=a.create_application('Example AI','Junior RAG Engineer','https://example.com/jobs/123',jd,'example'); ck('1 create application',x['decision']=='created' and x['application']['current_status']=='awaiting_resume_approval')
  aid=x['application']['application_id']; app=x['application']; ck('2 JD stored',Path(r/app['job_description_reference']).exists()); ck('3 Phase 8 integration',bool(app['supported_requirements'] or app['unsupported_requirements']) and app['phase8_plan_reference'])
  d=a.create_application('Other','Other Role','https://example.com/jobs/123','different'); ck('4 duplicate URL detected',d['decision']=='duplicate_requires_clarification')
  d=a.create_application('Example AI','Junior RAG Engineer','https://example.com/jobs/456',jd); ck('5 same company and role different URL warns',d['decision']=='duplicate_requires_clarification')
  d=a.create_application('IQLR','Junior RAG Engineer','https://example.com/jobs/789','Junior RAG Engineer\nRequired Skills:\n- Python\nResponsibilities:\n- Build a separate retrieval application.'); ck('same title with different company and JD is created',d['decision']=='created')
  d=a.create_application('Example AI','Another RAG Role','https://example.com/jobs/999',jd); ck('same company and JD with different title warns',d['decision']=='duplicate_requires_clarification')
  ck('6 approval false before approval',app['resume_generation_allowed'] is False)
  ap=a.approve_resume(aid); stored=next(item for item in a.load_store()['applications'] if item['application_id']==aid); ck('7 explicit approval enables Phase 6 handoff',ap['resume_generation_allowed'] is True and stored['current_status']=='resume_ready')
  cl=a.generate_cover_letter(aid); txt=(r/cl['cover_letter_reference']).read_text(); ck('8 cover letter generated without internal notes','Note for internal preparation:' not in txt and 'unsupported requirements' not in txt); ck('9 cover letter associated',bool(cl['cover_letter_reference']))
  stored=next(item for item in a.load_store()['applications'] if item['application_id']==aid); ck('10 checklist generated',bool(stored['application_checklist']['requirements']) and len(stored['application_checklist']['manual_actions'])>=5); ck('11 gaps visible',bool(stored['candidate_gap_summary']))
  u=a.update_status(aid,'applied',False); ck('12 applied requires explicit confirmation',u['decision']=='confirmation_required'); u=a.update_status(aid,'applied',True); ck('13 explicit manual submission changes status',u['application']['current_status']=='applied' and u['application']['date_applied'])
  u=a.update_status(aid,'interview'); ck('14 status history preserved',u['application']['current_status']=='interview' and len(u['application']['status_history'])>=3)
  n=a.add_note(aid,'Recruiter contacted me.','2026-10-01'); ck('15 notes and follow-up stored',n['application']['application_notes'][-1]['note']=='Recruiter contacted me.' and n['application']['follow_up_date']=='2026-10-01')
  ck('16 search works',len(a.search('Example AI'))==1 and len(a.search(status='interview'))==1)
  rep=a.summary_report(); ck('17 report created',rep.exists())
  ck('18 no submission functionality',not hasattr(a,'submit_application') and not hasattr(a,'browser'))
 finally:
  a.ROOT,a.DATA,a.JOBS,a.OUT,a.REPORTS,a.LETTERS,a.RESUMES=old; td.cleanup()
 out={'passed':all(x['passed'] for x in results),'results':results}; print(json.dumps(out,indent=2)); raise SystemExit(0 if out['passed'] else 1)
if __name__=='__main__': main()
