// Shared helpers. All user-provided text is inserted with textContent (never innerHTML).
import { lang, locale, t } from './i18n.js';

export class ApiError extends Error {
  constructor(status, detail, errors) {
    super(detail || t('err.request', { status }));
    this.status = status;
    this.errors = errors || [];
  }
}

export async function api(path, { method = 'GET', body, csrf } = {}) {
  const headers = { Accept: 'application/json', 'Accept-Language': lang };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (csrf) headers['X-CSRF-Token'] = csrf;
  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      cache: 'no-store',
    });
  } catch (e) {
    throw new ApiError(0, t('err.network'));
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) throw new ApiError(res.status, data && data.detail, data && data.errors);
  return data;
}

/** Tiny DOM builder: h('p', {class: 'x'}, 'text', child) — strings become text nodes. */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function showAlert(container, kind, message) {
  container.replaceChildren(h('div', { class: `alert ${kind}`, role: kind === 'error' ? 'alert' : 'status' }, message));
  container.hidden = false;
}

export function clearAlert(container) {
  container.replaceChildren();
  container.hidden = true;
}

export function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  if (lang === 'mn') {  // browsers lack consistent mn-MN data; use YYYY.MM.DD HH:mm
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  return d.toLocaleString(locale);
}

export function storage(kind = 'local') {
  try {
    const s = kind === 'session' ? window.sessionStorage : window.localStorage;
    const probe = '__hw26__';
    s.setItem(probe, '1');
    s.removeItem(probe);
    return s;
  } catch (e) {
    return null;
  }
}
