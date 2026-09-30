#!/usr/bin/env python3
import hashlib, json, shutil, subprocess, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT))
import application_assistant as aa

def main():
 results=[]
 def ck(name,v,d=''): results.append({'test':name,'passed':bool(v),'detail':d})
 app=(ROOT/'app.py').read_text(encoding='utf-8')
 for page in ['Dashboard','New Application','JD Analysis','Resume Workspace','Cover Letter Workspace','Application Package','Application History','Profile','Pending Actions','Search','Settings']:
  ck('page exists: '+page,page in app)
 for phrase in ['resume_generation_allowed','Approve Resume Plan','Finalize Resume','Generate working resume','Finalize Cover Letter','Save finalized resume to permanent history','Application submission is manual','Mark as applied','pua.plan_request','pua.apply_plan','planner.plan_resume','aa.create_application','st.link_button']:
  ck('integration marker: '+phrase,phrase in app)
 ck('no automatic submission implementation',all(x not in app.lower() for x in ['selenium','playwright','webdriver','submit_application','requests.post','httpx.post']))
 ck('protected files not edited by UI source',all(x not in app for x in ['resume_generator.py"','profile_update_agent.py"','jd_resume_planner.py"','application_assistant.py"']))
 ck('application store valid',json.loads((ROOT/'data/applications.json').read_text())=={'applications':[]})
 ck('streamlit syntax compiles',subprocess.run([sys.executable,'-m','py_compile','app.py'],cwd=ROOT).returncode==0)
 ck('streamlit installed',__import__('importlib.util').util.find_spec('streamlit') is not None)
 ck('phase 10 smoke startup',subprocess.run(['timeout','8s','streamlit','run','app.py','--server.headless','true','--server.port','8503'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).returncode in (0,124))
 # Isolated Phase 9A record and lifecycle smoke test.
 td=tempfile.TemporaryDirectory(); r=Path(td.name)
 for d in ['data','job_descriptions','output/reports','output/cover_letters','output/resumes']: (r/d).mkdir(parents=True)
 for p in (ROOT/'data').glob('*.json'): shutil.copy2(p,r/'data'/p.name)
 old=(aa.ROOT,aa.DATA,aa.JOBS,aa.OUT,aa.REPORTS,aa.LETTERS,aa.RESUMES); aa.ROOT=r; aa.DATA=r/'data'; aa.JOBS=r/'job_descriptions'; aa.OUT=r/'output'; aa.REPORTS=r/'output/reports'; aa.LETTERS=r/'output/cover_letters'; aa.RESUMES=r/'output/resumes'
 try:
  x=aa.create_application('QA Company','QA RAG Role','https://example.test/job/1','QA RAG Role\nRequired Skills:\n- Python\n- RAG'); aid=x['application']['application_id']; ck('new application integration',x['decision']=='created'); ck('approval initially false',x['application']['resume_generation_allowed'] is False); ck('manual applied confirmation enforced',aa.update_status(aid,'applied')['decision']=='confirmation_required'); ck('explicit applied confirmation',aa.update_status(aid,'applied',True)['application']['current_status']=='applied')
 finally: aa.ROOT,aa.DATA,aa.JOBS,aa.OUT,aa.REPORTS,aa.LETTERS,aa.RESUMES=old; td.cleanup()
 protected=Path('/home/ubuntu/phase10_before_hashes.txt').read_text().splitlines(); unchanged=True
 for line in protected:
  h,rel=line.split('  ',1); unchanged &= hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==h
 ck('all phase 6-9A protected hashes unchanged',unchanged)
 out={'passed':all(x['passed'] for x in results),'results':results}; print(json.dumps(out,indent=2)); raise SystemExit(0 if out['passed'] else 1)
if __name__=='__main__': main()
