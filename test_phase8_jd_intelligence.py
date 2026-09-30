#!/usr/bin/env python3
import json, copy, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import jd_resume_planner as p

ROOT=Path(__file__).resolve().parent
PROFILE=p.load_profile()

def plan(text): return p.plan_resume(text,copy.deepcopy(PROFILE))
def req(text,name):
  result=p.match_requirements(p.analyze_jd(text),copy.deepcopy(PROFILE))
  return next(x for x in result if x['requirement']==name)

def check(name,ok,detail=''): return {'test':name,'passed':bool(ok),'detail':detail}

def main():
 r=[]
 x=req('Required: vector database','vector databases'); r.append(check('1 vector database to ChromaDB semantic match',x['evidence_status'] in {'SUPPORTED','PARTIAL'} and x['match_type']=='semantic',str(x)))
 x=req('Required: LangChain','langchain'); r.append(check('2 LangChain unsupported without profile evidence',x['evidence_status']=='UNSUPPORTED',str(x)))
 x=req('Required: RAG','rag'); r.append(check('3 RAG supported by project evidence',x['evidence_status']=='SUPPORTED',str(x)))
 x=req('Required: natural-language database querying','natural-language database querying'); r.append(check('4 natural-language querying to Text-to-SQL semantic match',x['evidence_status'] in {'SUPPORTED','PARTIAL'} and x['match_type']=='semantic',str(x)))
 x=req('Required: Docker','docker'); r.append(check('5 Docker unsupported without project evidence',x['evidence_status']=='UNSUPPORTED',str(x)))
 x=req('Required: Python','python'); r.append(check('6 Python direct match',x['evidence_status']=='SUPPORTED' and x['match_type']=='direct',str(x)))
 jd=p.analyze_jd('Required: RAG'); matches=p.match_requirements(jd,PROFILE); scored,excluded=p.project_matches(jd,PROFILE,matches); unknown=next(x for x in excluded if x['record_id']=='project_retail_mini_etl'); r.append(check('7 unknown project excluded',unknown['eligible'] is False and unknown['project_status']=='unknown'))
 prof=copy.deepcopy(PROFILE); non_github=next(x for x in prof['projects']['projects'] if x['record_id']=='project_student_performance_rag'); non_github['github_availability']='github_not_uploaded'; matches=p.match_requirements(jd,prof); scored,_=p.project_matches(jd,prof,matches); chosen=next(x for x in scored if x['record_id']=='project_student_performance_rag'); r.append(check('8 completed non-GitHub project remains eligible',chosen['project_status']=='completed' and chosen['github_availability']=='github_not_uploaded'))
 q=plan('Junior Generative AI RAG Engineer\nRequired: Python, RAG, vector database\nResponsibilities: Build retrieval pipelines.'); ex=q['resume_plan']['experience_decisions']; r.append(check('9 broad AI/Python internship not automatically relevant',all(x['decision']=='NOT RELEVANT ENOUGH FOR RESUME' for x in ex)))
 q=plan('Junior Generative AI RAG Engineer\nRequired: Python, RAG, vector database\nResponsibilities: Build retrieval pipelines.'); r.append(check('10 third-project fallback and approval gate',q['resume_plan']['third_project_fallback_used'] and len(q['resume_plan']['projects_to_include'])==3 and q['approval_checkpoint']['resume_generation_allowed'] is False))
 q=plan('Required: RAG'); r.append(check('11 deterministic fallback without external model',q['safety']['external_model_used'] is False and 'candidate_matching' in q))
 q=plan('Required: LangChain'); selected=q['resume_plan']['skills_to_include']; r.append(check('12 unsupported semantic suggestion not added to plan/profile',not any(x.get('name','').lower()=='langchain' for x in selected) and not any('langchain' in x.get('name','').lower() for x in q['resume_plan']['projects_to_include'])))
 out={'passed':all(x['passed'] for x in r),'results':r}
 print(json.dumps(out,indent=2)); raise SystemExit(0 if out['passed'] else 1)
if __name__=='__main__':main()
