import { lang, t } from './i18n.js';
import { api, h, showAlert, clearAlert, storage } from './common.js';

const form = document.getElementById('request-form');
const nameInput = document.getElementById('name');
const nameCount = document.getElementById('name-count');
const emailInput = document.getElementById('email');
const gallery = document.getElementById('gallery');
const errorBox = document.getElementById('form-error');
const submitBtn = document.getElementById('submit-btn');

const local = storage('local');
const session = storage('session');
let maxLen = 40;

// One idempotency key per page view: double clicks / retries cannot create duplicates.
const clientKey = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random())
  .replace(/[^A-Za-z0-9]/g, '').slice(0, 64).padEnd(16, '0');

function showResume() {
  const last = local && local.getItem('hw26:lastToken');
  if (last) {
    document.getElementById('resume-link').href = '/track#' + last;
    document.getElementById('resume').hidden = false;
  }
}

async function loadConfig() {
  try {
    const cfg = await api('/api/config');
    maxLen = cfg.name_max_length;
    document.getElementById('fee-amount').textContent = cfg.amount_display;
    for (const tpl of cfg.templates) {
      gallery.append(
        h('label', { class: 'design' },
          h('input', { type: 'radio', name: 'template', value: tpl.id, 'aria-label': `${t('tpl.' + tpl.id)}: ${t('tpl.' + tpl.id + '.d')}` }),
          h('span', { class: 'tile' },
            h('img', { src: `/api/templates/${encodeURIComponent(tpl.id)}/preview.svg?lang=${lang}`, alt: t('index.previewAlt', { name: t('tpl.' + tpl.id) }), loading: 'lazy', width: 240, height: 240 }),
            h('span', {}, t('tpl.' + tpl.id))))
      );
    }
  } catch (e) {
    showAlert(errorBox, 'error', t('index.errLoad'));
  }
}

function updateCount() {
  const len = [...nameInput.value.trim()].length;
  nameCount.textContent = len ? `${len}/${maxLen}` : '';
}

form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  clearAlert(errorBox);
  const name = nameInput.value.replace(/\s+/g, ' ').trim();
  if (!name) {
    showAlert(errorBox, 'error', t('index.errName'));
    nameInput.focus();
    return;
  }
  if ([...name].length > maxLen) {
    showAlert(errorBox, 'error', t('index.errNameLong', { n: maxLen }));
    nameInput.focus();
    return;
  }
  const picked = form.querySelector('input[name=template]:checked');
  submitBtn.disabled = true;
  submitBtn.textContent = t('index.submitting');
  try {
    const res = await api('/api/requests', {
      method: 'POST',
      body: {
        name,
        email: emailInput.value.trim() || null,
        template_id: picked ? picked.value : null,
        client_key: clientKey,
        website: document.getElementById('website').value,
      },
    });
    let token = res.tracking_token;
    if (token) {
      session && session.setItem('hw26:req:' + clientKey, token);
    } else {
      token = session && session.getItem('hw26:req:' + clientKey);
    }
    if (!token) {
      showAlert(errorBox, 'info', t('index.duplicate', { code: res.request_code }));
      return;
    }
    local && local.setItem('hw26:lastToken', token);
    window.location.assign('/track#' + token);
  } catch (e) {
    showAlert(errorBox, 'error', e.message);
    submitBtn.disabled = false;
    submitBtn.textContent = t('index.submit');
  }
});

nameInput.addEventListener('input', updateCount);
showResume();
loadConfig();
