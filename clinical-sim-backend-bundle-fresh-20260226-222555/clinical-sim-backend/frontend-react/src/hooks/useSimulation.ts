/* Central simulation state hook */

import { useState, useCallback, useRef } from 'react';
import type { CaseInfo, Vitals, SimEvent, ActiveInfusion, LabResult, ImagingResult } from '../types';
import * as api from '../lib/api';

export interface SimState {
  phase: 'case-select' | 'running' | 'debrief';
  sessionId: string | null;
  caseId: string | null;
  caseTitle: string;
  patient: { name: string; age: number; sex: string; weight: number } | null;
  vitals: Vitals;
  events: SimEvent[];
  activeInfusions: ActiveInfusion[];
  labResults: LabResult[];
  imagingResults: ImagingResult[];
  examFindings: string[];
  score: number;
  simTimeSec: number;
  status: string;
  loading: boolean;
  error: string | null;
  report: Record<string, unknown> | null;
}

const DEFAULT_VITALS: Vitals = {
  sbp: 0, dbp: 0, map: 0, hr: 0, rr: 0, spo2: 0,
  rhythm: '—', alarm_flags: [],
};

export function useSimulation() {
  const [state, setState] = useState<SimState>({
    phase: 'case-select',
    sessionId: null,
    caseId: null,
    caseTitle: '',
    patient: null,
    vitals: DEFAULT_VITALS,
    events: [],
    activeInfusions: [],
    labResults: [],
    imagingResults: [],
    examFindings: [],
    score: 0,
    simTimeSec: 0,
    status: 'created',
    loading: false,
    error: null,
    report: null,
  });

  const sseRef = useRef<EventSource | null>(null);

  const selectCase = useCallback(async (caseInfo: CaseInfo) => {
    setState(s => ({ ...s, loading: true, error: null }));
    try {
      const sessionId = await api.createSession();
      const result = await api.startCase(sessionId, caseInfo.case_id) as Record<string, any>;
      const initial = result.initialState || {};
      const hemo = initial.hemodynamics || {};
      const resp = initial.respiratory || {};
      const profile = result.openingScript?.patient_profile || initial.patient_profile || {};

      // Connect SSE
      if (sseRef.current) sseRef.current.close();
      sseRef.current = api.connectSSE(sessionId, (data: any) => {
        if (data.vitals) {
          setState(s => ({ ...s, vitals: data.vitals }));
        }
      });

      setState(s => ({
        ...s,
        phase: 'running',
        sessionId,
        caseId: caseInfo.case_id,
        caseTitle: caseInfo.title,
        patient: {
          name: profile.name || 'Unknown',
          age: profile.age_years || 0,
          sex: profile.sex || '',
          weight: profile.weight_kg || 70,
        },
        vitals: {
          sbp: hemo.sbp || 0,
          dbp: hemo.dbp || 0,
          map: hemo.map || 0,
          hr: hemo.hr || 0,
          rr: resp.rr || 0,
          spo2: resp.spo2 || 0,
          rhythm: hemo.rhythm || 'sinus',
          alarm_flags: [],
        },
        events: [{
          eventId: 'opening',
          timeSec: 0,
          eventType: 'state_update',
          severity: 'info',
          summary: result.openingScript?.nurse_handoff || `Case started: ${caseInfo.title}`,
        }],
        activeInfusions: [],
        labResults: [],
        imagingResults: [],
        examFindings: [],
        score: 0,
        simTimeSec: 0,
        status: 'running',
        loading: false,
        report: null,
      }));
    } catch (err: any) {
      setState(s => ({ ...s, loading: false, error: err.message }));
    }
  }, []);

  const submitOrder = useCallback(async (text: string) => {
    if (!state.sessionId || !text.trim()) return;
    setState(s => ({ ...s, loading: true }));
    try {
      const result = await api.submitTurn(state.sessionId, text);
      const ui = result.engineResult?.uiUpdates;
      const scoring = result.engineResult?.scoringUpdates;
      const newEvents = result.engineResult?.newEvents || [];

      setState(s => {
        const vitals = ui?.monitorUpdates ? { ...ui.monitorUpdates } as Vitals : s.vitals;
        const panel = ui?.panelUpdates || {};

        return {
          ...s,
          loading: false,
          vitals,
          events: [...s.events, ...newEvents],
          activeInfusions: (panel as any).active_infusions || s.activeInfusions,
          labResults: [...s.labResults, ...((panel as any).new_lab_results || [])],
          imagingResults: [...s.imagingResults, ...((panel as any).new_imaging_results || [])],
          examFindings: (panel as any).exam_findings || s.examFindings,
          score: scoring?.runningScore ?? s.score,
          simTimeSec: result.engineResult
            ? (result.engineResult as any).timestampSimSecAfter || s.simTimeSec
            : s.simTimeSec,
        };
      });
    } catch (err: any) {
      setState(s => ({ ...s, loading: false, error: err.message }));
    }
  }, [state.sessionId]);

  const requestDebrief = useCallback(async () => {
    if (!state.sessionId) return;
    setState(s => ({ ...s, loading: true }));
    try {
      const data = await api.generateReport(state.sessionId);
      if (sseRef.current) sseRef.current.close();
      setState(s => ({
        ...s,
        phase: 'debrief',
        loading: false,
        report: data.report as Record<string, unknown>,
      }));
    } catch (err: any) {
      setState(s => ({ ...s, loading: false, error: err.message }));
    }
  }, [state.sessionId]);

  const resetToMenu = useCallback(() => {
    if (sseRef.current) sseRef.current.close();
    setState(s => ({
      ...s,
      phase: 'case-select',
      sessionId: null,
      caseId: null,
      events: [],
      report: null,
      error: null,
    }));
  }, []);

  return { state, selectCase, submitOrder, requestDebrief, resetToMenu };
}
