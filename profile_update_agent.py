#!/usr/bin/env python3
"""Phase 7 Profile Update Agent.

Default behavior is a read-only update plan. Persistent writes require --apply
and --confirm. The agent never regenerates resumes.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re, shutil, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from career_os_config import CODE_ROOT, DATA_DIR, OUTPUT_DIR, STORAGE_ROOT, storage_root

ROOT=CODE_ROOT
DATA=DATA_DIR; REPORTS=OUTPUT_DIR/'reports'
CATEGORIES=['projects','skills','certifications','education','experience','achievements','master_profile']
STATUSES={'idea','planned','in_progress','completed','unknown'}
GITHUB_STATUSES={'github_verified','github_not_uploaded','github_pending','github_unverified'}
CATEGORY_HINTS={
 'skill':('skills',), 'skills':('skills',), 'technology':('skills',), 'technologies':('skills',),
 'project':('projects',), 'github':('projects',), 'repository':('projects',),
 'certification':('certifications',), 'certificate':('certifications',),
 'internship':('experience',), 'job':('experience',), 'experience':('experience',), 'training':('experience',),
 'achievement':('achievements',), 'award':('achievements',), 'hackathon':('achievements',),
 'degree':('education',), 'education':('education',), 'cgpa':('education',), 'summary':('master_profile',)
}
TOOL_SKILLS={'docker','git','github','vs code','vscode','n8n','ollama','streamlit'}

def load(name,root=None): return json.loads((storage_root(root)/'data'/f'{name}.json').read_text(encoding='utf-8'))
def dump(name,obj,root=None): (storage_root(root)/'data'/f'{name}.json').write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def now(): return datetime.now(timezone.utc).isoformat()
def norm(s): return re.sub(r'[^a-z0-9]+',' ',str(s).lower()).strip()
def slug(s): return re.sub(r'[^a-z0-9]+','_',str(s).lower()).strip('_')
def source(): return {'source_id':'user_provided','evidence_type':'explicit_user_statement','evidence_location':'Phase 7 profile update request'}
def prov(): return {'source_id':'user_provided','evidence_type':'explicit_user_statement','evidence_location':'Phase 7 profile update request','claims_supported':['user-provided update']}
def all_data(root=None): return {n:load(n,root) for n in CATEGORIES}

def project_records(data): return data['projects'].get('projects',[])
def skill_groups(data): return data['skills'].get('skill_groups',[])
def find_project(data, name=None, url=None):
    nn=norm(name) if name else ''
    for p in project_records(data):
        if url and p.get('github_url')==url: return p
        candidates=[p.get('name',''),p.get('github_url','')] + p.get('aliases',[])
        if nn and any(norm(x)==nn or nn in norm(x) or norm(x) in nn for x in candidates if x): return p
    return None

def find_skill(data,name):
    nn=norm(name)
    for g in skill_groups(data):
        for s in g.get('skills',[]):
            if norm(s.get('name'))==nn: return g,s
    return None,None

def find_cert(data,name):
    nn=norm(name)
    for c in data['certifications'].get('certifications',[]):
        if norm(c.get('name'))==nn or nn in norm(c.get('name','')) or norm(c.get('name','')) in nn: return c
    return None

def find_experience(data,name):
    nn=norm(name)
    for e in data['experience'].get('experiences',[]):
        if nn in norm(e.get('organization','')) or nn in norm(e.get('title','')): return e
    return None

def parse_status(text):
    low=text.lower()
    for s in STATUSES:
        if re.search(r'\b'+re.escape(s)+r'\b',low): return s
    if re.search(r'\b(completed|finished|done)\b',low): return 'completed'
    if re.search(r'\b(in progress|working on|currently building)\b',low): return 'in_progress'
    return None

def parse_github(text):
    urls=re.findall(r'https?://github\.com/[^\s,;)]+',text)
    if urls: return urls[0].rstrip('.')
    low=text.lower()
    if 'not on github' in low or "isn't on github" in low or 'not uploaded' in low: return None
    if 'uploaded' in low and 'github' in low: return '__uploaded_without_url__'
    return None

def route(text):
    low=text.lower(); matches=[]
    if re.search(r'\b(learned|know|add)\b',low) and not re.search(r'\b(project|used|built|uploaded)\b',low): return 'skills'
    if re.search(r'\b(used|built|uploaded|completed|mark)\b',low):
        # A known project name is enough to route an update even if the word "project" is omitted.
        if any(norm(p.get('name','')) in norm(text) for p in project_records(all_data())): return 'projects'
    for key,cats in CATEGORY_HINTS.items():
        if re.search(r'\b'+re.escape(key)+r'\b',low): matches.extend(cats)
    unique=[]
    for x in matches:
        if x not in unique: unique.append(x)
    if len(unique)==1: return unique[0]
    if len(unique)>1:
        if any(x in low for x in ['used','built','uploaded','completed']) and 'project' in low: return 'projects'
        return 'ambiguous'
    return 'ambiguous'

def plan_skill_gap_addition(name,category,root=None,application_id=None):
    data=all_data(root)
    name=str(name or '').strip()
    if not name or len(name)>100:
        return result(f'Confirm JD skill gap: {name}','ask_clarification','skills',[],[],['Provide a valid skill name.'])
    _,existing=find_skill(data,name)
    if existing:
        return result(f'Confirm JD skill gap: {name}','no_change_duplicate','skills',[{'action':'no_change','record':existing.get('name'),'reason':'skill already exists'}],[],[])
    categories={group.get('category') for group in skill_groups(data)}
    if category not in categories:
        return result(f'Confirm JD skill gap: {name}','ask_clarification','skills',[],[],['Choose an existing canonical skill category.'])
    evidence={'source_id':'user_provided','evidence_type':'explicit_user_confirmation','evidence_location':f'Confirmed JD skill gap for {application_id}' if application_id else 'Confirmed JD skill gap','claims_supported':[name]}
    action={'action':'add_skill','category':category,'name':name,'status':'candidate_provided','evidence':evidence}
    return result(f'User explicitly confirmed adding candidate-provided skill: {name}','planned','skills',[action],[],[])

def plan_request(text,root=None):
    data=all_data(root); low=text.lower(); category=route(text); actions=[]; conflicts=[]; questions=[]
    status=parse_status(text); github=parse_github(text)
    if re.search(r'\b(delete|remove)\b',low) and 'project' in low:
        m=re.search(r'project\s+["“]?([^"”\.]+)',text,re.I); name=m.group(1).strip() if m else None; existing=find_project(data,name)
        if existing:
            return result(text,'confirmation_required_delete','projects',[{'action':'archive_or_delete_project','record_id':existing['record_id'],'name':existing['name'],'references':['projects.json','master_profile.json record indexes']}],[],['This is destructive. Confirm whether to archive or delete the identified project.'])
        return result(text,'ask_clarification','projects',[],[],['Which project should be removed?'])
    if category=='ambiguous':
        if re.fullmatch(r'\s*add\s+[\w.+#-]+\s*[.!]?\s*',text,re.I): questions.append('Do you mean add this as a learned skill, record its use in a project, or both?')
        else: questions.append('Which profile category and record should this update affect? Please provide the missing category or record details.')
        return result(text,'ask_clarification',category,actions,conflicts,questions)
    if category=='skills':
        m=re.search(r'(?:learned|know|add)\s+([A-Za-z0-9+#. -]+?)(?:\s+to\s+my\s+skills)?[.!]?$',text,re.I)
        if not m: return result(text,'ask_clarification',category,actions,conflicts,['What is the exact skill name?'])
        name=m.group(1).strip(); name=re.sub(r'\s+to\s+my\s+skills$','',name,flags=re.I).strip(); g,s=find_skill(data,name)
        if g: return result(text,'no_change_duplicate',category,[{'action':'no_change','record':s.get('name'),'reason':'skill already exists'}],conflicts,questions)
        group='tools_and_platforms' if norm(name) in {norm(x) for x in TOOL_SKILLS} else None
        if not group: questions.append(f'Which existing skill category should contain {name}?')
        else: actions.append({'action':'add_skill','category':group,'name':name,'status':'candidate_provided'})
        # Skill usage is only updated when explicitly stated in the same request.
        return result(text,'planned' if actions else 'ask_clarification',category,actions,conflicts,questions)
    if category=='projects':
        m=re.search(r'(?:project\s+(?:called|named)|called|named)\s+["“]?([^"”\.]+)',text,re.I)
        name=m.group(1).strip() if m else None
        if not name:
            for p in project_records(data):
                if norm(p.get('name','')) in norm(text): name=p['name']; break
        url=None if github=='__uploaded_without_url__' else github
        existing=find_project(data,name,url)
        if not existing and ('uploaded' in low and 'github' in low):
            questions.append('Which existing project did you upload to GitHub? Please provide its name or URL.')
            return result(text,'ask_clarification',category,actions,conflicts,questions)
        if existing:
            date_match=re.search(r'\b(?:in|on|completed)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}\b',text,re.I)
            new_date=date_match.group(0) if date_match else None
            if new_date and existing.get('completion_date') and norm(new_date)!=norm(existing.get('completion_date')):
                conflicts.append({'record_id':existing['record_id'],'field':'completion_date','existing_value':existing.get('completion_date'),'new_value':new_date})
                return result(text,'conflict_requires_confirmation',category,[],conflicts,['Which completion date is correct?'])
            if github:
                if github=='__uploaded_without_url__': questions.append('Please provide the actual GitHub URL; it will not be fabricated.')
                else: actions.append({'action':'update_project_github','record_id':existing['record_id'],'name':existing['name'],'github_url':github,'github_availability':'github_verified'})
            if status and status!=existing.get('project_status'):
                actions.append({'action':'update_project_status','record_id':existing['record_id'],'name':existing['name'],'old':existing.get('project_status'),'new':status})
            usage=re.search(r'(?:used|use|using)\s+([A-Za-z0-9+#. -]+?)\s+(?:in|on)\s+(?:my\s+)?(?:the\s+)?',text,re.I)
            if usage and any(x in low for x in ['used','uses','using']): actions.append({'action':'add_project_technologies','record_id':existing['record_id'],'name':existing['name'],'technologies':[usage.group(1).strip(' .,')]})
            if not actions and not questions: actions.append({'action':'no_change','record':existing['name'],'reason':'matching project already contains the supplied identity'})
            return result(text,'ask_clarification' if questions and not actions else ('planned' if actions else 'no_change_duplicate'),category,actions,conflicts,questions)
        if not name:
            return result(text,'ask_clarification',category,actions,conflicts,['What is the new project name?'])
        if status is None: status='unknown'
        gh='github_not_uploaded' if ('not on github' in low or "isn't on github" in low or 'not uploaded' in low) else ('github_verified' if github else 'github_unverified')
        tech=[]
        tm=re.search(r'(?:uses?|with)\s+(.+?)(?:\s+and\s+it|\s+it\s+is|\.|$)',text,re.I)
        if tm: tech=[x.strip() for x in re.split(r',|\band\b',tm.group(1)) if x.strip()]
        actions.append({'action':'create_project','record_id':'project_'+slug(name),'name':name,'project_status':status,'github_availability':gh,'technologies':tech,'github_url':None if not github or github=='__uploaded_without_url__' else github})
        return result(text,'planned',category,actions,conflicts,questions)
    if category=='certifications':
        m=re.search(r'(?:certification|certificate)\s+(?:called|named)?\s*["“]?([^"”\.]+)',text,re.I); name=(m.group(1).strip() if m else None)
        if not name:
            m=re.search(r'(?:got|earned|received|add)\s+(?:a\s+)?(.+?)(?:\s+certification|\s+certificate)[.!]?$',text,re.I); name=m.group(1).strip() if m else None
        if not name: return result(text,'ask_clarification',category,actions,conflicts,['What is the exact certification name?'])
        if find_cert(data,name): return result(text,'no_change_duplicate',category,[{'action':'no_change','record':name,'reason':'certification already exists'}],conflicts,questions)
        actions.append({'action':'create_certification','record_id':'credential_'+slug(name),'name':name,'issuer':None,'issue_date':None,'credential_id':None,'verification_url':None})
        return result(text,'planned',category,actions,conflicts,questions)
    if category=='experience':
        return result(text,'ask_clarification',category,[],conflicts,['Please provide organization, title, experience type, dates, responsibilities, and source before an experience record can be persisted.'])
    if category=='achievements':
        m=re.search(r'(?:won|received|earned|got)\s+(.+?)(?:[.!]|$)',text,re.I); name=m.group(1).strip() if m else None
        return result(text,'planned',category,[{'action':'create_achievement','name':name,'details':text.strip()}],conflicts,[])
    if category=='education': return result(text,'ask_clarification',category,[],conflicts,['Which education record and exact field values should be updated?'])
    if category=='master_profile': return result(text,'ask_clarification',category,[],conflicts,['What exact profile summary or field value should replace the current value?'])
    return result(text,'ask_clarification',category,actions,conflicts,['The request could not be safely classified.'])

def result(request,decision,category,actions,conflicts,questions):
    return {'request':request,'decision':decision,'category':category,'actions':actions,'conflicts':conflicts,'questions':questions,'persistent_write_allowed':decision=='planned' and bool(actions),'resume_regeneration':False}

def apply_plan(plan,root=None,confirm=False,confirm_delete=False):
    if not confirm: raise PermissionError('Persistent profile writes require explicit --confirm.')
    if plan.get('decision')!='planned' or not plan.get('actions'): raise ValueError('Only a non-ambiguous planned update can be applied.')
    supported={'add_skill','update_project_github','update_project_status','add_project_technologies','create_project','create_certification','create_achievement'}
    unsupported=[a.get('action') for a in plan['actions'] if a.get('action') not in supported]
    if unsupported: raise ValueError('Unsupported profile update action(s): '+', '.join(str(x) for x in unsupported))
    data=all_data(root); changed=[]
    for a in plan['actions']:
        action=a['action']
        if action=='add_skill':
            group=next(g for g in skill_groups(data) if g.get('category')==a['category']); group.setdefault('skills',[]).append({'name':a['name'],'status':'candidate_provided','evidence':[a.get('evidence') or source()],'review_flags':[]}); changed.append('skills.json')
        elif action=='update_project_github':
            p=next(p for p in project_records(data) if p['record_id']==a['record_id']); p['github_url']=a['github_url']; p['github_availability']=a['github_availability']; p.setdefault('provenance',[]).append(prov()); p.setdefault('sources',[]).append(source()); changed.append('projects.json')
        elif action=='update_project_status':
            p=next(p for p in project_records(data) if p['record_id']==a['record_id']); p['project_status']=a['new']; p.setdefault('provenance',[]).append(prov()); changed.append('projects.json')
        elif action=='add_project_technologies':
            p=next(p for p in project_records(data) if p['record_id']==a['record_id']); p.setdefault('technologies',[])
            for t in a['technologies']:
                if t and t not in p['technologies']: p['technologies'].append(t)
            p.setdefault('provenance',[]).append(prov()); changed.append('projects.json')
        elif action=='create_project':
            p={'record_id':a['record_id'],'status':'candidate_provided','sources':[source()],'review_flags':[],'conflicts':[],'name':a['name'],'project_type':'project','github_url':a['github_url'],'classification_invariant':'project','source_status':'candidate_provided','documentation_level':'user_provided','purpose':None,'functionality':[],'technologies':a['technologies'],'frameworks_libraries_tools':a['technologies'][:],'technical_details':[],'measurable_results':[],'demonstrated_skills':[],'supported_role_categories':[],'source_evidence':{},'provenance':[prov()],'duplicate_group_id':None,'selection_metadata':{'available_for_resume':a['project_status']=='completed','requires_review_before_claim':True,'lifecycle_selection_rule':'only_completed_or_explicitly_allowed_in_progress','completed_status_required_for_standard_resume':True,'idea_or_planned_excluded_from_final_resume':True,'in_progress_requires_explicit_permission':True},'project_status':a['project_status'],'github_availability':a['github_availability'],'lifecycle_review_required':a['project_status']=='unknown','lifecycle_notes':[]}; data['projects']['projects'].append(p); changed.append('projects.json')
        elif action=='create_certification':
            data['certifications']['certifications'].append({'record_id':a['record_id'],'status':'candidate_provided','sources':[source()],'review_flags':['Issuer, date, credential ID, and URL were not provided.'],'conflicts':[],'name':a['name'],'issuer':a['issuer'],'credential_type':'certificate','issue_date':a['issue_date'],'expiration_date':None,'credential_id':a['credential_id'],'verification_url':a['verification_url'],'related_experience_id':None}); changed.append('certifications.json')
        elif action=='create_achievement':
            data['achievements'].setdefault('achievements',[]).append({'record_id':'achievement_'+slug(a.get('name') or 'user_provided_achievement'),'status':'candidate_provided','sources':[source()],'review_flags':[],'conflicts':[],'name':a.get('name'),'description':a.get('details'),'date':None,'issuer':None,'provenance':[prov()]}); changed.append('achievements.json')
    sync_master(data)
    for n in sorted(set(changed)):
        key=n[:-5] if n.endswith('.json') else n
        dump(key,data[key],root)
    dump('master_profile',data['master_profile'],root)
    return sorted(set(changed))

def sync_master(data):
    m=data['master_profile']; idx=m.setdefault('record_indexes',{})
    idx['project_ids']=[p['record_id'] for p in project_records(data)]
    idx['experience_ids']=[e['record_id'] for e in data['experience'].get('experiences',[])]
    idx['certification_ids']=[c['record_id'] for c in data['certifications'].get('certifications',[])]
    idx['education_ids']=[e['record_id'] for e in data['education'].get('education',[])]
    idx['achievement_ids']=[a['record_id'] for a in data['achievements'].get('achievements',[])]
    idx['skill_categories']=[g.get('category') for g in skill_groups(data)]
    idx['project_lifecycle_statuses']={p['record_id']:p.get('project_status','unknown') for p in project_records(data)}
    idx['project_github_availability']={p['record_id']:p.get('github_availability','github_unverified') for p in project_records(data)}

def validate_data(root=None):
    data=all_data(root); errors=[]
    for p in project_records(data):
        if p.get('project_status') not in STATUSES: errors.append('invalid project status '+p.get('record_id',''))
        if p.get('github_availability') not in GITHUB_STATUSES: errors.append('invalid github status '+p.get('record_id',''))
    pids=[p.get('record_id') for p in project_records(data)]; cids=[c.get('record_id') for c in data['certifications'].get('certifications',[])]
    if len(pids)!=len(set(pids)): errors.append('duplicate project record_id')
    if len(cids)!=len(set(cids)): errors.append('duplicate certification record_id')
    idx=data['master_profile'].get('record_indexes',{})
    if set(idx.get('project_ids',[]))!=set(pids): errors.append('master project index out of sync')
    return {'valid':not errors,'errors':errors,'project_count':len(pids),'certification_count':len(cids),'skill_group_count':len(skill_groups(data))}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--request',required=True); ap.add_argument('--apply',action='store_true'); ap.add_argument('--confirm',action='store_true'); ap.add_argument('--confirm-delete',action='store_true'); ap.add_argument('--root',default=str(STORAGE_ROOT)); args=ap.parse_args(); root=Path(args.root)
    plan=plan_request(args.request,root)
    if args.apply: changed=apply_plan(plan,root,args.confirm,args.confirm_delete); plan['changed_files']=changed; plan['applied_at']=now(); plan['persistent_write_allowed']=True
    else: plan['changed_files']=[]
    plan['validation_after_update']=validate_data(root)
    REPORTS.mkdir(parents=True,exist_ok=True); report=REPORTS/('profile_update_'+datetime.now().strftime('%Y%m%dT%H%M%SZ')+'.json'); report.write_text(json.dumps(plan,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'plan':plan,'report':str(report)},indent=2,ensure_ascii=False))
if __name__=='__main__': main()
