from __future__ import annotations
import json, os, re, shutil, subprocess, tempfile
from pathlib import Path
import copy
import hashlib, uuid
from datetime import datetime
from html import escape
import streamlit as st
import streamlit.components.v1 as components
from career_os_config import (
  CODE_ROOT,
  DATA_DIR,
  OUTPUT_DIR,
  resolve_storage_reference,
  storage_reference,
)

ROOT=CODE_ROOT
DATA=DATA_DIR; OUT=OUTPUT_DIR; REPORTS=OUT/'reports'; RESUMES=OUT/'resumes'; LETTERS=OUT/'cover_letters'
for p in [REPORTS,RESUMES,LETTERS]: p.mkdir(parents=True,exist_ok=True)

import application_assistant as aa
import jd_resume_planner as planner
import profile_update_agent as pua
import profile_security as psecurity
import resume_generator as rg
import career_os_api as career_api

st.set_page_config(page_title='AI Career Command Center', page_icon='✦', layout='wide', initial_sidebar_state='expanded')

st.markdown('''<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap');
:root{--bg:#05080d;--panel:#0b111b;--panel2:#101927;--line:#1d2a3d;--line-strong:#30445d;--text:#f3f7fb;--muted:#8d9bad;--cyan:#7dd3fc;--violet:#a78bfa;--green:#6ee7b7;--amber:#fbbf74;--red:#fb7185;}
.stApp{background:radial-gradient(circle at 88% 0%,rgba(95,80,190,.18),transparent 28%),radial-gradient(circle at 10% 12%,rgba(24,153,180,.09),transparent 26%),var(--bg);color:var(--text);font-family:'Space Grotesk',sans-serif}.block-container{max-width:1480px;padding:2.2rem clamp(1rem,4vw,4rem) 4.5rem}.stSidebar{background:linear-gradient(180deg,#080c13,#0a1019);border-right:1px solid var(--line)}
.hero{padding:1.7rem 1.9rem;border:1px solid var(--line);border-radius:24px;background:linear-gradient(135deg,rgba(20,32,51,.9),rgba(9,14,23,.92));box-shadow:0 24px 70px rgba(0,0,0,.28),inset 0 1px rgba(255,255,255,.06);position:relative;overflow:hidden;animation:ui1-reveal .24s ease-out both}.hero:after{content:'';position:absolute;width:280px;height:280px;right:-100px;top:-135px;border-radius:50%;border:1px solid rgba(125,211,252,.22);box-shadow:0 0 0 20px rgba(125,211,252,.04),0 0 0 42px rgba(167,139,250,.035)}.eyebrow{font:500 .7rem 'DM Mono';letter-spacing:.18em;color:var(--cyan);text-transform:uppercase}.hero h1{font-size:clamp(1.8rem,3vw,2.55rem);margin:.35rem 0 .3rem;letter-spacing:-.05em}.hero p{color:var(--muted);margin:0;max-width:760px}.card{border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,rgba(16,25,39,.94),rgba(8,13,22,.94));padding:1.15rem 1.25rem;box-shadow:0 16px 42px rgba(0,0,0,.16);min-height:100%;transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease}.card:hover{transform:translateY(-2px);border-color:var(--line-strong);box-shadow:0 20px 50px rgba(0,0,0,.24)}.metric{font-size:2rem;font-weight:700;color:var(--text);letter-spacing:-.05em}.label{font:500 .68rem 'DM Mono';color:var(--muted);letter-spacing:.1em;text-transform:uppercase}.status{display:inline-flex;align-items:center;gap:.35rem;padding:.3rem .62rem;border-radius:999px;background:rgba(125,211,252,.1);border:1px solid rgba(125,211,252,.25);font:500 .7rem 'DM Mono';color:var(--cyan);transition:background .2s ease,border-color .2s ease}.status-green{color:var(--green);background:rgba(110,231,183,.1);border-color:rgba(110,231,183,.25)}.status-amber{color:var(--amber);background:rgba(251,191,116,.1);border-color:rgba(251,191,116,.25)}.status-violet{color:var(--violet);background:rgba(167,139,250,.1);border-color:rgba(167,139,250,.25)}.muted{color:var(--muted)}.section-title{font-size:1.18rem;font-weight:600;margin:1.8rem 0 .8rem;letter-spacing:-.02em}.small{font-size:.82rem;color:var(--muted)}.workspace-card{border:1px solid var(--line);border-radius:16px;background:rgba(10,16,26,.72);padding:.9rem 1rem;transition:border-color .2s ease,background .2s ease}.workspace-card:hover{border-color:var(--line-strong);background:rgba(16,25,39,.86)}.artifact-card{border:1px solid var(--line);border-radius:20px;background:linear-gradient(145deg,rgba(15,24,38,.96),rgba(7,12,20,.96));padding:1.25rem;min-height:100%;box-shadow:0 18px 45px rgba(0,0,0,.18);transition:border-color .2s ease,transform .2s ease}.artifact-card:hover{border-color:var(--line-strong);transform:translateY(-2px)}.artifact-card.working{border-color:rgba(251,191,116,.32)}.artifact-card.final{border-color:rgba(110,231,183,.28)}.artifact-card h3{margin:.25rem 0 .15rem;font-size:1.18rem;letter-spacing:-.02em}.artifact-meta{font:500 .72rem 'DM Mono';color:var(--muted);line-height:1.7}.lifecycle{display:flex;align-items:center;gap:.45rem;flex-wrap:wrap;margin:1.15rem 0 1.6rem}.lifecycle-step{padding:.42rem .68rem;border:1px solid var(--line);border-radius:999px;color:var(--muted);font:500 .68rem 'DM Mono';background:rgba(10,16,26,.7)}.lifecycle-step.done{color:var(--green);border-color:rgba(110,231,183,.28);background:rgba(110,231,183,.08)}.lifecycle-step.active{color:var(--cyan);border-color:rgba(125,211,252,.3);background:rgba(125,211,252,.08)}.lifecycle-arrow{color:var(--muted);font-size:.8rem}.artifact-dot{display:inline-block;width:.48rem;height:.48rem;border-radius:50%;background:var(--cyan);margin-right:.35rem}.artifact-dot.final{background:var(--green)}.artifact-dot.working{background:var(--amber)}div[data-testid="stMetric"]{background:rgba(10,17,27,.76);border:1px solid var(--line);padding:1rem;border-radius:16px;animation:ui1-reveal .28s ease-out both}div.stButton>button{border-radius:10px;border:1px solid #2b4058;background:linear-gradient(135deg,#15263b,#101b2b);color:#eef8ff;font-weight:600;transition:transform .15s ease,border-color .15s ease,background .15s ease}div.stButton>button:hover{border-color:var(--cyan);background:linear-gradient(135deg,#1a3550,#142338);color:white;transform:translateY(-1px)}textarea,input{background:#080f19!important;color:#edf5ff!important;border-color:var(--line)!important}.stAlert{border-radius:14px;border:1px solid var(--line)}[data-testid="stSidebarNav"]{padding-top:1rem}@keyframes ui1-reveal{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}@media (max-width:900px){.block-container{padding:1.2rem 1rem 3rem}.hero{padding:1.35rem}.hero h1{font-size:1.8rem}}@media (prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important;scroll-behavior:auto!important}}
</style>''', unsafe_allow_html=True)
st.markdown('''<style>
/* UI-5 polish: presentation only; no workflow, persistence, or callback changes. */
:root{--ui5-radius:16px;--ui5-control-height:2.7rem;--ui5-focus:rgba(125,211,252,.72)}
.block-container{padding-top:1.7rem;max-width:1520px}
.hero{margin-bottom:1.35rem;border-radius:var(--ui5-radius);padding:1.55rem 1.75rem}
.hero h1{line-height:1.1;font-weight:700}.hero p{font-size:.98rem;line-height:1.6}
.section-title{margin-top:1.55rem;margin-bottom:.7rem;font-size:1.05rem;line-height:1.35;color:var(--text)}
.card,.workspace-card,.artifact-card,div[data-testid="stMetric"]{border-radius:var(--ui5-radius)}.workspace-card,.artifact-card{animation:ui6-reveal .42s ease-out both}
.card,.workspace-card,.artifact-card{padding:1rem 1.1rem}
.workspace-card p,.artifact-card p,.card p{line-height:1.55}
.small,.artifact-meta{line-height:1.55}
.label{font-size:.66rem;line-height:1.35}
.status{min-height:1.6rem;line-height:1.2;white-space:normal}
div.stButton>button,div.stDownloadButton>button{min-height:var(--ui5-control-height);padding:.55rem .9rem;border-radius:10px;white-space:normal;line-height:1.25}
div.stButton>button:focus-visible,div.stDownloadButton>button:focus-visible,
input:focus-visible,textarea:focus-visible,[role="combobox"]:focus-visible{outline:2px solid var(--ui5-focus)!important;outline-offset:2px!important;box-shadow:0 0 0 3px rgba(125,211,252,.14)!important}
div.stButton>button:disabled,div.stDownloadButton>button:disabled{opacity:.52;cursor:not-allowed}
textarea,input,[data-baseweb="select"]>div{border-radius:10px!important;min-height:var(--ui5-control-height)}
textarea{line-height:1.55!important}
div[data-testid="stHorizontalBlock"]{gap:1rem;align-items:stretch;margin-bottom:.35rem}
div[data-testid="column"]{min-width:0}
div[data-testid="stAlert"]{padding:.8rem 1rem;border-radius:12px;line-height:1.5}
[data-testid="stSidebar"]{padding-top:.55rem}
[data-testid="stSidebar"] [data-testid="stRadio"] label{border-radius:9px;padding:.28rem .42rem;transition:background .15s ease,color .15s ease}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover{background:rgba(125,211,252,.08);color:var(--text)}
[data-testid="stSidebar"] hr{border-color:var(--line);margin:.65rem 0}
[data-testid="stTabs"] button{min-height:2.35rem;color:var(--muted);font-weight:600}
[data-testid="stTabs"] button[aria-selected="true"]{color:var(--cyan)}
[data-testid="stTabs"] button:focus-visible{outline:2px solid var(--ui5-focus);outline-offset:2px}
ul,ol{line-height:1.6}code{color:#c4b5fd}
@media (max-width:1100px){.block-container{padding-left:1.25rem;padding-right:1.25rem}.hero{padding:1.35rem}.artifact-meta{overflow-wrap:anywhere}}
@media (max-width:760px){.block-container{padding-left:.85rem;padding-right:.85rem}.hero h1{font-size:1.65rem}.hero p{font-size:.9rem}.section-title{font-size:1rem}div[data-testid="stHorizontalBlock"]{flex-wrap:wrap;gap:.7rem}div[data-testid="stHorizontalBlock"]>div[data-testid="column"]{flex:1 1 100%!important;min-width:100%!important;width:100%!important}.lifecycle{gap:.3rem;margin-bottom:1.1rem}.lifecycle-step{font-size:.62rem;padding:.36rem .52rem}.lifecycle-arrow{font-size:.7rem}.artifact-card,.workspace-card{padding:.9rem}.stDataFrame,[data-testid="stTable"]{max-width:100%;overflow-x:auto}}
@media (prefers-reduced-motion:reduce){.hero,.metric{animation:none!important}.card:hover,.workspace-card:hover,.artifact-card:hover,div.stButton>button:hover{transform:none!important}}
.ui6-visual{position:relative;overflow:hidden;isolation:isolate;border:1px solid rgba(125,211,252,.18);border-radius:20px;background:radial-gradient(circle at 50% 46%,rgba(125,211,252,.1),transparent 23%),linear-gradient(145deg,rgba(13,24,39,.92),rgba(7,12,21,.96));box-shadow:inset 0 1px rgba(255,255,255,.06),0 18px 45px rgba(0,0,0,.18);color:var(--text)}
.ui6-visual:before{content:'';position:absolute;inset:0;background:linear-gradient(115deg,transparent 20%,rgba(255,255,255,.035) 50%,transparent 80%);transform:translateX(-110%);animation:ui6-sheen 7s ease-in-out infinite;pointer-events:none}
.ui6-visual-header{position:relative;z-index:2;padding:1rem 1.1rem 0;display:flex;justify-content:space-between;align-items:center;gap:1rem}.ui6-visual-header strong{font-size:.92rem}.ui6-visual-header span{font:500 .66rem 'DM Mono';color:var(--muted);letter-spacing:.1em;text-transform:uppercase}
.ui6-agent-stage{height:245px;position:relative;perspective:900px}.ui6-agent-stage svg{position:absolute;inset:20px 7% 5px;width:86%;height:210px;opacity:.6}.ui6-agent-stage path{fill:none;stroke:rgba(125,211,252,.42);stroke-width:1.1;stroke-dasharray:4 7;animation:ui6-flow 8s linear infinite}.ui6-core{position:absolute;left:50%;top:47%;transform:translate(-50%,-50%);width:76px;height:76px;border-radius:50%;display:grid;place-items:center;text-align:center;background:radial-gradient(circle at 35% 28%,#e0f2fe,#7dd3fc 18%,#2563a8 48%,#101b32 73%);border:1px solid rgba(224,242,254,.75);box-shadow:0 0 0 9px rgba(125,211,252,.06),0 0 42px rgba(56,189,248,.3),inset -10px -12px 20px rgba(2,6,23,.45);font:600 .62rem 'DM Mono';letter-spacing:.07em;color:#06111f;animation:ui6-float 5s ease-in-out infinite;z-index:2}.ui6-node{position:absolute;z-index:2;padding:.48rem .62rem;border:1px solid rgba(125,211,252,.22);border-radius:10px;background:rgba(10,19,32,.9);font:500 .64rem 'DM Mono';color:#cfeeff;box-shadow:0 8px 22px rgba(0,0,0,.22);animation:ui6-node-float 6s ease-in-out infinite;transition:transform .2s ease,border-color .2s ease,background .2s ease}.ui6-node:hover{transform:translateY(-5px) scale(1.04);border-color:rgba(125,211,252,.72);background:rgba(18,34,56,.98)}.ui6-node.jd{left:4%;top:25%;animation-delay:-1.1s}.ui6-node.plan{left:18%;top:6%;animation-delay:-1.8s}.ui6-node.resume{right:4%;top:22%;animation-delay:-2.4s}.ui6-node.cover{right:17%;top:5%;animation-delay:-2.9s}.ui6-node.package{left:16%;bottom:8%;animation-delay:-3.2s}.ui6-node.track{right:13%;bottom:8%;animation-delay:-4.5s}
.agent-actions{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:.45rem;margin:.55rem 0 0}.agent-actions .stButton button{min-height:2.35rem;padding:.35rem .3rem;background:rgba(10,20,35,.74);border-color:rgba(125,211,252,.16);font:500 .62rem 'DM Mono';letter-spacing:.03em;text-transform:uppercase}.agent-actions .stButton button:hover{border-color:rgba(125,211,252,.68);background:rgba(20,42,68,.92)}
.quick-action-card{min-height:5.3rem;padding:.9rem 1rem;border:1px solid rgba(125,211,252,.15);border-radius:15px;background:linear-gradient(145deg,rgba(16,29,49,.88),rgba(8,15,26,.9));box-shadow:0 12px 28px rgba(0,0,0,.16);transition:transform .2s ease,border-color .2s ease}.quick-action-card:hover{transform:translateY(-3px);border-color:rgba(125,211,252,.5)}.quick-action-card strong{display:block;margin:.35rem 0 .25rem;font-size:.92rem}.quick-action-card span{display:block;color:var(--muted);font-size:.75rem;line-height:1.35}
.spline-hero{position:relative;min-height:0;overflow:visible;background:transparent;box-shadow:none}.spline-orb{border:0;background:transparent}.spline-orb iframe{border:0;background:transparent}.spline-fallback{display:none;color:var(--muted);font-size:.8rem;text-align:center;padding:2rem}
.ui6-network{padding:1.1rem;display:flex;align-items:center;justify-content:space-between;gap:.55rem;min-height:112px}.ui6-network-node{position:relative;flex:1;text-align:center;padding:.7rem .4rem;border:1px solid rgba(167,139,250,.24);border-radius:12px;background:rgba(10,17,29,.78);font:500 .67rem 'DM Mono';color:#e9e5ff;animation:ui6-reveal .5s ease-out both}.ui6-network-node:nth-child(2){animation-delay:.08s}.ui6-network-node:nth-child(3){animation-delay:.16s}.ui6-network-node:nth-child(4){animation-delay:.24s}.ui6-network-node:nth-child(5){animation-delay:.32s}.ui6-network-link{height:1px;flex:0 0 16px;background:linear-gradient(90deg,rgba(167,139,250,.18),rgba(125,211,252,.75),rgba(167,139,250,.18));position:relative}.ui6-network-link:after{content:'';position:absolute;width:5px;height:5px;border-radius:50%;background:var(--cyan);top:-2px;left:0;animation:ui6-pulse-line 2.8s linear infinite}
.ui6-package-flow{display:flex;align-items:center;justify-content:center;gap:.7rem;padding:1.05rem 1.1rem;border:1px solid rgba(110,231,183,.16);border-radius:16px;background:linear-gradient(135deg,rgba(12,28,32,.78),rgba(9,16,26,.8));overflow:hidden}.ui6-package-item{padding:.55rem .7rem;border:1px solid rgba(110,231,183,.24);border-radius:10px;background:rgba(8,19,24,.72);font:500 .66rem 'DM Mono';color:#d9fff0;text-align:center}.ui6-package-arrow{color:var(--green);font-size:1rem;animation:ui6-pulse-line 2.8s ease-in-out infinite}
@keyframes ui6-reveal{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}@keyframes ui6-float{0%,100%{transform:translate(-50%,-50%) translateY(0) rotateX(0deg)}50%{transform:translate(-50%,-50%) translateY(-5px) rotateX(4deg)}}@keyframes ui6-node-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}@keyframes ui6-flow{to{stroke-dashoffset:-44}}@keyframes ui6-pulse-line{0%{opacity:.3;transform:translateX(0)}50%{opacity:1}100%{opacity:.3;transform:translateX(12px)}}@keyframes ui6-sheen{0%,55%{transform:translateX(-110%)}75%,100%{transform:translateX(110%)}}
@media (max-width:760px){.ui6-agent-stage{height:205px}.ui6-agent-stage svg{inset:12px 3% 0;width:94%;height:180px}.ui6-core{width:62px;height:62px;font-size:.55rem}.ui6-node{font-size:.55rem;padding:.38rem .45rem}.ui6-node.jd{left:2%}.ui6-node.resume{right:2%}.ui6-network{overflow-x:auto;justify-content:flex-start}.ui6-network-node{min-width:84px}.ui6-package-flow{flex-wrap:wrap}.ui6-package-arrow{transform:rotate(90deg)}}
.agent-actions{grid-template-columns:repeat(3,minmax(0,1fr))}
@media (prefers-reduced-motion:reduce){.ui6-visual:before,.ui6-core,.ui6-node,.ui6-network-node,.ui6-network-link:after,.ui6-package-arrow{animation:none!important}.ui6-agent-stage path{animation:none!important}.ui6-visual{background:linear-gradient(145deg,rgba(13,24,39,.92),rgba(7,12,21,.96))}}
.stApp{background:radial-gradient(circle at 76% 2%,rgba(124,92,255,.2),transparent 25%),radial-gradient(circle at 8% 18%,rgba(26,196,255,.12),transparent 27%),radial-gradient(circle at 88% 70%,rgba(236,72,153,.06),transparent 23%),linear-gradient(rgba(125,211,252,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(125,211,252,.018) 1px,transparent 1px),var(--bg);background-size:auto,auto,auto,42px 42px,42px 42px,auto;background-position:center,center,center,center,center,center}
.hero{border-color:rgba(125,211,252,.2);background:linear-gradient(135deg,rgba(25,34,61,.86),rgba(9,14,26,.9) 62%,rgba(26,17,47,.84));box-shadow:0 28px 80px rgba(0,0,0,.3),0 0 0 1px rgba(167,139,250,.035),inset 0 1px rgba(255,255,255,.08)}
.hero:after{border-color:rgba(167,139,250,.26);box-shadow:0 0 0 20px rgba(167,139,250,.05),0 0 0 42px rgba(236,72,153,.035)}
.hero h1{font-size:clamp(2rem,4vw,3.1rem);letter-spacing:-.065em;background:linear-gradient(105deg,#f8fbff 18%,#b9ddff 58%,#c4b5fd 92%);-webkit-background-clip:text;background-clip:text;color:transparent}
.metric{background:linear-gradient(145deg,rgba(20,31,53,.88),rgba(8,14,25,.8));border-color:rgba(125,211,252,.17);box-shadow:0 15px 42px rgba(0,0,0,.2),inset 0 1px rgba(255,255,255,.05)}
.card,.workspace-card,.artifact-card{background:linear-gradient(145deg,rgba(19,29,47,.78),rgba(8,14,24,.78));backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.card{border-color:rgba(125,211,252,.14)}.workspace-card{border-color:rgba(125,211,252,.12)}.artifact-card{border-color:rgba(167,139,250,.17)}
.workspace-card:hover{box-shadow:0 14px 34px rgba(0,0,0,.2),0 0 0 1px rgba(125,211,252,.08)}.artifact-card.working:hover{box-shadow:0 16px 38px rgba(251,191,116,.1)}.artifact-card.final:hover{box-shadow:0 16px 38px rgba(110,231,183,.1)}
.section-title{font-size:1.12rem;letter-spacing:-.035em}.section-title:before{content:'//';font:500 .72rem 'DM Mono';color:var(--violet);margin-right:.45rem;opacity:.8}
.status{box-shadow:0 0 18px rgba(125,211,252,.05)}.status-green{box-shadow:0 0 18px rgba(110,231,183,.08)}.status-amber{box-shadow:0 0 18px rgba(251,191,116,.08)}.status-violet{box-shadow:0 0 18px rgba(167,139,250,.08)}
div.stButton>button{background:linear-gradient(120deg,#172a49,#17203a 54%,#241d4c);border-color:rgba(125,211,252,.24);box-shadow:0 8px 20px rgba(0,0,0,.18)}div.stButton>button:hover{box-shadow:0 10px 26px rgba(56,189,248,.16),0 0 0 1px rgba(167,139,250,.18)}
.ui6-visual{border-color:rgba(125,211,252,.26);background:radial-gradient(circle at 52% 46%,rgba(125,211,252,.13),transparent 24%),linear-gradient(145deg,rgba(18,28,53,.94),rgba(10,12,28,.96));box-shadow:inset 0 1px rgba(255,255,255,.08),0 22px 70px rgba(30,20,80,.22)}
@media (max-width:760px){.hero h1{font-size:1.9rem}.stApp{background-size:auto,auto,auto,30px 30px,30px 30px,auto}.card,.workspace-card,.artifact-card{backdrop-filter:none;-webkit-backdrop-filter:none}}
@media (prefers-reduced-motion:reduce){.stApp{background-size:auto;background-position:center}.hero h1{background:none;color:var(--text)}.card,.workspace-card,.artifact-card{backdrop-filter:none;-webkit-backdrop-filter:none}}
</style>''', unsafe_allow_html=True)

