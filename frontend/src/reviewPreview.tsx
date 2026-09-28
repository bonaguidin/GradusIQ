// Intentional test-only Vite fixture used by reviewInteraction.test.mjs.
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { CareerReview } from './components/CareerReview';
import './index.css';
import './interaction.ts';

const SECTIONS = {
  career_profile: {
    id: 'cp-1', source: 'resume_parse',
    target_roles: ['Machine Learning Engineer', 'AI Research Intern'],
    interests: ['computer vision', 'systems'],
    career_goals: 'Work on training-infrastructure problems at a lab that ships models to production, and eventually lead a small team doing the same. I want the work to stay close to the hardware.',
    geographic_preference: null, ai_anxiety_level: null,
    skills_technical: ['Python', 'PyTorch', 'CUDA', 'Triton', 'C++', 'Bash'],
    skills_soft: ['written communication'], ai_exposure: null,
  },
  certifications: [
    { id: 'c-1', source: 'resume_parse', name: 'Deep Learning Specialization', issuer: 'DeepLearning.AI', status: 'completed', date: null },
    { id: 'c-2', source: 'resume_parse', name: 'AWS Cloud Practitioner', issuer: null, status: null, date: null },
  ],
  work_experience: [
    { id: 'w-1', source: 'resume_parse', employer: 'NVIDIA', role: 'AI Intern', duration: 'Jan 2025 – Nov 2025', location: null,
      description: 'Built a profiling harness for distributed training runs that cut per-experiment setup from about forty minutes to under five, and used it to find a collective-communication stall that was costing roughly 11% of throughput on eight-GPU jobs.',
      skills_gained: ['PyTorch', 'NCCL', 'profiling'] },
  ],
  projects: [
    { id: 'p-1', source: 'resume_parse', name: 'Campus Scheduler', timeframe: null, description: 'A React app for course planning.', tools: ['React', 'TypeScript'] },
  ],
};

const original = globalThis.fetch;
globalThis.fetch = ((url: string, init?: RequestInit) => {
  const u = String(url);
  if (u.includes('/career/review') && (!init || init.method === undefined || init.method === 'GET')) {
    return Promise.resolve(new Response(JSON.stringify(SECTIONS), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  if (init?.method === 'PATCH') {
    // Mirror the real contract: project_row() returns the FULL row (id + every
    // editable field + source), not just what changed.
    const body = JSON.parse(String(init.body));
    const id = decodeURIComponent(u.split('/').pop()!);
    const all = [SECTIONS.career_profile, ...SECTIONS.certifications, ...SECTIONS.work_experience, ...SECTIONS.projects];
    const base = all.find((r) => r.id === id) ?? {};
    const merged = { ...base, ...body };
    Object.assign(base, body);
    return new Promise((res) => setTimeout(() => res(new Response(JSON.stringify(merged), { status: 200, headers: { 'Content-Type': 'application/json' } })), 120));
  }
  if (u.includes('/career/confirm') && init?.method === 'POST') {
    return new Promise((resolve) => window.setTimeout(
      () => resolve(new Response(JSON.stringify({
        scope: 'all',
        confirmed: { career_profiles: 1, certifications: 2, work_experience: 1, projects: 1 },
        total_confirmed: 5,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })),
      120,
    ));
  }
  return original(url as never, init);
}) as typeof fetch;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <CareerReview accessToken="preview" onConfirmed={() => undefined} sourceName="ada_lovelace_resume.pdf" parsedAt={new Date('2026-08-10')} />
  </StrictMode>,
);
