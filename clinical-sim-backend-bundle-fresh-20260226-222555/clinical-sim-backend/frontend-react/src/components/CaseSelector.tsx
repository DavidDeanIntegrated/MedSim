import { useEffect, useState } from 'react';
import type { CaseInfo } from '../types';
import { fetchCases } from '../lib/api';
import './CaseSelector.css';

const CATEGORY_COLORS: Record<string, string> = {
  hypertensive_emergency: '#f85149',
  septic_shock: '#db6d28',
  dka: '#d29922',
  stemi: '#f85149',
  eclampsia: '#bc8cff',
  massive_pe: '#58a6ff',
  aortic_dissection: '#f85149',
  anaphylaxis: '#ff7b72',
  ich: '#e6edf3',
  copd_exacerbation: '#3fb950',
  acute_pulmonary_edema: '#58a6ff',
};

interface Props {
  onSelect: (c: CaseInfo) => void;
  loading: boolean;
}

export default function CaseSelector({ onSelect, loading }: Props) {
  const [cases, setCases] = useState<CaseInfo[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchCases()
      .then(setCases)
      .catch(() => setError('Failed to load cases'));
  }, []);

  return (
    <div className="case-selector">
      <div className="cs-header">
        <h1>MedSim</h1>
        <p className="cs-subtitle">Emergency Medicine Clinical Simulation</p>
        <p className="cs-desc">Select a case to begin your simulation</p>
      </div>

      {error && <div className="cs-error">{error}</div>}

      <div className="cs-grid">
        {cases.map(c => (
          <button
            key={c.case_id}
            className="case-card"
            onClick={() => onSelect(c)}
            disabled={loading}
            style={{ borderLeftColor: CATEGORY_COLORS[c.category] || '#58a6ff' }}
          >
            <div className="cc-header">
              <span className="cc-title">{c.title}</span>
              <span className={`cc-diff diff-${c.difficulty}`}>{c.difficulty}</span>
            </div>
            <span className="cc-category">{c.category?.replace(/_/g, ' ')}</span>
            {c.description && <p className="cc-desc">{c.description}</p>}
          </button>
        ))}
      </div>

      {loading && <div className="cs-loading">Loading simulation...</div>}
    </div>
  );
}
