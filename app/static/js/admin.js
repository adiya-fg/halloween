import { t } from './i18n.js';
import { api, h, showAlert, clearAlert, fmtTime } from './common.js';

const $ = (id) => document.getElementById(id);
let csrf = null;
let statusFilter = 'ALL';
let active = null; // request currently in a dialog


async function call(path, opts = {}) {
  try {
    return await api(path, { ...opts, csrf });
  } catch (e) {
    if (e.status === 401) showLogin();
    throw e;
  }
}

// ------------------------------------------------------------------ auth
function showLogin() {
  csrf = null;
  $('dash-view').hidden = true;
  $('login-view').hidden = false;
  $('username').focus();
}

function showDashboard(me) {
  csrf = me.csrf_token;
  $('admin-name').textContent = me.username;
  $('login-view').hidden = true;
  $('dash-view').hidden = false;
  loadRequests();
}

$('login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  clearAlert($('login-error'));
  try {
    const me = await api('/api/admin/login', {
      method: 'POST',
      body: { username: $('username').value.trim(), password: $('password').value },
    });
    $('password').value = '';
    showDashboard(me);
  } catch (e) {
    showAlert($('login-error'), 'error', e.message);
  }
});

$('logout-btn').addEventListener('click', async () => {
  try { await call('/api/admin/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
  showLogin();
});

// ------------------------------------------------------------------ tabs
const tabs = ['requests', 'settings', 'stats', 'audit'];
for (const name of tabs) {
  $(`tab-${name}`).addEventListener('click', () => {
    for (const other of tabs) {
      $(`tab-${other}`).setAttribute('aria-selected', String(other === name));
      $(`panel-${other}`).hidden = other !== name;
    }
    clearAlert($('dash-flash'));
    if (name === 'requests') loadRequests();
    if (name === 'settings') loadSettings();
    if (name === 'stats') loadStats();
    if (name === 'audit') loadAudit();
  });
}

// ------------------------------------------------------------- requests
for (const btn of document.querySelectorAll('.filter')) {
  btn.addEventListener('click', () => {
    statusFilter = btn.dataset.status;
    for (const b of document.querySelectorAll('.filter')) b.setAttribute('aria-pressed', String(b === btn));
    loadRequests();
  });
}
$('reload-btn').addEventListener('click', () => loadRequests());

async function loadRequests() {
  const list = $('req-list');
  list.replaceChildren(h('p', { class: 'empty' }, t('admin.loading')));
  try {
    const data = await call(`/api/admin/requests?status=${encodeURIComponent(statusFilter)}`);
    list.replaceChildren();
    if (!data.items.length) {
      list.append(h('p', { class: 'empty' }, t('admin.empty')));
      return;
    }
    for (const r of data.items) list.append(renderRequest(r));
  } catch (e) {
    list.replaceChildren(h('div', { class: 'alert error' }, e.message));
  }
}

function row(label, value) {
  return [h('dt', {}, label), h('dd', {}, value === null || value === undefined || value === '' ? '—' : value)];
}

function renderRequest(r) {
  const actions = h('div', { class: 'btn-row' });
  if (r.status === 'PAYMENT_REPORTED') {
    actions.append(
      h('button', { type: 'button', class: 'btn small success', onclick: () => openApprove(r) }, t('admin.approve')),
      h('button', { type: 'button', class: 'btn small danger', onclick: () => openReject(r) }, t('admin.reject')),
    );
  }
  actions.append(h('button', { type: 'button', class: 'btn small secondary', onclick: () => openNote(r) }, t('admin.addNote')));

  const decided = r.status === 'APPROVED'
    ? t('admin.by', { time: fmtTime(r.approved_at), who: r.approved_by || '?' })
    : r.status === 'REJECTED' ? t('admin.by', { time: fmtTime(r.rejected_at), who: r.rejected_by || '?' }) : null;

  return h('article', { class: `req${r.status === 'PAYMENT_REPORTED' ? ' highlight' : ''}` },
    h('header', {},
      h('span', { class: 'code' }, r.request_code),
      h('span', { class: `badge ${r.status}` }, t('status.' + r.status))),
    h('dl', { class: 'details' },
      row(t('admin.name'), r.name),
      row(t('admin.email'), r.email),
      row(t('admin.design'), r.template_id ? t('tpl.' + r.template_id) : null),
      row(t('admin.character'), r.character ? characterName(r.character) : null),
      row(t('admin.amount'), r.amount_display),
      row(t('admin.created'), fmtTime(r.created_at)),
      row(t('admin.reported'), r.payment_reported_at ? fmtTime(r.payment_reported_at) : null),
      row(t('admin.decided'), decided),
      r.transaction_reference ? row(t('admin.txRef'), r.transaction_reference) : [],
      r.rejection_reason ? row(t('admin.rejReason'), r.rejection_reason) : []),
    r.admin_notes ? h('div', {}, h('span', { class: 'small muted' }, t('admin.notes')), h('pre', { class: 'notes' }, r.admin_notes)) : null,
    actions);
}

// --------------------------------------------------------------- dialogs
for (const btn of document.querySelectorAll('[data-close]')) {
  btn.addEventListener('click', () => btn.closest('dialog').close());
}

function openApprove(r) {
  active = r;
  $('ap-code').textContent = r.request_code;
  $('ap-name').textContent = r.name;
  $('ap-amount').textContent = r.amount_display;
  $('ap-ref').value = '';
  $('ap-confirm').checked = false;
  $('ap-submit').disabled = true;
  clearAlert($('ap-error'));
  $('approve-dialog').showModal();
}
$('ap-confirm').addEventListener('change', () => { $('ap-submit').disabled = !$('ap-confirm').checked; });

$('approve-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  if (!$('ap-confirm').checked) return;
  try {
    const r = await call(`/api/admin/requests/${active.id}/approve`, {
      method: 'POST', body: { confirm: true, transaction_reference: $('ap-ref').value.trim() || null },
    });
    $('approve-dialog').close();
    showAlert($('dash-flash'), 'success', t('admin.approved', { code: r.request_code }));
    loadRequests();
  } catch (e) {
    showAlert($('ap-error'), 'error', e.message);
  }
});

function openReject(r) {
  active = r;
  $('rj-code').textContent = r.request_code;
  $('rj-name').textContent = r.name;
  $('rj-reason').value = '';
  clearAlert($('rj-error'));
  $('reject-dialog').showModal();
}

$('reject-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const reason = $('rj-reason').value.trim();
  if (reason.length < 3) return showAlert($('rj-error'), 'error', t('admin.rjErr'));
  try {
    const r = await call(`/api/admin/requests/${active.id}/reject`, { method: 'POST', body: { reason } });
    $('reject-dialog').close();
    showAlert($('dash-flash'), 'success', t('admin.rejected', { code: r.request_code }));
    loadRequests();
  } catch (e) {
    showAlert($('rj-error'), 'error', e.message);
  }
});

