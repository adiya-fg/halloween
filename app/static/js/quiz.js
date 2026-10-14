import { lang, t } from './i18n.js';
import { api, h, showAlert, clearAlert, storage } from './common.js';
import { createQuizState } from './quiz-state.js';
import { fitSvgText, svgBlobUrl } from './sticker.js';

const $ = (id) => document.getElementById(id);
const session = storage('session');
const local = storage('local');
const quiz = createQuizState(session);
const VIEWS = ['intro', 'question-view', 'result-view', 'builder-view'];
const NAME_KEY = 'hw26:quizName';

let content = null;      // { questions, characters } localized by the server
let existing = null;     // the visitor's live sticker request, if any
let galleryBuilt = false;
let previewUrl = null;
const clientKey = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random())
  .replace(/[^A-Za-z0-9]/g, '').slice(0, 64).padEnd(16, '0');

function show(view) {
  for (const v of VIEWS) $(v).hidden = v !== view;
  window.scrollTo(0, 0);
}

function trackStart() {
  api('/api/events', { method: 'POST', body: { event: 'quiz_started' } }).catch(() => {});
}

// ---------------------------------------------------------------- questions
function renderQuestion() {
  const i = quiz.index;
  const q = content.questions[i];
  $('progress-label').textContent = t('quiz.progress', { n: i + 1, total: quiz.total });
  $('progress-bar').style.width = `${((i + 1) / quiz.total) * 100}%`;
  $('question-text').textContent = q.text;
  $('pick-hint').hidden = true;
  const options = $('options');
  options.replaceChildren();
  for (const opt of q.options) {
    options.append(h('label', { class: 'quiz-option' },
      h('input', { type: 'radio', name: 'answer', value: opt.id, checked: quiz.current() === opt.id }),
      h('span', { class: 'quiz-letter', 'aria-hidden': 'true' }, opt.id),
      h('span', {}, opt.text)));
  }
  $('next-btn').textContent = quiz.isLast() ? t('quiz.finish') : t('quiz.next');
  show('question-view');
  const focusTarget = options.querySelector('input:checked') || options.querySelector('input');
  if (focusTarget) focusTarget.focus({ preventScroll: true });
}

$('options').addEventListener('change', (ev) => {
  if (ev.target.name === 'answer') {
    quiz.answer(ev.target.value);
    $('pick-hint').hidden = true;
  }
});

$('back-btn').addEventListener('click', () => {
  if (quiz.index === 0) return show('intro');
  quiz.back();
  renderQuestion();
});

$('question-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  if (!quiz.current()) {
    $('pick-hint').hidden = false;
    return;
  }
  if (!quiz.isLast()) {
    quiz.next();
    renderQuestion();
    return;
  }
  await finish();
});

async function finish() {
  const btn = $('next-btn');
  btn.disabled = true;
  btn.textContent = t('quiz.loading');
  try {
    // The server computes the character; the browser only remembers which one it was.
    const res = await api('/api/quiz/result', { method: 'POST', body: { answers: quiz.answers } });
    quiz.setResult(res.id);
    renderResult();
  } catch (e) {
    showAlert($('quiz-error'), 'error', e.message);
  } finally {
    btn.disabled = false;
  }
}

$('start-btn').addEventListener('click', () => {
  quiz.reset();
  trackStart();
  renderQuestion();
});

// ------------------------------------------------------------------- result
function character() {
  return content.characters[quiz.result];
}

function renderResult() {
  const c = character();
  $('result-img').src = c.image;
  $('result-img').alt = c.name;
  $('result-name').textContent = c.name;
  $('result-desc').textContent = c.description;
  $('result-traits').replaceChildren(...c.traits.map((tr) => h('li', {}, tr)));
  $('result-tagline').textContent = `“${c.tagline}”`;
  $('share-btn').textContent = navigator.share ? t('quiz.share') : t('quiz.copy');
  clearAlert($('share-status'));
  $('share-fallback').hidden = true;
  show('result-view');
}

$('retry-btn').addEventListener('click', () => {
  quiz.reset();
  trackStart();
  renderQuestion();
});

$('share-btn').addEventListener('click', async () => {
  const c = character();
  const text = t('quiz.shareText', { name: c.name.toUpperCase(), emoji: c.emoji });
  const url = `${window.location.origin}/quiz`;
  if (navigator.share) {
    try {
      await navigator.share({ title: t('quizCard.title'), text, url });
      return;
    } catch (e) {
      if (e && e.name === 'AbortError') return; // user closed the share sheet
    }
  }
  const full = `${text} ${url}`;
  try {
    await navigator.clipboard.writeText(full);
    showAlert($('share-status'), 'success', t('quiz.copied'));
  } catch (e) {
    // Old browsers / insecure contexts: let the user copy manually.
    $('share-text').value = full;
    $('share-fallback').hidden = false;
    showAlert($('share-status'), 'info', t('quiz.copyManual'));
    $('share-text').focus();
    $('share-text').select();
  }
});

