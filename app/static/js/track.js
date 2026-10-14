import { lang, t } from './i18n.js';
import { api, h, showAlert, clearAlert, fmtTime, storage } from './common.js';
import { fitSvgText, svgBlobUrl, svgToPng, saveBlob } from './sticker.js';
import { LOOP, createStory, recordingFormat } from './animate.js';

// The tracking token lives in the URL fragment, which browsers never send to
// servers or leak via Referer headers.
const token = decodeURIComponent(window.location.hash.replace(/^#/, ''));
const $ = (id) => document.getElementById(id);
const local = storage('local');

let current = null;
let pollTimer = null;
let previewUrl = null;
let lastSvg = null;
let lastTemplate = null;
let pvUrl = null;
let story = null;
let storyFile = null;
const builtGalleries = new Set();
let quizContent = null;

const SECTIONS = ['payment-card', 'waiting-card', 'preview-card', 'rejected-card', 'expired-card', 'generator-card'];

function apiPath(suffix = '') {
  return `/api/requests/${encodeURIComponent(token)}${suffix}`;
}

function fail(message) {
  $('loading').hidden = true;
  showAlert($('page-error'), 'error', message);
}

async function load({ quiet = false } = {}) {
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(token)) {
    fail(t('track.errLink'));
    return;
  }
  try {
    const data = await api(apiPath());
    render(data);
  } catch (e) {
    if (e.status === 404) {
      if (local && local.getItem('hw26:lastToken') === token) local.removeItem('hw26:lastToken');
      fail(t('track.errNotFound'));
    } else if (!quiet) {
      fail(e.message);
    }
  }
}

function render(data) {
  current = data;
  $('loading').hidden = true;
  clearAlert($('page-error'));
  $('status-card').hidden = false;
  $('req-code').textContent = data.request_code;
  $('req-name').textContent = data.name;
  $('req-message').textContent = data.status_message;
  const badge = $('req-badge');
  badge.textContent = t('status.' + data.status);
  badge.className = `badge ${data.status}`;

  $('link-card').hidden = data.status === 'EXPIRED';
  $('private-link').value = window.location.href;

  for (const id of SECTIONS) $(id).hidden = true;

  if (data.payment) {
    const p = data.payment;
    $('payment-card').hidden = false;
    $('pay-bank').textContent = p.bank_name;
    $('pay-holder').textContent = p.account_holder;
    $('pay-number').textContent = p.account_number;
    $('pay-amount').textContent = p.amount_display;
    $('pay-ref').textContent = p.reference;
    $('pay-instructions').textContent = p.instructions;
    $('report-box').hidden = data.status !== 'PENDING_PAYMENT';
    if (data.status === 'PENDING_PAYMENT' && data.expires_at) {
      $('req-message').textContent = `${data.status_message} ${t('track.payBefore', { date: fmtTime(data.expires_at) })}`;
    }
  }
  if (data.status === 'PAYMENT_REPORTED') {
    $('waiting-card').hidden = false;
    $('wait-text').textContent = t('track.waitText', { date: fmtTime(data.payment_reported_at) });
  }
  if (data.status === 'REJECTED') {
    $('rejected-card').hidden = false;
    $('reject-reason').textContent = data.rejection_reason || '—';
    $('reject-steps').textContent = data.next_steps || '';
  }
  if (data.status === 'EXPIRED') $('expired-card').hidden = false;

  const live = ['PENDING_PAYMENT', 'PAYMENT_REPORTED', 'APPROVED'].includes(data.status);
  renderCharacter(data.character, live);
  for (const el of document.querySelectorAll('.char-options')) el.hidden = !data.character;

  // Free watermarked preview while the donation is not yet verified.
  if (data.status === 'PENDING_PAYMENT' || data.status === 'PAYMENT_REPORTED') {
    $('preview-card').hidden = false;
    buildGallery('pv-gallery', 'pv-template', data.template_id);
  }
  // Only the backend's authoritative status unlocks the generator.
  if (data.status === 'APPROVED' && data.can_generate) {
    $('generator-card').hidden = false;
    buildGallery('gen-gallery', 'gen-template', data.template_id);
  }

  clearTimeout(pollTimer);
  if (data.status === 'PAYMENT_REPORTED' || data.status === 'PENDING_PAYMENT') {
    const delay = data.status === 'PAYMENT_REPORTED' ? 30000 : 60000;
    pollTimer = setTimeout(() => load({ quiet: true }), delay);
  }
}

async function renderCharacter(character, live) {
  $('char-chip').hidden = !character;
  $('add-character').hidden = !!character || !live;
  if (!character) return;
  try {
    quizContent = quizContent || await api('/api/quiz');
    const info = quizContent.characters[character];
    $('char-img').src = info.image;
    $('char-name').textContent = `${info.name} ${info.emoji}`;
  } catch (e) { /* the chip is decorative; ignore */ }
}

function charOptions(card) {
  const box = $(card).querySelector('.char-options');
  return {
    with_character: !box.hidden && box.querySelector('.opt-character').checked,
    show_traits: box.querySelector('.opt-traits').checked,
  };
}

async function buildGallery(containerId, inputName, selected) {
  if (builtGalleries.has(containerId)) return;
  builtGalleries.add(containerId);
  const cfg = await api('/api/config');
  const chosen = selected || cfg.templates[0].id;
  for (const tpl of cfg.templates) {
    $(containerId).append(
      h('label', { class: 'design' },
        h('input', { type: 'radio', name: inputName, value: tpl.id, checked: tpl.id === chosen, 'aria-label': t('tpl.' + tpl.id) }),
        h('span', { class: 'tile' },
          h('img', { src: `/api/templates/${encodeURIComponent(tpl.id)}/preview.svg?lang=${lang}`, alt: '', loading: 'lazy', width: 240, height: 240 }),
          h('span', {}, t('tpl.' + tpl.id))))
    );
  }
}

$('refresh-btn').addEventListener('click', () => load());

$('copy-btn').addEventListener('click', async () => {
  const input = $('private-link');
  try {
    await navigator.clipboard.writeText(input.value);
    $('copy-btn').textContent = t('track.copied');
  } catch (e) {
    input.select();
    $('copy-btn').textContent = t('track.copyManual');
  }
  setTimeout(() => { $('copy-btn').textContent = t('track.copy'); }, 2500);
});

$('report-btn').addEventListener('click', async () => {
  const btn = $('report-btn');
  btn.disabled = true;
  btn.textContent = t('track.sending');
  try {
    const data = await api(apiPath('/report-payment'), { method: 'POST' });
    render(data);
    showAlert($('flash'), 'success', data.message);
  } catch (e) {
    showAlert($('flash'), 'error', e.message);
    await load({ quiet: true });
  } finally {
    btn.disabled = false;
    btn.textContent = t('track.report');
  }
});

async function showWatermarkedPreview() {
  const el = document.querySelector('input[name=pv-template]:checked');
  if (!el) return;
  const btn = $('pv-btn');
  btn.disabled = true;
  clearAlert($('pv-error'));
  try {
    const params = new URLSearchParams({
      template_id: el.value, transparent: String($('pv-transparent').checked),
      ...Object.fromEntries(Object.entries(charOptions('preview-card')).map(([k, v]) => [k, String(v)])),
    });
    const res = await api(apiPath('/preview') + '?' + params);
    if (pvUrl) URL.revokeObjectURL(pvUrl);
    pvUrl = svgBlobUrl(fitSvgText(res.svg));
    $('pv-img').src = pvUrl;
    $('pv-wrap').hidden = false;
  } catch (e) {
    showAlert($('pv-error'), 'error', e.message);
  } finally {
    btn.disabled = false;
  }
}

$('pv-btn').addEventListener('click', showWatermarkedPreview);
$('preview-card').addEventListener('change', () => { if (!$('pv-wrap').hidden) showWatermarkedPreview(); });

$('open-generator').addEventListener('click', () => {
  $('gen-intro').hidden = true;
  $('gen-body').hidden = false;
  const first = document.querySelector('input[name=gen-template]:checked') || document.querySelector('input[name=gen-template]');
  if (first) first.focus();
});

function selectedTemplate() {
  const el = document.querySelector('input[name=gen-template]:checked');
  return el ? el.value : null;
}

$('generate-btn').addEventListener('click', async () => {
  const tpl = selectedTemplate();
  if (!tpl) return showAlert($('gen-error'), 'error', t('track.errChoose'));
  const btn = $('generate-btn');
  btn.disabled = true;
  btn.textContent = t('track.brewing');
  clearAlert($('gen-error'));
  try {
    const res = await api(apiPath('/generate'), {
      method: 'POST', body: { template_id: tpl, transparent: $('transparent').checked, ...charOptions('generator-card') },
    });
    lastSvg = fitSvgText(res.svg);
    lastTemplate = tpl;
    resetStory();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = svgBlobUrl(lastSvg);
    $('preview-img').src = previewUrl;
    $('preview-wrap').hidden = false;
  } catch (e) {
    showAlert($('gen-error'), 'error', e.message);
    if (e.status === 403 || e.status === 410) load({ quiet: true });
  } finally {
    btn.disabled = false;
    btn.textContent = t('track.preview');
  }
});

async function fetchHighRes() {
  const opts = charOptions('generator-card');
  const params = new URLSearchParams({
    template_id: lastTemplate, transparent: String($('transparent').checked),
    with_character: String(opts.with_character), show_traits: String(opts.show_traits),
  });
  const res = await fetch(apiPath('/download') + '?' + params, {
    cache: 'no-store', credentials: 'same-origin', headers: { 'Accept-Language': document.documentElement.lang },
  });
  if (!res.ok) {
    let detail = t('track.errDownload');
    try { detail = (await res.json()).detail || detail; } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  return fitSvgText(await res.text());
}

function fileBase() {
  return `halloween-2026-${current.request_code}-${lastTemplate}`;
}

$('download-png').addEventListener('click', async () => {
  const btn = $('download-png');
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = t('track.rendering');
  clearAlert($('gen-error'));
  try {
    const svg = await fetchHighRes();
    const png = await svgToPng(svg);
    saveBlob(png, fileBase() + '.png');
  } catch (e) {
    showAlert($('gen-error'), 'error', e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
});

$('download-svg').addEventListener('click', async () => {
  try {
    const svg = await fetchHighRes();
    saveBlob(new Blob([svg], { type: 'image/svg+xml' }), fileBase() + '.svg');
  } catch (e) {
    showAlert($('gen-error'), 'error', e.message);
  }
});

// --- Living sticker: animated story video, built in the browser from approved layers.
// One tap records the 6-second loop with visible progress, then the finished video
// replaces the live canvas, so it is obvious when it is done.
let storyUrl = null;

function resetStory() {
  if (story) story.stop();
  story = null;
  storyFile = null;
  if (storyUrl) URL.revokeObjectURL(storyUrl);
  storyUrl = null;
  $('anim-wrap').hidden = true;
  $('anim-canvas').hidden = false;
  $('anim-video').hidden = true;
  $('anim-video').removeAttribute('src');
  $('anim-progress').hidden = true;
  $('anim-done').hidden = true;
  $('anim-share').hidden = true;
  clearAlert($('anim-error'));
}

function showProgress(fraction) {
  const left = Math.max(0, Math.ceil(LOOP * (1 - fraction)));
  $('anim-bar').value = Math.round(fraction * 100);
  $('anim-status').textContent = t('anim.recording', { sec: left });
}

$('anim-btn').addEventListener('click', async () => {
  if (!lastTemplate) return;
  const btn = $('anim-btn');
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = t('anim.making');
  resetStory();
  try {
    const res = await api(apiPath('/animate'), {
      method: 'POST', body: { template_id: lastTemplate, ...charOptions('generator-card') },
    });
    const layers = { ...res.layers, front: fitSvgText(res.layers.front) };
    $('anim-canvas').setAttribute('aria-label', t('anim.alt', { name: current.name || '' }));
    story = await createStory($('anim-canvas'), layers, {
      title: 'HALLOWEEN 2026', caption: t('anim.caption'), footer: '🎃 ' + window.location.host,
    });
    $('anim-wrap').hidden = false;
    $('anim-wrap').scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (!recordingFormat()) {
      // Live animation still plays; only saving is unavailable.
      showAlert($('anim-error'), 'error', t('anim.unsupported'));
      return;
    }
    $('anim-progress').hidden = false;
    showProgress(0);
    const { blob, ext } = await story.record(showProgress);
    story.stop();
    const name = `${fileBase()}-story.${ext}`;
    storyUrl = URL.createObjectURL(blob);
    storyFile = new File([blob], name, { type: blob.type });
    $('anim-download').href = storyUrl;
    $('anim-download').download = name;
    $('anim-canvas').hidden = true;
    $('anim-video').src = storyUrl;
    $('anim-video').hidden = false;
    $('anim-progress').hidden = true;
    $('anim-done').hidden = false;
    $('anim-share').hidden = !(navigator.canShare && navigator.canShare({ files: [storyFile] }));
  } catch (e) {
    $('anim-progress').hidden = true;
    showAlert($('anim-error'), 'error', e.message);
    if (e.status === 403 || e.status === 410) load({ quiet: true });
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
});

$('anim-share').addEventListener('click', async () => {
  if (!storyFile) return;
  try {
    await navigator.share({ files: [storyFile], title: t('anim.caption') });
  } catch (e) {
    if (e.name !== 'AbortError') showAlert($('anim-error'), 'error', e.message);
  }
});

window.addEventListener('hashchange', () => window.location.reload());
load();
