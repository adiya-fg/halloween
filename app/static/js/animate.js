// Animated "living" sticker for stories: a 1080×1920 canvas scene built from the
// server-rendered sticker layers (base, hero, front), recorded to a video file in the
// browser. Every motion repeats a whole number of times per LOOP seconds, so the
// recorded clip loops seamlessly.
import { t } from './i18n.js';
import { svgBlobUrl } from './sticker.js';

export const W = 1080;
export const H = 1920;
export const LOOP = 6;

const TAU = Math.PI * 2;
const S = 940;                 // sticker size on the canvas, px
const CX = W / 2;
const CY = 1000;
const K = S / 1000;            // sticker units (viewBox 0..1000) → canvas px
const DISC_R = 466 * K;
const HERO = { x: 0, y: -40 * K };   // approximate centre of the central figure
const BANNER = { x: (90 - 500) * K, y: (690 - 500) * K, w: 820 * K, h: 160 * K, r: 30 * K };
const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", Arial, sans-serif';
const BAT = new Path2D(
  'M0,-6 C4,-16 8,-20 10,-26 L14,-14 C24,-24 40,-26 54,-16 C46,-12 42,-4 44,6 ' +
  'C36,0 28,2 24,10 C18,4 10,6 6,14 L0,20 L-6,14 C-10,6 -18,4 -24,10 ' +
  'C-28,2 -36,0 -44,6 C-42,-4 -46,-12 -54,-16 C-40,-26 -24,-24 -14,-14 ' +
  'L-10,-26 C-8,-20 -4,-16 0,-6 Z');

// Deterministic randomness so every render of the same sticker looks the same.
function rng(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let x = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

const wave = (time, perLoop, phase = 0) => Math.sin(TAU * (time / LOOP) * perLoop + phase);

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(t('err.render')));
    img.src = url;
  });
}

