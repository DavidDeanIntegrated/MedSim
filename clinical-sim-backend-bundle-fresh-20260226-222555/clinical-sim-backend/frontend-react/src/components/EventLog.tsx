import { useEffect, useRef } from 'react';
import type { SimEvent } from '../types';
import './EventLog.css';

interface Props {
  events: SimEvent[];
}

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `T+${m}:${s.toString().padStart(2, '0')}`;
}

const SEVERITY_CLASS: Record<string, string> = {
  info: 'ev-info',
  low: 'ev-low',
  moderate: 'ev-mod',
  high: 'ev-high',
  critical: 'ev-crit',
};

const EVENT_ICONS: Record<string, string> = {
  critical_action_completed: '✓',
  harm_event_triggered: '✕',
  clinical_improvement: '↑',
  clinical_deterioration: '↓',
  medication_effect: '◉',
  diagnostic_result_available: '⬤',
  monitor_alarm: '⚠',
  state_update: '●',
};

export default function EventLog({ events }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  return (
    <div className="event-log">
      <div className="el-header">Event Log</div>
      <div className="el-scroll">
        {events.map((evt, i) => (
          <div
            key={evt.eventId || i}
            className={`el-item ${SEVERITY_CLASS[evt.severity] || 'ev-info'}`}
          >
            <span className="el-time">{fmtTime(evt.timeSec)}</span>
            <span className="el-icon">{EVENT_ICONS[evt.eventType] || '●'}</span>
            <span className="el-text">{evt.summary}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
