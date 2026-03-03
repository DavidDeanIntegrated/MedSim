import type { ActiveInfusion, LabResult, ImagingResult } from '../types';
import './InfoPanel.css';

interface Props {
  activeInfusions: ActiveInfusion[];
  labResults: LabResult[];
  imagingResults: ImagingResult[];
  examFindings: string[];
}

function cleanMedName(id: string): string {
  return id
    .replace(/_(iv|po|neb|im|sq|sl|pr|inhaled|topical)$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

export default function InfoPanel({ activeInfusions, labResults, imagingResults, examFindings }: Props) {
  return (
    <div className="info-panel">
      {/* Active infusions */}
      <div className="ip-section">
        <div className="ip-header">Active Infusions</div>
        {activeInfusions.length === 0 ? (
          <div className="ip-empty">No active drips</div>
        ) : (
          <ul className="ip-list">
            {activeInfusions.map((inf, i) => (
              <li key={i} className="ip-item infusion">
                <span className="ip-dot" />
                <span className="ip-med">{cleanMedName(inf.medication_id)}</span>
                <span className="ip-rate">{inf.display_rate}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Exam findings */}
      {examFindings.length > 0 && (
        <div className="ip-section">
          <div className="ip-header">Exam Findings</div>
          <ul className="ip-list">
            {examFindings.map((f, i) => (
              <li key={i} className="ip-item">{f}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Lab results */}
      {labResults.length > 0 && (
        <div className="ip-section">
          <div className="ip-header">Lab Results</div>
          <ul className="ip-list">
            {labResults.map((lab, i) => (
              <li key={i} className="ip-item lab">
                <span className="ip-lab-id">{lab.lab_id}</span>
                <span className="ip-lab-val">{lab.display_text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Imaging results */}
      {imagingResults.length > 0 && (
        <div className="ip-section">
          <div className="ip-header">Imaging</div>
          <ul className="ip-list">
            {imagingResults.map((img, i) => (
              <li key={i} className="ip-item imaging">
                <span className="ip-lab-id">{img.study_id}</span>
                <span className="ip-lab-val">{img.display_text}</span>
                {img.image_url && (
                  <div className="ip-image-wrap">
                    <img src={img.image_url} alt={img.study_id} className="ip-image" />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
