#!/usr/bin/env python3
"""Phase 8 JD intelligence and evidence-based resume planning.

This implementation intentionally uses deterministic normalization rather than
an external LLM or embedding API. The profile JSON remains authoritative;
semantic relationships only identify relevance and never create evidence.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parent; DATA=ROOT/'data'
STATUSES={'idea','planned','in_progress','completed','unknown'}

# Canonical requirement -> explicitly recognized related terms. These mappings
# are relevance aids, not claims that the candidate used every related tool.
SEMANTIC_GROUPS={
 'python':['python'], 'sql':['sql','sqlite','mysql','postgresql'],
 'vector databases':['vector database','vector databases','chromadb','chroma db','faiss','pinecone','weaviate'],
 'rag':['rag','retrieval augmented generation','retrieval-augmented generation','retrieval pipeline','semantic retrieval'],
 'embeddings':['embedding','embeddings','vector embeddings'],
 'generative ai':['generative ai','genai','llm application','ai application'],
 'llm integration':['llm','llms','large language model','ollama','gemini api','openai-compatible'],
 'nlp':['nlp','natural language processing','natural-language processing'],
 'natural-language database querying':['natural language database querying','natural-language database querying','text to sql','text-to-sql','sql generation'],
 'data preprocessing':['data preprocessing','preprocessing','data cleaning','cleaning','missing value handling','feature preparation'],
 'exploratory data analysis':['exploratory data analysis','eda','pandas analysis','visualization','statistical exploration'],
 'streamlit':['streamlit'], 'langchain':['langchain'], 'chromadb':['chromadb','chroma db'], 'faiss':['faiss'], 'ollama':['ollama'],
 'docker':['docker'], 'git':['git'], 'github':['github'], 'pandas':['pandas'], 'numpy':['numpy'],
 'scikit-learn':['scikit-learn','sklearn'], 'pyspark':['pyspark','spark'], 'xgboost':['xgboost'],
 'prompt engineering':['prompt engineering','prompt design'], 'ai evaluation':['ai evaluation','evaluation of ai','model evaluation'],
 'document processing':['document processing','document ingestion','chunking','text splitting'],
 'semantic search':['semantic search','semantic retrieval','vector search','similarity search'],
 'data science':['data science','data analytics','analytics'], 'machine learning':['machine learning','ml'],
}
CATEGORIES={
 'programming_languages':{'python','sql','java','javascript','c++','r'},
 'frameworks_libraries':{'pandas','numpy','scikit-learn','streamlit','fastapi','react','plotly','matplotlib','seaborn','langchain','chromadb','faiss','ollama'},
 'databases':{'sql','sqlite','mysql','postgresql','mongodb','vector databases'},
 'cloud_platforms':{'aws','azure','gcp','docker','kubernetes','cloud'},
 'data_ml_ai':set(SEMANTIC_GROUPS)-{'python','sql','streamlit','langchain','chromadb','faiss','ollama','docker','git','github','pandas','numpy','scikit-learn'},
 'tools':{'git','github','jupyter','vscode','pytest','n8n'},
}
SOFT=['communication','teamwork','collaboration','problem-solving','analytical','leadership','adaptability']
EDU=['bachelor','b.tech','btech','computer science','information technology','artificial intelligence','data science','degree','graduate','education']

def load_profile():
 return {n:json.loads((DATA/f'{n}.json').read_text(encoding='utf-8')) for n in ['master_profile','skills','projects','experience','certifications','education','achievements']}
def norm(x): return re.sub(r'[^a-z0-9+#]+',' ',str(x).lower()).strip()
def contains(text,term):
 t=norm(text); q=norm(term); return bool(q and re.search(r'(?<![a-z0-9])'+re.escape(q)+r'(?![a-z0-9])',t))
def unique(xs):
 out=[]; seen=set()
 for x in xs:
  k=norm(x)
  if k and k not in seen: seen.add(k); out.append(x)
 return out
def candidate_text(record):
 excluded={'github_url','sources','provenance','source_evidence','github_availability','selection_metadata'}
 return json.dumps({k:v for k,v in record.items() if k not in excluded},ensure_ascii=False)
def skills(profile):
 return [{**s,'category':g.get('category')} for g in profile['skills'].get('skill_groups',[]) for s in g.get('skills',[])]
def extract_section(raw,heads):
 lines=raw.splitlines(); start=None
 for i,l in enumerate(lines):
  if any(re.search(r'\b'+re.escape(h)+r'\b',l.lower()) for h in heads): start=i+1; break
 if start is None:return ''
 vals=[]
 for l in lines[start:]:
  s=l.strip()
  if re.match(r'^[A-Za-z /&-]{2,40}:?$',s) and not s.startswith(('-', '*')): break
  if s: vals.append(s.lstrip('-* '))
 return ' '.join(vals)
def classify(term,required,preferred):
 if contains(required,term): return 'required'
 if contains(preferred,term): return 'preferred'
 return 'uncertain'
def extract_identity(raw):
 lines=[x.strip() for x in raw.splitlines() if x.strip()]; title=lines[0] if lines else 'Unspecified role'
 def field(labels):
  for l in lines:
   for label in labels:
    m=re.search(r'\b'+label+r'\s*:\s*(.+)',l,re.I)
    if m:return m.group(1).strip()
  return None
 years=re.findall(r'\b(?:at least|minimum of)?\s*(\d+)\+?\s+years?\b',raw,re.I)
 return {'job_title':title,'company':field(['company','employer']),'location':field(['location','based in']),'experience_level':('fresher' if re.search(r'\bfresher|entry[- ]level|graduate\b',raw,re.I) else None),'employment_type':field(['employment type','type']),'explicit_years_experience':years}
def analyze_jd(jd_text):
 raw=jd_text.strip(); required=extract_section(raw,['required skills','required qualifications','requirements','must have','mandatory']); preferred=extract_section(raw,['preferred skills','preferred qualifications','nice to have','bonus','desirable','preferred'])
 all_text=norm(raw); reqs=[]; categories={k:[] for k in CATEGORIES}
 for canonical,syns in SEMANTIC_GROUPS.items():
  found=[s for s in syns if contains(all_text,s)]
  if not found: continue
  cls=classify(canonical+' '+' '.join(found),required,preferred)
  item={'canonical':canonical,'jd_phrases':unique(found),'classification':cls,'match_classification':None}
  reqs.append(item)
  for cat,terms in CATEGORIES.items():
   if canonical in terms: categories[cat].append(item)
 for c in categories: categories[c]=unique([x['canonical'] for x in categories[c]])
 responsibilities=[]
 for l in raw.splitlines():
  s=l.strip(' -*\t')
  if s and (s.endswith('.') or re.match(r'^(build|develop|design|work|assist|integrate|perform|collaborate|document|maintain|analy)',s,re.I)): responsibilities.append(s)
 soft=[x for x in SOFT if contains(raw,x)]
 edu=[x for x in EDU if contains(raw,x)]
 return {'job_identity':extract_identity(raw),'job_title':extract_identity(raw)['job_title'],'role_function':extract_identity(raw)['job_title'],'required_technical_skills':[x['canonical'] for x in reqs if x['classification']=='required'],'preferred_technical_skills':[x['canonical'] for x in reqs if x['classification']=='preferred'],'uncertain_technical_skills':[x['canonical'] for x in reqs if x['classification']=='uncertain'],'requirements':reqs,'skill_categories':categories,'soft_skills_explicitly_requested':soft,'education_requirements':edu,'experience_requirements':re.findall(r'\b(fresher|entry[- ]level|internship|experience|\d+\+? years?)\b',raw,re.I),'responsibilities':unique(responsibilities),'domain_keywords':unique([x['canonical'] for x in reqs]),'keywords_phrases':unique(re.findall(r'\b[A-Za-z][A-Za-z0-9+#.-]{2,}\b',raw))[:100],'classification_notes':['Required/preferred is assigned only when the surrounding JD section or explicit wording supports it; otherwise classification is uncertain.','Semantic mappings identify related evidence but do not add unsupported technologies to the profile.']}
def evidence_for(req,profile):
 canonical=req['canonical']; syns=SEMANTIC_GROUPS.get(canonical,[canonical]); ev=[]
 for s in skills(profile):
  name=s.get('name',''); exact=any(norm(name)==norm(x) or contains(name,x) for x in syns)
  if exact: ev.append({'type':'skill','record_id':None,'name':name,'status':s.get('status'),'match_type':'direct' if any(norm(name)==norm(p) for p in req['jd_phrases']) else 'semantic','category':s.get('category'),'source':'skills.json'})
 for p in profile['projects'].get('projects',[]):
  txt=candidate_text(p); found=[x for x in syns if contains(txt,x)]
  if found: ev.append({'type':'project','record_id':p.get('record_id'),'name':p.get('name'),'project_status':p.get('project_status','unknown'),'github_availability':p.get('github_availability'),'match_type':'direct' if any(contains(txt,x) and any(norm(x)==norm(y) for y in req['jd_phrases']) for x in found) else 'semantic','matched_evidence':found,'source':'projects.json'})
 for e in profile['experience'].get('experiences',[]):
  found=[x for x in syns if contains(candidate_text(e),x)]
  if found: ev.append({'type':'experience','record_id':e.get('record_id'),'name':e.get('organization'),'match_type':'direct' if any(contains(candidate_text(e),x) and x in req['jd_phrases'] for x in found) else 'semantic','matched_evidence':found,'source':'experience.json'})
 for c in profile['certifications'].get('certifications',[]):
  text=candidate_text(c); found=[x for x in syns if contains(text,x)]
  if found: ev.append({'type':'certification','record_id':c.get('record_id'),'name':c.get('name'),'status':c.get('status'),'match_type':'direct' if any(contains(text,x) and any(norm(x)==norm(y) for y in req['jd_phrases']) for x in found) else 'semantic','matched_evidence':found,'source':'certifications.json'})
 return ev
def classify_evidence(ev):
 if not ev:return 'UNSUPPORTED'
 if any(x.get('match_type')=='direct' and (x.get('status') in {'verified','candidate_provided'} or x.get('project_status')=='completed') for x in ev):return 'SUPPORTED'
 if any(x.get('project_status')=='completed' for x in ev):return 'SUPPORTED'
 if any(x.get('match_type')=='semantic' for x in ev):return 'PARTIAL'
 return 'UNKNOWN'
def match_requirements(jd,profile):
 out=[]
 for req in jd['requirements']:
  ev=evidence_for(req,profile); classification=classify_evidence(ev); req=dict(req); req['match_classification']='direct' if any(x.get('match_type')=='direct' for x in ev) else ('semantic' if ev else None)
  out.append({'requirement':req['canonical'],'classification':req['classification'],'match_type':req['match_classification'],'evidence_status':classification,'evidence':ev,'explanation':explain(req,classification,ev)})
 return out
def explain(req,status,ev):
 if not ev:return 'No matching skill, project, or experience evidence was found in the profile.'
 names=unique([x.get('name','') for x in ev if x.get('name')]); kind='direct' if any(x.get('match_type')=='direct' for x in ev) else 'related semantic'
 return f"{status}: {kind} evidence from {', '.join(names[:3])}. Actual profile technologies are preserved."
def project_matches(jd,profile,matches):
 reqmap={x['requirement']:x for x in matches}; scored=[]; excluded=[]
 for p in profile['projects'].get('projects',[]):
  status=p.get('project_status','unknown'); relevant=[]; direct=0; semantic=0
  txt=candidate_text(p)
  generic={'python','git','github','data science','machine learning','sql','streamlit'}
  for req,mat in reqmap.items():
   if req in generic: continue
   hits=[e for e in mat['evidence'] if e.get('type')=='project' and e.get('record_id')==p.get('record_id')]
   if hits:
    relevant.append(req); direct+=sum(e.get('match_type')=='direct' for e in hits); semantic+=sum(e.get('match_type')=='semantic' for e in hits)
  if status!='completed': excluded.append({'record_id':p.get('record_id'),'name':p.get('name'),'project_status':status,'eligible':False,'reason':'lifecycle-ineligible; GitHub availability does not change this'})
  elif relevant: scored.append({'record_id':p.get('record_id'),'name':p.get('name'),'project_status':status,'github_availability':p.get('github_availability'),'matched_requirements':unique(relevant),'direct_matches':direct,'semantic_matches':semantic,'relevance_score':direct*3+semantic*2,'selection_reason':'completed project with source-supported direct/semantic evidence'})
  else: excluded.append({'record_id':p.get('record_id'),'name':p.get('name'),'project_status':status,'eligible':True,'reason':'no meaningful requirement-level evidence'})
 scored.sort(key=lambda x:(x['relevance_score'],x['direct_matches'],x['semantic_matches']),reverse=True)
 return scored,excluded
def experience_decisions(jd,profile,matches):
 decisions=[]
 for e in profile['experience'].get('experiences',[]):
  found=[]
  generic={'python','git','github','data science','machine learning','sql'}
  for m in matches:
   if m['requirement'] in generic: continue
   if any(x.get('type')=='experience' and x.get('record_id')==e.get('record_id') for x in m['evidence']): found.append(m['requirement'])
  relevant=bool(found and len(found)>=1)
  decisions.append({'record_id':e.get('record_id'),'organization':e.get('organization'),'title':e.get('title'),'decision':'INCLUDE' if relevant else 'NOT RELEVANT ENOUGH FOR RESUME','matched_requirements':found,'reason':'Actual responsibilities/evidence were compared; broad AI/Python wording alone is insufficient.'})
 return decisions
def select_projects(scored,experience):
 relevant_exp=any(x['decision']=='INCLUDE' for x in experience); limit=2 if relevant_exp else 3
 return scored[:limit], relevant_exp
def plan_resume(jd_text,profile):
 jd=analyze_jd(jd_text); matches=match_requirements(jd,profile); scored,excluded=project_matches(jd,profile,matches); exp=experience_decisions(jd,profile,matches); selected,exp_relevant=select_projects(scored,exp)
 selected_ids={x['record_id'] for x in selected}; relevant_skills=[]
 for m in matches:
  for e in m['evidence']:
   if e.get('type')=='skill' and e.get('status') in {'verified','candidate_provided','partially_verified'}:
    relevant_skills.append({'name':e['name'],'category':e.get('category'),'status':e.get('status'),'match_type':e.get('match_type'),'matched_requirement':m['requirement'],'why':m['explanation']})
 # Certifications are selected only when their actual record text matches a requirement; no invented relevance.
 certs=[]
 for c in profile['certifications'].get('certifications',[]):
  hits=[m['requirement'] for m in matches if any(x.get('type')=='certification' and x.get('record_id')==c.get('record_id') and x.get('status')=='verified' for x in m['evidence'])]
  if hits: certs.append({'record_id':c.get('record_id'),'name':c.get('name'),'issuer':c.get('issuer'),'matched_requirements':hits})
 supported=[m for m in matches if m['evidence_status']=='SUPPORTED']; partial=[m for m in matches if m['evidence_status']=='PARTIAL']; unsupported=[m for m in matches if m['evidence_status']=='UNSUPPORTED']; unknown=[m for m in matches if m['evidence_status']=='UNKNOWN']
 education=[{'record_id':e.get('record_id'),'institution':e.get('institution'),'degree':e.get('degree'),'field_of_study':e.get('field_of_study'),'grade':e.get('grade'),'why':'Education is fixed and sourced from education.json.'} for e in profile['education'].get('education',[])]
 rag_evidence=[{'record_id':p.get('record_id'),'name':p.get('name'),'evidence':p.get('technical_details',[]) or p.get('technologies',[]),'claim_scope':'project-level evidence only'} for p in profile['projects'].get('projects',[]) if any(x in candidate_text(p).lower() for x in ['ollama','llama3','rag'])]
 concerns=[]
 for m in unsupported: concerns.append({'type':'gap','requirement':m['requirement'],'message':'No profile evidence; do not add this technology or claim.'})
 for m in partial: concerns.append({'type':'partial','requirement':m['requirement'],'message':'Related evidence exists but does not fully establish the exact JD requirement.'})
 return {'mode':'job_application_planning','source_jd_text':jd_text,'candidate_positioning':'Fresher positioning based only on current JD relevance and source-supported profile evidence.','jd_analysis':jd,'candidate_matching':matches,'evidence_summary':{'supported_requirements':supported,'partial_requirements':partial,'unsupported_requirements':unsupported,'unknown_requirements':unknown},'gap_analysis':{'strong_evidence':supported,'partial_related_evidence':partial,'missing_requirements':unsupported,'unknown_requirements':unknown,'potential_risks':concerns},'resume_plan':{'skills_to_include':unique_dict(relevant_skills),'projects_to_include':selected,'experience_to_include':[x for x in exp if x['decision']=='INCLUDE'],'experience_decisions':exp,'experience_relevance_sufficient':exp_relevant,'third_project_fallback_used':not exp_relevant and len(selected)>=3,'education_to_include':education,'certifications_to_include':certs,'items_intentionally_excluded':{'projects':excluded,'note':'Excluded projects remain in the master profile and are not permanently ranked.'},'supported_requirements':supported,'partial_requirements':partial,'unsupported_requirements':unsupported,'summary_direction':'Emphasize only the selected completed projects and actual technologies; preserve gaps rather than substituting unsupported tools.','evidence_notes':[x['explanation'] for x in matches if x['evidence']], 'warnings':concerns,'project_selection_scope':'Dynamic for this JD only; completed lifecycle is mandatory and GitHub availability is independent.','llm_evidence':{'standalone_skill_record':False,'project_level_evidence':rag_evidence,'model_used':None,'validation_rule':'Deterministic profile evidence is authoritative; no external model was used.'}},'approval_checkpoint':{'resume_generation_allowed':False,'required_next_step':'Show this plan and wait for explicit user approval or requested changes.'},'safety':{'profile_data_modified':False,'resume_generated':False,'resume_docx_modified':False,'ats_template_modified':False,'external_model_used':False}}
def unique_dict(xs):
 out=[]; seen=set()
 for x in xs:
  k=(x.get('name'),x.get('matched_requirement'))
  if k not in seen:seen.add(k);out.append(x)
 return out

def main():
 ap=argparse.ArgumentParser(description='Phase 8 semantic JD analysis and approval-gated resume planning only'); ap.add_argument('--jd'); ap.add_argument('--sample-jd'); ap.add_argument('--output',required=True); args=ap.parse_args()
 if bool(args.jd)==bool(args.sample_jd): ap.error('provide exactly one of --jd or --sample-jd')
 text=Path(args.jd).read_text(encoding='utf-8') if args.jd else args.sample_jd; out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(plan_resume(text,load_profile()),indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); print(f'Wrote planning report: {out}\nProfile data modified: False\nResume generated: False')
if __name__=='__main__': main()
