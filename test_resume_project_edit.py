#!/usr/bin/env python3
import ast
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import app as ui
import jd_resume_planner as planner
import resume_generator as rg


def main():
 profile=planner.load_profile()
 eligible=[p for p in profile['projects']['projects'] if p.get('project_status')=='completed']
 assert len(eligible)>=3
 with tempfile.TemporaryDirectory() as td:
  temp=Path(td); plan_a=temp/'plan_a.json'; plan_b=temp/'plan_b.json'
  auto_a=eligible[:1]; auto_b=eligible[1:2]
  plan_a.write_text(json.dumps({'resume_plan':{'projects_to_include':auto_a,'automatic_projects_to_include':auto_a,'project_selection_source':'automatic'},'approval_checkpoint':{'resume_generation_allowed':True}}))
  plan_b.write_text(json.dumps({'resume_plan':{'projects_to_include':auto_b,'automatic_projects_to_include':auto_b,'project_selection_source':'automatic'},'approval_checkpoint':{'resume_generation_allowed':True}}))
  apps=[
   {'application_id':'app_a','phase8_plan_reference':'plan_a.json','selected_projects':[auto_a[0]['name']],'project_selection_mode':'automatic','project_selection_source':'automatic','project_selection_record_ids':[auto_a[0]['record_id']],'resume_generation_allowed':True,'resume_working_artifact_stale':False,'current_status':'resume_ready','last_updated':None},
   {'application_id':'app_b','phase8_plan_reference':'plan_b.json','selected_projects':[auto_b[0]['name']],'project_selection_mode':'automatic','project_selection_source':'automatic','project_selection_record_ids':[auto_b[0]['record_id']],'resume_generation_allowed':True,'resume_working_artifact_stale':False,'current_status':'resume_ready','last_updated':None},
  ]
  original=(ui.ROOT,ui.load_apps,ui.aa.save_store,ui.planner.load_profile); ui.ROOT=temp; ui.load_apps=lambda:apps; ui.aa.save_store=lambda store:None; ui.planner.load_profile=lambda:profile
  try:
   chosen=[eligible[2]['record_id'],eligible[3]['record_id']]
   ui.persist_project_selection_change('app_a','manual',chosen)
   assert apps[0]['project_selection_record_ids']==chosen and apps[0]['selected_projects']==[eligible[2]['name'],eligible[3]['name']]
   assert apps[0]['resume_generation_allowed'] is False and apps[0]['resume_working_artifact_stale'] is True and apps[0]['current_status']=='awaiting_resume_approval'
   saved=json.loads(plan_a.read_text()); assert saved['resume_plan']['project_selection_source']=='manual' and saved['resume_plan']['project_selection_record_ids']==chosen and saved['approval_checkpoint']['resume_generation_allowed'] is False
   assert apps[1]['project_selection_record_ids']==[auto_b[0]['record_id']]
   ui.persist_project_selection_change('app_a','automatic',[])
   assert apps[0]['project_selection_mode']=='automatic' and apps[0]['project_selection_record_ids']==[auto_a[0]['record_id']]
   assert [p['record_id'] for p in rg.effective_selection(json.loads(plan_a.read_text()),profile)]==[auto_a[0]['record_id']]
   for invalid in ([x['record_id'] for x in eligible[:4]],[next(p for p in profile['projects']['projects'] if p.get('project_status')!='completed')['record_id']]):
    try: ui.persist_project_selection_change('app_a','manual',invalid)
    except ValueError: pass
    else: raise AssertionError('invalid project selection was accepted')
  finally: ui.ROOT,ui.load_apps,ui.aa.save_store,ui.planner.load_profile=original
 source=(ROOT/'app.py').read_text(encoding='utf-8'); ast.parse(source)
 assert 'Edit Project Selection' in source and 'Confirm Project Changes' in source and 'Cancel' in source
 assert 'resume_working_artifact_stale' in source and 'Finalization blocked: the working resume is outdated.' in source
 assert source.index("st.session_state['draft_manual_ids']=chosen") > source.index("if st.button('Confirm Project Selection'")
 print(json.dumps({'passed':True,'test':'resume project edit persistence, isolation, approval invalidation, limits, and confirmation gating'},indent=2))


if __name__=='__main__': main()
