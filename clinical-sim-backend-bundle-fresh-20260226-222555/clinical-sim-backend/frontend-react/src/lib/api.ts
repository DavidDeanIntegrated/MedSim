/* MedSim API client */

import type { CaseInfo, TurnResponse, DebriefReport } from '../types';

const BASE = '';  // Vite proxy handles routing

export async function fetchCases(): Promise<CaseInfo[]> {
  const res = await fetch(`${BASE}/cases`);
  if (!res.ok) throw new Error('Failed to fetch cases');
  const data = await res.json();
  return data.cases;
}

export async function createSession(userId?: string): Promise<string> {
  const res = await fetch(`${BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      userId: userId || 'anonymous',
      deviceMode: 'local_demo',
      metadata: {},
    }),
  });
  if (!res.ok) throw new Error('Failed to create session');
  const data = await res.json();
  return data.sessionId;
}

export async function startCase(
  sessionId: string,
  caseId: string,
  difficulty = 'standard',
): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/start-case`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ caseId, difficulty }),
  });
  if (!res.ok) throw new Error('Failed to start case');
  return res.json();
}

export async function submitTurn(
  sessionId: string,
  inputText: string,
  parserMode = 'text_to_actions',
  advanceTimeSec = 5,
): Promise<TurnResponse> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/turns`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ inputText, parserMode, advanceTimeSec }),
  });
  if (!res.ok) throw new Error('Failed to submit turn');
  return res.json();
}

export async function getSessionState(sessionId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/state`);
  if (!res.ok) throw new Error('Failed to get state');
  return res.json();
}

export async function generateReport(sessionId: string): Promise<{ report: DebriefReport }> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/reports/final`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ includeTranscript: true, includeTimeline: true }),
  });
  if (!res.ok) throw new Error('Failed to generate report');
  return res.json();
}

export async function getDebrief(sessionId: string): Promise<{ debrief: Record<string, unknown> }> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/debrief`);
  if (!res.ok) throw new Error('Failed to get debrief');
  return res.json();
}

export function connectSSE(sessionId: string, onVitals: (data: Record<string, unknown>) => void): EventSource {
  const es = new EventSource(`${BASE}/sessions/${sessionId}/stream`);
  es.addEventListener('vitals', (e) => {
    onVitals(JSON.parse(e.data));
  });
  return es;
}
