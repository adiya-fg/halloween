// Client-side finishing of server-rendered sticker SVGs:
//  1. exact text fitting (measured with the fonts actually available), and
//  2. rasterisation to a high-resolution PNG via <canvas>.
import { t } from './i18n.js';

export const PNG_SIZE = 3000;

/** Measure each name line and compress it if it would overflow the banner. */
export function fitSvgText(svgText) {
  const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');
  if (doc.querySelector('parsererror')) throw new Error(t('err.svg'));
  const svg = document.importNode(doc.documentElement, true);
  const holder = document.createElement('div');
  holder.setAttribute('aria-hidden', 'true');
  holder.className = 'sr-only';
  holder.append(svg);
  document.body.append(holder);
  try {
    for (const node of svg.querySelectorAll('text[data-fit-max]')) {
      const max = parseFloat(node.getAttribute('data-fit-max'));
      if (node.hasAttribute('textLength')) continue;
      const w = node.getComputedTextLength();
      if (w > max) {
        node.setAttribute('textLength', String(max));
        node.setAttribute('lengthAdjust', 'spacingAndGlyphs');
      }
    }
    return new XMLSerializer().serializeToString(svg);
  } finally {
    holder.remove();
  }
}

export function svgBlobUrl(svgText) {
  return URL.createObjectURL(new Blob([svgText], { type: 'image/svg+xml' }));
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(t('err.render')));
    img.src = url;
  });
}

/** Rasterise an SVG string to a PNG Blob of size×size pixels. */
export async function svgToPng(svgText, size = PNG_SIZE) {
  const url = svgBlobUrl(svgText);
  try {
    const img = await loadImage(url);
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, 0, 0, size, size);
    return await new Promise((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error(t('err.png')))), 'image/png'));
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
