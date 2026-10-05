#!/usr/bin/env python3
"""Phase 9A human-in-the-loop application assistant.

This module stores application records and prepares artifacts. It never logs
in, submits applications, automates portals, sends email, or uses a browser.
Resume generation is a separate explicit action requiring approval.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re, subprocess, threading, uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from career_os_config import (
  CODE_ROOT,
  DATA_DIR,
  JOB_DESCRIPTIONS_DIR,
  OUTPUT_DIR,
  resolve_storage_reference,
  storage_reference,
)
ROOT=CODE_ROOT
DATA=DATA_DIR; JOBS=JOB_DESCRIPTIONS_DIR; OUT=OUTPUT_DIR; REPORTS=OUT/'reports'; LETTERS=OUT/'cover_letters'; RESUMES=OUT/'resumes'
STATUSES={'saved','analyzing','awaiting_resume_approval','resume_ready','ready_to_apply','applied','assessment','interview','offer','rejected','withdrawn','closed'}
FINAL_SUBMISSION_WORDS=('applied','submitted','i submitted','application submitted')
APPLICATION_STORE_LOCK=threading.RLock()
DELETED_APPLICATION_IDS=set()

def now(): return datetime.now(timezone.utc).isoformat()
def slug(s): return re.sub(r'[^a-z0-9]+','_',str(s).lower()).strip('_')[:80]
def artifact_stem(app, kind, lifecycle, suffix=None):
 label={'resume':'Resume','cover_letter':'CoverLetter'}.get(kind, slug(kind))
 stem=f"{slug(app.get('company_name') or 'company')}_{slug(app.get('job_title') or 'role')}_{app.get('application_id')}_{label}_{lifecycle}"
 return f'{stem}_{suffix}' if suffix else stem
def norm(s): return re.sub(r'[^a-z0-9]+',' ',str(s or '').lower()).strip()
def load_store():
 p=DATA/'applications.json'
 if not p.exists(): return {'applications':[]}
 return json.loads(p.read_text(encoding='utf-8'))
def save_store(store):
 with APPLICATION_STORE_LOCK:
  applications=[app for app in store.get('applications',[]) if app.get('application_id') not in DELETED_APPLICATION_IDS]
  payload={**store,'applications':applications}
  (DATA/'applications.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def load_profile(): return {n:json.loads((DATA/f'{n}.json').read_text(encoding='utf-8')) for n in ['master_profile','skills','projects','experience','certifications','education','achievements']}
def phase8_plan(jd_text,report_path):
 import jd_resume_planner
 plan=jd_resume_planner.plan_resume(jd_text,jd_resume_planner.load_profile()); report_path.parent.mkdir(parents=True,exist_ok=True); report_path.write_text(json.dumps(plan,indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); return plan
def extract_job(jd_text):
 lines=[x.strip() for x in jd_text.splitlines() if x.strip()]; title=lines[0] if lines else None
 company=None
 for line in lines[:12]:
  m=re.search(r'(?:company|employer)\s*:\s*(.+)',line,re.I)
  if m: company=m.group(1).strip()
 return title,company
def duplicate_candidates(store,company,title,url,jd_text):
 nurl=norm(url); nc=norm(company); nt=norm(title); nj=norm(jd_text)[:500]
 found=[]
 for a in store.get('applications',[]):
  score=0
  if nurl and norm(a.get('job_url'))==nurl: score+=5
  if nc and nc==norm(a.get('company_name')): score+=2
  if nj and nj==norm(a.get('job_description_text'))[:500]: score+=2
  if score>=2: found.append({'application_id':a['application_id'],'company_name':a.get('company_name'),'job_title':a.get('job_title'),'job_url':a.get('job_url'),'current_status':a.get('current_status'),'similarity_score':score})
 return found
def checklist(plan):
 jd=plan.get('jd_analysis',{}); summary=[]
 for x in jd.get('required_technical_skills',[]): summary.append({'item':x,'kind':'required','status':'supported' if any(m.get('requirement')==x and m.get('evidence_status')=='SUPPORTED' for m in plan.get('evidence_summary',{}).get('supported_requirements',[])) else 'review'})
 for x in jd.get('preferred_technical_skills',[]): summary.append({'item':x,'kind':'preferred','status':'review'})
 for x in plan.get('evidence_summary',{}).get('partial_requirements',[]): summary.append({'item':x.get('requirement'),'kind':'partial','status':'partial'})
 for x in plan.get('evidence_summary',{}).get('unsupported_requirements',[]): summary.append({'item':x.get('requirement'),'kind':'unsupported','status':'unsupported'})
 documents=[{'item':'Tailored resume','status':'pending'},{'item':'Cover letter','status':'pending'}]
 manual=[{'item':x,'status':'pending'} for x in ['Submit application','Upload resume','Upload cover letter','Complete application questions','Verify contact information','Final manual submission']]
 return {'requirements':summary,'documents':documents,'manual_actions':manual}
def gap_summary(plan):
 return [{'requirement':x.get('requirement'),'status':'unsupported','message':'No supporting profile evidence; do not add this claim.'} for x in plan.get('evidence_summary',{}).get('unsupported_requirements',[])] + [{'requirement':x.get('requirement'),'status':'partial','message':'Related evidence exists but does not fully satisfy the requirement.'} for x in plan.get('evidence_summary',{}).get('partial_requirements',[])]
def create_application(company,title,url,jd_text,source=None,location=None,employment_type=None):
	store=load_store(); dup=duplicate_candidates(store,company,title,url,jd_text)
	if dup: return {'decision':'duplicate_requires_clarification','possible_existing_applications':dup,'persistent_write_allowed':False}
	aid='app_'+uuid.uuid4().hex[:12]; jd_path=JOBS/f'{aid}_{slug(title or "role")}.txt'; jd_path.parent.mkdir(parents=True,exist_ok=True); jd_path.write_text(jd_text,encoding='utf-8')
	plan_report=REPORTS/f'{aid}_phase8_plan.json'; plan=phase8_plan(jd_text,plan_report)
	plan.setdefault('resume_plan',{})['automatic_projects_to_include']=copy.deepcopy(plan['resume_plan'].get('projects_to_include',[]))
	plan_report.write_text(json.dumps(plan,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
	app={'application_id':aid,'company_name':company,'job_title':title,'job_url':url,'source_platform':source,'location':location,'employment_type':employment_type,'job_description_reference':storage_reference(jd_path, root=ROOT),'job_description_text':jd_text,'date_added':date.today().isoformat(),'date_applied':None,'current_status':'awaiting_resume_approval','status_history':[{'old_status':None,'new_status':'awaiting_resume_approval','timestamp':now(),'source':'application_assistant'}],'resume_reference':None,'cover_letter_reference':None,'project_selection_mode':'automatic','project_selection_source':'automatic','project_selection_record_ids':[x.get('record_id') for x in plan['resume_plan']['projects_to_include']],'selected_projects':[x.get('name') for x in plan['resume_plan']['projects_to_include']],'selected_skills':[x.get('name') for x in plan['resume_plan']['skills_to_include']],'selected_certifications':[x.get('name') for x in plan['resume_plan']['certifications_to_include']],'experience_decision':plan['resume_plan']['experience_decisions'],'requirements_summary':plan['jd_analysis'].get('requirements',[]),'supported_requirements':[x.get('requirement') for x in plan['evidence_summary']['supported_requirements']],'partial_requirements':[x.get('requirement') for x in plan['evidence_summary']['partial_requirements']],'unsupported_requirements':[x.get('requirement') for x in plan['evidence_summary']['unsupported_requirements']],'candidate_gap_summary':gap_summary(plan),'application_checklist':checklist(plan),'application_notes':[],'follow_up_date':None,'last_updated':now(),'phase8_plan_reference':storage_reference(plan_report, root=ROOT),'resume_generation_allowed':False,'provenance':{'job_source':'user_provided','candidate_source':'data/*.json','phase8_source':storage_reference(plan_report, root=ROOT)},'manual_submission_required':True,'automatic_submission_enabled':False}
	store['applications'].append(app); save_store(store); return {'decision':'created','application':app,'persistent_write_allowed':True}
def get_app(aid=None,company=None,title=None,url=None):
 apps=load_store().get('applications',[]); matches=[]
 for a in apps:
  if aid and a['application_id']==aid: matches.append(a)
  elif not aid and ((company and norm(company)==norm(a.get('company_name'))) or (title and norm(title)==norm(a.get('job_title'))) or (url and norm(url)==norm(a.get('job_url')))): matches.append(a)
 return matches
def update_status(aid,status,explicit_submission=False):
 if status not in STATUSES: raise ValueError('Invalid application status')
 store=load_store(); app=next((x for x in store['applications'] if x['application_id']==aid),None)
 if not app: return {'decision':'not_found'}
 if status=='applied' and not explicit_submission: return {'decision':'confirmation_required','message':'The user must explicitly confirm manual submission before status becomes applied.','application_id':aid}
 old=app['current_status']; app['current_status']=status; app['last_updated']=now(); app['status_history'].append({'old_status':old,'new_status':status,'timestamp':now(),'source':'explicit_user_confirmation' if status=='applied' else 'user_status_update'})
 if status=='applied': app['date_applied']=date.today().isoformat()
 save_store(store); return {'decision':'updated','application':app}
def add_note(aid,note,follow_up_date=None):
 store=load_store(); app=next((x for x in store['applications'] if x['application_id']==aid),None)
 if not app:return {'decision':'not_found'}
 app['application_notes'].append({'note':note,'timestamp':now(),'source':'user_provided'})
 if follow_up_date: app['follow_up_date']=follow_up_date
 app['last_updated']=now(); save_store(store); return {'decision':'updated','application':app}
def generate_cover_letter(aid):
 store=load_store(); app=next((x for x in store['applications'] if x['application_id']==aid),None)
 if not app:return {'decision':'not_found'}
 import jd_resume_planner as planner
 import resume_generator as resume
 profile=load_profile(); name=profile['master_profile']['profile']['name']
 jd=app.get('job_description_text','').strip()
 plan_ref=app.get('phase8_plan_reference'); plan_path=resolve_storage_reference(plan_ref,root=ROOT) if plan_ref else None
 plan=json.loads(plan_path.read_text(encoding='utf-8')) if plan_path and plan_path.exists() else {}
 approved=plan.get('evidence_summary',{})
 supported={str(x.get('requirement','')).lower() for x in approved.get('supported_requirements',[]) if isinstance(x,dict)}
 if not supported and app.get('supported_requirements'):
  supported={str(x).lower() for x in app.get('supported_requirements',[])}
 unsupported={str(x.get('requirement','')).lower() for x in approved.get('unsupported_requirements',[]) if isinstance(x,dict)}
 if not unsupported and app.get('unsupported_requirements'):
  unsupported={str(x).lower() for x in app.get('unsupported_requirements',[])}
 project_records={x.get('record_id'):x for x in profile.get('projects',{}).get('projects',[])}
 selected_ids=app.get('project_selection_record_ids') or [x.get('record_id') for x in plan.get('resume_plan',{}).get('projects_to_include',[])]
 projects=[project_records[x] for x in selected_ids if x in project_records and project_records[x].get('project_status')=='completed']
 if not projects:
  projects=[x for x in profile.get('projects',{}).get('projects',[]) if x.get('name') in (app.get('selected_projects') or []) and x.get('project_status')=='completed']
 jd_lower=jd.lower()
 jd_analysis=plan.get('jd_analysis',{})
 generic_roles={'entry level technical','entry level technical role','fresher','freshers','role not specified','unspecified role'}
 role=None
 for candidate in (app.get('job_title'),jd_analysis.get('target_role'),jd_analysis.get('job_title'),planner.infer_target_role(jd)):
  candidate=str(candidate or '').strip()
  normalized=re.sub(r'[\s_-]+',' ',candidate.casefold()).strip()
  if candidate and normalized not in generic_roles and not re.fullmatch(r'fresher(?:s)? role',normalized) and len(candidate)<=80 and not re.search(r'\b(is hiring|we are looking|we are seeking|responsibilities|minimum qualifications)\b',candidate,re.I):
    role=re.sub(r'\s*[-—]\s*fresher\s*$','',candidate,flags=re.I).strip()
    break
 if not role:
  role='AI/ML Training Data and Evaluation' if any(term in jd_lower for term in ('data labeling','rlhf','prompt evaluation')) else 'entry-level AI/ML'
 company_value=str(app.get('company_name') or '').strip()
 company=company_value if norm(company_value) not in {'abcd','company name','your company','unknown company','your organization'} else ''
 is_ml_engineering='machine learning engineer' in norm(role) or ('machine learning' in jd_lower and 'feature engineering' in jd_lower)
 def join_evidence(values):
  if len(values)==1: return values[0]
  if len(values)==2: return f'{values[0]} and {values[1]}'
  return ', '.join(values[:-1])+f', and {values[-1]}'
 def project_evidence_sentences(project):
  project_name=project.get('name','')
  action_verbs={'accepted','analyzed','applied','built','cleaned','compared','created','displayed','evaluated','exported','generated','implemented','inspected','integrated','loaded','optimized','performed','prepared','removed','returned','saved','stored','used'}
  sentences=[]
  bullets=resume.project_bullets(project,plan)[:2]
  for index,bullet in enumerate(bullets):
   evidence=str(bullet).strip().rstrip('.!?')
   if not evidence: continue
   first_word=re.match(r'([A-Za-z]+)\b',evidence)
   if first_word and first_word.group(1).casefold() in action_verbs:
    prefix=f'For the {project_name} project, I ' if index==0 else 'I '
   else:
    prefix=f'The {project_name} project involved ' if index==0 else 'The project also involved '
   sentences.append(prefix+evidence[0].lower()+evidence[1:]+'.')
  if not sentences:
   evidence=[str(value).strip() for value in project.get('demonstrated_skills',[]) if isinstance(value,str) and value.strip()]
   if evidence: sentences.append(f'The completed {project_name} project demonstrates {join_evidence(evidence[:2])}.')
  return sentences
 project_sentences=[]
 for project in projects[:3]:
  name_text=project.get('name','')
  if is_ml_engineering:
   project_id=project.get('record_id')
   ml_project_sentences={
    'project_smartfraud_classifier':'For SmartFraud Classifier, I applied SMOTE during preprocessing and compared Decision Tree, Random Forest, and XGBoost models for fraud classification.',
    'project_bank_customer_clustering_dashboard':'In the Bank Customer Clustering and Financial Analytics Dashboard, I cleaned an 8,950-record credit-card dataset, engineered features, standardized the data, and compared K-Means, Agglomerative, and DBSCAN clustering.',
    'project_telecom_churn_logistic_regression':'For Telecom Churn Logistic Regression, I built a scaled and one-hot-encoded preprocessing pipeline and tuned the classifier with GridSearchCV.',
   }
   if project_id in ml_project_sentences:
    project_sentences.append(ml_project_sentences[project_id])
    continue
  project_sentences.extend(project_evidence_sentences(project))
 skill_phrases=[]
 for phrase in ('python','scikit-learn','pandas','numpy','xgboost','sql','nlp','machine learning','llm integration'):
  if phrase in supported and phrase not in unsupported:
   m={'python':'Python','scikit-learn':'Scikit-learn','sql':'SQL','pandas':'Pandas','numpy':'NumPy','xgboost':'XGBoost','nlp':'NLP','machine learning':'machine learning','llm integration':'LLM integration'}
   skill_phrases.append(m[phrase])
 skills_sentence=join_evidence(skill_phrases[:4])
 sql_supported='sql' in supported and 'sql' not in unsupported
 is_ai_eval=any(term in jd_lower for term in ('data labeling','rlhf','prompt evaluation','annotation guidelines','content safety','evaluation and calibration','language-model','large language model','training-data quality','training data quality'))
 is_analytics=any(term in jd_lower for term in ('data analyst','business analyst','business intelligence','analytics','data cleaning','exploratory data analysis','data visualization','reporting','dashboard','dashboards'))
 if is_ai_eval:
  intro_focus="The role's focus on training-data quality and evaluation aligns with the completed project evidence in my profile."
  skill_suffix='SQL-based data checks and evaluation workflows' if sql_supported else 'data checks and evaluation workflows'
  closing_target=f'evaluation and calibration work at {company}' if company else 'evaluation and calibration work with an AI/ML team'
 elif is_ml_engineering:
  intro_focus="The role's focus on data preparation, feature engineering, and model evaluation aligns with the completed projects in my profile."
  skill_suffix='data preprocessing, feature engineering, and model evaluation.'
  closing_target=f'machine-learning work at {company}' if company else 'evidence-based machine-learning work'
 elif is_analytics:
  intro_focus="The role's focus on data cleaning, analysis, reporting, and dashboards aligns with the completed projects in my profile."
  skill_suffix='data analysis and SQL-based workflows' if sql_supported else 'data analysis and reporting workflows'
  closing_target=f'data and analytics work at {company}' if company else 'data and analytics work'
 else:
  intro_focus="The role's focus on hands-on data analysis and technical workflows aligns with the completed projects in my profile."
  skill_suffix='SQL-based technical workflows' if sql_supported else 'technical workflows'
  closing_target=f'technical and data work at {company}' if company else 'technical and data work'
 application_target=f'the {role} role'+(f' at {company}' if company else '')
 project_summary=' '.join(project_sentences)
 lines=['Dear Hiring Manager,','',f"I am writing to apply for {application_target}. {intro_focus}"]
 if project_summary: lines += ['',project_summary]
 if skills_sentence:
  lines += ['', f'My experience with {skills_sentence} is relevant to {skill_suffix.rstrip(".")}.']
 lines += ['', f"I would welcome the opportunity to contribute to {closing_target}. Thank you for your consideration.",'', 'Regards,', name]
 content='\n'.join(lines)+'\n'
 base=artifact_stem(app,'cover_letter','Working'); path=LETTERS/f'{base}.md'; path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(content,encoding='utf-8')
 for a in store['applications']:
  if a['application_id']==aid:
    a['cover_letter_working_reference']=storage_reference(path, root=ROOT)
    a['cover_letter_source_reference']=storage_reference(path, root=ROOT)
    if not a.get('cover_letter_reference'):
     a['cover_letter_reference']=storage_reference(path, root=ROOT)
    a['application_checklist']['documents'][1]['status']='ready'
    a['last_updated']=now()
 save_store(store)
 return {'decision':'created','cover_letter_reference':storage_reference(path, root=ROOT),'cover_letter_working_reference':storage_reference(path, root=ROOT),'content':content}
def edit_cover_letter(aid, content):
 store=load_store(); app=next((x for x in store['applications'] if x['application_id']==aid),None)
 if not app:return {'decision':'not_found'}
 content=str(content or '').strip()
 if not content:return {'decision':'invalid','message':'Cover letter content cannot be empty.'}
 if len(content)>12000:return {'decision':'invalid','message':'Cover letter content is too long.'}
 company=str(app.get('company_name') or '').strip()
 if company and company.lower() not in content.lower():return {'decision':'invalid','message':'The working letter must remain tied to the selected application company.'}
 forbidden=('open role','source-supported experience can be composed','direct rlhf','production content-safety labeling','named-entity annotation','computer-vision annotation','production qa ownership')
 found=[phrase for phrase in forbidden if phrase in content.lower()]
 if found:return {'decision':'invalid','message':'Unsupported or placeholder wording is not allowed: '+', '.join(found)}
 reference=app.get('cover_letter_working_reference') or app.get('cover_letter_source_reference')
 if not reference:return {'decision':'invalid','message':'Generate a working cover letter before editing.'}
 path=resolve_storage_reference(str(reference))
 if path is None: return {'decision':'invalid','message':'The cover-letter reference is invalid.'}
 path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content+'\n',encoding='utf-8')
 for item in store['applications']:
  if item.get('application_id')==aid: item['last_updated']=now(); item['cover_letter_edited_at']=item['last_updated']
 save_store(store); return {'decision':'saved','cover_letter_reference':reference,'content':content+'\n'}

def apply_persisted_project_selection(plan,app,profile):
 selection_source=app.get('project_selection_mode') or app.get('project_selection_source') or 'automatic'
 if selection_source!='manual': return plan
 plan_ref=app.get('phase8_plan_reference')
 plan_path=resolve_storage_reference(str(plan_ref),root=ROOT) if plan_ref else None
 if not plan_path or not plan_path.is_file(): raise ValueError('The confirmed manual project selection could not be resolved.')
 saved=json.loads(plan_path.read_text(encoding='utf-8')); saved_resume=saved.get('resume_plan',{})
 app_ids=list(app.get('project_selection_record_ids') or [])
 saved_ids=list(saved_resume.get('project_selection_record_ids') or [])
 saved_project_ids=[item.get('record_id') for item in saved_resume.get('projects_to_include',[])]
 if (saved_resume.get('project_selection_source')!='manual' or not app_ids or len(app_ids)>3
         or len(app_ids)!=len(set(app_ids)) or saved_ids!=app_ids or saved_project_ids!=app_ids):
  raise ValueError('The application project selection does not match its stored Reviewed Resume Plan.')
 from jd_resume_planner import project_matches
 scored,_=project_matches(plan.get('jd_analysis',{}),profile,plan.get('candidate_matching',[]))
 scored_by_id={item.get('record_id'):item for item in scored}
 canonical={item.get('record_id'):item for item in profile.get('projects',{}).get('projects',[])
            if item.get('project_status')=='completed' and item.get('status')=='verified'}
 if any(record_id not in canonical for record_id in app_ids):
  raise ValueError('The confirmed selection includes a project that is no longer eligible.')
 projects=[]
 for record_id in app_ids:
  if record_id in scored_by_id:
   projects.append(scored_by_id[record_id])
  else:
   projects.append({**canonical[record_id],'matched_requirements':[]})
 result=copy.deepcopy(plan); resume_plan=result.setdefault('resume_plan',{})
 resume_plan['automatic_projects_to_include']=copy.deepcopy(resume_plan.get('projects_to_include',[]))
 resume_plan['projects_to_include']=projects
 resume_plan['project_selection_source']='manual'
 resume_plan['project_selection_record_ids']=app_ids
 result['project_selection_source']='manual'
 return result

def approve_resume(aid,reviewed_plan=None):
  store=load_store(); app=next((x for x in store['applications'] if x['application_id']==aid),None)
  if not app:return {'decision':'not_found'}
  plan_ref=app.get('phase8_plan_reference')
  if reviewed_plan is not None:
    if not isinstance(reviewed_plan,dict) or reviewed_plan.get('mode')!='job_application_planning':
      return {'decision':'invalid_plan','message':'A planner-generated Resume Plan is required for approval.'}
    jd_text=str(app.get('job_description_text') or '').strip()
    if not jd_text or reviewed_plan.get('source_jd_text','').strip()!=jd_text:
      return {'decision':'plan_jd_mismatch','message':'The reviewed plan does not match this application’s saved job description.'}
    import jd_resume_planner as planner
    profile=load_profile()
    expected=planner.plan_resume(jd_text,profile)
    categories=[group.get('category') for group in profile.get('skills',{}).get('skill_groups',[]) if group.get('category')]
    if reviewed_plan.get('candidate_skill_categories',categories)!=categories:
      return {'decision':'plan_evidence_mismatch','message':'The reviewed plan contains a non-canonical skill category list.'}
    manual_selection=(app.get('project_selection_mode') or app.get('project_selection_source'))=='manual'
    if manual_selection:
      try: expected=apply_persisted_project_selection(expected,app,profile)
      except (OSError,ValueError,json.JSONDecodeError) as exc:
        return {'decision':'plan_evidence_mismatch','message':str(exc)}
    reviewed=copy.deepcopy(reviewed_plan)
    if manual_selection:
      reviewed_resume=reviewed.get('resume_plan',{})
      selected_ids=list(app.get('project_selection_record_ids') or [])
      reviewed_ids=[item.get('record_id') for item in reviewed_resume.get('projects_to_include',[])]
      if (reviewed_resume.get('project_selection_source')!='manual'
              or list(reviewed_resume.get('project_selection_record_ids') or [])!=selected_ids
              or reviewed_ids!=selected_ids
              or reviewed.get('project_selection_source') not in {None,'manual'}):
        return {'decision':'plan_evidence_mismatch','message':'The reviewed projects do not match the confirmed manual project selection.'}
      expected_resume=expected['resume_plan']
      reviewed_resume['projects_to_include']=copy.deepcopy(expected_resume['projects_to_include'])
      reviewed_resume['automatic_projects_to_include']=copy.deepcopy(expected_resume['automatic_projects_to_include'])
      reviewed_resume['project_selection_source']='manual'
      reviewed_resume['project_selection_record_ids']=selected_ids
      reviewed['project_selection_source']='manual'
    allowed_keys=set(expected)|{'candidate_skill_categories'}
    if set(reviewed)-allowed_keys or any(reviewed.get(key)!=value for key,value in expected.items()):
      return {'decision':'plan_evidence_mismatch','message':'The reviewed plan differs from the current deterministic plan or canonical profile evidence.'}
    approved_plan=reviewed
    approved_plan.setdefault('approval_checkpoint',{})['resume_generation_allowed']=True
    plan_payload=json.dumps(approved_plan,indent=2,ensure_ascii=False)+'\n'
    plan_digest=hashlib.sha256(plan_payload.encode('utf-8')).hexdigest()[:16]
    plan_path=REPORTS/f'{aid}_phase8_plan_{plan_digest}.json'
    plan_path.parent.mkdir(parents=True,exist_ok=True)
    if plan_path.exists():
      if json.loads(plan_path.read_text(encoding='utf-8'))!=approved_plan:
        return {'decision':'plan_reference_conflict','message':'The deterministic approved-plan reference already contains different content.'}
    else:
      plan_path.write_text(plan_payload,encoding='utf-8')
    plan_ref=storage_reference(plan_path, root=ROOT)
    resume_plan=approved_plan['resume_plan']
    projects=resume_plan.get('projects_to_include',[])
    experiences=resume_plan.get('experience_to_include',[])
    certifications=resume_plan.get('certifications_to_include',[])
    selection_source=resume_plan.get('project_selection_source') or approved_plan.get('project_selection_source') or 'automatic'
    old_status=app.get('current_status')
    app.update({
      'phase8_plan_reference':plan_ref,
      'project_selection_mode':selection_source,
      'project_selection_source':selection_source,
      'project_selection_record_ids':[item.get('record_id') for item in projects],
      'selected_projects':[item.get('name') for item in projects],
      'selected_skills':[item.get('name') for item in resume_plan.get('skills_to_include',[])],
      'selected_certifications':[item.get('name') for item in certifications],
      'selected_experience':[item.get('record_id') for item in experiences],
      'experience_decision':resume_plan.get('experience_decisions',[]),
      'requirements_summary':approved_plan.get('jd_analysis',{}).get('requirements',[]),
      'supported_requirements':[item.get('requirement') for item in approved_plan.get('evidence_summary',{}).get('supported_requirements',[])],
      'partial_requirements':[item.get('requirement') for item in approved_plan.get('evidence_summary',{}).get('partial_requirements',[])],
      'unsupported_requirements':[item.get('requirement') for item in approved_plan.get('evidence_summary',{}).get('unsupported_requirements',[])],
      'candidate_gap_summary':gap_summary(approved_plan),
      'application_checklist':checklist(approved_plan),
      'resume_generation_allowed':True,
      'resume_working_artifact_stale':bool(app.get('working_resume_generation_id') or app.get('working_resume_docx_path')),
      'current_status':'resume_ready',
      'last_updated':now(),
    })
    app.setdefault('provenance',{})['phase8_source']=plan_ref
    app.setdefault('status_history',[]).append({'old_status':old_status,'new_status':'resume_ready','timestamp':app['last_updated'],'source':'explicit_user_approval'})
    save_store(store)
    return {'decision':'approved','application_id':aid,'resume_generation_allowed':True,'phase8_plan_reference':plan_ref,'application':app}
  if plan_ref:
    plan_path=resolve_storage_reference(str(plan_ref))
    if plan_path is None: return {'decision':'error','message':'The approved Resume Plan reference is invalid.'}
    if plan_path.exists():
      plan=json.loads(plan_path.read_text(encoding='utf-8')); plan.setdefault('approval_checkpoint',{})['resume_generation_allowed']=True; plan_path.write_text(json.dumps(plan,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
  app['resume_generation_allowed']=True; app['current_status']='resume_ready'; app['last_updated']=now(); app['status_history'].append({'old_status':'awaiting_resume_approval','new_status':'resume_ready','timestamp':now(),'source':'explicit_user_approval'}); save_store(store); return {'decision':'approved','application_id':aid,'resume_generation_allowed':True}
def search(query=None,status=None):
 apps=load_store().get('applications',[]); q=norm(query); return [a for a in apps if (not status or a.get('current_status')==status) and (not q or q in norm(a.get('company_name')) or q in norm(a.get('job_title')) or q in norm(a.get('application_notes')))]
def summary_report():
 rows=[]
 for a in load_store().get('applications',[]): rows.append({k:a.get(k) for k in ['application_id','company_name','job_title','job_url','current_status','date_applied','resume_reference','cover_letter_reference','unsupported_requirements','follow_up_date','application_notes']})
 path=REPORTS/'application_summary.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps({'generated_at':now(),'applications':rows},indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); return path

def main():
 ap=argparse.ArgumentParser(description='Phase 9A human-in-the-loop application assistant'); sub=ap.add_subparsers(dest='command',required=True)
 c=sub.add_parser('create'); c.add_argument('--company'); c.add_argument('--title'); c.add_argument('--url'); c.add_argument('--source'); c.add_argument('--location'); c.add_argument('--employment-type'); c.add_argument('--jd',required=True)
 l=sub.add_parser('cover-letter'); l.add_argument('--application-id',required=True)
 a=sub.add_parser('approve-resume'); a.add_argument('--application-id',required=True)
 s=sub.add_parser('status'); s.add_argument('--application-id',required=True); s.add_argument('--value',required=True); s.add_argument('--explicit-submission',action='store_true')
 n=sub.add_parser('note'); n.add_argument('--application-id',required=True); n.add_argument('--text',required=True); n.add_argument('--follow-up-date')
 q=sub.add_parser('search'); q.add_argument('--query'); q.add_argument('--status')
 sub.add_parser('report')
 args=ap.parse_args()
 if args.command=='create': text=Path(args.jd).read_text(encoding='utf-8'); out=create_application(args.company,args.title,args.url,text,args.source,args.location,args.employment_type)
 elif args.command=='cover-letter': out=generate_cover_letter(args.application_id)
 elif args.command=='approve-resume': out=approve_resume(args.application_id)
 elif args.command=='status': out=update_status(args.application_id,args.value,args.explicit_submission)
 elif args.command=='note': out=add_note(args.application_id,args.text,args.follow_up_date)
 elif args.command=='search': out={'applications':search(args.query,args.status)}
 else: out={'report':storage_reference(summary_report(), root=ROOT)}
 print(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=='__main__': main()
