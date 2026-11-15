// Synthetic room impulse response: three decaying noise bands (125 Hz, 500 Hz, 2 kHz), listener 1.5 m away.
export function impulse(c: AudioContext, rt: number[], absorb: number) {
  const sr = c.sampleRate,
    len = Math.round(sr * Math.min(3.5, Math.max(...rt) * 1.3 + 0.05));
  const ir = c.createBuffer(2, len, sr),
    ratio = (16 * Math.PI * 1.5 * 1.5) / absorb;
  const lpA = Math.exp((-2 * Math.PI * 300) / sr),
    hpA = Math.exp((-2 * Math.PI * 1500) / sr),
    pre = Math.round(sr * 0.004);
  for (let ch = 0; ch < 2; ch++) {
    const d = ir.getChannelData(ch);
    let lo = 0,
      lp2 = 0,
      energy = 0;
    for (let i = pre; i < len; i++) {
      const t = (i - pre) / sr,
        w = Math.random() * 2 - 1;
      lo = lpA * lo + (1 - lpA) * w;
      lp2 = hpA * lp2 + (1 - hpA) * w;
      const hi = w - lp2,
        mid = w - lo - hi;
      d[i] =
        lo * Math.exp((-6.91 * t) / rt[0]) +
        mid * Math.exp((-6.91 * t) / rt[1]) +
        hi * Math.exp((-6.91 * t) / rt[2]);
      energy += d[i] * d[i];
    }
    const gain = Math.sqrt(ratio / Math.max(energy, 1e-9));
    for (let i = pre; i < len; i++) d[i] *= gain;
    d[0] = 1;
  }
  return ir;
}

export function clap(c: AudioContext) {
  const n = Math.round(c.sampleRate * 0.012),
    buffer = c.createBuffer(1, Math.round(c.sampleRate * 0.5), c.sampleRate),
    d = buffer.getChannelData(0);
  for (let i = 0; i < n; i++)
    d[i] = (Math.random() * 2 - 1) * Math.exp(-i / (n / 4));
  return buffer;
}

export type SoundKind = "clap" | "footsteps" | "chime";
// Dry, synthesized references only; these are not measurements of occupants or traffic.
export function soundSample(c: AudioContext, kind: Exclude<SoundKind, "clap">) {
  const duration = kind === "footsteps" ? 2.4 : 1.8;
  const buffer = c.createBuffer(
    1,
    Math.round(c.sampleRate * duration),
    c.sampleRate,
  );
  const samples = buffer.getChannelData(0);
  if (kind === "footsteps") {
    for (let step = 0; step < 4; step++) {
      const start = Math.round((0.1 + step * 0.5) * c.sampleRate);
      let low = 0;
      for (
        let j = 0;
        j < Math.round(0.22 * c.sampleRate) && start + j < samples.length;
        j++
      ) {
        const t = j / c.sampleRate;
        low = 0.85 * low + 0.15 * (Math.random() * 2 - 1);
        samples[start + j] +=
          0.65 * Math.sin(2 * Math.PI * 85 * t) * Math.exp(-30 * t) +
          low * 0.45 * Math.exp(-18 * t);
      }
    }
  } else {
    for (let i = 0; i < samples.length; i++) {
      const t = i / c.sampleRate,
        attack = Math.min(1, t / 0.006);
      samples[i] =
        attack *
        (0.45 * Math.sin(2 * Math.PI * 660 * t) * Math.exp(-3 * t) +
          0.2 * Math.sin(2 * Math.PI * 1320 * t) * Math.exp(-5 * t));
    }
  }
  return buffer;
}