function openNote(r) {
  active = r;
  $('nt-code').textContent = r.request_code;
  $('nt-text').value = '';
  clearAlert($('nt-error'));
  $('note-dialog').showModal();
}

$('note-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const note = $('nt-text').value.trim();
  if (!note) return showAlert($('nt-error'), 'error', t('admin.ntErr'));
  try {
    await call(`/api/admin/requests/${active.id}/notes`, { method: 'POST', body: { note } });
    $('note-dialog').close();
    loadRequests();
  } catch (e) {
    showAlert($('nt-error'), 'error', e.message);
  }
});

// -------------------------------------------------------------- settings
async function loadSettings() {
  clearAlert($('settings-msg'));
  try {
    const s = await call('/api/admin/settings');
    $('s-bank').value = s.bank_name;
    $('s-holder').value = s.account_holder;
    $('s-number').value = s.account_number;
    $('s-amount').value = s.amount;
    $('s-currency').value = s.currency;
    $('s-instructions').value = s.payment_instructions;
    $('s-instructions-mn').value = s.payment_instructions_mn;
    $('s-expiry').value = s.request_expiration_hours;
  } catch (e) {
    showAlert($('settings-msg'), 'error', e.message);
  }
}

$('settings-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  try {
    const s = await call('/api/admin/settings', {
      method: 'PATCH',
      body: {
        bank_name: $('s-bank').value,
        account_holder: $('s-holder').value,
        account_number: $('s-number').value,
        amount: $('s-amount').value,
        currency: $('s-currency').value,
        payment_instructions: $('s-instructions').value,
        payment_instructions_mn: $('s-instructions-mn').value,
        request_expiration_hours: parseInt($('s-expiry').value, 10),
      },
    });
    showAlert($('settings-msg'), 'success', t('admin.saved', { amount: s.amount_display }));
  } catch (e) {
    const msg = e.errors && e.errors.length ? e.errors.map((x) => `${x.field}: ${x.message}`).join(' · ') : e.message;
    showAlert($('settings-msg'), 'error', msg);
  }
});

// ----------------------------------------------------------------- stats
let quizContent = null;

function characterName(id) {
  const c = quizContent && quizContent.characters[id];
  return c ? `${c.name} ${c.emoji}` : id;
}

async function loadStats() {
  const body = $('stats-body');
  body.replaceChildren();
  try {
    const data = await call('/api/admin/stats');
    const events = ['quiz_started', 'quiz_completed',
      ...['WIZARD', 'VAMPIRE', 'FRIENDLY_GHOST', 'BLACK_CAT'].map((c) => 'character:' + c),
      'sticker_request_created', 'approved_download'];
    for (const ev of events) {
      const label = ev.startsWith('character:')
        ? t('ev.character', { name: characterName(ev.slice(10)) })
        : t('ev.' + ev);
      body.append(h('tr', {},
        h('td', {}, label),
        h('td', {}, String(data.today[ev] || 0)),
        h('td', {}, String(data.totals[ev] || 0))));
    }
  } catch (e) {
    body.append(h('tr', {}, h('td', { colspan: 3 }, e.message)));
  }
}

// ----------------------------------------------------------------- audit
async function loadAudit() {
  const body = $('audit-body');
  body.replaceChildren();
  try {
    const data = await call('/api/admin/audit?limit=200');
    for (const a of data.items) {
      body.append(h('tr', {},
        h('td', {}, fmtTime(a.created_at)),
        h('td', {}, a.actor),
        h('td', {}, a.action),
        h('td', {}, a.target || '—'),
        h('td', {}, a.details ? JSON.stringify(a.details) : '')));
    }
  } catch (e) {
    body.append(h('tr', {}, h('td', { colspan: 5 }, e.message)));
  }
}

// ------------------------------------------------------------------ init
(async () => {
  try { quizContent = await api('/api/quiz'); } catch (e) { /* names fall back to ids */ }
  try {
    showDashboard(await api('/api/admin/me'));
  } catch (e) {
    showLogin();
  }
})();
