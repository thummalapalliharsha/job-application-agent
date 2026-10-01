#!/usr/bin/env python3
import json, shutil, tempfile
from pathlib import Path
import profile_update_agent as agent

ROOT=Path(__file__).resolve().parent

def sandbox():
    td=tempfile.TemporaryDirectory(); root=Path(td.name); (root/'data').mkdir()
    for p in (ROOT/'data').glob('*.json'): shutil.copy2(p,root/'data'/p.name)
    return td,root

def run():
    results=[]
    def check(name,ok,detail=''): results.append({'test':name,'passed':bool(ok),'detail':detail})
    td,root=sandbox();
    try:
        p=agent.plan_request('I learned Docker.',root); check('1 learned skill routes to skills',p['category']=='skills' and p['decision']=='ask_clarification' or p['actions'] and p['actions'][0]['action']=='add_skill','Requires an existing tools category or a clarification; no project action.')
        # Use an existing tools category in the fixture; Docker should be planned as a skill.
        check('1 no project usage claim',not any(a.get('action') in {'add_project_technologies','create_project'} for a in p['actions']))
        p=agent.plan_skill_gap_addition('Kubernetes','tools_and_platforms',root,'app_confirmation'); check('confirmed JD skill is candidate-provided',p['decision']=='planned' and p['actions'][0]['status']=='candidate_provided' and p['actions'][0]['evidence']['evidence_type']=='explicit_user_confirmation')
        agent.apply_plan(p,root,confirm=True); data=agent.all_data(root); group,skill=agent.find_skill(data,'Kubernetes'); check('confirmed skill creates no project evidence',skill['status']=='candidate_provided' and not any('Kubernetes' in project.get('technologies',[]) for project in agent.project_records(data)))
        p=agent.plan_skill_gap_addition('Python','programming_languages',root,'app_confirmation'); check('existing skill cannot be added twice',p['decision']=='no_change_duplicate')
        p=agent.plan_request('I used Docker in Student Performance RAG Chatbot.',root); check('2 explicit project usage',p['category']=='projects' and any(a['action']=='add_project_technologies' for a in p['actions']))
        p=agent.plan_request("I completed a new FastAPI project called Employee Management API. It isn't on GitHub.",root); a=p['actions'][0]; check('3 new completed non-GitHub project',a['action']=='create_project' and a['project_status']=='completed' and a['github_availability']=='github_not_uploaded')
        p=agent.plan_request('I uploaded Student Performance RAG Chatbot to GitHub.',root); check('4 existing GitHub update no duplicate',p['category']=='projects' and (p['decision']=='ask_clarification' or any(a['action']=='update_project_github' for a in p['actions'])))
        p=agent.plan_request('I got a new AWS certification.',root); check('5 new certification leaves missing fields empty',p['category']=='certifications' and p['actions'][0]['action']=='create_certification' and p['actions'][0]['issue_date'] is None and p['actions'][0]['credential_id'] is None)
        p=agent.plan_request('I completed my existing project.',root); check('6 ambiguous existing completion asks',p['decision']=='ask_clarification')
        p=agent.plan_request('I won a hackathon.',root); check('7 achievement routes correctly',p['category']=='achievements' and p['actions'][0]['action']=='create_achievement')
        p=agent.plan_request('Add FastAPI.',root); check('8 ambiguous skill/project asks',p['decision']=='ask_clarification')
        # Conflict-like status change is planned and exposes old/new values.
        p=agent.plan_request('Mark Retail Mini ETL completed.',root); status=[a for a in p['actions'] if a['action']=='update_project_status']; check('9 status update exposes old/new',bool(status) and status[0].get('old')=='unknown' and status[0].get('new')=='completed')
        d=agent.all_data(root); next(x for x in d['projects']['projects'] if x['record_id']=='project_retail_mini_etl')['completion_date']='March 2026'; agent.dump('projects',d['projects'],root)
        p=agent.plan_request('I completed Retail Mini ETL in June 2025.',root); check('9 conflicting date requires confirmation',p['decision']=='conflict_requires_confirmation' and bool(p['conflicts']))
        p=agent.plan_request('Delete project Retail Mini ETL.',root); check('safe delete requires confirmation',p['decision']=='confirmation_required_delete' and not p['persistent_write_allowed'])
        before=(ROOT/'resumes'/'RESUME.docx').read_bytes(); p=agent.plan_request('I learned Docker.',root); after=(ROOT/'resumes'/'RESUME.docx').read_bytes(); check('10 profile workflow does not modify resume',before==after)
        v=agent.validate_data(root); check('schema validation',v['valid'],str(v))
    finally: td.cleanup()
    print(json.dumps({'passed':all(x['passed'] for x in results),'results':results},indent=2))
    raise SystemExit(0 if all(x['passed'] for x in results) else 1)
if __name__=='__main__': run()
