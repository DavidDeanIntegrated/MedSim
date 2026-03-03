import './DebriefPanel.css';

interface Props {
  report: Record<string, unknown>;
  onClose: () => void;
}

export default function DebriefPanel({ report, onClose }: Props) {
  const r = report as any;
  const grade = r.letterGrade || '';
  const scorePct = r.score ?? r.scoringBreakdown?.final_percent ?? 0;
  const summary = r.summary || '';

  return (
    <div className="debrief-panel">
      <div className="db-header">
        <h1>Case Debrief</h1>
        <button className="db-close" onClick={onClose}>Back to Cases</button>
      </div>

      {/* Overall assessment */}
      <div className="db-assessment">
        <div className={`db-grade grade-${grade.charAt(0)}`}>{grade}</div>
        <div className="db-score-pct">{Math.round(scorePct)}%</div>
        <p className="db-summary">{summary}</p>
      </div>

      {/* Critical Actions */}
      <Section title="Critical Actions">
        {(r.criticalActionsAnalysis || []).map((a: any, i: number) => (
          <div key={i} className={`db-action ${a.completed ? 'completed' : 'missed'}`}>
            <span className="db-action-icon">{a.completed ? '✓' : '✕'}</span>
            <div className="db-action-detail">
              <span className="db-action-desc">{a.description}</span>
              {a.completed && a.timing_multiplier !== undefined && (
                <span className="db-action-timing">
                  {a.timing_multiplier >= 1.0 ? 'On time' : 'Late'} ({a.points_earned?.toFixed(1)} pts)
                </span>
              )}
              {!a.completed && <span className="db-action-missed">Not completed (-{a.weight} pts possible)</span>}
            </div>
          </div>
        ))}
      </Section>

      {/* Harm Events */}
      {(r.harmEventsAnalysis || []).some((h: any) => h.triggered) && (
        <Section title="Harm Events">
          {(r.harmEventsAnalysis || []).filter((h: any) => h.triggered).map((h: any, i: number) => (
            <div key={i} className="db-harm">
              <span className="db-harm-icon">⚠</span>
              <div>
                <span className="db-harm-desc">{h.description}</span>
                <span className="db-harm-penalty">-{h.penalty} pts</span>
              </div>
            </div>
          ))}
        </Section>
      )}

      {/* Strengths */}
      <Section title="Strengths">
        <ul className="db-list green">
          {(r.strengths || r.whatWentWell || []).map((s: string, i: number) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      </Section>

      {/* Areas for improvement */}
      <Section title="Areas for Improvement">
        <ul className="db-list yellow">
          {(r.areasForImprovement || r.whatCouldHaveGoneBetter || []).map((s: string, i: number) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      </Section>

      {/* Study Recommendations */}
      {(r.studyRecommendations || []).length > 0 && (
        <Section title="Study Recommendations">
          <ul className="db-list accent">
            {r.studyRecommendations.map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </Section>
      )}

      {/* Board Review Topics */}
      {(r.boardReviewTopics || []).length > 0 && (
        <Section title="Board Review Topics">
          <ul className="db-list purple">
            {r.boardReviewTopics.map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </Section>
      )}

      {/* Annotated Timeline */}
      {(r.annotatedTimeline || []).length > 0 && (
        <Section title="Timeline" collapsible>
          <div className="db-timeline">
            {r.annotatedTimeline.map((e: any, i: number) => (
              <div key={i} className={`db-tl-item tl-${e.annotation_type || 'neutral'}`}>
                <span className="db-tl-time">{e.time_display}</span>
                <div className="db-tl-content">
                  <span className="db-tl-summary">{e.summary}</span>
                  {e.annotation && <span className="db-tl-annotation">{e.annotation}</span>}
                  {e.timing_note && <span className="db-tl-timing">{e.timing_note}</span>}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children, collapsible = false }: { title: string; children: React.ReactNode; collapsible?: boolean }) {
  return (
    <details className="db-section" open={!collapsible}>
      <summary className="db-section-title">{title}</summary>
      <div className="db-section-content">{children}</div>
    </details>
  );
}