st.markdown('''<style>
/* Command-center layer: presentation and interaction only. */
.block-container{max-width:1560px;padding-top:1.15rem;padding-bottom:5rem}
.stApp:before{content:'';position:fixed;inset:0;pointer-events:none;opacity:.34;background:radial-gradient(circle at 70% 18%,rgba(56,189,248,.08),transparent 28%),radial-gradient(circle at 20% 78%,rgba(139,92,246,.07),transparent 24%);z-index:-1}
.cc-topline{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin:0 0 1rem;padding:.42rem .7rem;border:1px solid rgba(125,211,252,.12);border-radius:999px;background:rgba(7,14,25,.54);font:500 .64rem 'DM Mono';letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.cc-topline strong{color:#dff7ff;font-weight:500}.cc-topline .live{display:inline-flex;align-items:center;gap:.4rem;color:var(--green)}.cc-topline .live:before{content:'';width:.42rem;height:.42rem;border-radius:50%;background:var(--green);box-shadow:0 0 12px rgba(110,231,183,.7);animation:cc-pulse 2.2s ease-in-out infinite}
.hero{margin-bottom:1rem;min-height:126px}.hero h1{max-width:900px}.hero p{max-width:820px}
 .cc-hero-grid{display:grid;grid-template-columns:minmax(270px,.58fr) minmax(0,1.42fr);gap:.1rem;align-items:center;margin:0 0 .8rem;min-height:400px;overflow:hidden;border-radius:26px;background:radial-gradient(circle at 78% 48%,rgba(56,189,248,.12),transparent 31%),linear-gradient(115deg,rgba(20,24,48,.76),rgba(8,14,26,.34) 58%,rgba(5,10,19,.12));box-shadow:inset 0 1px rgba(255,255,255,.06),0 24px 70px rgba(0,0,0,.18)}
 .cc-command-panel{position:relative;z-index:2;overflow:hidden;border:0;border-radius:0;padding:1.25rem 1rem 1.25rem 1.5rem;background:transparent;box-shadow:none}
.cc-command-panel:after{content:'';position:absolute;width:180px;height:180px;right:-72px;bottom:-92px;border-radius:50%;border:1px solid rgba(125,211,252,.2);box-shadow:0 0 0 18px rgba(125,211,252,.035),0 0 0 38px rgba(167,139,250,.025);pointer-events:none}
 .cc-command-title{font-size:.78rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#dcecff}.cc-command-panel h1{max-width:390px;margin:.32rem 0 .45rem;font-size:clamp(1.45rem,2.2vw,2.1rem);line-height:1.08;letter-spacing:-.045em}.cc-command-copy{margin:.42rem 0 .85rem;color:var(--muted);font-size:.86rem;line-height:1.5;max-width:390px}
.cc-command-meta{display:flex;justify-content:space-between;gap:.7rem;margin-top:.9rem;font:500 .63rem 'DM Mono';color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.cc-command-meta b{color:var(--cyan);font-weight:500}
.cc-action-row{display:flex;flex-wrap:wrap;gap:.5rem}.cc-action-row .stButton{flex:1 1 145px}.cc-action-row button{width:100%!important;min-height:2.7rem}
 .cc-hero-orb{position:relative;min-width:0;min-height:400px;display:flex;align-items:center;justify-content:center;margin-right:-1rem}.cc-hero-orb:after{content:'';position:absolute;inset:10% 2% 7% 5%;border-radius:50%;background:radial-gradient(circle,rgba(56,189,248,.14),transparent 60%);filter:blur(18px);pointer-events:none;z-index:-1}
 div[data-testid="stHorizontalBlock"]:has(.dashboard-hero-marker){margin:0 0 .8rem;padding:.65rem .8rem .65rem 1.25rem;min-height:380px;align-items:center;border:1px solid rgba(125,211,252,.12);border-radius:26px;background:radial-gradient(circle at 78% 48%,rgba(56,189,248,.12),transparent 31%),linear-gradient(115deg,rgba(20,24,48,.76),rgba(8,14,26,.34) 58%,rgba(5,10,19,.12));box-shadow:inset 0 1px rgba(255,255,255,.06),0 24px 70px rgba(0,0,0,.18)}
 .dashboard-hero-marker{display:block}.dashboard-hero-marker h1{max-width:390px;margin:.32rem 0 .45rem;font-size:clamp(1.45rem,2.2vw,2.1rem);line-height:1.08;letter-spacing:-.045em}.dashboard-hero-marker p{max-width:390px;margin:.42rem 0 .85rem;color:var(--muted);font-size:.86rem;line-height:1.5}
.cc-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem;margin:0 0 1.35rem}.cc-kpi{border:1px solid rgba(125,211,252,.12);border-radius:16px;padding:.9rem 1rem;background:rgba(9,17,29,.68);box-shadow:inset 0 1px rgba(255,255,255,.035);transition:transform .2s ease,border-color .2s ease}.cc-kpi:hover{transform:translateY(-3px);border-color:rgba(125,211,252,.3)}.cc-kpi .value{font-size:1.65rem;font-weight:700;letter-spacing:-.06em;color:#f3f8ff}.cc-kpi .delta{font:500 .62rem 'DM Mono';color:var(--green);letter-spacing:.05em}
.cc-section-head{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;margin:1.4rem 0 .7rem}.cc-section-head h2{margin:0;font-size:1rem;letter-spacing:-.03em}.cc-section-head span{font:500 .62rem 'DM Mono';letter-spacing:.1em;color:var(--muted);text-transform:uppercase}
.cc-rail-brand{display:flex;align-items:center;gap:.7rem;margin:.25rem 0 1.35rem;padding:.5rem .2rem}.cc-rail-orb{width:2rem;height:2rem;border-radius:50%;display:grid;place-items:center;border:1px solid rgba(125,211,252,.6);background:radial-gradient(circle at 35% 30%,#e0f2fe,#7dd3fc 18%,#263b89 55%,#0a1021 75%);box-shadow:0 0 22px rgba(56,189,248,.22);font:600 .62rem 'DM Mono';color:#07111e}.cc-rail-brand strong{font-size:.84rem;letter-spacing:-.02em}.cc-rail-brand small{display:block;margin-top:.1rem;color:var(--muted);font:500 .6rem 'DM Mono';letter-spacing:.08em;text-transform:uppercase}
.cc-rail-label{margin:1.2rem 0 .35rem;color:#70839c;font:500 .58rem 'DM Mono';letter-spacing:.16em;text-transform:uppercase}.cc-rail-status{margin-top:1.25rem;padding:.72rem .8rem;border:1px solid rgba(110,231,183,.16);border-radius:12px;background:rgba(8,25,24,.42);font-size:.72rem;line-height:1.45;color:var(--muted)}.cc-rail-status b{color:var(--green);font-weight:600}
@keyframes cc-pulse{0%,100%{opacity:.55;transform:scale(.85)}50%{opacity:1;transform:scale(1.1)}}
 @media (max-width:900px){.cc-hero-grid{grid-template-columns:1fr;min-height:0}div[data-testid="stHorizontalBlock"]:has(.dashboard-hero-marker){padding:.75rem;min-height:0}.dashboard-hero-orb{min-height:330px;margin-top:.25rem}.cc-command-panel{padding:1.15rem 1.1rem .2rem}.cc-hero-orb{min-height:330px;margin-right:0;margin-top:-.6rem}.cc-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:600px){.cc-topline{border-radius:12px;align-items:flex-start;flex-direction:column;gap:.35rem}.cc-kpi-grid{gap:.5rem}.cc-kpi{padding:.75rem}.cc-kpi .value{font-size:1.35rem}}
@media (prefers-reduced-motion:reduce){.cc-rail-status,.cc-topline .live:before{animation:none}.cc-kpi:hover{transform:none}.cc-kpi,.cc-action-row button{transition:none}}
</style>''', unsafe_allow_html=True)
if st.session_state.get('settings_motion_preference') == 'Reduced motion':
 st.markdown('''<style>
 *,*::before,*::after{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.001ms!important}
 </style>''', unsafe_allow_html=True)

