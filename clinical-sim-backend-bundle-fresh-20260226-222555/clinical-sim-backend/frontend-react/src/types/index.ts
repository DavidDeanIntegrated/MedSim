/* MedSim shared types */

export interface CaseInfo {
  case_id: string;
  title: string;
  category: string;
  difficulty: string;
  description?: string;
}

export interface Vitals {
  sbp: number;
  dbp: number;
  map: number;
  hr: number;
  rr: number;
  spo2: number;
  rhythm: string;
  alarm_flags: string[];
}

export interface PatientProfile {
  name: string;
  age_years: number;
  sex: string;
  weight_kg: number;
}

export interface ActiveInfusion {
  medication_id: string;
  display_rate: string;
}

export interface LabResult {
  lab_id: string;
  display_text: string;
}

export interface ImagingResult {
  study_id: string;
  display_text: string;
  image_url?: string;
}

export interface SimEvent {
  eventId: string;
  timeSec: number;
  eventType: string;
  severity: 'info' | 'low' | 'moderate' | 'high' | 'critical';
  summary: string;
  structuredData?: Record<string, unknown>;
}

export interface ScoringUpdates {
  criticalActionsCompleted: string[];
  harmEventsTriggered: string[];
  scoreDelta: number;
  runningScore: number;
  teachingMarkersAdded: string[];
}

export interface EngineResult {
  executionStatus: string;
  uiUpdates: {
    monitorUpdates: Vitals;
    panelUpdates: {
      new_lab_results: LabResult[];
      new_imaging_results: ImagingResult[];
      active_infusions: ActiveInfusion[];
      exam_findings: string[];
    };
    notificationUpdates: { level: string; message: string }[];
  };
  newEvents: SimEvent[];
  scoringUpdates: ScoringUpdates;
  voiceResponsePlan?: Record<string, unknown>;
}

export interface TurnResponse {
  sessionId: string;
  turnId: string;
  parsedTurn: {
    turnId: string;
    actions: ParsedAction[];
    parserStatus: string;
  };
  engineResult: EngineResult;
}

export interface ParsedAction {
  actionUuid: string;
  sequenceIndex: number;
  toolName: string;
  payload: Record<string, unknown>;
}

export interface SessionState {
  sessionId: string;
  caseId: string;
  status: 'created' | 'active' | 'completed' | 'failed';
  vitals: Vitals;
  patient: PatientProfile;
  activeInfusions: ActiveInfusion[];
  labResults: LabResult[];
  imagingResults: ImagingResult[];
  examFindings: string[];
  events: SimEvent[];
  score: number;
  simTimeSec: number;
}

export interface DebriefReport {
  summary: string;
  score: number;
  letterGrade: string;
  criticalActionsAnalysis: ActionScore[];
  harmEventsAnalysis: HarmScore[];
  strengths: string[];
  areasForImprovement: string[];
  studyRecommendations: string[];
  boardReviewTopics: string[];
  annotatedTimeline: TimelineEntry[];
  scoringBreakdown: Record<string, unknown>;
}

export interface ActionScore {
  action_id: string;
  description: string;
  weight: number;
  completed: boolean;
  completed_at_sec: number | null;
  timing_multiplier: number;
  points_earned: number;
}

export interface HarmScore {
  harm_id: string;
  description: string;
  severity: number;
  triggered: boolean;
  triggered_at_sec: number | null;
  penalty: number;
}

export interface TimelineEntry {
  time_sec: number;
  time_display: string;
  event_type: string;
  summary: string;
  annotation?: string;
  annotation_type?: 'positive' | 'negative' | 'neutral' | 'warning';
  timing_note?: string;
}
