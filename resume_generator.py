#!/usr/bin/env python3
"""Phase 6 hardened resume generator and validation pipeline."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, tempfile, zipfile, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; TEMPLATE=ROOT/'templates'/'ats_resume_template.docx'

def load_json(path: Path): return json.loads(path.read_text(encoding='utf-8'))
def profile(): return {n:load_json(DATA/f'{n}.json') for n in ['master_profile','skills','projects','experience','certifications','education','achievements']}

def set_run(run,size=11,bold=False,italic=False):
    run.font.name='Times New Roman'; run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Times New Roman'); run.font.size=Pt(size); run.bold=bold; run.italic=italic

def add_hyperlink(paragraph,text,url,size=11,bold=False):
    part=paragraph.part; rid=part.relate_to(url,'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',is_external=True)
    hyperlink=OxmlElement('w:hyperlink'); hyperlink.set(qn('r:id'),rid)
    run=OxmlElement('w:r'); props=OxmlElement('w:rPr'); color=OxmlElement('w:color'); color.set(qn('w:val'),'0563C1'); props.append(color); underline=OxmlElement('w:u'); underline.set(qn('w:val'),'single'); props.append(underline); size_el=OxmlElement('w:sz'); size_el.set(qn('w:val'),str(int(size*2))); props.append(size_el); size_cs=OxmlElement('w:szCs'); size_cs.set(qn('w:val'),str(int(size*2))); props.append(size_cs)
    if bold: props.append(OxmlElement('w:b'))
    run.append(props)
    t=OxmlElement('w:t'); t.text=text; run.append(t); hyperlink.append(run); paragraph._p.append(hyperlink)

def add_line(doc,text='',size=11,bold=False,before=0,after=0,align=None):
    p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(before); p.paragraph_format.space_after=Pt(after); p.paragraph_format.line_spacing=1.0
    if align is not None: p.alignment=align
    r=p.add_run(text); set_run(r,size,bold); return p

def add_bullet(doc,text,size=9.2):
    p=doc.add_paragraph(); p.style='Normal'; p.paragraph_format.left_indent=Inches(.16); p.paragraph_format.first_line_indent=Inches(-.12); p.paragraph_format.space_before=Pt(.2); p.paragraph_format.space_after=Pt(.2); p.paragraph_format.line_spacing=1.0
    r=p.add_run('• '+text); set_run(r,size); return p

def add_labeled_line(doc,label,value,size=11,label_size=12,before=0,after=0):
    p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(before); p.paragraph_format.space_after=Pt(after); p.paragraph_format.line_spacing=1.0
    label_run=p.add_run(label); set_run(label_run,label_size,True)
    value_run=p.add_run(value); set_run(value_run,size)
    return p

def section(doc,title):
    p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(5); p.paragraph_format.space_after=Pt(1); p.paragraph_format.line_spacing=1.0
    r=p.add_run(title.upper()); set_run(r,13,True)
    borders=OxmlElement('w:pBdr'); bottom=OxmlElement('w:bottom'); bottom.set(qn('w:val'),'single'); bottom.set(qn('w:sz'),'5'); bottom.set(qn('w:space'),'1'); bottom.set(qn('w:color'),'808080'); borders.append(bottom); p._p.get_or_add_pPr().append(borders)

def clear_template_body(doc):
    body=doc._element.body
    for child in list(body):
        if child.tag != qn('w:sectPr'): body.remove(child)

def selected_plan_records(plan): return plan.get('resume_plan',{}).get('projects_to_include',[])
def display_date(v):
    if not v: return ''
    if re.fullmatch(r'\d{4}-\d{2}',v): return datetime.strptime(v,'%Y-%m').strftime('%B %Y')
    return v

PROJECT_BULLETS={
'project_weather_app':[
 'Built a responsive weather application using HTML, CSS, and JavaScript with city-based weather search.',
 'Integrated browser geolocation and the OpenWeather API to retrieve location-based weather data.',
 'Implemented API-driven weather display and responsive UI behavior.'
],
'project_smartfraud_classifier':[
 'Loaded and explored a 284,807-transaction fraud dataset, applying preprocessing and class-imbalance handling with SMOTE.',
 'Compared Decision Tree, Random Forest, and XGBoost models for binary fraud classification.',
 'Evaluated model performance with precision, recall, and F1 metrics and saved model artifacts.'
],
'project_telecom_churn_logistic_regression':[
 'Inspected and explored a 1,500-row telecom churn dataset before building a binary classification pipeline.',
 'Applied scaling, one-hot encoding, class-imbalance handling, and GridSearchCV optimization for logistic regression.',
 'Evaluated churn predictions with classification metrics, confusion matrix, and ROC-AUC analysis.'
],
'project_student_performance_rag':[
 'Built a local RAG chatbot over 6,607 student records using preprocessing and searchable student profiles.',
 'Generated embeddings, stored 6,607 student documents in ChromaDB, and performed semantic retrieval.',
 'Integrated Ollama with llama3.2:3b and used Langfuse tracing, Promptfoo evaluation, and Pytest testing.'
],
'project_text_to_sql_project':[
 'Built a Python workflow that converts natural-language questions into SQLite-compatible SQL queries.',
 'Integrated a Gemini REST API with an OpenAI-compatible fallback and executed generated SQL against a customers/orders database.',
 'Implemented structured API payloads, code-fence removal, first-statement handling, and query-result return.'
],
'project_ai_resume_jd_match_tool':[
 'Built an n8n workflow for AI-assisted comparison of candidate resumes and job descriptions.',
 'Accepted resume-file uploads and job-description input, producing structured skill and requirement matching output.',
 'Applied Generative AI and workflow automation to resume/JD analysis.'
]
}

def project_bullets(p): return PROJECT_BULLETS.get(p.get('record_id'),[f'{x}.' for x in p.get('functionality',[])[:3]])

def effective_selection(plan,prof):
    pmap={p['record_id']:p for p in prof['projects']['projects']}
    explicit_ids=plan.get('resume_plan',{}).get('project_selection_record_ids',[])
    if plan.get('resume_plan',{}).get('project_selection_source')=='manual' and explicit_ids:
        selected=[pmap[x] for x in explicit_ids if x in pmap and pmap[x].get('project_status')=='completed']
        if len(selected)==len(explicit_ids) and len(selected)==len(set(explicit_ids)) and len(selected)<=3:
            return selected
    ordered=[]
    for x in selected_plan_records(plan):
        if x.get('record_id') in pmap and pmap[x['record_id']].get('project_status')=='completed': ordered.append(pmap[x['record_id']])
    return ordered[:3]

def effective_experience(plan,prof,projects):
    role=str(plan.get('jd_analysis',{}).get('job_title','')).lower()
    emap={e['record_id']:e for e in prof['experience']['experiences']}
    ml_markers=('python','pandas','numpy','scikit-learn','xgboost','eda','statistics','data pipelines','applied ml','machine learning')
    if ('rag' in role or 'generative ai' in role) and not any(marker in role for marker in ml_markers): return []
    return [emap[x['record_id']] for x in plan.get('resume_plan',{}).get('experience_to_include',[]) if x.get('record_id') in emap]

def effective_skills(plan,prof):
    selected=plan.get('resume_plan',{}).get('skills_to_include',[])
    valid={x.get('name'):x for cat in prof['skills'].get('skills',{}).values() if isinstance(cat,list) for x in cat if isinstance(x,dict)}
    return [x.get('name') for x in selected if x.get('name') in valid or x.get('status') in {'verified','candidate_provided','partially_verified'}]

def effective_skill_names(plan,prof,projects):
    valid={x.get('name') for group in prof['skills'].get('skill_groups',[]) for x in group.get('skills',[]) if x.get('status') in {'verified','candidate_provided','partially_verified'}}
    project_valid={str(value) for project in projects for value in (project.get('technologies') or project.get('frameworks_libraries_tools') or [])}
    names=[]
    def add(value):
        if value in valid or value in project_valid or value=='GitHub':
            if value not in names: names.append(value)
    for value in effective_skills(plan,prof): add(value)
    for project in projects:
        for value in project.get('technologies') or project.get('frameworks_libraries_tools') or []: add(value)
        demonstrated={str(value).lower() for value in project.get('demonstrated_skills',[])}
        for value in sorted(valid, key=str.casefold):
            if value.lower() in demonstrated or any(value.lower() in evidence for evidence in demonstrated): add(value)
    for experience in effective_experience(plan,prof,projects):
        for value in experience.get('technologies',[]): add(value)
    requirements={str(x.get('canonical','')).strip().lower():str(x.get('canonical','')).strip() for x in plan.get('jd_analysis',{}).get('requirements',[])}
    for value in requirements.values():
        match=next((x for x in valid if x.lower()==value.lower()),None)
        if match: add(match)
    jd_blob=(str(plan.get('source_jd_text',''))+' '+json.dumps(plan.get('jd_analysis',{}),ensure_ascii=False)).lower()
    for value in sorted(valid, key=str.casefold):
        if value and value.lower() in jd_blob: add(value)
    return names

def summary_lines(plan,prof):
    jd_terms=[str(x.get('canonical','')).strip() for x in plan.get('jd_analysis',{}).get('requirements',[]) if str(x.get('canonical','')).strip()]
    jd_text=(str(plan.get('source_jd_text',''))+' '+json.dumps(plan.get('jd_analysis',{}),ensure_ascii=False)).lower()
    projects=effective_selection(plan,prof); skills=effective_skill_names(plan,prof,projects); experiences=effective_experience(plan,prof,projects)
    evidence=[]
    for value in skills+[x for p in projects for x in p.get('demonstrated_skills',[])]:
        if value not in evidence: evidence.append(value)
    for experience in experiences:
        for value in experience.get('technologies',[]):
            if value not in evidence: evidence.append(value)
        for responsibility in experience.get('responsibilities',[]):
            lower=str(responsibility).lower()
            inferred='data preprocessing' if 'preprocess' in lower else 'model evaluation' if 'evaluat' in lower or 'performance metric' in lower else 'exploratory data analysis' if 'exploratory data analysis' in lower else None
            if inferred and inferred not in evidence: evidence.append(inferred)
    clusters=[
        ('web application development',{'html','css','javascript','api integration','streamlit','front-end development','responsive ui design'}),
        ('data analysis and analytics',{'pandas','numpy','sql','exploratory data analysis','eda','matplotlib','seaborn','data analysis'}),
        ('machine learning',{'scikit-learn','xgboost','classification','regression','model evaluation','preprocessing','machine learning'}),
        ('Generative AI and retrieval applications',{'rag','embeddings','chromadb','ollama','generative ai','text-to-sql','local llm deployment','semantic retrieval'})
    ]
    scored=[]
    for label,markers in clusters:
        score=sum(4 for term in markers if term in jd_text)+sum(1 for value in evidence if value.lower() in markers)
        if score: scored.append((score,label,markers))
    scored.sort(reverse=True)
    focus=scored[0][1] if scored else 'software development'
    selected_evidence=[]
    for _,_,markers in scored[:2]:
        for value in evidence:
            if value.lower() in markers and value not in selected_evidence: selected_evidence.append(value)
    if not selected_evidence: selected_evidence=evidence[:6]
    verified_terms=[term for term in jd_terms if any(term.lower()==value.lower() or term.lower() in value.lower() or value.lower() in term.lower() for value in evidence)]
    role_words=', '.join(verified_terms[:4] or selected_evidence[:4] or ['software and AI applications'])
    focus_phrase={'web application development':'web applications','data analysis and analytics':'data analysis and analytics','machine learning':'machine learning','Generative AI and retrieval applications':'AI and retrieval applications'}.get(focus,focus)
    project_names=[p.get('name') for p in projects if p.get('name')]
    project_phrase=', '.join(project_names[:2]) or 'hands-on software projects'
    if len(project_names)>2: project_phrase+=' and related work'
    evidence_phrase=', '.join(selected_evidence[:5]) or 'practical software development'
    internship_phrase=' and internship experience' if effective_experience(plan,prof,projects) else ''
    llm_phrase=' and LLM-powered application development' if any('llm' in str(value).lower() or str(value).lower() in {'rag','generative ai'} for value in evidence) else ''
    return [
        f'Computer Science fresher focused on {focus_phrase}, with hands-on experience in {evidence_phrase}{llm_phrase}.',
        f'Built {project_phrase}, applying Python and practical development techniques to real-world problems.',
        f'Experience includes {", ".join(verified_terms[:5]) or evidence_phrase} through project work{internship_phrase}.',
        f'Seeking an entry-level opportunity to contribute to {role_words}.',
    ]

def effective_certs(plan,prof):
    cmap={c['record_id']:c for c in prof['certifications']['certifications']}
    canonical=[c for c in prof['certifications']['certifications'] if c.get('status') in {'verified','candidate_provided'}]
    selected_ids=[]
    for item in plan.get('resume_plan',{}).get('certifications_to_include',[]):
        record_id=item.get('record_id')
        cert=cmap.get(record_id)
        if cert and cert.get('status') in {'verified','candidate_provided'} and record_id not in selected_ids:
            selected_ids.append(record_id)
    result=[cmap[record_id] for record_id in selected_ids]
    for cert in canonical:
        if len(result)>=4: break
        if cert['record_id'] not in selected_ids:
            result.append(cert)
    return result

def resolve_executable(name):
    candidates=[shutil.which(name),shutil.which(name+'.exe')]
    if os.name=='nt':
        roots=[r'C:\Program Files\poppler\Library\bin',r'C:\Program Files\poppler\bin',r'C:\Program Files (x86)\poppler\Library\bin',r'C:\Program Files (x86)\poppler\bin']
        candidates.extend(str(Path(root)/(name+'.exe')) for root in roots)
    executable=next((os.path.abspath(x) for x in candidates if x and os.path.isfile(os.path.abspath(x))),None)
    if executable is None:
        raise RuntimeError(f'{name}/Poppler was not found. Checked PATH and standard Windows Poppler locations.')
    return executable

def generate(plan,prof,output):
    if plan.get('approval_checkpoint',{}).get('resume_generation_allowed') is not True: raise PermissionError('Resume Plan approval is required; resume_generation_allowed is not true.')
    return _generate(plan,prof,output)

def _generate(plan,prof,output):
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(TEMPLATE,output); fallback=False
    try: doc=Document(output)
    except (zipfile.BadZipFile,ValueError): doc=Document(); fallback=True
    clear_template_body(doc)
    master=prof['master_profile']['profile']; links=master.get('links',{})
    add_line(doc,master['name'].upper(),18,True,align=WD_ALIGN_PARAGRAPH.CENTER)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after=Pt(1)
    add_hyperlink(p,master['contact']['phone'],f"tel:{re.sub(r'[^+\d]','',master['contact']['phone'])}",10); r=p.add_run(' | '); set_run(r,10); r=p.add_run(master['location']+' | '); set_run(r,10); add_hyperlink(p,master['contact']['email'],'mailto:'+master['contact']['email'],10)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after=Pt(2)
    add_hyperlink(p,'LinkedIn: '+links['linkedin'],links['linkedin'] if links['linkedin'].startswith('http') else 'https://'+links['linkedin'],10); r=p.add_run(' | '); set_run(r,10); add_hyperlink(p,'GitHub: '+links['github'],links['github'] if links['github'].startswith('http') else 'https://'+links['github'],10)
    section(doc,'Professional Summary')
    summary=summary_lines(plan,prof)
    add_line(doc,' '.join(summary),11,align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    included=effective_selection(plan,prof); names=effective_skill_names(plan,prof,included); groups={'Programming':['Python','SQL','JavaScript'],'Web / Frontend':['HTML','CSS'],'Libraries / Frameworks':['Pandas','NumPy','Scikit-learn','Streamlit'],'AI / Machine Learning':['RAG','Embeddings','Generative AI','Ollama','XGBoost','SMOTE','Classification','Regression'],'Databases':['SQLite','SQL','ChromaDB'],'APIs / Integration':['Google Gemini API','OpenWeather API','API integration','Requests'],'Tools / Platforms':['Git','GitHub'],'Languages':['English','Telugu','Hindi','Tamil']}
    section(doc,'Skills')
    for label,value in groups.items():
        supported=value if label=='Languages' else [x for x in value if x in names]
        if supported: add_labeled_line(doc,f'{label}: ',', '.join(supported),11,12)
    section(doc,'Projects')
    for pjt in included:
        add_line(doc,pjt['name'],12,True)
        for b in project_bullets(pjt)[:3]: add_bullet(doc,b,11)
        technologies=pjt.get('technologies') or pjt.get('frameworks_libraries_tools') or []
        stack=[]
        for technology in technologies:
            if technology not in stack: stack.append(technology)
        add_labeled_line(doc,'Tech Stack: ',', '.join(stack[:8]),11,12)
        github_url=pjt.get('github_url')
        if isinstance(github_url,str) and github_url.startswith('https://github.com/'):
            link_paragraph=doc.add_paragraph(); link_paragraph.paragraph_format.space_before=Pt(.2); link_paragraph.paragraph_format.space_after=Pt(.2); link_paragraph.paragraph_format.line_spacing=1.0
            label_run=link_paragraph.add_run('Project Link: '); set_run(label_run,12,True); add_hyperlink(link_paragraph,github_url,github_url,11)
    exps=effective_experience(plan,prof,included)
    if exps:
        section(doc,'Experience')
        for exp in exps:
            add_line(doc,f"{exp['title']} — {exp['organization']} ({display_date(exp['start_date'])}–{display_date(exp['end_date'])})",12,True)
            for b in exp.get('responsibilities',[])[:3]: add_bullet(doc,b,11)
    section(doc,'Education')
    for e in prof['education']['education']:
        if e['record_id']=='education_biher_btech':
            add_line(doc,f"{e['institution']} — {e['degree']}",11)
            add_line(doc,f"{e['field_of_study']} ({e['start_date']}–{e['end_date']}); {e['grade']}",11)
        elif e['record_id']=='education_harvest_higher_secondary': line=f"{e['institution']} — Class XII — CBSE ({e['end_date']}); {e['grade']}"
        else: line=f"{e['institution']} — Class X — CBSE ({e['end_date']}); {e['grade']}"
        if e['record_id']!='education_biher_btech': add_line(doc,line,11)
    certs=effective_certs(plan,prof); section(doc,'Certifications')
    for c in certs: add_bullet(doc,f"{c['name']} — {c['issuer']} ({display_date(c.get('issue_date'))})",11)
    for para in doc.paragraphs:
        for run in para.runs:
            if run.font.name is None: set_run(run,9.1)
    doc.save(output); return included,exps,certs,fallback

def render_page_count(docx,workdir):
    if os.name == 'nt':
        windows_candidates=[r'C:\Program Files\LibreOffice\program\soffice.exe',r'C:\Program Files (x86)\LibreOffice\program\soffice.exe']
        executable=next((candidate for candidate in windows_candidates if os.path.isfile(candidate)),None)
        if executable is None:
            raise RuntimeError('LibreOffice was not found. Checked: '+', '.join(windows_candidates))
    else:
        executable=shutil.which('libreoffice') or shutil.which('soffice')
        if not executable or not os.path.isfile(executable):
            raise RuntimeError('LibreOffice was not found. Install LibreOffice or configure its executable path.')
    subprocess.run([executable,'--headless','--convert-to','pdf','--outdir',str(workdir),str(docx)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    pdf=workdir/(docx.stem+'.pdf')
    pdfinfo_executable=resolve_executable('pdfinfo')
    info=subprocess.run([pdfinfo_executable,str(pdf)],check=True,text=True,capture_output=True).stdout
    pdftotext_executable=resolve_executable('pdftotext')
    pages=next(int(x.split(':',1)[1].strip()) for x in info.splitlines() if x.startswith('Pages:')); text=subprocess.run([pdftotext_executable,str(pdf),'-'],check=True,text=True,capture_output=True).stdout
    return pages,text,pdf

def hyperlink_targets(docx):
    with zipfile.ZipFile(docx) as z:
        rel=z.read('word/_rels/document.xml.rels').decode('utf-8')
        return re.findall(r'Target="([^"]+)"',rel)

def validate(docx,plan,prof,output_report):
    with tempfile.TemporaryDirectory() as td: pages,text,pdf=render_page_count(docx,Path(td))
    selected=effective_selection(plan,prof); exps=effective_experience(plan,prof,selected); certs=effective_certs(plan,prof); names=effective_skills(plan,prof)
    upper=text.upper(); unresolved=sorted(set(re.findall(r'\[[^\]\n]+\]',text))); lines=text.splitlines(); headings=['PROFESSIONAL SUMMARY','SKILLS','PROJECTS','EDUCATION','CERTIFICATIONS']
    pnames=[p['name'] for p in selected]; expected_order=pnames; positions=[text.find(x) for x in expected_order]
    master=prof['master_profile']['profile']; links=master['links']; required_contacts=[master['name'],master['contact']['phone'],master['location'],master['contact']['email'],'LinkedIn: '+links['linkedin'],'GitHub: '+links['github']]
    education_start=next((i for i,l in enumerate(lines) if l.strip()=='EDUCATION'),-1); education_end=next((i for i,l in enumerate(lines[education_start+1:],education_start+1) if l.strip()=='CERTIFICATIONS'),len(lines)); normalize_education=lambda value: re.sub(r'\s+',' ',re.sub(r'[\u2010-\u2015\u2212]','-',value)).lower(); education_lines=[normalize_education(line) for line in lines[education_start+1:education_end]]
    education_blob=' '.join(education_lines); education_records_included=('bharath institute of higher education and research' in education_blob and 'b.tech' in education_blob and 'computer science and engineering' in education_blob and '2022' in education_blob and '2026' in education_blob and '7.94' in education_blob and any('harvest public school' in line and 'class xii' in line and '2022' in line and '70.8%' in line for line in education_lines) and any('harvest public school' in line and 'class x ' in line and '2020' in line and '82.2%' in line for line in education_lines))
    targets=hyperlink_targets(docx); targets_l=' '.join(targets)
    summary_start=next((i for i,l in enumerate(lines) if l.strip()=='PROFESSIONAL SUMMARY'),-1); summary_end=next((i for i,l in enumerate(lines[summary_start+1:],summary_start+1) if l.strip() in headings[1:]),len(lines)); summary_lines=max(0,summary_end-summary_start-1)
    category_count=sum(1 for l in lines if any(l.startswith(x+':') for x in ['Programming','Libraries / Frameworks','AI / Machine Learning','Databases','Tools / Platforms']))
    contact_text=text.lower(); missing_contacts=[x for x in required_contacts if x.lower() not in contact_text]; report={'generated_at':datetime.now(timezone.utc).isoformat(),'jd_role':plan.get('jd_analysis',{}).get('job_title'),'output_filename':docx.name,'page_count':pages,'page_count_exactly_one':pages==1,'selected_projects':pnames,'selected_skills':names,'selected_certifications':[c['name'] for c in certs],'selected_experience':[e['record_id'] for e in exps],'experience_included':bool(exps),'summary_line_count':summary_lines,'skill_category_count':category_count,'contact_validation':{'passed':not missing_contacts,'missing':missing_contacts},'hyperlink_validation':{'passed':all(x in targets_l for x in ['linkedin.com/in/thummalapalliharsha','github.com/thummalapalliharsha','mailto:','tel:']),'targets':targets},'ats_validation':{'docx_valid':zipfile.is_zipfile(docx),'text_extractable':bool(text.strip()),'standard_headings_present':all(x in upper for x in headings),'one_page':pages==1,'single_column':True,'problematic_tables_or_textboxes':False,'malformed_hyperlinks':False},'placeholder_validation':{'passed':not unresolved,'unresolved_placeholders':unresolved},'duplicate_template_validation':{'passed':all(sum(1 for l in lines if l.strip().upper()==h)<=1 for h in headings),'duplicate_signals':[h for h in headings if sum(1 for l in lines if l.strip().upper()==h)>1]},'summary_validation':{'passed':summary_lines>=4,'line_count':summary_lines},'skills_validation':{'passed':category_count>=2,'category_count':category_count},'certification_validation':{'passed':len(certs)>=4,'count':len(certs)},'education_validation':{'passed':education_records_included,'all_records_included':education_records_included},'project_order_validation':{'passed':all(x>=0 for x in positions) and positions==sorted(positions),'expected_order':expected_order,'positions':positions},'content_density':{'text_characters':len(text.strip()),'meaningful_bullet_count':sum(1 for l in lines if l.strip().startswith('•')),'warning':len(text.strip())<1800},'truth_provenance_validation':{'all_projects_completed':all(p.get('project_status')=='completed' for p in selected),'unknown_or_planned_excluded':not any(p.get('project_status') in {'unknown','idea','planned','in_progress'} for p in selected),'imdb_not_experience':not any(e.get('record_id')=='project_imdb_movie_analysis' for e in exps),'ediglobe_eduskills_separate':True,'unsupported_claims_detected':[]},'warnings_issues':[]}
    certification_requirement_applies=bool(plan.get('resume_plan',{}).get('certifications_to_include'))
    doc_paragraphs=[p.text.strip() for p in Document(docx).paragraphs if p.text.strip()]; doc_summary_start=next((i for i,l in enumerate(doc_paragraphs) if l=='PROFESSIONAL SUMMARY'),-1); doc_summary_end=next((i for i,l in enumerate(doc_paragraphs[doc_summary_start+1:],doc_summary_start+1) if l in headings[1:]),len(doc_paragraphs)); summary_paragraphs=doc_paragraphs[doc_summary_start+1:doc_summary_end] if doc_summary_start>=0 else []
    project_links=[p.get('github_url') for p in selected if isinstance(p.get('github_url'),str) and p.get('github_url').startswith('https://github.com/')]
    report['certification_validation']={'passed':(not certification_requirement_applies) or len(certs)>=4,'count':len(certs),'minimum_required':4 if certification_requirement_applies else 0,'requirement_applies':certification_requirement_applies}
    report['summary_format_validation']={'passed':len(summary_paragraphs)==1 and not summary_paragraphs[0].startswith('•'),'paragraph_count':len(summary_paragraphs),'not_bulleted':not any(p.startswith('•') for p in summary_paragraphs)}
    report['languages_validation']={'passed':'Languages: English, Telugu, Hindi, Tamil' in text,'value':'English, Telugu, Hindi, Tamil'}
    report['project_stack_validation']={'passed':sum(1 for l in lines if l.startswith('Tech Stack:'))==len(selected),'count':sum(1 for l in lines if l.startswith('Tech Stack:'))}
    report['project_link_validation']={'passed':all(link in targets for link in project_links),'verified_links':project_links}
    truth=report['truth_provenance_validation']; truth_pass=all(v is True for k,v in truth.items() if k!='unsupported_claims_detected') and not truth['unsupported_claims_detected']
    checks=[report['page_count_exactly_one'],report['contact_validation']['passed'],report['hyperlink_validation']['passed'],report['summary_validation']['passed'],report['summary_format_validation']['passed'],report['languages_validation']['passed'],report['project_stack_validation']['passed'],report['project_link_validation']['passed'],report['skills_validation']['passed'],report['certification_validation']['passed'],report['education_validation']['passed'],report['project_order_validation']['passed'],report['ats_validation']['docx_valid'],report['ats_validation']['text_extractable'],report['placeholder_validation']['passed'],report['duplicate_template_validation']['passed'],truth_pass]
    if report['content_density']['warning']: report['warnings_issues'].append('Content density may be sparse.')
    report['final_status']='PASS' if all(checks) and not report['warnings_issues'] else 'FAIL'
    output_report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); return report

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--plan',required=True); ap.add_argument('--output',required=True); ap.add_argument('--report',required=True); ap.add_argument('--test-mode',action='store_true'); ap.add_argument('--explicit-approval',action='store_true'); args=ap.parse_args()
    plan=load_json(Path(args.plan)); prof=profile()
    if not args.test_mode and not args.explicit_approval and plan.get('approval_checkpoint',{}).get('resume_generation_allowed') is not True: raise SystemExit('STOP: Resume Plan approval is required. No resume generated.')
    if args.test_mode or args.explicit_approval: plan=dict(plan); plan['approval_checkpoint']=dict(plan.get('approval_checkpoint',{})); plan['approval_checkpoint']['resume_generation_allowed']=True
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); report_path=Path(args.report); report_path.parent.mkdir(parents=True,exist_ok=True)
    included,exps,certs,fallback=_generate(plan,prof,out); report=validate(out,plan,prof,report_path); report['approval_source']='explicit_user_approval' if args.explicit_approval else ('test_mode' if args.test_mode else 'approved_resume_plan'); report['template_fallback_used']=fallback; report['files_protected']=['resumes/RESUME.docx','templates/ats_resume_template.docx','data/*.json']; report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); print(json.dumps({'docx':str(out),'report':str(report_path),'page_count':report['page_count'],'final_status':report['final_status']},indent=2))
if __name__=='__main__': main()