// ------------------------------------------------------------------ builder
async function loadExisting() {
  const token = local && local.getItem('hw26:lastToken');
  if (!token) return null;
  try {
    const data = await api(`/api/requests/${encodeURIComponent(token)}`);
    return ['PENDING_PAYMENT', 'PAYMENT_REPORTED', 'APPROVED'].includes(data.status) ? { ...data, token } : null;
  } catch (e) {
    return null;
  }
}

async function buildGallery() {
  if (galleryBuilt) return;
  galleryBuilt = true;
  const cfg = await api('/api/config');
  cfg.templates.forEach((tpl, i) => {
    $('b-gallery').append(
      h('label', { class: 'design' },
        h('input', { type: 'radio', name: 'b-template', value: tpl.id, checked: i === 0, 'aria-label': t('tpl.' + tpl.id) }),
        h('span', { class: 'tile' },
          h('img', { src: `/api/templates/${encodeURIComponent(tpl.id)}/preview.svg?lang=${lang}`, alt: '', loading: 'lazy', width: 240, height: 240 }),
          h('span', {}, t('tpl.' + tpl.id)))));
  });
}

$('create-btn').addEventListener('click', async () => {
  show('builder-view');
  await buildGallery();
  existing = await loadExisting();
  const saved = session && session.getItem(NAME_KEY);
  if (!$('b-name').value) $('b-name').value = saved || (existing ? existing.name : '');
  $('b-name').focus();
});

$('builder-back').addEventListener('click', () => renderResult());

function selectedTemplate() {
  const el = document.querySelector('input[name=b-template]:checked');
  return el ? el.value : null;
}

async function preview() {
  clearAlert($('b-error'));
  const name = $('b-name').value.replace(/\s+/g, ' ').trim();
  if (!name) {
    showAlert($('b-error'), 'error', t('index.errName'));
    $('b-name').focus();
    return;
  }
  session && session.setItem(NAME_KEY, name);
  const btn = $('b-preview-btn');
  btn.disabled = true;
  btn.textContent = t('track.brewing');
  try {
    const res = await api('/api/quiz/preview', {
      method: 'POST',
      body: {
        answers: quiz.answers, name, template_id: selectedTemplate(),
        transparent: $('b-transparent').checked, show_traits: $('b-traits').checked,
      },
    });
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = svgBlobUrl(fitSvgText(res.svg));
    $('b-preview-img').src = previewUrl;
    $('b-preview-wrap').hidden = false;
    $('b-existing').hidden = !existing;
    $('b-request').hidden = !!existing;
    if (existing) {
      $('b-existing-note').textContent = t('quiz.existingNote', { code: existing.request_code, status: t('status.' + existing.status) });
      $('b-use-existing').textContent = t('quiz.useExisting', { code: existing.request_code });
    }
  } catch (e) {
    showAlert($('b-error'), 'error', e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = t('quiz.previewBtn');
  }
}

$('b-preview-btn').addEventListener('click', preview);
// Switching designs or options re-renders the preview without retaking the quiz.
for (const id of ['b-gallery', 'b-transparent', 'b-traits']) {
  $(id).addEventListener('change', () => { if (!$('b-preview-wrap').hidden) preview(); });
}

$('b-use-existing').addEventListener('click', async () => {
  try {
    await api(`/api/requests/${encodeURIComponent(existing.token)}/character`, {
      method: 'POST', body: { answers: quiz.answers },
    });
    window.location.assign('/track#' + existing.token);
  } catch (e) {
    showAlert($('b-error'), 'error', e.message);
  }
});

$('b-new-request').addEventListener('click', () => {
  existing = null;
  $('b-existing').hidden = true;
  $('b-request').hidden = false;
  $('b-request').focus();
});

$('b-request').addEventListener('click', async () => {
  const btn = $('b-request');
  btn.disabled = true;
  clearAlert($('b-error'));
  try {
    const res = await api('/api/requests', {
      method: 'POST',
      body: {
        name: $('b-name').value.replace(/\s+/g, ' ').trim(),
        template_id: selectedTemplate(),
        quiz_answers: quiz.answers,
        client_key: clientKey,
      },
    });
    let token = res.tracking_token;
    if (token) session && session.setItem('hw26:req:' + clientKey, token);
    else token = session && session.getItem('hw26:req:' + clientKey);
    if (!token) {
      showAlert($('b-error'), 'info', t('index.duplicate', { code: res.request_code }));
      return;
    }
    local && local.setItem('hw26:lastToken', token);
    window.location.assign('/track#' + token);
  } catch (e) {
    showAlert($('b-error'), 'error', e.message);
  } finally {
    btn.disabled = false;
  }
});

// --------------------------------------------------------------------- init
(async () => {
  try {
    content = await api('/api/quiz');
  } catch (e) {
    showAlert($('quiz-error'), 'error', t('quiz.errLoad'));
    return;
  }
  // A reload never recomputes or changes a stored result.
  if (quiz.result && quiz.isComplete() && content.characters[quiz.result]) renderResult();
  else if (quiz.answers.some((a) => a !== null)) renderQuestion();
  else show('intro');
})();
