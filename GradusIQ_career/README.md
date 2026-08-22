# Gradus IQ — Career Features

**Team 6 | Dallas AI Summer Program | SMU | July 2026**

---

## Overview

This folder contains the research foundation, mock data, and prompt 
architecture for the three career-side features of Gradus IQ — an 
AI-powered longitudinal academic and career companion launching at 
Texas A&M University.

The career features answer three questions no current tool answers 
for students:

- **Where do I fit?** → Role Explorer (FIT)
- **What am I missing?** → Readiness Check (GAP)
- **What is changing?** → Trend-Aware Guidance (SHIFT)

---

## Folder Structure
Gradus IQ/

(student profiles live at repo root in data/students/, not inside this folder)
data/students/                       # Five mock student profiles (4 A&M, 1 SMU)
├── student_jordanReyes.json         # Jordan Reyes — Business Administration (pre-major), Freshman — PRIMARY demo student
├── student_ethanBrooks.json         # Ethan Brooks — Computer Science, Sophomore (SMU)
├── student_marcusWebb.json          # Marcus Webb — Psychology, Sophomore
├── student_priyaNair.json           # Priya Nair — Aerospace Engineering, Sophomore
└── student_sofiaRamirez.json        # Sofia Ramirez — Biology, Sophomore
│
├── gradus_iq_prompt_FIT.md      # Role Explorer prompt (at GradusIQ_career/ root)
├── gradus_iq_prompt_GAP.md      # Readiness Check prompt
├── gradus_iq_prompt_SHIFT.md    # Trend-Aware Guidance prompt
└── gradus_iq_prompt_ACADEMIC.md # Academic analysis prompt

Feature outputs are not saved to disk. The FastAPI bridge (`api.py`) returns
results over HTTP. There is no `demo_outputs/` directory today; a
saved-output convention is not yet implemented.

---

## Student Profiles

Each profile is grounded in real Texas A&M enrollment and 
demographic data and designed to represent a realistic A&M 
undergraduate across college, major, year, internship status, 
and career clarity level.

Each profile includes a `primary_feature` field that indicates which 
career feature is most relevant for that student.

---

## Prompt Architecture

Four prompt templates back the Gradus IQ features — three career-side
(FIT / GAP / SHIFT) and one academic-side:

| Template | Feature | What It Does |
|---|---|---|
| `gradus_iq_prompt_FIT.md` | Role Explorer | Surfaces 3-5 DFW-anchored career paths with fit reasoning |
| `gradus_iq_prompt_GAP.md` | Readiness Check | Compares student profile to real posting requirements |
| `gradus_iq_prompt_SHIFT.md` | Trend-Aware Guidance | Explains how target roles are evolving and what to learn |
| `gradus_iq_prompt_ACADEMIC.md` | Professor Comment Analyzer | Aggregates professor comments across a student's courses into recurring themes (strengths, concerns, praise, flags) |

The three career prompts share a common system prompt that establishes Campus 
IQ's identity, reasoning rules, tone, and hard constraints.

---

## Research Foundation

The prompt architecture and market context are grounded in:
- BLS OEWS DFW metro employment data
- Texas Workforce Commission 2022-2032 projections
- NACE Job Outlook 2026
- Strada Education Network research
- Handshake Class of 2026 data
- Stanford HAI 2026 AI Index
- Primary field research (two practitioner interviews)

Full research documentation is in `DFW_Market_Research_MVP_Analysis_v3`

---

## Next Steps

- [ ] Connect to live job market API (Lightcast or O*NET)
- [ ] Build front end UI for recruiter showcase
- [ ] Run all five profiles and save demo outputs
- [ ] Integrate with academic side student profile