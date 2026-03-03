import { useState, useRef, useEffect } from 'react';
import './OrderBar.css';

interface Props {
  onSubmit: (text: string) => void;
  loading: boolean;
  suggestions?: string[];
}

const DEFAULT_SUGGESTIONS = [
  'Start nicardipine 5 mg/hr',
  'Order head CT',
  'Check vitals',
  'Give labetalol 20 mg IV push',
  'Order CBC, CMP, troponin',
  'Set monitoring continuous, NIBP q5min',
  'Reassess neuro status',
  'Start norepinephrine 5 mcg/min',
  'Give NS 1L bolus',
  'Order 12-lead ECG',
  'Admit to ICU',
];

export default function OrderBar({ onSubmit, loading, suggestions }: Props) {
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const chips = suggestions || DEFAULT_SUGGESTIONS;

  const handleSubmit = () => {
    if (text.trim() && !loading) {
      onSubmit(text.trim());
      setText('');
    }
  };

  const handleChip = (chip: string) => {
    if (!loading) {
      onSubmit(chip);
    }
  };

  useEffect(() => {
    inputRef.current?.focus();
  }, [loading]);

  return (
    <div className="order-bar">
      <div className="ob-chips">
        {chips.slice(0, 6).map((chip, i) => (
          <button
            key={i}
            className="ob-chip"
            onClick={() => handleChip(chip)}
            disabled={loading}
          >
            {chip}
          </button>
        ))}
      </div>
      <div className="ob-input-row">
        <input
          ref={inputRef}
          className="ob-input"
          type="text"
          placeholder="Enter clinical orders (e.g., 'Start nicardipine 5 mg/hr and order head CT')"
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          disabled={loading}
        />
        <button
          className="ob-submit"
          onClick={handleSubmit}
          disabled={loading || !text.trim()}
        >
          {loading ? '...' : 'Submit'}
        </button>
      </div>
    </div>
  );
}
