import { useEffect, useRef } from 'react';

/**
 * Capnography (ETCO2) waveform.
 * Square-wave-like pattern that varies with respiratory rate.
 */

interface Props {
  rr: number;
  etco2?: number;
  width?: number;
  height?: number;
}

function generateCapno(rr: number, etco2: number = 38, numSamples: number = 600): number[] {
  if (rr <= 0) return new Array(numSamples).fill(0);

  const samplesPerBreath = Math.round((60 / rr) * 200);
  const trace: number[] = [];
  const peak = etco2 / 50; // Normalize to ~0-1

  for (let i = 0; i < numSamples; i++) {
    const phase = (i % samplesPerBreath) / samplesPerBreath;

    let val: number;
    if (phase < 0.05) {
      // Inspiratory baseline
      val = 0;
    } else if (phase < 0.15) {
      // Expiratory upstroke (fast rise)
      const t = (phase - 0.05) / 0.1;
      val = peak * (1 - Math.exp(-5 * t));
    } else if (phase < 0.4) {
      // Alveolar plateau (slight upslope)
      const t = (phase - 0.15) / 0.25;
      val = peak * (0.92 + 0.08 * t);
    } else if (phase < 0.45) {
      // End-tidal peak then inspiratory downstroke
      const t = (phase - 0.4) / 0.05;
      val = peak * (1 - t);
    } else {
      // Inspiratory baseline
      val = 0;
    }

    trace.push(val);
  }

  return trace;
}

export default function CapnoWaveform({ rr, etco2 = 38, width = 300, height = 40 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const traceRef = useRef<number[]>([]);
  const offsetRef = useRef(0);
  const frameRef = useRef(0);

  useEffect(() => {
    traceRef.current = generateCapno(rr, etco2);
  }, [rr, etco2]);

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
      const trace = traceRef.current;

      ctx.fillStyle = '#0a0e14';
      ctx.fillRect(0, 0, w, h);

      // Subtle grid
      ctx.strokeStyle = 'rgba(255,235,59,0.05)';
      ctx.lineWidth = 0.5;
      for (let y = 0; y < h; y += 15) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }

      // Draw trace
      ctx.strokeStyle = '#ffeb3b';
      ctx.lineWidth = 1.5;
      ctx.shadowColor = '#ffeb3b';
      ctx.shadowBlur = 2;
      ctx.beginPath();

      const offset = offsetRef.current;
      for (let x = 0; x < w; x++) {
        const idx = (offset + x * 2) % trace.length;
        const y = h - trace[idx] * h * 0.8 - h * 0.05;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Label
      ctx.fillStyle = '#ffeb3b';
      ctx.font = '9px monospace';
      ctx.fillText('CO₂', 4, 12);

      offsetRef.current += 2; // Slower sweep for capno
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
      style={{ width: '100%', height: `${height}px`, display: 'block' }}
    />
  );
}
