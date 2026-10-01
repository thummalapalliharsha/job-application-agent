#!/usr/bin/env python3
import copy, json, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT))
import app as ui
import jd_resume_planner as planner
import application_assistant as aa
import resume_generator as rg

def main():
 results=[]
 def ck(name, value): results.append({'test':name,'passed':bool(value)})
 profile=planner.load_profile(); all_projects=profile['projects']['projects']; eligible=[p for p in all_projects if p.get('project_status')=='completed' and p.get('status')=='verified']; unknown=[p for p in all_projects if p not in eligible]
 ck('automatic Phase 8 recommendations remain available',bool(planner.plan_resume('Junior RAG Engineer\nRequired Skills:\n- Python\n- RAG',profile)['resume_plan']['projects_to_include']))
 ck('eligible list is canonical verified completed projects only',len(ui.eligible_completed_projects())==len(eligible) and all(p.get('project_status')=='completed' and p.get('status')=='verified' for p in ui.eligible_completed_projects()))
 ck('unknown and incomplete projects excluded',not any(p in ui.eligible_completed_projects() for p in unknown))
 ck('project limit enforced',ui.PROJECT_LIMIT==3)
 td=tempfile.TemporaryDirectory(); temp=Path(td.name); plan_path=temp/'plan.json';
 selected=eligible[:2]; plan_path.write_text(json.dumps({'resume_plan':{'projects_to_include':selected}}))
 original=(ui.ROOT,ui.DATA,ui.load_apps,ui.aa.save_store,ui.planner.load_profile)
 apps=[{'application_id':'app_test','phase8_plan_reference':'plan.json','selected_projects':[],'last_updated':None}]
 ui.ROOT=temp; ui.planner.load_profile=lambda: profile; ui.load_apps=lambda: apps; ui.aa.save_store=lambda store: None; ui.aa.now=lambda:'now'
 try:
  out=ui.apply_project_selection_override('app_test',[selected[0]['record_id'],selected[1]['record_id']],'manual')
  saved=json.loads(plan_path.read_text()); ck('manual override uses selected canonical records',[x['record_id'] for x in out]==[x['record_id'] for x in selected]); ck('manual source persisted',saved['project_selection_source']=='manual' and saved['resume_plan']['project_selection_source']=='manual'); ck('manual selection survives rerender',saved['resume_plan']['project_selection_record_ids']==[x['record_id'] for x in selected]); ck('application selected project names synchronized',apps[0]['selected_projects']==[x['name'] for x in selected])
  manual_plan={'jd_analysis':{'job_title':'Junior Generative AI RAG Engineer'},'resume_plan':{'project_selection_source':'manual','project_selection_record_ids':[x['record_id'] for x in selected]}}
  ck('resume generator uses manual selection', [x['record_id'] for x in rg.effective_selection(manual_plan,profile)]==[x['record_id'] for x in selected])
  try: ui.apply_project_selection_override('app_test',[selected[0]['record_id'],selected[0]['record_id']],'manual'); duplicate=False
  except ValueError: duplicate=True
  ck('duplicate selection rejected',duplicate)
  try: ui.apply_project_selection_override('app_test',[unknown[0]['record_id']],'manual'); incomplete=False
  except ValueError: incomplete=True
  ck('unknown or incomplete selection rejected',incomplete)
  try: ui.apply_project_selection_override('app_test',[x['record_id'] for x in eligible[:4]],'manual'); too_many=False
  except ValueError: too_many=True
  ck('selection limit rejection is explicit',too_many)
 finally:
  ui.ROOT,ui.DATA,ui.load_apps,ui.aa.save_store,ui.planner.load_profile=original
  td.cleanup()
 ck('resume approval gate remains in UI',"if not app.get('resume_generation_allowed')" in (ROOT/'app.py').read_text())
 ck('Phase 6/7/9A integration interfaces preserved',all(x in (ROOT/'app.py').read_text() for x in ['import application_assistant as aa','import jd_resume_planner as planner','import profile_update_agent as pua','import resume_generator as rg']))
 ck('Phase 9B remains unimplemented',"PHASE 9B IS NOT IMPLEMENTED" in (ROOT/'app.py').read_text())
 out={'passed':all(x['passed'] for x in results),'results':results}; print(json.dumps(out,indent=2)); raise SystemExit(0 if out['passed'] else 1)
if __name__=='__main__': main()
