import { useEffect, useRef } from 'react';

/**
 * Animated ECG waveform using SVG path animation.
 * Generates a synthetic PQRST complex that varies with heart rate.
 */

interface Props {
  hr: number;
  rhythm: string;
  width?: number;
  height?: number;
}

// Generate one PQRST complex as SVG path segments (y values, where 0 = baseline)
function pqrstComplex(amplitude: number = 1): number[] {
  const a = amplitude;
  // Flat -> P wave -> PR segment -> QRS -> ST segment -> T wave -> flat
  return [
    // Baseline
    0, 0, 0, 0, 0,
    // P wave (small upward deflection)
    0.05 * a, 0.12 * a, 0.18 * a, 0.15 * a, 0.08 * a, 0.02 * a,
    // PR segment
    0, 0, 0,
    // Q wave (small downward)
    -0.08 * a, -0.12 * a,
    // R wave (tall upward spike)
    0.15 * a, 0.55 * a, 0.85 * a, 1.0 * a, 0.82 * a, 0.45 * a, 0.1 * a,
    // S wave (downward)
    -0.2 * a, -0.3 * a, -0.15 * a,
    // ST segment (slight elevation)
    0.02 * a, 0.04 * a, 0.05 * a, 0.05 * a,
    // T wave (broad upward)
    0.08 * a, 0.15 * a, 0.22 * a, 0.25 * a, 0.22 * a, 0.15 * a, 0.08 * a, 0.03 * a,
    // Return to baseline
    0, 0, 0, 0, 0, 0, 0, 0,
  ];
}

function generateECGTrace(hr: number, rhythm: string, numSamples: number): number[] {
  if (hr <= 0) return new Array(numSamples).fill(0);

  const complex = pqrstComplex(1.0);
  const complexLen = complex.length;

  // Samples per beat based on HR (at ~200 samples/sec display rate)
  const samplesPerBeat = Math.round((60 / hr) * 200);
  const trace: number[] = [];

  // Add jitter for afib
  const isAfib = rhythm?.toLowerCase().includes('fib');

  for (let i = 0; i < numSamples; i++) {
    const beatPhase = i % samplesPerBeat;
    const complexPhaseNorm = beatPhase / samplesPerBeat;

    // Map phase [0,1] to complex array position
    // Complex takes ~60% of the beat, rest is flat baseline
    if (complexPhaseNorm < 0.6) {
      const idx = Math.floor((complexPhaseNorm / 0.6) * complexLen);
      let val = complex[Math.min(idx, complexLen - 1)];
      // Afib: irregular R-R and no P wave
      if (isAfib) {
        val += (Math.random() - 0.5) * 0.05;
      }
      trace.push(val);
    } else {
      // Baseline between beats
      trace.push(isAfib ? (Math.random() - 0.5) * 0.03 : 0);
    }
  }

  return trace;
}

export default function ECGWaveform({ hr, rhythm, width = 300, height = 60 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const traceRef = useRef<number[]>([]);
  const offsetRef = useRef(0);
  const frameRef = useRef(0);

  useEffect(() => {
    traceRef.current = generateECGTrace(hr, rhythm, 600);
  }, [hr, rhythm]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let running = true;
    const draw = () => {
      if (!running) return;

      const w = canvas.width;
      const h = canvas.height;
      const mid = h * 0.55;
      const scale = h * 0.4;
      const trace = traceRef.current;

      ctx.fillStyle = '#0a0e14';
      ctx.fillRect(0, 0, w, h);

      // Grid lines
      ctx.strokeStyle = 'rgba(0,255,65,0.06)';
      ctx.lineWidth = 0.5;
      for (let y = 0; y < h; y += 15) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }
      for (let x = 0; x < w; x += 15) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      }

      // Draw trace
      ctx.strokeStyle = '#00ff41';
      ctx.lineWidth = 1.5;
      ctx.shadowColor = '#00ff41';
      ctx.shadowBlur = 3;
      ctx.beginPath();

      const offset = offsetRef.current;
      for (let x = 0; x < w; x++) {
        const idx = (offset + x * 2) % trace.length;
        const y = mid - trace[idx] * scale;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Sweep line
      const sweepX = w - 1;
      ctx.strokeStyle = 'rgba(0,255,65,0.3)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(sweepX, 0);
      ctx.lineTo(sweepX, h);
      ctx.stroke();

      // Label
      ctx.fillStyle = '#00ff41';
      ctx.font = '9px monospace';
      ctx.fillText('II', 4, 12);

      offsetRef.current += 3;
      if (offsetRef.current >= trace.length) offsetRef.current = 0;

      frameRef.current = requestAnimationFrame(draw);
    };

    frameRef.current = requestAnimationFrame(draw);
    return () => { running = false; cancelAnimationFrame(frameRef.current); };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="ecg-canvas"
      style={{ width: '100%', height: `${height}px`, display: 'block' }}
    />
  );
}