/** Rasterise one SVG layer once, so each frame only blits a bitmap. */
async function rasterise(svgText) {
  const url = svgBlobUrl(svgText);
  try {
    const img = await loadImage(url);
    const c = document.createElement('canvas');
    c.width = S;
    c.height = S;
    const ctx = c.getContext('2d');
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, 0, 0, S, S);
    return c;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function buildScene() {
  const r = rng(2026);
  const stars = Array.from({ length: 90 }, () => ({
    x: r() * W, y: r() * H * 0.92, size: 1 + r() * 2.6, speed: 1 + Math.floor(r() * 3), phase: r() * TAU,
  }));
  const sparkles = Array.from({ length: 14 }, () => {
    const a = r() * TAU;
    const d = Math.sqrt(r()) * DISC_R * 0.85;
    return { x: Math.cos(a) * d, y: Math.sin(a) * d - 60 * K, size: 10 + r() * 16, speed: 1 + Math.floor(r() * 2), phase: r() };
  });
  // Bats cross the frame a whole number of times per loop; some fly behind the sticker.
  const bats = [
    { y: 420, amp: 40, s: 1.3, laps: 1, off: 0.05, dir: 1, front: false },
    { y: 560, amp: 30, s: 0.8, laps: 2, off: 0.55, dir: -1, front: false },
    { y: 1480, amp: 50, s: 1.1, laps: 1, off: 0.6, dir: -1, front: true },
    { y: 330, amp: 25, s: 0.7, laps: 2, off: 0.3, dir: 1, front: false },
    { y: 1600, amp: 35, s: 1.6, laps: 1, off: 0.15, dir: 1, front: true },
  ];
  return { stars, sparkles, bats };
}

function roundRect(ctx, x, y, w, h, rad) {
  ctx.beginPath();
  ctx.moveTo(x + rad, y);
  ctx.arcTo(x + w, y, x + w, y + h, rad);
  ctx.arcTo(x + w, y + h, x, y + h, rad);
  ctx.arcTo(x, y + h, x, y, rad);
  ctx.arcTo(x, y, x + w, y, rad);
  ctx.closePath();
}

function drawBat(ctx, bat, time) {
  const p = ((time / LOOP) * bat.laps + bat.off) % 1;
  const x = bat.dir > 0 ? -160 + p * (W + 320) : W + 160 - p * (W + 320);
  const y = bat.y + Math.sin(p * TAU * 2) * bat.amp;
  const flap = 0.45 + 0.55 * Math.abs(wave(time, 12));
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(bat.s * 1.6 * bat.dir, bat.s * 1.6 * flap);
  ctx.fillStyle = '#0B0414';
  ctx.strokeStyle = 'rgba(255, 140, 40, 0.45)';
  ctx.lineWidth = 1.5 / bat.s;
  ctx.fill(BAT);
  ctx.stroke(BAT);
  ctx.restore();
}

function drawSparkle(ctx, x, y, size, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.translate(x, y);
  ctx.fillStyle = '#FFF4C2';
  ctx.beginPath();
  for (let i = 0; i < 8; i++) {
    const rad = i % 2 === 0 ? size : size * 0.22;
    const a = (i / 8) * TAU - Math.PI / 2;
    ctx.lineTo(Math.cos(a) * rad, Math.sin(a) * rad);
  }
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawBackdrop(ctx, scene, time) {
  const sky = ctx.createLinearGradient(0, 0, 0, H);
  sky.addColorStop(0, '#12051F');
  sky.addColorStop(0.45, '#3A1460');
  sky.addColorStop(1, '#0E0418');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, H);

  // Moon with a slowly breathing glow.
  const glow = 0.5 + 0.5 * wave(time, 1);
  const halo = ctx.createRadialGradient(880, 300, 60, 880, 300, 330);
  halo.addColorStop(0, `rgba(255, 220, 150, ${0.35 + 0.15 * glow})`);
  halo.addColorStop(1, 'rgba(255, 220, 150, 0)');
  ctx.fillStyle = halo;
  ctx.fillRect(500, 0, W - 500, 700);
  ctx.fillStyle = '#FFF1C9';
  ctx.beginPath();
  ctx.arc(880, 300, 105, 0, TAU);
  ctx.fill();

  for (const s of scene.stars) {
    ctx.globalAlpha = 0.25 + 0.75 * (0.5 + 0.5 * wave(time, s.speed, s.phase));
    ctx.fillStyle = '#FFF6DA';
    ctx.beginPath();
    ctx.arc(s.x, s.y, s.size, 0, TAU);
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  // Drifting fog along the bottom.
  for (let i = 0; i < 3; i++) {
    const fx = W / 2 + wave(time, 1, i * 2) * 220;
    const fog = ctx.createRadialGradient(fx, H - 120 + i * 30, 40, fx, H - 120 + i * 30, 620);
    fog.addColorStop(0, 'rgba(160, 110, 220, 0.28)');
    fog.addColorStop(1, 'rgba(160, 110, 220, 0)');
    ctx.fillStyle = fog;
    ctx.fillRect(0, H - 760, W, 760);
  }
}

function drawTitle(ctx, time, labels) {
  const pulse = 0.5 + 0.5 * wave(time, 2);
  ctx.save();
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = `900 100px ${FONT}`;
  ctx.shadowColor = `rgba(255, 122, 26, ${0.55 + 0.35 * pulse})`;
  ctx.shadowBlur = 30 + 25 * pulse;
  const g = ctx.createLinearGradient(0, 160, 0, 260);
  g.addColorStop(0, '#FFD23F');
  g.addColorStop(1, '#FF7A1A');
  ctx.fillStyle = g;
  ctx.fillText(labels.title, W / 2, 215, W - 140);
  ctx.shadowBlur = 0;
  ctx.font = `800 54px ${FONT}`;
  ctx.fillStyle = '#FFFFFF';
  ctx.fillText(labels.caption, W / 2, 1620, W - 120);
  ctx.font = `800 42px ${FONT}`;
  ctx.fillStyle = '#FFD23F';
  ctx.fillText(labels.footer, W / 2, 1745, W - 120);
  ctx.restore();
}

function drawSticker(ctx, layers, scene, time) {
  const bob = wave(time, 2) * 12;
  const tilt = wave(time, 1) * 0.025;
  ctx.save();
  ctx.translate(CX, CY + bob);
  ctx.rotate(tilt);
  ctx.drawImage(layers.base, -S / 2, -S / 2);

  ctx.save();
  ctx.beginPath();
  ctx.arc(0, 0, DISC_R, 0, TAU);
  ctx.clip();
  // Pulsing glow behind the central figure.
  const pulse = 0.5 + 0.5 * wave(time, 3);
  const glow = ctx.createRadialGradient(HERO.x, HERO.y, 20, HERO.x, HERO.y, 360 * K);
  glow.addColorStop(0, `rgba(255, 170, 60, ${0.25 + 0.3 * pulse})`);
  glow.addColorStop(1, 'rgba(255, 170, 60, 0)');
  ctx.globalCompositeOperation = 'lighter';
  ctx.fillStyle = glow;
  ctx.fillRect(-S / 2, -S / 2, S, S);
  ctx.globalCompositeOperation = 'source-over';
  // The hero floats and breathes on its own rhythm.
  const float = wave(time, 3) * 16 * K;
  const breathe = 1 + 0.035 * wave(time, 3, Math.PI / 2);
  ctx.save();
  ctx.translate(HERO.x, HERO.y + float);
  ctx.scale(breathe, breathe);
  ctx.translate(-HERO.x, -HERO.y);
  ctx.drawImage(layers.hero, -S / 2, -S / 2);
  ctx.restore();
  ctx.globalCompositeOperation = 'lighter';
  for (const sp of scene.sparkles) {
    const a = Math.max(0, Math.sin(TAU * ((time / LOOP) * sp.speed + sp.phase)));
    if (a > 0.01) drawSparkle(ctx, sp.x, sp.y, sp.size * (0.6 + 0.4 * a), a ** 2);
  }
  ctx.restore();

  ctx.drawImage(layers.front, -S / 2, -S / 2);

  // A light sweep across the name banner every two seconds.
  const u = (time % 2) / 1.1;
  if (u < 1) {
    ctx.save();
    roundRect(ctx, BANNER.x, BANNER.y, BANNER.w, BANNER.h, BANNER.r);
    ctx.clip();
    const bx = BANNER.x - 200 + u * (BANNER.w + 400);
    const band = ctx.createLinearGradient(bx - 110, 0, bx + 110, 0);
    band.addColorStop(0, 'rgba(255,255,255,0)');
    band.addColorStop(0.5, 'rgba(255,255,255,0.55)');
    band.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.globalCompositeOperation = 'lighter';
    ctx.fillStyle = band;
    ctx.fillRect(BANNER.x, BANNER.y, BANNER.w, BANNER.h);
    ctx.restore();
  }
  ctx.restore();
}

/** Pick the best video format this browser can record (MP4 first, for Instagram). */
export function recordingFormat() {
  if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) return null;
  const options = [
    ['video/mp4;codecs=avc1.42E01E', 'mp4'], ['video/mp4', 'mp4'],
    ['video/webm;codecs=vp9', 'webm'], ['video/webm;codecs=vp8', 'webm'], ['video/webm', 'webm'],
  ];
  for (const [mime, ext] of options) if (MediaRecorder.isTypeSupported(mime)) return { mime, ext };
  return null;
}

/**
 * Build the animated story on `canvas` from the three SVG layers and start playing it.
 * Returns { stop(), record(onProgress) → Promise<{blob, ext}> }.
 */
export async function createStory(canvas, svgLayers, labels) {
  const [base, hero, front] = await Promise.all(
    [svgLayers.base, svgLayers.hero, svgLayers.front].map(rasterise));
  const layers = { base, hero, front };
  const scene = buildScene();
  const ctx = canvas.getContext('2d');
  canvas.width = W;
  canvas.height = H;
  let start = performance.now();
  let frame = 0;

  function draw(now) {
    const time = ((now - start) / 1000) % LOOP;
    drawBackdrop(ctx, scene, time);
    for (const b of scene.bats) if (!b.front) drawBat(ctx, b, time);
    drawSticker(ctx, layers, scene, time);
    for (const b of scene.bats) if (b.front) drawBat(ctx, b, time);
    drawTitle(ctx, time, labels);
    frame = requestAnimationFrame(draw);
  }
  frame = requestAnimationFrame(draw);

  return {
    stop() { cancelAnimationFrame(frame); },
    async record(onProgress) {
      const format = recordingFormat();
      if (!format) throw new Error(t('anim.unsupported'));
      const stream = canvas.captureStream(30);
      const recorder = new MediaRecorder(stream, { mimeType: format.mime, videoBitsPerSecond: 8_000_000 });
      const chunks = [];
      recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      const done = new Promise((resolve, reject) => {
        recorder.onstop = resolve;
        recorder.onerror = (e) => reject(e.error || new Error(t('anim.failed')));
      });
      start = performance.now();  // record exactly one loop from its first frame
      recorder.start(250);
      const tick = setInterval(() => onProgress && onProgress(Math.min(1, (performance.now() - start) / (LOOP * 1000))), 200);
      await new Promise((r) => setTimeout(r, LOOP * 1000 + 120));
      recorder.stop();
      await done;
      clearInterval(tick);
      stream.getTracks().forEach((track) => track.stop());
      const blob = new Blob(chunks, { type: format.mime.split(';')[0] });
      if (!blob.size) throw new Error(t('anim.failed'));
      return { blob, ext: format.ext };
    },
  };
}
