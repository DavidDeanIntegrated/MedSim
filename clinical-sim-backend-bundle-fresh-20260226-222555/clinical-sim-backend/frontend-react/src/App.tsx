import { useEffect, useState } from 'react';
import { useSimulation } from './hooks/useSimulation';
import CaseSelector from './components/CaseSelector';
import VitalMonitor from './components/VitalMonitor';
import EventLog from './components/EventLog';
import OrderBar from './components/OrderBar';
import InfoPanel from './components/InfoPanel';
import DebriefPanel from './components/DebriefPanel';
import './App.css';

export default function App() {
  const { state, selectCase, submitOrder, requestDebrief, resetToMenu } = useSimulation();
  const [toastVisible, setToastVisible] = useState(false);

  useEffect(() => {
    if (state.error) {
      setToastVisible(true);
      const timer = setTimeout(() => setToastVisible(false), 5000);
      return () => clearTimeout(timer);
    }
    setToastVisible(false);
  }, [state.error]);

  if (state.phase === 'case-select') {
    return <CaseSelector onSelect={selectCase} loading={state.loading} />;
  }

  if (state.phase === 'debrief' && state.report) {
    return <DebriefPanel report={state.report} onClose={resetToMenu} />;
  }

  return (
    <div className="sim-layout">
      {/* Header */}
      <header className="sim-header">
        <div className="sh-left">
          <h1 className="sh-title">{state.caseTitle}</h1>
          <span className="sh-status">{state.status}</span>
        </div>
        <div className="sh-right">
          <button className="sh-btn debrief-btn" onClick={requestDebrief} disabled={state.loading}>
            End Case &amp; Debrief
          </button>
          <button className="sh-btn" onClick={resetToMenu}>Exit</button>
        </div>
      </header>

      {/* Main content */}
      <div className="sim-body">
        {/* Left column: Monitor + Info */}
        <aside className="sim-sidebar">
          <VitalMonitor
            vitals={state.vitals}
            patientName={state.patient?.name}
            patientAge={state.patient?.age}
            patientSex={state.patient?.sex}
            patientWeight={state.patient?.weight}
            score={state.score}
            simTimeSec={state.simTimeSec}
          />
          <InfoPanel
            activeInfusions={state.activeInfusions}
            labResults={state.labResults}
            imagingResults={state.imagingResults}
            examFindings={state.examFindings}
          />
        </aside>

        {/* Right column: Event log + Order bar */}
        <main className="sim-main">
          <EventLog events={state.events} />
          <OrderBar onSubmit={submitOrder} loading={state.loading} />
        </main>
      </div>

      {/* Error toast */}
      {state.error && toastVisible && (
        <div className="error-toast">{state.error}</div>
      )}
    </div>
  );
}
