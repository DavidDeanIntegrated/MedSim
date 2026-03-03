import type { Vitals } from '../types';
import ECGWaveform from './ECGWaveform';
import ArtLinePleth from './ArtLinePleth';
import CapnoWaveform from './CapnoWaveform';
import './VitalMonitor.css';

interface Props {
  vitals: Vitals;
  patientName?: string;
  patientAge?: number;
  patientSex?: string;
  patientWeight?: number;
  score: number;
  simTimeSec: number;
}

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function vitalClass(value: number, critLow: number, warnLow: number, warnHigh: number, critHigh: number): string {
  if (value <= 0) return '';
  if (value < critLow || value > critHigh) return 'vital-critical';
  if (value < warnLow || value > warnHigh) return 'vital-warning';
  return 'vital-normal';
}

export default function VitalMonitor({ vitals, patientName, patientAge, patientSex, patientWeight, score, simTimeSec }: Props) {
  const bpClass = vitalClass(vitals.sbp, 80, 90, 160, 200);
  const mapClass = vitalClass(vitals.map, 55, 65, 105, 120);
  const hrClass = vitalClass(vitals.hr, 40, 50, 110, 150);
  const spo2Class = vitalClass(vitals.spo2, 85, 92, 101, 101);
  const rrClass = vitalClass(vitals.rr, 6, 10, 24, 35);

  return (
    <div className="vital-monitor">
      {/* Waveform displays */}
      <div className="waveform-strip">
        <ECGWaveform hr={vitals.hr} rhythm={vitals.rhythm} />
        <ArtLinePleth sbp={vitals.sbp} dbp={vitals.dbp} hr={vitals.hr} />
        <CapnoWaveform rr={vitals.rr} />
      </div>

      {/* Numeric vitals */}
      <div className="vitals-grid">
        <div className={`vital-tile bp ${bpClass}`}>
          <span className="vital-label">BP</span>
          <span className="vital-value">{vitals.sbp}/{vitals.dbp}</span>
        </div>
        <div className={`vital-tile map ${mapClass}`}>
          <span className="vital-label">MAP</span>
          <span className="vital-value">{vitals.map}</span>
        </div>
        <div className={`vital-tile hr ${hrClass}`}>
          <span className="vital-label">HR</span>
          <span className="vital-value">{vitals.hr}</span>
        </div>
        <div className={`vital-tile spo2 ${spo2Class}`}>
          <span className="vital-label">SpO2</span>
          <span className="vital-value">{vitals.spo2}%</span>
        </div>
        <div className={`vital-tile rr ${rrClass}`}>
          <span className="vital-label">RR</span>
          <span className="vital-value">{vitals.rr}</span>
        </div>
        <div className="vital-tile rhythm">
          <span className="vital-label">Rhythm</span>
          <span className="vital-value">{vitals.rhythm}</span>
        </div>
      </div>

      {/* Alarms */}
      {vitals.alarm_flags?.length > 0 && (
        <div className="alarm-strip">
          {vitals.alarm_flags.map((f, i) => (
            <div key={i} className="alarm-flag">{f}</div>
          ))}
        </div>
      )}

      {/* Patient info and score */}
      <div className="monitor-footer">
        <div className="patient-info">
          {patientName && <span>{patientName}</span>}
          {patientAge && <span>{patientAge}yo {patientSex}</span>}
          {patientWeight && <span>{patientWeight}kg</span>}
        </div>
        <div className="monitor-meta">
          <span className="sim-time">T+{fmtTime(simTimeSec)}</span>
          <div className="score-bar-wrap">
            <span className="score-label">Score</span>
            <div className="score-track">
              <div className="score-fill" style={{ width: `${Math.min(100, score)}%` }} />
            </div>
            <span className="score-value">{Math.round(score)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