def load_apps(): return aa.load_store().get('applications',[])
def save_apps(apps): aa.save_store({'applications':apps})
def app_by_id(aid): return next((x for x in load_apps() if x['application_id']==aid),None)
def resolve_ref(ref):
 path=resolve_storage_reference(str(ref))
 if path is None: raise ValueError('Invalid application storage reference')
 return path
def card(title,value,sub=''):
 st.markdown(f'<div class="card"><div class="label">{title}</div><div class="metric">{value}</div><div class="small">{sub}</div></div>',unsafe_allow_html=True)
def status_badge(status):
 tone='status-green' if status in {'ready_to_apply','interview','offer'} else ('status-amber' if status in {'awaiting_resume_approval','resume_ready','assessment'} else ('status-violet' if status in {'applied'} else ''))
 return f'<span class="status {tone}">{str(status or "unknown").replace("_"," ").title()}</span>'
def artifact_state(app):
 final=bool(app.get('resume_reference') or app.get('resume_pdf_reference')); working=bool(app.get('working_resume_docx_path') or app.get('working_resume_pdf_path'))
 if final and working: return '<span class="artifact-dot final"></span>Final + Working'
 if final: return '<span class="artifact-dot final"></span>Final resume'
 if working: return '<span class="artifact-dot working"></span>Working resume'
 return '<span class="muted">No resume artifact</span>'
def selected_app():
 apps=load_apps();
 if not apps: st.info('Create an application to open a workspace.'); return None
 labels={a['application_id']:f"{a.get('company_name') or 'Unknown company'} · {a.get('job_title') or 'Untitled role'}" for a in apps}; aid=st.selectbox('Application workspace',list(labels),format_func=lambda x:labels[x],key='workspace_app')
 if st.session_state.get('_resume_workspace_app_id')!=aid:
  st.session_state.pop('resume_generation_result',None); st.session_state.pop('last_final',None); st.session_state['_resume_workspace_app_id']=aid
 return app_by_id(aid)
PROJECT_LIMIT=3
def eligible_completed_projects():
 profile=planner.load_profile(); projects=profile['projects'].get('projects',[]); seen=set(); eligible=[]
 for p in projects:
  rid=p.get('record_id')
  if rid and rid not in seen and p.get('project_status')=='completed' and p.get('status')=='verified': eligible.append(p); seen.add(rid)
 return eligible
def project_stack(p):
 vals=p.get('technologies') or p.get('frameworks_libraries_tools') or []
 return ', '.join(str(x) for x in vals if x) or 'Not specified in canonical profile'
def format_experience_requirement(jd_text,jdinfo):
 raw=str(jd_text or '')
 items=[]
 ranges=re.findall(r'\b(\d+)\s*[–-]\s*(\d+)\s+years?\b',raw,re.I)
 if ranges:
  items.append(f'{ranges[0][0]}–{ranges[0][1]} years')
 else:
  years=re.findall(r'\b(?:at least|minimum of)?\s*(\d+\+?)\s+years?\b',raw,re.I)
  if years: items.append(f'{years[0]} years')
 if re.search(r'fresh\s+graduates?|freshers?|entry[- ]level',raw,re.I): items.append('Fresh graduates accepted')
 if re.search(r'academic|internship|personal\s+ai\s+projects?',raw,re.I): items.append('Academic/internship/project experience relevant')
 return items or ['Not specified']

def workflow_indicator(active):
 steps=[('01','Job Details'),('02','JD Analysis'),('03','Resume Plan'),('04','Resume')]; parts=[]
 for index,(number,label) in enumerate(steps,1):
  state='active' if index==active else ('done' if index<active else '')
  parts.append(f'<span class="lifecycle-step {state}">{number} {label}</span>')
  if index<len(steps): parts.append('<span class="lifecycle-arrow">→</span>')
 st.markdown('<div class="lifecycle">'+''.join(parts)+'</div>',unsafe_allow_html=True)

def render_plan_review(plan,app=None):
 jd=plan.get('jd_analysis',{}); summary=plan.get('evidence_summary',{}); resume_plan=plan.get('resume_plan',{}); identity=jd.get('job_identity',{}) or {}; app=app or {}
 st.markdown('<div class="section-title">Role Overview</div>',unsafe_allow_html=True)
 overview=[('Company',identity.get('company') or app.get('company_name')),('Role',jd.get('job_title') or app.get('job_title')),('Location',identity.get('location') or app.get('location')),('Application type',identity.get('employment_type') or app.get('employment_type')),('Source',app.get('source_platform'))]
 cols=st.columns(3)
 for i,(label,value) in enumerate(overview):
  if value: cols[i%3].markdown(f'<div class="workspace-card"><div class="label">{escape(label)}</div><b>{escape(str(value))}</b></div>',unsafe_allow_html=True)
 st.markdown('<div class="section-title">Requirements</div>',unsafe_allow_html=True)
 req_cols=st.columns(2)
 req_cols[0].markdown(f'<div class="workspace-card"><div class="label">REQUIRED SKILLS</div><p>{escape(", ".join(jd.get("required_technical_skills",[])) or "None returned")}</p></div>',unsafe_allow_html=True)
 req_cols[1].markdown(f'<div class="workspace-card"><div class="label">PREFERRED SKILLS</div><p>{escape(", ".join(jd.get("preferred_technical_skills",[])) or "None returned")}</p></div>',unsafe_allow_html=True)
 if jd.get('responsibilities'): st.markdown('<div class="workspace-card"><div class="label">RESPONSIBILITIES</div><ul>'+''.join(f'<li>{escape(str(x))}</li>' for x in jd['responsibilities'])+'</ul></div>',unsafe_allow_html=True)
 st.markdown('<div class="section-title">Evidence Alignment</div>',unsafe_allow_html=True)
 for title,key,tone in [('Supported','supported_requirements','status-green'),('Partial','partial_requirements','status-amber'),('Unsupported','unsupported_requirements','status-violet'),('Unknown','unknown_requirements','')]:
  items=summary.get(key,[]); chips=' '.join(f'<span class="status {tone}">{escape(str(item.get("requirement") or "Requirement"))}</span>' for item in items) or '<span class="muted">No items returned by the planner.</span>'
  st.markdown(f'<div class="workspace-card"><div class="label">{title.upper()}</div><div style="margin-top:.55rem">{chips}</div></div>',unsafe_allow_html=True)
  for item in items:
   evidence=item.get('evidence',[])
   if evidence: st.caption(f"{item.get('requirement')}: "+'; '.join(str(e.get('name') or ', '.join(e.get('matched_evidence',[]))) for e in evidence[:4]))
 st.markdown('<div class="section-title">Project Alignment</div>',unsafe_allow_html=True)
 projects=resume_plan.get('projects_to_include',[])
 if projects:
  pcols=st.columns(min(3,len(projects)))
  for col,project in zip(pcols,projects):
   with col: st.markdown(f'<div class="workspace-card"><b>{escape(str(project.get("name") or "Project"))}</b><br><span class="small">{escape(str(project.get("selection_reason") or "Selected by existing planner output."))}</span><br><span class="status status-green">Selected</span><p class="small">{escape(", ".join(project.get("matched_requirements",[])) or "Planner evidence available")}</p></div>',unsafe_allow_html=True)
 else: st.info('No project alignment was returned by the planner.')
 excluded=resume_plan.get('items_intentionally_excluded',{}).get('projects',[])
 if excluded: st.caption('Other planner results: '+', '.join(str(x.get('name')) for x in excluded[:8] if x.get('name')))
 st.markdown('<div class="section-title">Experience Alignment</div>',unsafe_allow_html=True)
 experiences=resume_plan.get('experience_decisions',[])
 if experiences:
  blocks=[]
  for experience in experiences:
   tone='status-green' if experience.get('decision')=='INCLUDE' else 'status-amber'; blocks.append(f'<p><b>{escape(str(experience.get("organization") or "Experience"))}</b> · {escape(str(experience.get("title") or ""))}<br><span class="status {tone}">{escape(str(experience.get("decision") or "Review"))}</span><br><span class="small">{escape(str(experience.get("reason") or ""))}</span></p>')
  st.markdown('<div class="workspace-card">'+''.join(blocks)+'</div>',unsafe_allow_html=True)
 else: st.info('No meaningful experience alignment was returned by the planner.')
 gaps=plan.get('gap_analysis',{}).get('potential_risks',[]) or resume_plan.get('warnings',[])
 if gaps:
  st.markdown('<div class="section-title">Areas to Review</div>',unsafe_allow_html=True)
  st.markdown('<div class="workspace-card">'+''.join(f'<p><span class="status status-amber">{escape(str(gap.get("type") or "REVIEW"))}</span> <b>{escape(str(gap.get("requirement") or "Requirement"))}</b><br><span class="small">{escape(str(gap.get("message") or "Review planner output before making claims."))}</span></p>' for gap in gaps)+'</div>',unsafe_allow_html=True)
 st.markdown('<div class="section-title">Resume Plan</div>',unsafe_allow_html=True)
 plan_cols=st.columns(4)
 plan_cols[0].markdown(f'<div class="workspace-card"><div class="label">PROJECTS</div><b>{escape(", ".join(x.get("name","") for x in projects) or "None")}</b></div>',unsafe_allow_html=True)
 plan_cols[1].markdown(f'<div class="workspace-card"><div class="label">SKILLS</div><b>{escape(", ".join(x.get("name","") for x in resume_plan.get("skills_to_include",[])[:8]) or "None")}</b></div>',unsafe_allow_html=True)
 plan_cols[2].markdown(f'<div class="workspace-card"><div class="label">CERTIFICATIONS</div><b>{escape(", ".join(x.get("name","") for x in resume_plan.get("certifications_to_include",[])) or "None")}</b></div>',unsafe_allow_html=True)
 plan_cols[3].markdown(f'<div class="workspace-card"><div class="label">EXPERIENCE DECISION</div><b>{"Included" if resume_plan.get("experience_relevance_sufficient") else "Project-focused"}</b></div>',unsafe_allow_html=True)
