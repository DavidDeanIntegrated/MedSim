import { useEffect, useRef } from 'react';

/**
 * Arterial line / plethysmography waveform.
 * Draws a pulsatile arterial pressure waveform scaled to SBP/DBP.
 */

interface Props {
  sbp: number;
  dbp: number;
  hr: number;
  width?: number;
  height?: number;
}

function generateArtLine(sbp: number, dbp: number, hr: number, numSamples: number): number[] {
  if (hr <= 0 || sbp <= 0) return new Array(numSamples).fill(0);

  const samplesPerBeat = Math.round((60 / hr) * 200);
  const trace: number[] = [];
  const pp = sbp - dbp; // pulse pressure

  for (let i = 0; i < numSamples; i++) {
    const phase = (i % samplesPerBeat) / samplesPerBeat;

    let val: number;
    if (phase < 0.12) {
      // Systolic upstroke (fast rise)
      const t = phase / 0.12;
      val = dbp + pp * Math.sin(t * Math.PI / 2);
    } else if (phase < 0.2) {
      // Peak and initial descent
      const t = (phase - 0.12) / 0.08;
      val = sbp - pp * 0.15 * t;
    } else if (phase < 0.35) {
      // Dicrotic notch
      const t = (phase - 0.2) / 0.15;
      const notchDepth = pp * 0.12;
      val = sbp - pp * 0.15 - notchDepth * Math.sin(t * Math.PI);
      if (t > 0.3 && t < 0.7) val -= notchDepth * 0.5; // The notch itself
    } else {
      // Diastolic runoff (exponential decay)
      const t = (phase - 0.35) / 0.65;
      const startVal = dbp + pp * 0.35;
      val = dbp + (startVal - dbp) * Math.exp(-3 * t);
    }

    // Normalize to 0-1 range for drawing
    trace.push((val - dbp * 0.8) / (sbp * 1.1 - dbp * 0.8));
  }

  return trace;
}

export default function ArtLinePleth({ sbp, dbp, hr, width = 300, height = 45 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const traceRef = useRef<number[]>([]);
  const offsetRef = useRef(0);
  const frameRef = useRef(0);

  useEffect(() => {
    traceRef.current = generateArtLine(sbp, dbp, hr, 600);
  }, [sbp, dbp, hr]);

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
      ctx.strokeStyle = 'rgba(255,68,68,0.05)';
      ctx.lineWidth = 0.5;
      for (let y = 0; y < h; y += 15) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }

      // Draw trace
      ctx.strokeStyle = '#ff4444';
      ctx.lineWidth = 1.5;
      ctx.shadowColor = '#ff4444';
      ctx.shadowBlur = 2;
      ctx.beginPath();

      const offset = offsetRef.current;
      for (let x = 0; x < w; x++) {
        const idx = (offset + x * 2) % trace.length;
        const y = h - trace[idx] * h * 0.85 - h * 0.05;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Label
      ctx.fillStyle = '#ff4444';
      ctx.font = '9px monospace';
      ctx.fillText('ART', 4, 12);

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
      style={{ width: '100%', height: `${height}px`, display: 'block' }}
    />
  );
}