def apply_project_selection_override(aid,record_ids,source):
 if len(record_ids)!=len(set(record_ids)): raise ValueError('Duplicate projects are not allowed.')
 if len(record_ids)>PROJECT_LIMIT: raise ValueError(f'At most {PROJECT_LIMIT} projects can be selected for this resume.')
 eligible={p['record_id']:p for p in eligible_completed_projects()}; invalid=[x for x in record_ids if x not in eligible]
 if invalid: raise ValueError('Only canonical completed projects may be selected: '+', '.join(invalid))
 apps=load_apps(); app=next((x for x in apps if x['application_id']==aid),None)
 if not app: raise ValueError('Application not found.')
 plan_path=resolve_ref(app['phase8_plan_reference']); plan=json.loads(plan_path.read_text(encoding='utf-8'))
 selected=[eligible[x] for x in record_ids]
 plan.setdefault('resume_plan',{})['projects_to_include']=selected
 plan['resume_plan']['project_selection_source']=source
 plan['resume_plan']['project_selection_record_ids']=list(record_ids)
 plan['project_selection_source']=source
 plan_path.write_text(json.dumps(plan,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
 app['selected_projects']=[x['name'] for x in selected]; app['project_selection_mode']='manual' if source=='manual' else 'automatic'; app['project_selection_source']=source; app['project_selection_record_ids']=list(record_ids); app['last_updated']=aa.now(); aa.save_store({'applications':apps})
 return selected
def persist_project_selection_change(aid,mode,record_ids):
 if mode not in {'automatic','manual'}: raise ValueError('Invalid project selection mode.')
 if len(record_ids)!=len(set(record_ids)): raise ValueError('Duplicate projects are not allowed.')
 if len(record_ids)>PROJECT_LIMIT: raise ValueError(f'At most {PROJECT_LIMIT} projects can be selected for this resume.')
 apps=load_apps(); app=next((x for x in apps if x['application_id']==aid),None)
 if not app: raise ValueError('Application not found.')
 plan_path=resolve_ref(app['phase8_plan_reference']); plan=json.loads(plan_path.read_text(encoding='utf-8')); resume_plan=plan.setdefault('resume_plan',{})
 eligible={p['record_id']:p for p in eligible_completed_projects()}
 if mode=='automatic':
  automatic=resume_plan.get('automatic_projects_to_include')
  if not automatic: automatic=resume_plan.get('projects_to_include',[])
  record_ids=[p.get('record_id') for p in automatic if p.get('record_id') in eligible]
  selected=[eligible[x] for x in record_ids]
 else:
  invalid=[x for x in record_ids if x not in eligible]
  if invalid: raise ValueError('Only canonical completed projects may be selected: '+', '.join(invalid))
  selected=[eligible[x] for x in record_ids]
 resume_plan['projects_to_include']=selected; resume_plan['project_selection_source']=mode; resume_plan['project_selection_record_ids']=list(record_ids)
 plan['project_selection_source']=mode
 plan.setdefault('approval_checkpoint',{})['resume_generation_allowed']=False
 plan_path.write_text(json.dumps(plan,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
 app['selected_projects']=[x['name'] for x in selected]; app['project_selection_mode']=mode; app['project_selection_source']=mode; app['project_selection_record_ids']=list(record_ids); app['resume_generation_allowed']=False; app['resume_working_artifact_stale']=True; app['current_status']='awaiting_resume_approval'; app['last_updated']=aa.now(); aa.save_store({'applications':apps})
 return selected
def resume_project_edit_state_key(aid,suffix): return f'_resume_project_edit_{aid}_{suffix}'
def resume_preview_state_key(aid): return f'_resume_preview_{aid}'
def begin_resume_project_edit(app):
 aid=app['application_id']; plan=json.loads(resolve_ref(app['phase8_plan_reference']).read_text(encoding='utf-8')); rp=plan.get('resume_plan',{}); mode=app.get('project_selection_mode') or rp.get('project_selection_source') or 'automatic'; current=list(app.get('project_selection_record_ids') or [x.get('record_id') for x in rp.get('projects_to_include',[])])
 automatic=rp.get('automatic_projects_to_include') or (rp.get('projects_to_include',[]) if mode!='manual' else [])
 st.session_state[resume_project_edit_state_key(aid,'mode')]=mode; st.session_state[resume_project_edit_state_key(aid,'ids')]=current; st.session_state[resume_project_edit_state_key(aid,'automatic_ids')]=[x.get('record_id') for x in automatic]; st.session_state[resume_project_edit_state_key(aid,'active')]=True; st.session_state.pop(resume_project_edit_state_key(aid,'widget'),None)
def clear_resume_project_edit(app):
 aid=app['application_id']
 for suffix in ('mode','ids','automatic_ids','active','widget'): st.session_state.pop(resume_project_edit_state_key(aid,suffix),None)
def render_resume_project_editor(app):
 aid=app['application_id']; mode_key=resume_project_edit_state_key(aid,'mode'); ids_key=resume_project_edit_state_key(aid,'ids'); auto_key=resume_project_edit_state_key(aid,'automatic_ids'); mode=st.session_state.get(mode_key,'automatic'); automatic_ids=st.session_state.get(auto_key,[])
 st.warning('Edit mode: changes are temporary until you confirm them.')
 st.markdown('**Project Selection**')
 automatic,manual=st.columns(2)
 if automatic.button('Automatic Recommendation',key=resume_project_edit_state_key(aid,'automatic_button')):
  st.session_state[mode_key]='automatic'; st.session_state[ids_key]=list(automatic_ids); st.session_state.pop(resume_project_edit_state_key(aid,'widget'),None); st.rerun()
 if manual.button('Choose Projects Manually',key=resume_project_edit_state_key(aid,'manual_button')):
  st.session_state[mode_key]='manual'; st.session_state.setdefault(ids_key,list(st.session_state.get(ids_key,[]))); st.rerun()
 mode=st.session_state.get(mode_key,'automatic'); st.caption('Current edit mode: '+('Manual' if mode=='manual' else 'Automatic Recommendation'))
 if mode=='automatic':
  eligible={p['record_id']:p for p in eligible_completed_projects()}; proposed=[eligible[x]['name'] for x in automatic_ids if x in eligible]; st.write(', '.join(proposed) or 'No sufficiently supported project recommendation.')
 else:
  eligible=eligible_completed_projects(); labels={x['record_id']:x['name'] for x in eligible}; default=[x for x in st.session_state.get(ids_key,[]) if x in labels]; chosen=st.multiselect('Completed projects',list(labels),default=default,format_func=lambda x:labels[x],key=resume_project_edit_state_key(aid,'widget')); st.session_state[ids_key]=list(chosen); st.caption(f'Maximum: {PROJECT_LIMIT} completed canonical projects.')
 left,right=st.columns(2)
 if left.button('Confirm Project Changes',type='primary',key=resume_project_edit_state_key(aid,'confirm')):
  ids=list(st.session_state.get(ids_key,[]))
  if mode=='manual' and not ids: st.error('Select at least one completed project.'); return
  if len(ids)>PROJECT_LIMIT: st.error(f'Select no more than {PROJECT_LIMIT} projects for a one-page resume.'); return
  persist_project_selection_change(aid,mode,ids); clear_resume_project_edit(app); st.success('Project selection updated. Approve the updated Resume Plan before regenerating the working resume.'); st.rerun()
 if right.button('Cancel',key=resume_project_edit_state_key(aid,'cancel')): clear_resume_project_edit(app); st.rerun()
def md_to_docx(md:Path,out:Path):
 from docx import Document
 d=Document();
 for line in md.read_text(encoding='utf-8').splitlines(): d.add_paragraph(line)
 d.save(out)
def pdf_convert(src:Path):
 with tempfile.TemporaryDirectory() as td:
  _,_,pdf=rg.render_page_count(src,Path(td)); dest=src.with_suffix('.pdf'); shutil.copy2(pdf,dest)
 return dest
def pdf_is_readable(pdf:Path):
 try:
  executable=rg.resolve_executable('pdfinfo')
  info=subprocess.run([executable,str(pdf)],check=True,text=True,capture_output=True).stdout
  pages=next(int(x.split(':',1)[1].strip()) for x in info.splitlines() if x.startswith('Pages:'))
  text=subprocess.run([rg.resolve_executable('pdftotext'),str(pdf),'-'],check=True,text=True,capture_output=True).stdout
  return {'exists':pdf.exists(),'pages':pages,'text_extractable':bool(text.strip()),'passed':pdf.exists() and bool(text.strip())}
 except Exception as exc: return {'exists':pdf.exists(),'pages':None,'text_extractable':False,'passed':False,'error':str(exc)}
def file_sha256(path:Path):
 with path.open('rb') as f:
  digest=hashlib.sha256()
  for chunk in iter(lambda:f.read(1024*1024),b''): digest.update(chunk)
  return digest.hexdigest()
def artifact_record(app,kind):
 prefix='working_resume_' if kind=='working' else 'resume_'
 return {k:app.get(prefix+k) for k in ['docx_path','pdf_path','docx_sha256','pdf_sha256','generation_id','generated_at' if kind=='working' else 'finalized_at']}
def validate_resume_artifacts(app,kind):
 record=artifact_record(app,kind)
 required=list(record)
 if not all(record.get(k) for k in required): return None,'Resume artifact mismatch detected. Regenerate working resume.'
 try:
  docx=resolve_ref(record['docx_path']); pdf=resolve_ref(record['pdf_path'])
  if not docx.exists() or not pdf.exists(): raise FileNotFoundError('referenced artifact is missing')
  if app.get('application_id') not in docx.name or app.get('application_id') not in pdf.name: raise ValueError('artifact does not belong to this application')
  if file_sha256(docx)!=record['docx_sha256'] or file_sha256(pdf)!=record['pdf_sha256']: raise ValueError('artifact hash does not match persisted hash')
  if not pdf_is_readable(pdf).get('passed'): raise ValueError('PDF is not readable')
  return {'docx':docx,'pdf':pdf,'generation_id':record['generation_id']},None
 except Exception as exc: return None,f'Resume artifact mismatch detected. Regenerate working resume. ({exc})'
def _artifact_timestamp(value):
 try: return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
 except (TypeError,ValueError): return None
def working_resume_is_newer(app,final_record,working_record):
 if not final_record or not working_record: return False
 working_ts=_artifact_timestamp(app.get('working_resume_generated_at')); final_ts=_artifact_timestamp(app.get('resume_finalized_at'))
 if working_ts is not None and final_ts is not None: return working_ts>final_ts
 try:
  working_mtime=max(working_record['docx'].stat().st_mtime,working_record['pdf'].stat().st_mtime)
  final_mtime=max(final_record['docx'].stat().st_mtime,final_record['pdf'].stat().st_mtime)
  return working_mtime>final_mtime
 except OSError: return False
def finalize_doc(app,kind,src):
 final=src.with_name(src.stem.replace('_Working','_Final')+src.suffix)
 if final.exists() or final.with_suffix('.pdf').exists():
  base=final.with_suffix(''); version=2
  while True:
   candidate=base.with_name(f'{base.name}_v{version}').with_suffix(final.suffix)
   candidate_pdf=candidate.with_suffix('.pdf')
   if not candidate.exists() and not candidate_pdf.exists(): final=candidate; break
   version+=1
 shutil.copy2(src,final); pdf=pdf_convert(final)
 if not pdf_is_readable(pdf).get('passed'): raise RuntimeError('Generated final PDF is not readable.')
 app=app_by_id(app['application_id']); apps=load_apps(); target=next(x for x in apps if x['application_id']==app['application_id'])
 key='resume_reference' if kind=='resume' else 'cover_letter_reference'; target[key]=str(final.relative_to(ROOT)); target[f'{kind}_pdf_reference']=str(pdf.relative_to(ROOT)); target[f'{kind}_status']='final'
 if kind=='resume':
  target.update({'resume_docx_path':str(final.relative_to(ROOT)),'resume_pdf_path':str(pdf.relative_to(ROOT)),'resume_docx_sha256':file_sha256(final),'resume_pdf_sha256':file_sha256(pdf),'resume_generation_id':'gen_'+uuid.uuid4().hex,'resume_finalized_at':aa.now(),'resume_final_stale':False})
 target['last_updated']=aa.now(); save_apps(apps); return final,pdf
def load_document_history():
 path=DATA/'document_history.json'
 if not path.exists(): return {'documents':[]}
 try:
  raw=path.read_text(encoding='utf-8')
  if not raw.strip(): return {'documents':[]}
  history=json.loads(raw)
  if not isinstance(history,dict) or not isinstance(history.get('documents'),list): return {'documents':[]}
  return history
 except (OSError,UnicodeError,json.JSONDecodeError):
  return {'documents':[]}
def save_document_history(history):
 path=DATA/'document_history.json'; path.parent.mkdir(parents=True,exist_ok=True); payload=json.dumps(history,indent=2,ensure_ascii=False)+'\n'; temporary=None
 try:
  with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,prefix=f'.{path.name}.',suffix='.tmp',delete=False) as handle:
   temporary=Path(handle.name); handle.write(payload); handle.flush(); os.fsync(handle.fileno())
  os.replace(str(temporary),str(path))
 finally:
  if temporary and temporary.exists(): temporary.unlink()
def save_history(app,kind,doc,pdf):
 h=load_document_history(); h['documents'].append({'application_id':app['application_id'],'company':app.get('company_name'),'role':app.get('job_title'),'kind':kind,'date':aa.now(),'docx':str(doc.relative_to(ROOT)),'pdf':str(pdf.relative_to(ROOT)),'selected_projects':app.get('selected_projects',[]),'selected_skills':app.get('selected_skills',[]),'selected_certifications':app.get('selected_certifications',[])}); save_document_history(h)

def header(eyebrow,title,desc):
 st.markdown('<div class="cc-topline"><strong>CAREER OS / COMMAND CENTER</strong><span class="live">SYSTEM ONLINE · LOCAL-FIRST</span></div>',unsafe_allow_html=True)
 st.markdown(f'<div class="hero"><div class="eyebrow">{escape(str(eyebrow))}</div><h1>{escape(str(title))}</h1><p>{escape(str(desc))}</p></div>',unsafe_allow_html=True)
def dashboard_agent_visual():
 components.html('''<!doctype html><html><head><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}spline-viewer{display:block;width:100%;height:100%;background:transparent}</style></head><body><script type="module" src="https://cdn.spline.design/@splinetool/viewer@2.0.55/build/spline-viewer.js"></script><spline-viewer class="spline-orb" url="https://prod.spline.design/q7IZR3vyGue1MLyp/scene.splinecode" loading="eager"></spline-viewer></body></html>''',height=430,scrolling=False)
 actions=[('ANALYZE JD','JD Analysis'),('PLAN','New Application'),('RESUME','Resume Workspace'),('COVER LETTER','Cover Letter Workspace'),('PACKAGE','Application Package'),('TRACK','Application History')]
 cols=st.columns(6)
 for col,(label,destination) in zip(cols,actions):
  with col:
   if st.button(label,key='agent_node_'+destination.lower().replace(' ','_')):
    st.session_state['dashboard_destination']=destination; st.rerun()
def analysis_visual():
 st.markdown('''<div class="ui6-visual" role="img" aria-label="Decorative JD analysis workflow visualization"><div class="ui6-visual-header"><strong>Evidence flow</strong><span>visual guide</span></div><div class="ui6-network"><div class="ui6-network-node">JOB<br>DESCRIPTION</div><div class="ui6-network-link"></div><div class="ui6-network-node">REQUIREMENTS</div><div class="ui6-network-link"></div><div class="ui6-network-node">EVIDENCE</div><div class="ui6-network-link"></div><div class="ui6-network-node">PROJECTS<br>+ EXPERIENCE</div><div class="ui6-network-link"></div><div class="ui6-network-node">RESUME<br>PLAN</div></div></div>''',unsafe_allow_html=True)
def package_visual():
 st.markdown('''<div class="ui6-package-flow" role="img" aria-label="Decorative application package composition visualization"><span class="ui6-package-item">RESUME</span><span class="ui6-package-arrow">+</span><span class="ui6-package-item">COVER LETTER</span><span class="ui6-package-arrow">+</span><span class="ui6-package-item">APPLICATION DETAILS</span><span class="ui6-package-arrow">→</span><span class="ui6-package-item">PACKAGE</span></div>''',unsafe_allow_html=True)
def dashboard():
 st.markdown('<div class="cc-topline"><strong>CAREER OS / COMMAND CENTER</strong><span class="live">SYSTEM ONLINE · LOCAL-FIRST</span></div>',unsafe_allow_html=True)
 apps=load_apps(); counts={s:sum(a.get('current_status')==s for a in apps) for s in ['saved','awaiting_resume_approval','resume_ready','ready_to_apply','interview','offer']}
 in_progress=counts['saved']+counts['awaiting_resume_approval']+counts['resume_ready']
 hero_left,hero_right=st.columns([1,1],gap='small')
 with hero_left:
  st.markdown('<div class="dashboard-hero-marker"><div class="eyebrow">AI CAREER AGENT</div><h1>Your AI-powered job application workspace.</h1><p>Analyze jobs, build tailored resumes, and create application-ready materials.</p><div class="cc-action-row">',unsafe_allow_html=True)
  if st.button('Analyze JD',key='dashboard_analyze_jd',type='primary'):
   st.session_state['dashboard_destination']='JD Analysis'; st.rerun()
  if st.button('Build Resume',key='dashboard_build_resume'):
   st.session_state['dashboard_destination']='Resume Workspace'; st.rerun()
  if st.button('Create Cover Letter',key='dashboard_create_cover_letter'):
   st.session_state['dashboard_destination']='Cover Letter Workspace'; st.rerun()
  st.markdown('</div><div class="cc-command-meta"><span>Next best action</span><b>'+('Review pending work' if in_progress else 'Start with a job description')+'</b></div></div>',unsafe_allow_html=True)
 with hero_right:
  components.html('''<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8"><style>html,body{margin:0;width:100%;height:320px;overflow:hidden;background:transparent}thinking-orb{display:block!important;width:128px!important;height:128px!important;min-width:128px;min-height:128px;flex:0 0 128px;margin:0 auto}thinking-orb canvas{display:block!important;width:128px!important;height:128px!important;min-width:128px;min-height:128px;max-width:none!important;max-height:none!important}</style></head><body><thinking-orb state="working" theme="dark" interactive size="128" aria-label="AI Career Agent working"></thinking-orb><script type="module">import 'https://cdn.jsdelivr.net/gh/Schoolees/thinking-orbs@main/dist/register.js';</script></body></html>''',height=320,scrolling=False)
 st.markdown('<div class="cc-section-head"><h2>Launch a workflow</h2><span>real workspace actions</span></div>',unsafe_allow_html=True)
 quick_actions=[('＋ New Application','Create and analyze a role','New Application'),('⌁ JD Analysis','Inspect evidence alignment','JD Analysis'),('▣ Resume Workspace','Review the current resume artifact','Resume Workspace'),('◈ Application Package','Check package readiness','Application Package')]
 quick_cols=st.columns(4)
 for col,(label,copy,destination) in zip(quick_cols,quick_actions):
  with col:
   st.markdown(f'<div class="quick-action-card"><div class="label">WORKFLOW ENTRY</div><strong>{escape(label)}</strong><span>{escape(copy)}</span></div>',unsafe_allow_html=True)
   if st.button('Open workspace',key='quick_'+destination.lower().replace(' ','_')):
    st.session_state['dashboard_destination']=destination; st.rerun()
 kpis=[('Applications',len(apps),'ALL RECORDS'),('In progress',in_progress,'ACTIVE WORK'),('Ready to apply',counts['ready_to_apply'],'REVIEWED'),('Interviews',counts['interview'],'LIVE PIPELINE')]
 st.markdown('<div class="cc-kpi-grid">'+''.join(f'<div class="cc-kpi"><div class="label">{label}</div><div class="value">{value}</div><div class="delta">{sub}</div></div>' for label,value,sub in kpis)+'</div>',unsafe_allow_html=True)
 st.markdown('<div class="cc-section-head"><h2>Application pipeline</h2><span>signal / lifecycle</span></div>',unsafe_allow_html=True); st.progress(min(1,len(apps)/10),text='Saved → Resume Ready → Ready to Apply → Applied → Interview → Offer')
 st.markdown('<div class="cc-section-head"><h2>Needs your review</h2><span>human approval queue</span></div>',unsafe_allow_html=True)
 pending=[a for a in apps if a.get('current_status') in {'awaiting_resume_approval','resume_ready','ready_to_apply'}]
 if pending:
  review_cols=st.columns(min(3,len(pending)))
  for c,a in zip(review_cols,pending[:3]):
   with c: st.markdown(f'<div class="workspace-card"><div class="label">REVIEW QUEUE</div><h4>{escape(str(a.get("company_name") or "Unknown company"))}</h4><div class="muted">{escape(str(a.get("job_title") or "Untitled role"))}</div><p>{status_badge(a.get("current_status"))}</p><div class="small">{artifact_state(a)}</div></div>',unsafe_allow_html=True)
 else: st.success('No applications currently need review.')
 left,right=st.columns([1.35,1])
 with left:
  st.markdown('<div class="cc-section-head"><h2>Recent applications</h2><span>latest activity</span></div>',unsafe_allow_html=True)
  for a in apps[-5:][::-1]:
   st.markdown(f'<div class="workspace-card" style="margin-bottom:.65rem"><div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start"><div><b>{escape(str(a.get("company_name") or "Unknown company"))}</b><br><span class="muted">{escape(str(a.get("job_title") or "Untitled role"))}</span></div>{status_badge(a.get("current_status"))}</div><div class="small" style="margin-top:.7rem">Updated {escape(str(a.get("last_updated") or a.get("date_added") or "—"))} · {artifact_state(a)}</div></div>',unsafe_allow_html=True)
  if not apps: st.info('Your application pipeline is empty.')
 with right:
  st.markdown('<div class="cc-section-head"><h2>System signal</h2><span>guardrails active</span></div>',unsafe_allow_html=True)
  st.markdown('<div class="workspace-card"><div class="label">LOCAL-FIRST OPERATING MODE</div><p><span class="status status-green">ONLINE</span> Phase 8 evidence matching</p><p><span class="status status-green">LOCKED</span> Resume generator approval gate</p><p><span class="status status-green">MANUAL</span> Application submission boundary</p><div class="small">Animations are presentation-only. Backend workflows remain authoritative.</div></div>',unsafe_allow_html=True)

def new_application():
 header('NEW APPLICATION','New Application','Create an application and analyze the job before preparing your application package.')
 workflow_indicator(2 if 'draft_plan' in st.session_state else 1)
 st.markdown('<div class="section-title">Job Details</div>',unsafe_allow_html=True)
 left,right=st.columns([1.35,.8])
 with left:
  st.markdown('<div class="workspace-card"><div class="label">JOB DESCRIPTION</div><p class="small">Paste the complete job description for evidence-based analysis.</p></div>',unsafe_allow_html=True)
  jd=st.text_area('Job Description',height=300,key='new_jd',placeholder='Paste the complete job description here…')
 with right:
  st.markdown('<div class="workspace-card"><div class="label">APPLICATION DETAILS</div><p class="small">Capture the source details that are already supported by the application record.</p></div>',unsafe_allow_html=True)
  company=st.text_input('Company',key='new_company'); title=st.text_input('Job title / role',key='new_title'); url=st.text_input('Job URL',key='new_url'); source=st.text_input('Source',key='new_source'); location=st.text_input('Location',key='new_location'); employment_type=st.text_input('Employment/application type',key='new_employment_type')
 if st.button('Create Application & Analyze JD',type='primary',key='new_application_create_analyze'):
  if not jd.strip(): st.error('Paste a job description before analysis.'); return
  with st.spinner('Analyzing job description · extracting requirements · matching verified profile evidence…'):
   plan=planner.plan_resume(jd,planner.load_profile()); plan['resume_plan']['automatic_projects_to_include']=copy.deepcopy(plan['resume_plan']['projects_to_include']); st.session_state['draft_plan']=plan; st.session_state['draft_automatic_projects']=copy.deepcopy(plan['resume_plan']['automatic_projects_to_include']); st.session_state['draft_jd']=jd; st.session_state['draft_meta']={'url':url,'company':company,'title':title,'source':source,'location':location,'employment_type':employment_type}; st.session_state['draft_project_selection_mode']='automatic'; st.session_state['draft_project_selection_source']='automatic'; st.session_state.pop('manual_project_mode',None); st.session_state.pop('draft_manual_ids',None); st.session_state.pop('manual_project_ids',None)
 if 'draft_plan' not in st.session_state: return
 p=st.session_state['draft_plan']; auto_projects=st.session_state.get('draft_automatic_projects',p['resume_plan']['projects_to_include']); mode=st.session_state.get('draft_project_selection_mode','automatic')
 render_plan_review(p)
 st.markdown('<div class="section-title">Project Selection</div>',unsafe_allow_html=True)
 automatic,manual=st.columns(2)
 if automatic.button('Automatic Recommendation',key='automatic_project_mode'):
  st.session_state['draft_project_selection_mode']='automatic'; st.session_state['draft_project_selection_source']='automatic'; st.session_state.pop('draft_manual_ids',None); st.session_state.pop('manual_project_ids',None); p['resume_plan']['projects_to_include']=copy.deepcopy(auto_projects); p['resume_plan']['automatic_projects_to_include']=copy.deepcopy(auto_projects); p['resume_plan']['project_selection_source']='automatic'; p['resume_plan'].pop('project_selection_record_ids',None); st.session_state['draft_plan']=p; st.rerun()
 if manual.button('Choose Projects Manually',key='choose_projects_manually'):
  st.session_state['draft_project_selection_mode']='manual'; st.session_state['draft_project_selection_source']='manual'; st.session_state.setdefault('draft_manual_ids',[x['record_id'] for x in p['resume_plan']['projects_to_include'] or auto_projects]); st.session_state['manual_project_mode']=True; st.rerun()
 st.caption('Project Selection: ● '+('Manual' if mode=='manual' else 'Automatic Recommendation'))
 if mode=='automatic': st.info('Automatic Recommendation is selected. The planner output remains unchanged until you explicitly choose a different mode.')
 if mode=='manual':
  eligible=eligible_completed_projects(); labels={x['record_id']:x['name'] for x in eligible}; default=[x for x in st.session_state.get('draft_manual_ids',[y['record_id'] for y in auto_projects]) if x in labels]
  chosen=st.multiselect('Completed projects',list(labels),default=default,format_func=lambda x:labels[x],key='manual_project_ids'); st.caption(f'Only canonical completed projects are shown. Maximum: {PROJECT_LIMIT}.')
  if st.button('Confirm Project Selection',type='primary',key='confirm_project_selection'):
   if not chosen: st.error('Select at least one completed project.'); return
   if len(chosen)>PROJECT_LIMIT: st.error(f'Select no more than {PROJECT_LIMIT} projects for a one-page resume.'); return
   st.session_state['draft_manual_ids']=chosen; st.session_state['draft_project_selection_mode']='manual'; st.session_state['draft_project_selection_source']='manual'; p['resume_plan']['projects_to_include']=[next(x for x in eligible if x['record_id']==rid) for rid in chosen]; p['resume_plan']['project_selection_source']='manual'; p['resume_plan']['project_selection_record_ids']=list(chosen); st.session_state['draft_plan']=p; st.success('Manual project selection confirmed. It will override the automatic recommendation.'); st.rerun()
 st.info('Resume generation is locked until you explicitly approve the Resume Plan.')
 if st.button('Create tracked application',type='primary',key='new_application_create_tracked'):
  meta=st.session_state['draft_meta']; result=aa.create_application(meta.get('company'),meta.get('title') or p.get('jd_analysis',{}).get('job_title'),meta.get('url'),jd,'user_provided',meta.get('location'),meta.get('employment_type'))
  if result['decision']=='created':
   aid=result['application']['application_id']
   if st.session_state.get('draft_project_selection_source')=='manual': apply_project_selection_override(aid,st.session_state.get('draft_manual_ids',[]),'manual')
   st.session_state['selected_app']=aid; st.success('Application created and stored. Open JD Analysis or Resume Workspace next.')
  else: st.warning(result)

def jd_analysis_page():
 header('JD ANALYSIS','JD Analysis','Understand the role requirements and how your verified profile evidence aligns.')
 workflow_indicator(3)
 analysis_visual()
 app=selected_app()
 if not app: return
 plan_ref=app.get('phase8_plan_reference')
 if not plan_ref: st.info('No JD analysis is available for this application yet.'); return
 try: plan=json.loads(resolve_ref(plan_ref).read_text(encoding='utf-8'))
 except Exception as exc: st.error(f'JD analysis could not be loaded: {type(exc).__name__}: {exc}'); return
 st.markdown(f'<div class="workspace-card"><b>{escape(str(app.get("company_name") or "Unknown company"))}</b><br><span class="muted">{escape(str(app.get("job_title") or plan.get("jd_analysis",{}).get("job_title") or "Untitled role"))}</span><br><span class="small">Status: {escape(str(app.get("current_status") or "unknown"))}</span></div>',unsafe_allow_html=True)
 render_plan_review(plan,app)
 required_gaps=[item for item in plan.get('candidate_matching',[]) if item.get('classification')=='required' and item.get('evidence_status') in {'UNSUPPORTED','UNKNOWN'} and not any(evidence.get('type')=='skill' and evidence.get('status') in {'verified','candidate_provided'} for evidence in item.get('evidence',[]))]
 if required_gaps:
  st.markdown('<div class="section-title">Required Skill Gaps</div>',unsafe_allow_html=True)
  profile_data=pua.all_data()
  categories=[group.get('category') for group in profile_data['skills'].get('skill_groups',[]) if group.get('category')]
  for gap in required_gaps:
   skill=gap.get('requirement')
   st.warning(f'This JD strongly requires {skill}, but {skill} is not currently in your profile. Do you want to add it?')
   category=st.selectbox('Profile category',categories,key=f'skill_gap_category_{app["application_id"]}_{planner.norm(skill)}')
   if st.button(f'Confirm adding {skill} as candidate-provided',key=f'skill_gap_confirm_{app["application_id"]}_{planner.norm(skill)}'):
    result=career_api.confirm_skill_gap(app['application_id'],{'skill':skill,'category':category,'confirmed':True})
    if result.get('decision')=='skill_added_candidate_provided': st.success(result.get('message','Skill recorded for verification.')); st.rerun()
    else: st.error(result.get('message') or result)
 st.markdown('<div class="section-title">Resume Plan Review</div>',unsafe_allow_html=True)
 if app.get('resume_generation_allowed'): st.success('Resume Plan approved. Resume generation is available in Resume Workspace.')
 else:
  st.warning('Resume plan ready for review. Explicit approval is required before resume generation.')
  if st.button('Approve Resume Plan',type='primary',key='jd_analysis_approve_plan'):
   approval=aa.approve_resume(app['application_id'],plan)
   if approval.get('decision')=='approved': st.success('Resume Plan approved.'); st.session_state['selected_app']=app['application_id']; st.rerun()
   else: st.error(approval)

def resume_workspace():
 header('RESUME WORKSPACE','Resume Workspace','Review, edit, and finalize your application-specific resume.')
 app=selected_app()
 if not app:return
 st.markdown(f'<div class="workspace-card"><b>{app.get("company_name") or "Unknown company"}</b><br><span class="muted">{app.get("job_title") or "Untitled role"}</span><br><span style="display:inline-block;margin-top:.55rem">{status_badge(app.get("current_status"))}</span><span class="small" style="margin-left:.65rem">Resume lifecycle: {"Finalized" if app.get("resume_generation_id") else ("Working generated" if app.get("working_resume_generation_id") else ("Plan approved" if app.get("resume_generation_allowed") else "Plan review required"))}</span></div>',unsafe_allow_html=True)
 plan_approved=bool(app.get('resume_generation_allowed'))
 st.markdown('<div class="lifecycle"><span class="lifecycle-step '+('done' if plan_approved else 'active')+'">Plan Approved</span><span class="lifecycle-arrow">→</span><span class="lifecycle-step '+('done' if app.get('working_resume_generation_id') else ('active' if plan_approved else ''))+'">Working Generated</span><span class="lifecycle-arrow">→</span><span class="lifecycle-step '+('active' if app.get('working_resume_generation_id') and not app.get('resume_generation_id') else ('done' if app.get('resume_generation_id') else ''))+'">Review</span><span class="lifecycle-arrow">→</span><span class="lifecycle-step '+('done' if app.get('resume_generation_id') else '')+'">Finalized</span></div>',unsafe_allow_html=True)
 if st.session_state.pop('resume_plan_approved_notice',False): st.success('Resume Plan approved. Resume generation is now available.')
 if app.get('current_status')=='awaiting_resume_approval':
  st.warning('Resume Plan approval required.')
  if st.button('Approve Resume Plan',type='primary'):
   plan=json.loads(resolve_ref(app['phase8_plan_reference']).read_text(encoding='utf-8'))
   approval=aa.approve_resume(app['application_id'],plan)
   if approval.get('decision')=='approved': st.session_state['resume_plan_approved_notice']=True
   st.rerun()
 if st.button('Generate working resume'):
  if not app.get('resume_generation_allowed'): st.error('Approve the Resume Plan first.'); return
  try:
    plan=json.loads(resolve_ref(app['phase8_plan_reference']).read_text()); plan['approval_checkpoint']['resume_generation_allowed']=True; base=aa.artifact_stem(app,'resume','Working'); out=RESUMES/f'{base}.docx'; version=2
    while out.exists() or out.with_suffix('.pdf').exists(): out=RESUMES/f'{base}_v{version}.docx'; version+=1
    report=REPORTS/f"{app['application_id']}_resume_validation.json"
    with st.spinner('Generating and validating one-page resume…'):
     rg.generate(plan,rg.profile(),out); validation=rg.validate(out,plan,rg.profile(),report)
     working_pdf=pdf_convert(out); generation_id='gen_'+uuid.uuid4().hex; generated_at=aa.now(); docx_rel=str(out.relative_to(ROOT)); pdf_rel=str(working_pdf.relative_to(ROOT))
    st.session_state['resume_generation_result']={'docx':str(out.relative_to(ROOT)),'validation_report':str(report.relative_to(ROOT)),'validation':validation}
    if validation.get('page_count')==1 and validation.get('final_status')=='PASS':
      apps=load_apps(); target=next(x for x in apps if x['application_id']==app['application_id']); target.update({'working_resume_reference':docx_rel,'working_resume_pdf_reference':pdf_rel,'working_resume_docx_path':docx_rel,'working_resume_pdf_path':pdf_rel,'working_resume_docx_sha256':file_sha256(out),'working_resume_pdf_sha256':file_sha256(working_pdf),'working_resume_generation_id':generation_id,'working_resume_generated_at':generated_at,'resume_validation_reference':str(report.relative_to(ROOT)),'resume_working_artifact_stale':False,'resume_final_stale':bool(target.get('resume_generation_id')),'current_status':'resume_ready','last_updated':aa.now()}); save_apps(apps); st.success('Working resume generated and validated.'); st.rerun()
    else: st.error(f"Resume validation failed: {validation.get('final_status','UNKNOWN')}. Review {report.relative_to(ROOT)} before retrying.")
  except Exception as exc:
   st.error(f'Resume generation failed: {type(exc).__name__}: {exc}')
   st.exception(exc)
 app=app_by_id(app['application_id']); final_record,final_error=validate_resume_artifacts(app,'final') if app.get('resume_generation_id') else (None,None); working_record,working_error=validate_resume_artifacts(app,'working') if app.get('working_resume_generation_id') else (None,None); working_newer=working_resume_is_newer(app,final_record,working_record)
 aid=app['application_id']; preview_key=resume_preview_state_key(aid); default_preview='final' if final_record else ('working' if working_record else None); active_preview=st.session_state.get(preview_key,default_preview)
 if active_preview not in {'working','final'}: active_preview=default_preview
 if working_record and working_newer: st.info('Working version is newer than the active Final version. Final remains preserved until you explicitly finalize the Working version.')
 if final_record is None and final_error: st.error(f'Final artifact unavailable: {final_error}')
 if working_record is None and working_error: st.error(f'Working artifact unavailable: {working_error}')
 if working_record and not final_record and not st.session_state.get(resume_project_edit_state_key(aid,'active')):
  if st.button('Edit Project Selection',type='secondary',key='edit_resume_project_selection'): begin_resume_project_edit(app); st.rerun()
 if st.session_state.get(resume_project_edit_state_key(aid,'active')) and not final_record: render_resume_project_editor(app)
 left,right=st.columns(2)
 with left:
  st.markdown('<div class="artifact-card working"><div class="label">WORKING VERSION</div><h3>Current editable candidate</h3></div>',unsafe_allow_html=True)
  if working_record:
   st.markdown(f'<div class="artifact-meta">Generated: {app.get("working_resume_generated_at") or "Not available"}<br>Generation ID: {working_record["generation_id"]}<br>DOCX: persisted and validated<br>PDF: persisted and readable<br>Projects: {", ".join(app.get("selected_projects",[])) or "Not recorded"}</div>',unsafe_allow_html=True)
   if working_newer: st.markdown('<p><span class="status status-amber">Newer than Final</span></p>',unsafe_allow_html=True)
   b1,b2=st.columns(2)
   if b1.button('Preview Working',key=f'preview_working_{aid}'):
    st.session_state[preview_key]='working'; st.rerun()
   b2.download_button('Download Working DOCX',working_record['docx'].read_bytes(),file_name=working_record['docx'].name,key=f'download_working_docx_{aid}')
   if active_preview=='working':
    st.markdown('#### Working PDF preview')
    try: st.pdf(working_record['pdf'].read_bytes())
    except Exception as exc: st.error(f'Working PDF preview failed: {type(exc).__name__}: {exc}')
  else:
   st.info('No working resume generated yet. Approve the Resume Plan, then generate a Working version for review.')
 with right:
  st.markdown('<div class="artifact-card final"><div class="label">FINAL VERSION</div><h3>Active finalized resume</h3></div>',unsafe_allow_html=True)
  if final_record:
   st.markdown(f'<div class="artifact-meta">Finalized: {app.get("resume_finalized_at") or "Not available"}<br>Generation ID: {final_record["generation_id"]}<br>DOCX: persisted and validated<br>PDF: persisted and readable</div>',unsafe_allow_html=True)
   b1,b2=st.columns(2)
   if b1.button('Preview Final',key=f'preview_final_{aid}'):
    st.session_state[preview_key]='final'; st.rerun()
   b2.download_button('Download Final DOCX',final_record['docx'].read_bytes(),file_name=final_record['docx'].name,key=f'download_final_docx_{aid}')
   if active_preview=='final':
    st.markdown('#### Final PDF preview')
    try: st.pdf(final_record['pdf'].read_bytes())
    except Exception as exc: st.error(f'Final PDF preview failed: {type(exc).__name__}: {exc}')
  else:
   st.info('No finalized resume yet. Finalize the Working Version after review to create the active Final resume.')
 finalize_allowed=bool(working_record and (not final_record or working_newer))
 if finalize_allowed:
  finalize_label='Finalize Current Working Resume' if final_record and working_newer else 'Finalize Resume'
  if st.button(finalize_label,type='primary',key='finalize_current_working_resume'):
   try:
    if app.get('resume_working_artifact_stale'): st.error('Finalization blocked: the working resume is outdated. Approve the updated Resume Plan and regenerate it first.'); return
    if not working_record: st.error(working_error or 'Resume artifact mismatch detected. Regenerate working resume.'); return
    path=working_record['docx']; plan=json.loads(resolve_ref(app['phase8_plan_reference']).read_text()); validation=rg.validate(path,plan,rg.profile(),REPORTS/f"{app['application_id']}_finalization_validation.json")
    if validation.get('final_status')!='PASS': st.error('Resume finalization blocked: validation did not pass. Review the validation report.'); return
    final,pdf=finalize_doc(app,'resume',path); pdfcheck=pdf_is_readable(pdf)
    if not pdfcheck['passed']: st.error('Resume finalization blocked: generated PDF is not readable.'); return
    st.success(f'Finalized and converted to PDF: {final.name}'); st.session_state['last_final']=(str(final),str(pdf)); st.rerun()
   except Exception as exc:
    st.error(f'Resume finalization failed: {type(exc).__name__}: {exc}')
    st.exception(exc)
 if final_record:
  if st.checkbox('Save finalized resume to permanent history',key='save_resume_history'): save_history(app,'resume',resolve_ref(app['resume_reference']),resolve_ref(app['resume_pdf_reference'])); st.success('Saved to document history.')

def cover_workspace():
 header('COVER LETTER WORKSPACE','Cover Letter Workspace','Create, review, and finalize your application-specific cover letter.')
 app=selected_app()
 if not app:return
 st.markdown(f'<div class="workspace-card"><b>{escape(str(app.get("company_name") or "Unknown company"))}</b><br><span class="muted">{escape(str(app.get("job_title") or "Untitled role"))}</span><br><span style="display:inline-block;margin-top:.55rem">{status_badge(app.get("current_status"))}</span></div>',unsafe_allow_html=True)
 working_ref=app.get('cover_letter_working_reference'); final_ref=app.get('cover_letter_reference'); final_pdf_ref=app.get('cover_letter_pdf_reference')
 lifecycle_active=4 if final_ref and final_pdf_ref else (3 if working_ref or final_ref else 1)
 st.markdown('<div class="lifecycle"><span class="lifecycle-step done">Application</span><span class="lifecycle-arrow">→</span><span class="lifecycle-step '+('done' if working_ref else 'active' if not final_ref else '')+'">Draft</span><span class="lifecycle-arrow">→</span><span class="lifecycle-step '+('done' if final_ref else 'active' if working_ref else '')+'">Review</span><span class="lifecycle-arrow">→</span><span class="lifecycle-step '+('done' if final_ref and final_pdf_ref else '')+'">Final</span></div>',unsafe_allow_html=True)
 if st.button('Generate Working Cover Letter',type='primary',key=f'cover_generate_{app["application_id"]}'):
  result=aa.generate_cover_letter(app['application_id'])
  if result.get('decision')=='created':
   source=resolve_ref(result['cover_letter_working_reference']); doc=source.with_suffix('.docx'); pdf=source.with_suffix('.pdf')
   md_to_docx(source,doc); pdf_convert(doc)
   apps=load_apps(); target=next(x for x in apps if x['application_id']==app['application_id']); target['cover_letter_working_docx_reference']=str(doc.relative_to(ROOT)); target['cover_letter_working_pdf_reference']=str(pdf.relative_to(ROOT)); save_apps(apps)
  st.success('Working cover letter generated.'); st.rerun()
 app=app_by_id(app['application_id']); working_ref=app.get('cover_letter_working_reference'); final_ref=app.get('cover_letter_reference'); final_pdf_ref=app.get('cover_letter_pdf_reference')
 left,right=st.columns(2)
 with left:
  st.markdown('<div class="artifact-card working"><div class="label">WORKING VERSION</div><h3>Application-specific draft</h3></div>',unsafe_allow_html=True)
  if working_ref:
   path=resolve_ref(working_ref)
   if not path.exists(): st.error(f'Working cover-letter artifact is unavailable: {working_ref}')
   else:
    working_pdf_ref=app.get('cover_letter_working_pdf_reference')
    working_pdf=resolve_ref(working_pdf_ref) if working_pdf_ref else path.with_suffix('.pdf')
    if not working_pdf.exists():
     doc=resolve_ref(app.get('cover_letter_working_docx_reference')) if app.get('cover_letter_working_docx_reference') else path.with_suffix('.docx')
     if not doc.exists(): md_to_docx(path,doc)
     working_pdf=pdf_convert(doc)
     apps=load_apps(); target=next(x for x in apps if x['application_id']==app['application_id']); target['cover_letter_working_docx_reference']=str(doc.relative_to(ROOT)); target['cover_letter_working_pdf_reference']=str(working_pdf.relative_to(ROOT)); save_apps(apps)
    st.markdown(f'<div class="artifact-meta">Reference: {escape(str(working_ref))}<br>PDF: {escape(str(working_pdf.relative_to(ROOT)))}<br>Availability: persisted<br>Format: PDF (source Markdown preserved)</div>',unsafe_allow_html=True)
    st.text_area('Working cover-letter preview',path.read_text(encoding='utf-8',errors='replace'),height=300,key=f'cover_working_preview_{app["application_id"]}')
    st.download_button('Download Working Cover Letter',working_pdf.read_bytes(),file_name=working_pdf.name,mime='application/pdf',key=f'cover_download_working_{app["application_id"]}')
    if st.button('Finalize Cover Letter',type='primary',key=f'cover_finalize_{app["application_id"]}'):
     try:
      apps=load_apps(); target=next(x for x in apps if x['application_id']==app['application_id']); target['cover_letter_working_reference']=str(path.relative_to(ROOT)); save_apps(apps); doc=resolve_ref(target.get('cover_letter_working_docx_reference')) if target.get('cover_letter_working_docx_reference') else path.with_suffix('.docx');
      if not doc.exists(): md_to_docx(path,doc)
      final,pdf=finalize_doc(app,'cover_letter',doc); check=pdf_is_readable(pdf)
      if check['passed']: st.success('Cover letter finalized and converted to PDF.'); st.rerun()
      st.error('Cover letter finalization completed, but PDF validation failed. Review the generated files.')
     except Exception as exc: st.error(f'Cover letter finalization failed: {type(exc).__name__}: {exc}'); st.exception(exc)
  else: st.info('No Working cover letter generated yet.')
 with right:
  st.markdown('<div class="artifact-card final"><div class="label">FINAL VERSION</div><h3>Active finalized cover letter</h3></div>',unsafe_allow_html=True)
  if final_ref and final_pdf_ref:
   final_path=resolve_ref(final_ref); pdf_path=resolve_ref(final_pdf_ref)
   if not final_path.exists() or not pdf_path.exists(): st.error('Final cover-letter artifact reference is unavailable.')
   else:
    st.markdown(f'<div class="artifact-meta">DOCX: {escape(str(final_ref))}<br>PDF: {escape(str(final_pdf_ref))}<br>Availability: persisted and readable</div>',unsafe_allow_html=True)
    st.download_button('Download Final Cover Letter',pdf_path.read_bytes(),file_name=pdf_path.name,mime='application/pdf',key=f'cover_download_final_{app["application_id"]}')
    try: st.pdf(pdf_path.read_bytes())
    except Exception: st.info('Inline PDF preview is unavailable in this Streamlit environment. Use Download Final Cover Letter to review the validated PDF.')
  else: st.info('No finalized cover letter yet. Review the Working Version before finalizing.')

def package_page():
 header('APPLICATION PACKAGE','Application Package','Review the documents and application details before submitting.')
 package_visual()
 app=selected_app()
 if not app:return
 st.info('Manual submission only. This workspace never logs in, fills portals, handles CAPTCHAs, or clicks Submit.')
 summary=[('Company',app.get('company_name')),('Role',app.get('job_title')),('Location',app.get('location')),('Status',app.get('current_status')),('Source',app.get('source_platform')),('Job URL',app.get('job_url'))]
 cols=st.columns(3)
 for i,(label,value) in enumerate(summary):
  if value: cols[i%3].markdown(f'<div class="workspace-card"><div class="label">{escape(label)}</div><b>{escape(str(value))}</b></div>',unsafe_allow_html=True)
 st.markdown('<div class="section-title">Package Readiness</div>',unsafe_allow_html=True)
 plan_ready=bool(app.get('phase8_plan_reference')); approved=bool(app.get('resume_generation_allowed')); working=bool(app.get('working_resume_docx_path') and app.get('working_resume_pdf_path')); final=bool(app.get('resume_reference') and app.get('resume_pdf_reference')); cover=bool(app.get('cover_letter_reference'))
 checklist=[('JD analyzed',plan_ready),('Resume plan approved',approved),('Working resume generated',working),('Final resume available',final),('Cover letter available',cover)]
 st.markdown('<div class="workspace-card">'+''.join(f'<p><span class="status {"status-green" if ok else "status-amber"}">{"READY" if ok else "PENDING"}</span> {escape(label)}</p>' for label,ok in checklist)+'</div>',unsafe_allow_html=True)
 st.markdown('<div class="section-title">Documents</div>',unsafe_allow_html=True)
 dcols=st.columns(2)
 with dcols[0]:
  st.markdown('<div class="artifact-card final"><div class="label">RESUME</div><h3>'+('Final available' if final else 'Final missing')+'</h3></div>',unsafe_allow_html=True)
  if app.get('working_resume_docx_path'): st.caption(f'Working DOCX: {app.get("working_resume_docx_path")}')
  if app.get('working_resume_pdf_path'): st.caption(f'Working PDF: {app.get("working_resume_pdf_path")}')
  if app.get('resume_reference'): st.caption(f'Final DOCX: {app.get("resume_reference")}')
  if app.get('resume_pdf_reference'): st.caption(f'Final PDF: {app.get("resume_pdf_reference")}')
  if st.button('Open Resume Workspace',key=f'package_resume_{app["application_id"]}'): st.session_state['navigation']='Resume Workspace'; st.session_state['selected_app']=app['application_id']; st.session_state['dashboard_destination']='Resume Workspace'; st.rerun()
 with dcols[1]:
  st.markdown('<div class="artifact-card working"><div class="label">COVER LETTER</div><h3>'+('Available' if cover else 'Missing')+'</h3></div>',unsafe_allow_html=True)
  if app.get('cover_letter_reference'): st.caption(f'Final/reference: {app.get("cover_letter_reference")}')
  if app.get('cover_letter_pdf_reference'): st.caption(f'PDF: {app.get("cover_letter_pdf_reference")}')
  if st.button('Open Cover Letter Workspace',key=f'package_cover_{app["application_id"]}'): st.session_state['navigation']='Cover Letter Workspace'; st.session_state['selected_app']=app['application_id']; st.session_state['dashboard_destination']='Cover Letter Workspace'; st.rerun()
 if app.get('job_url'): st.link_button('Open job posting',app['job_url'])
 st.markdown('<div class="section-title">Manual Submission</div>',unsafe_allow_html=True)
 if app.get('current_status')!='applied':
  st.warning('Mark as applied only after you personally submit the application on the employer site.')
  if st.button('Mark as Applied',type='primary',key=f'package_mark_applied_{app["application_id"]}'):
   if st.checkbox('I personally submitted this application',key=f'package_confirm_applied_{app["application_id"]}'):
    aa.update_status(app['application_id'],'applied',True); st.success('Marked applied with explicit confirmation.'); st.rerun()

def history_page():
 header('APPLICATION HISTORY','Application History','Track application progress and review previous application activity.')
 apps=load_apps(); options=['All']+sorted({a.get('current_status') for a in apps}); requested=st.session_state.pop('dashboard_status_filter',None); default=options.index(requested) if requested in options else 0
 f=st.selectbox('Status filter',options,index=default,key='history_status_filter'); q=st.text_input('Search company, role, platform',key='history_search')
 st.markdown(f'<div class="small">{len(aa.search(q or None,None if f=="All" else f))} application record(s)</div>',unsafe_allow_html=True)
 for a in aa.search(q or None,None if f=='All' else f):
  aid=a['application_id']; events=a.get('status_history',[]); st.markdown(f'<div class="workspace-card" style="margin-top:.75rem"><div style="display:flex;justify-content:space-between;gap:1rem"><div><b>{escape(str(a.get("company_name") or "Unknown"))}</b><br><span class="muted">{escape(str(a.get("job_title") or "Untitled"))}</span></div>{status_badge(a.get("current_status"))}</div><p class="small">Last updated: {escape(str(a.get("last_updated") or a.get("date_added") or "—"))}<br>Artifacts: {artifact_state(a)}</p></div>',unsafe_allow_html=True)
  with st.expander(f'Activity timeline · {aid}'):
   if events: st.markdown(''.join(f'<p class="small"><b>{escape(str(e.get("new_status") or "event"))}</b> · {escape(str(e.get("timestamp") or "date unavailable"))}<br>{escape(str(e.get("source") or "recorded event"))}</p>' for e in events),unsafe_allow_html=True)
   else: st.info('No lifecycle events recorded.')
  b1,b2,b3=st.columns(3)
  if b1.button('Open Application',key=f'history_open_{aid}'): st.session_state['selected_app']=aid; st.session_state['dashboard_destination']='Application Package'; st.rerun()
  if b2.button('Resume Workspace',key=f'history_resume_{aid}'): st.session_state['selected_app']=aid; st.session_state['dashboard_destination']='Resume Workspace'; st.rerun()
  if b3.button('Application Package',key=f'history_package_{aid}'): st.session_state['selected_app']=aid; st.session_state['dashboard_destination']='Application Package'; st.rerun()

@st.dialog('VERIFY PROFILE CHANGE',dismissible=False)
def profile_update_pin_dialog():
 st.write('Enter your 6-digit security PIN')
 st.text_input('6-digit security PIN',type='password',max_chars=6,key='profile_update_pin_input',label_visibility='collapsed')
 error=st.session_state.get('profile_update_pin_error')
 if error: st.error(error)
 cancel,verify=st.columns(2)
 if cancel.button('CANCEL',key='profile_update_pin_cancel'):
  st.session_state['profile_update_pin_dialog_open']=False; st.session_state['profile_update_pin_clear']=True; st.session_state.pop('profile_update_pin_error',None); st.rerun()
 if verify.button('VERIFY & SAVE',type='primary',key='profile_update_pin_verify'):
  pin=st.session_state.get('profile_update_pin_input','')
  try:
   result=pua.apply_plan(st.session_state['profile_plan'],confirm=True,pin=pin)
   st.session_state['profile_update_result']=f'Profile updated: {result}'; st.session_state['profile_plan']=None; st.session_state['profile_update_pin_dialog_open']=False; st.session_state.pop('profile_update_pin_error',None)
  except psecurity.ProfilePinVerificationError:
   st.session_state['profile_update_pin_error']='A valid six-digit security PIN is required. No profile changes were saved.'
  except Exception:
   st.session_state['profile_update_pin_error']='The profile update could not be saved. No PIN was included in the error.'
  st.session_state['profile_update_pin_clear']=True; st.rerun()


def profile_page():
 if st.session_state.pop('profile_update_pin_clear',False): st.session_state.pop('profile_update_pin_input',None)
 header('PROFILE','Profile','Manage the verified information used by your application workflow.')
 prof=planner.load_profile(); st.caption('Canonical profile data is displayed read-only. Proposed changes use the existing Phase 7 review → confirm → apply flow.')
 with st.expander('Profile Security'):
  st.write('Profile Security: ' + ('PIN configured' if psecurity.pin_is_configured() else 'PIN not configured'))
  if not psecurity.pin_is_configured(): st.warning('Profile writes are disabled until CAREER_OS_PROFILE_PIN_HASH is configured on the server.')
 if st.button('Edit Profile',type='primary',key='edit_profile_entry'): st.session_state['profile_edit_mode']=True
 tabs=st.tabs(['Contact','Education','Skills','Projects','Experience','Certifications','Achievements','Edit Profile'])
 contact=prof.get('master_profile',{}).get('profile',{})
 with tabs[0]:
  if contact: st.markdown('<div class="workspace-card">'+''.join(f'<p><span class="label">{escape(str(k))}</span><br><b>{escape(str(v))}</b></p>' for k,v in contact.items() if v and not isinstance(v,(dict,list)))+'</div>',unsafe_allow_html=True)
  else: st.info('No contact information is available in the canonical profile.')
 tab_offset=1
 for tab,name in zip(tabs[tab_offset:-1],['education','skills','projects','experience','certifications','achievements']):
  with tab:
   payload=prof[name]
   records=payload.get('projects') or payload.get('experiences') or payload.get('education') or payload.get('certifications') or payload.get('achievements')
   if records:
    for record in records:
     label=record.get('name') or record.get('title') or record.get('degree') or record.get('institution') or record.get('organization') or record.get('record_id','Record')
     with st.expander(str(label)):
      st.write({k:v for k,v in record.items() if k not in {'sources','evidence','provenance','source_evidence'}})
   else:
    groups=payload.get('skill_groups',[])
    for group in groups:
     with st.expander(str(group.get('category','Skills'))): st.write([x.get('name') for x in group.get('skills',[])])
 with tabs[-1]:
  st.markdown('<div class="lifecycle"><span class="lifecycle-step done">Review changes</span><span class="lifecycle-arrow">→</span><span class="lifecycle-step '+('active' if st.session_state.get('profile_plan') else '')+'">Confirm</span><span class="lifecycle-arrow">→</span><span class="lifecycle-step">Apply</span></div>',unsafe_allow_html=True)
  text=st.text_area('Natural-language update',placeholder='Describe a factual profile update for review.',disabled=not st.session_state.get('profile_edit_mode',False),key='profile_update_text')
  if st.button('Plan Profile Update',type='primary',key='profile_plan_update'):
   if text: st.session_state['profile_plan']=pua.plan_request(text); st.json(st.session_state['profile_plan'])
  if st.session_state.get('profile_plan'):
   st.markdown('<div class="workspace-card"><div class="label">REVIEW CHANGES</div></div>',unsafe_allow_html=True); st.json(st.session_state['profile_plan'])
   if st.button('Confirm and Apply Profile Update',key='profile_confirm_apply'):
    st.session_state['profile_update_pin_dialog_open']=True
  if st.session_state.get('profile_update_result'):
   st.success(st.session_state.pop('profile_update_result'))
  if st.session_state.get('profile_update_pin_dialog_open'):
   profile_update_pin_dialog()

def pending_page():
 header('PENDING ACTIONS','Pending Actions','Review application tasks that still need your attention.')
 apps=load_apps(); groups={'Resume Review':[],'Resume Finalization':[],'Application Review':[],'Follow-up':[]}
 for a in apps:
  if a.get('current_status')=='awaiting_resume_approval': groups['Resume Review'].append((a,'Review Resume'))
  if a.get('current_status') in {'resume_ready','ready_to_apply'}: groups['Application Review'].append((a,'Open Application Package'))
  if a.get('working_resume_generation_id') and not a.get('resume_generation_id'): groups['Resume Finalization'].append((a,'Open Resume Workspace'))
  if a.get('follow_up_date'): groups['Follow-up'].append((a,'Open Application Package'))
 visible=sum(len(v) for v in groups.values()); st.markdown(f'<div class="small">{visible} pending task(s)</div>',unsafe_allow_html=True)
 if not visible: st.success('No pending actions.')
 for group,items in groups.items():
  if not items: continue
  st.markdown(f'<div class="section-title">{group}</div>',unsafe_allow_html=True)
  for a,label in items:
   aid=a['application_id']; st.markdown(f'<div class="workspace-card"><b>{escape(str(a.get("company_name") or "Unknown"))}</b><br><span class="muted">{escape(str(a.get("job_title") or "Untitled"))}</span><p>{status_badge(a.get("current_status"))}<br><span class="small">{escape(str(a.get("last_updated") or a.get("follow_up_date") or "—"))}</span></p></div>',unsafe_allow_html=True)
   if st.button(label,key=f'pending_{group.lower().replace(" ","_")}_{aid}'):
    st.session_state['selected_app']=aid; st.session_state['dashboard_destination']='Resume Workspace' if 'Resume' in label else 'Application Package'; st.rerun()

def search_page():
 header('SEARCH','Search','Find applications, projects, skills, and profile information.')
 q=st.text_input('Search applications and profile',placeholder='GenAI, RAG, company, role…',key='global_search_query')
 if not q: st.info('Enter a search term to search the application and canonical profile records.'); return
 apps=aa.search(q); profile=planner.load_profile(); collections=[('Project','projects',profile.get('projects',{}).get('projects',[])),('Skill','skills',sum((g.get('skills',[]) for g in profile.get('skills',{}).get('skill_groups',[])),[])),('Experience','experience',profile.get('experience',{}).get('experiences',[])),('Certification','certifications',profile.get('certifications',{}).get('certifications',[]))]
 st.markdown('<div class="section-title">Applications</div>',unsafe_allow_html=True)
 if apps:
  for a in apps: st.markdown(f'<div class="workspace-card"><span class="status status-violet">Application</span> <b>{escape(str(a.get("company_name") or "Unknown"))}</b><br><span class="muted">{escape(str(a.get("job_title") or "Untitled"))}</span><br><span class="small">{escape(str(a.get("current_status") or ""))}</span></div>',unsafe_allow_html=True)
 else: st.caption('No matching applications.')
 for kind,name,records in collections:
  hits=[r for r in records if q.lower() in json.dumps(r,ensure_ascii=False).lower()]
  if hits:
   st.markdown(f'<div class="section-title">{kind}s</div>',unsafe_allow_html=True)
   for record in hits[:20]:
    title=record.get('name') or record.get('title') or record.get('organization') or record.get('record_id') or kind
    st.markdown(f'<div class="workspace-card"><span class="status">{kind}</span> <b>{escape(str(title))}</b><br><span class="small">{escape(str(record.get("purpose") or record.get("issuer") or record.get("category") or "Canonical profile record"))}</span></div>',unsafe_allow_html=True)

def settings_page():
 header('SETTINGS','Settings','System preferences and safety boundaries for the command center.')
 st.markdown('<div class="workspace-card"><div class="label">SAFETY BOUNDARIES</div><p>Manual submission only. No browser automation, CAPTCHA handling, automatic login, or automatic email submission.</p></div>',unsafe_allow_html=True)
 st.markdown('<div class="section-title">Display Preferences</div>',unsafe_allow_html=True)
 density=st.selectbox('Display density',['Comfortable','Compact'],key='settings_display_density'); motion=st.selectbox('Motion preference',['Respect system preference','Reduced motion'],key='settings_motion_preference')
 st.caption('These are UI-only session preferences and are not persisted to the application store.')
 st.markdown('<div class="section-title">System Status</div>',unsafe_allow_html=True)
 st.markdown('<div class="workspace-card"><p>Phase 8 matching: deterministic and evidence-based.</p><p>Phase 9A application assistant: local application records.</p><p>Profile updates: approval-gated.</p></div>',unsafe_allow_html=True)

def _sync_navigation(value):
 st.session_state['navigation_legacy']=value; st.session_state['navigation']=value

with st.sidebar:
 st.markdown('<div class="cc-rail-brand"><div class="cc-rail-orb">AI</div><div><strong>Career OS</strong><small>Application command center</small></div></div>',unsafe_allow_html=True)
 st.markdown('<div class="cc-rail-label">PRIMARY NAVIGATION</div>',unsafe_allow_html=True)
 legacy_page=st.radio('NAVIGATION',['Dashboard','New Application','JD Analysis','Resume Workspace','Cover Letter Workspace','Application Package','Application History','Profile','Pending Actions','Search','Settings'],key='navigation_legacy',label_visibility='collapsed')
 st.markdown('<div class="cc-rail-status"><b>● SYSTEM ONLINE</b><br>Approval gates active · manual submission only</div>',unsafe_allow_html=True)
 page=legacy_page
page=st.session_state.pop('dashboard_destination',page)
st.session_state['navigation']=page
if page=='Dashboard': dashboard()
elif page=='New Application': new_application()
elif page=='JD Analysis': jd_analysis_page()
elif page=='Resume Workspace': resume_workspace()
elif page in {'Cover Letter','Cover Letter Workspace'}: cover_workspace()
elif page=='Application Package': package_page()
elif page in {'Applications','History','Application History'}: history_page()
elif page=='Profile': profile_page()
elif page=='Pending Actions': pending_page()
elif page=='Search': search_page()
else: settings_page()
