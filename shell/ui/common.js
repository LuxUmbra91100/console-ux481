/* Console UX481 — code commun : pont avec le shell Python, icônes, glyphes,
   sons d'interface, navigation spatiale et clavier virtuel. */
'use strict';

/* ------------------------------------------------------------------ Pont ---- */
const Shell = {
  _id: 0, _pending: new Map(), _handlers: {},
  native: !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.shell),
  call(cmd, args = {}) {
    if (!this.native) return window.MockShell ? MockShell.call(cmd, args) : Promise.resolve(null);
    return new Promise((resolve, reject) => {
      const id = ++this._id;
      this._pending.set(id, { resolve, reject });
      window.webkit.messageHandlers.shell.postMessage(JSON.stringify({ id, cmd, args }));
      setTimeout(() => { if (this._pending.delete(id)) reject(new Error('délai dépassé : ' + cmd)); }, 90000);
    });
  },
  send(cmd, args = {}) { this.call(cmd, args).catch(e => console.warn(cmd, e)); },
  on(event, fn) { (this._handlers[event] = this._handlers[event] || []).push(fn); },
  _receive(msg) {
    const p = this._pending.get(msg.id); if (!p) return;
    this._pending.delete(msg.id);
    msg.ok ? p.resolve(msg.result) : p.reject(new Error(msg.error));
  },
  _emit(event, data) { (this._handlers[event] || []).forEach(fn => { try { fn(data); } catch (e) { console.error(event, e); } }); },
};
window.Shell = Shell;

/* --------------------------------------------------------------- Utilitaires */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// Chemin local → URL : chaque morceau encodé (« # », « ? », « % » ou « & » dans un nom de jeu ne cassent rien).
const fileUrl = (p) => p ? (p.startsWith('file:') || p.startsWith('data:') || p.startsWith('http') ? p : 'file://' + p.split('/').map(encodeURIComponent).join('/')) : '';
const h = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };

/* ------------------------------------------------------------------ Icônes --- */
const ICONS = {
  battery: '<rect x="2.5" y="7" width="17" height="10" rx="2.2"/><path d="M21.5 10.5v3"/><path d="M5.5 10v4M8.5 10v4"/>',
  pulse: '<path d="M2.5 12h4l2.5-6 4 12 2.5-6h6"/>',
  palette: '<path d="M12 2.5a9.5 9.5 0 1 0 0 19c1.3 0 2-.8 2-1.8 0-1.4-1.2-1.9-1.2-3.2 0-1 .8-1.8 1.9-1.8H17a4.5 4.5 0 0 0 4.5-4.5C21.5 6 17.2 2.5 12 2.5z"/><circle cx="7.5" cy="11" r="1.2"/><circle cx="10" cy="7" r="1.2"/><circle cx="14.5" cy="7" r="1.2"/>',
  thermo: '<path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z"/><path d="M12 9v7"/>',
  disk: '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M7 15h.01M10.5 15h6"/>',
  gamepad: '<path d="M7.5 9.5v4M5.5 11.5h4"/><path d="M15.5 10.5h.01M18 12.5h.01"/><path d="M7.2 5.5h9.6a4 4 0 0 1 3.94 3.3l1.04 5.9a2.9 2.9 0 0 1-5.1 2.3L15.3 15.5H8.7l-1.4 1.5a2.9 2.9 0 0 1-5.1-2.3l1.04-5.9A4 4 0 0 1 7.2 5.5z"/>',
  stream: '<rect x="2.5" y="3.5" width="19" height="13" rx="2.2"/><path d="M8.5 20.5h7M12 16.5v4"/><path d="M10.2 7.6l4.4 2.4-4.4 2.4z"/>',
  globe: '<circle cx="12" cy="12" r="9.5"/><path d="M2.5 12h19M12 2.5c2.6 2.7 3.9 5.9 3.9 9.5s-1.3 6.8-3.9 9.5M12 2.5C9.4 5.2 8.1 8.4 8.1 12s1.3 6.8 3.9 9.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  settings: '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17" r="2"/>',
  power: '<path d="M12 3v9"/><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/>',
  moon: '<path d="M20.5 13.3A8.5 8.5 0 1 1 10.7 3.5a6.6 6.6 0 0 0 9.8 9.8z"/>',
  wifi: '<path d="M4.9 12.3a10 10 0 0 1 14.2 0M1.8 9.1a14.5 14.5 0 0 1 20.4 0M8.1 15.5a5.5 5.5 0 0 1 7.8 0"/><circle cx="12" cy="19" r=".9" fill="currentColor"/>',
  wifiOff: '<path d="M3 3l18 18M8.1 15.5a5.5 5.5 0 0 1 7.8 0M4.9 12.3a10 10 0 0 1 4-2.4M14.6 9.6a10 10 0 0 1 4.5 2.7"/><circle cx="12" cy="19" r=".9" fill="currentColor"/>',
  ethernet: '<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M8 7.5V4.5h8v3M8.5 13v2.5M12 13v2.5M15.5 13v2.5"/>',
  bluetooth: '<path d="M7 7l10 10-5 4.5V2.5L17 7 7 17"/>',
  restart: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 3.5v5h5"/>',
  home: '<path d="M3.5 10.5L12 3.5l8.5 7V19a1.5 1.5 0 0 1-1.5 1.5h-4v-6h-6v6H5A1.5 1.5 0 0 1 3.5 19z"/>',
  close: '<path d="M18 6L6 18M6 6l12 12"/>',
  check: '<path d="M20 6.5L9.5 17 4 11.5"/>',
  pin: '<path d="M12 16.5V22"/><path d="M8.5 3h7M9.5 3v6.5L6.5 13v3.5h11V13l-3-3.5V3"/>',
  keyboard: '<rect x="2.5" y="5.5" width="19" height="13" rx="2.2"/><path d="M6.5 9.5h.01M10 9.5h.01M14 9.5h.01M17.5 9.5h.01M6.5 13h.01M17.5 13h.01M10 13h4M8 15.8h8"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20.5 20.5l-4.6-4.6"/>',
  tv: '<rect x="2.5" y="7.5" width="19" height="13" rx="2.2"/><path d="M16.5 3l-4.5 4.5L7.5 3"/>',
  pointer: '<path d="M5 3.5l6.7 16.3 2.4-6.8 6.8-2.4z"/>',
  volume: '<path d="M11 5.5L6.5 9H3v6h3.5l4.5 3.5z"/><path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.5 6a8.5 8.5 0 0 1 0 12"/>',
  volumeMute: '<path d="M11 5.5L6.5 9H3v6h3.5l4.5 3.5z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
  camera: '<path d="M3.5 8a1.5 1.5 0 0 1 1.5-1.5h2.7l1.6-2.5h5.4l1.6 2.5H19A1.5 1.5 0 0 1 20.5 8v10.5A1.5 1.5 0 0 1 19 20H5a1.5 1.5 0 0 1-1.5-1.5z"/><circle cx="12" cy="13" r="3.6"/>',
  save: '<path d="M5 3.5h11l3.5 3.5v12A1.5 1.5 0 0 1 18 20.5H6A1.5 1.5 0 0 1 4.5 19V5A1.5 1.5 0 0 1 6 3.5z"/><path d="M8 3.5v5h7v-5M8 20.5v-6h8v6"/>',
  load: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 3.5v5h5"/><path d="M12 7.5V12l3 2"/>',
  tabs: '<rect x="2.5" y="6.5" width="19" height="14" rx="2"/><path d="M6.5 6.5v-3h7v3"/>',
  trash: '<path d="M4 6.5h16M9 6.5V4h6v2.5M6.5 6.5l1 14h9l1-14"/>',
  edit: '<path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17z"/><path d="M14.5 7.5l3 3"/>',
  move: '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M3 12h18"/>',
  info: '<circle cx="12" cy="12" r="9.5"/><path d="M12 16.5v-5M12 8h.01"/>',
  warning: '<path d="M10.3 4.2L2.2 18a2 2 0 0 0 1.7 3h16.2a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4M12 17.2h.01"/>',
  library: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/>',
  display: '<rect x="2.5" y="4" width="19" height="13" rx="2"/><path d="M8.5 20.5h7"/>',
  chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 2.5V6M14.5 2.5V6M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/>',
  link: '<path d="M10 13.5a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10.5a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V7a3.5 3.5 0 0 1 7 0v3.5"/>',
  play: '<path d="M7.5 4.5l12 7.5-12 7.5z" fill="currentColor"/>',
  folder: '<path d="M3.5 7a2 2 0 0 1 2-2h3.8l2 2.2H18.5a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  sparkle: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>',
  back: '<path d="M10 6.5L4.5 12l5.5 5.5M5 12h14.5"/>',
  chevron: '<path d="M9.5 6l6 6-6 6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
};
function icon(name, cls = '') {
  return `<span class="icon ${cls}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg></span>`;
}

/* ----------------------------------------------------------------- Glyphes --- */
const Pad = { kind: 'xbox' };
function glyph(btn) {
  const ps = Pad.kind === 'playstation';
  const face = { a: ps ? '✕' : 'A', b: ps ? '○' : 'B', x: ps ? '□' : 'X', y: ps ? '△' : 'Y' };
  if (face[btn]) return `<span class="glyph round ${btn}${ps ? ' ps' : ''}">${face[btn]}</span>`;
  const sh = { lb: ps ? 'L1' : 'LB', rb: ps ? 'R1' : 'RB', lt: ps ? 'L2' : 'LT', rt: ps ? 'R2' : 'RT', ls: 'L3', rs: 'R3' };
  if (sh[btn]) return `<span class="glyph shoulder">${sh[btn]}</span>`;
  if (btn === 'start') return `<span class="glyph round"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 8h12M6 12h12M6 16h12"/></svg></span>`;
  if (btn === 'back') return `<span class="glyph round"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="4" y="6" width="10" height="10" rx="2"/><rect x="10" y="9" width="10" height="10" rx="2"/></svg></span>`;
  if (btn === 'guide') return `<span class="glyph round"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><circle cx="12" cy="12" r="7.5"/><path d="M8.6 8.6l6.8 6.8M15.4 8.6l-6.8 6.8"/></svg></span>`;
  if (btn === 'dpad') return `<span class="glyph round"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M9.5 3h5v6.5H21v5h-6.5V21h-5v-6.5H3v-5h6.5z"/></svg></span>`;
  return `<span class="glyph">${esc(btn)}</span>`;
}
function hints(list) {
  return list.filter(Boolean).map(([btn, label]) => `<span class="hint">${glyph(btn)}${esc(label)}</span>`).join('');
}

/* ------------------------------------------------------------------- Sons ---- */
// Sons de l'interface. Le contexte audio reste actif tant qu'on s'en sert (mise en sommeil après une
// minute de silence ou quand l'accueil est caché) : le relancer à chaque appui retardait le son de
// plusieurs dizaines de millisecondes, et la sortie HDMI de la TV avalait souvent le premier.
const Sound = {
  enabled: true, ctx: null, idle: null,
  _ensure() {
    if (!this.enabled) return null;
    try {
      if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
      if (this.ctx.state === 'suspended') this.ctx.resume();
    } catch (e) { return null; }
    clearTimeout(this.idle);
    this.idle = setTimeout(() => this.sleep(), 60000);
    return this.ctx;
  },
  sleep() {
    clearTimeout(this.idle);
    try { if (this.ctx && this.ctx.state === 'running') this.ctx.suspend(); } catch (e) {}
  },
  _tone(freq, dur, type = 'sine', gain = 0.05, when = 0, slide = 0) {
    const ctx = this._ensure(); if (!ctx) return;
    const t = ctx.currentTime + when, o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(freq * slide, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + dur + 0.02);
  },
  move() { this._tone(1320, 0.045, 'triangle', 0.035); },
  select() { this._tone(880, 0.07, 'sine', 0.06); this._tone(1320, 0.09, 'sine', 0.05, 0.05); },
  back() { this._tone(700, 0.08, 'sine', 0.05, 0, 0.7); },
  bump() { this._tone(180, 0.07, 'square', 0.025); },
  launch() { this._tone(520, 0.25, 'sine', 0.05, 0, 2.2); this._tone(1040, 0.3, 'triangle', 0.025, 0.06, 1.6); },
  key() { this._tone(1700, 0.03, 'triangle', 0.025); },
  toast() { this._tone(988, 0.08, 'sine', 0.04); this._tone(1480, 0.12, 'sine', 0.035, 0.08); },
};

// N'écrit dans le DOM que si le contenu a changé : les mises à jour périodiques (état du PC, réseau…)
// ne reconstruisent plus des panneaux identiques.
function setHTML(el, html) { if (el && el._html !== html) { el._html = html; el.innerHTML = html; } }

/* ------------------------------------------------- Navigation spatiale ------ */
// Choisit l'élément le plus proche dans une direction parmi « candidates ».
function spatialNext(current, candidates, dir) {
  if (!current) return candidates[0] || null;
  const r = current.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  let best = null, bestScore = Infinity;
  for (const el of candidates) {
    if (el === current) continue;
    const q = el.getBoundingClientRect();
    if (!q.width && !q.height) continue;
    const x = q.left + q.width / 2, y = q.top + q.height / 2, dx = x - cx, dy = y - cy;
    let main, cross;
    if (dir === 'left') { if (q.right > r.left + 2 && dx >= -2) continue; main = -dx; cross = Math.abs(dy); }
    if (dir === 'right') { if (q.left < r.right - 2 && dx <= 2) continue; main = dx; cross = Math.abs(dy); }
    if (dir === 'up') { if (q.bottom > r.top + 2 && dy >= -2) continue; main = -dy; cross = Math.abs(dx); }
    if (dir === 'down') { if (q.top < r.bottom - 2 && dy <= 2) continue; main = dy; cross = Math.abs(dx); }
    if (main <= 0) continue;
    const score = main + cross * 2.2;
    if (score < bestScore) { bestScore = score; best = el; }
  }
  return best;
}

/* ------------------------------------------------------- Clavier virtuel ---- */
const OSK_LAYOUTS = {
  azerty: [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    ['a', 'z', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['q', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'm'],
    ['{shift}', 'w', 'x', 'c', 'v', 'b', 'n', 'é', 'è', '{bksp}'],
    ['{sym}', '{acc}', '@', ',', '{space}', '.', '-', '{enter}'],
  ],
  qwerty: [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', "'"],
    ['{shift}', 'z', 'x', 'c', 'v', 'b', 'n', 'm', '?', '{bksp}'],
    ['{sym}', '{acc}', '@', ',', '{space}', '.', '-', '{enter}'],
  ],
  sym: [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    ['@', '#', '€', '$', '%', '&', '*', '-', '+', '='],
    ['(', ')', '[', ']', '{', '}', '<', '>', '!', '?'],
    ['{abc}', '_', ';', ':', "'", '"', '/', '\\', '|', '{bksp}'],
    ['{abc}', '~', '^', '`', '{space}', '.', '°', '{enter}'],
  ],
  acc: [
    ['à', 'â', 'ä', 'æ', 'ç', 'é', 'è', 'ê', 'ë', 'î'],
    ['ï', 'ô', 'ö', 'œ', 'ù', 'û', 'ü', 'ÿ', 'ñ', 'ß'],
    ['«', '»', '…', '–', '’', '€', '£', '¿', '¡', '²'],
    ['{shift}', 'á', 'í', 'ó', 'ú', 'ã', 'õ', 'å', 'ø', '{bksp}'],
    ['{abc}', '{sym}', '@', ',', '{space}', '.', '-', '{enter}'],
  ],
};
const URL_ROW = ['{sym}', '{acc}', '/', ':', '{space}', '.', '.com', '.fr', '{enter}'];

class OSK {
  // opts: { layout: 'azerty'|'qwerty', onCommit(text, submit), onCancel() }
  constructor(root, opts) {
    this.root = root; this.opts = opts;
    this.text = ''; this.caret = 0; this.page = 'abc'; this.shift = false; this.caps = false;
    this.row = 1; this.col = 0; this.field = {}; this.reveal = false;
  }
  open(field = {}) {
    this.field = field; this.text = field.value || ''; this.caret = this.text.length;
    this.page = 'abc'; this.shift = false; this.caps = false; this.reveal = false;
    const firstUpper = !this.text && !['url', 'email', 'password'].includes(field.type) && field.inputmode !== 'url';
    this.shift = firstUpper && field.type !== 'search';
    this.row = 1; this.col = 0;
    this.render();
  }
  get isUrl() { return this.field.type === 'url' || this.field.inputmode === 'url'; }
  rows() {
    const layout = this.opts.layout === 'qwerty' ? 'qwerty' : 'azerty';
    let rows = this.page === 'sym' ? OSK_LAYOUTS.sym : this.page === 'acc' ? OSK_LAYOUTS.acc : OSK_LAYOUTS[layout];
    rows = rows.map(r => r.slice());
    if (this.isUrl && this.page === 'abc') rows[4] = URL_ROW.slice();
    return rows;
  }
  label(k) {
    const up = this.shift || this.caps;
    switch (k) {
      case '{shift}': return icon('back', '') .replace('class="icon ', 'class="icon shift-ic ');
      case '{bksp}': return '⌫';
      case '{space}': return 'espace';
      case '{enter}': return '↵';
      case '{sym}': return '?123';
      case '{abc}': return 'ABC';
      case '{acc}': return 'àé';
      default: return esc(up && k.length === 1 ? k.toUpperCase() : k);
    }
  }
  keyClass(k) {
    const w = { '{shift}': 'w15 mod', '{bksp}': 'w15 mod', '{space}': 'w5', '{enter}': 'w15 primary', '{sym}': 'w15 mod',
      '{abc}': 'w15 mod', '{acc}': 'mod', '.com': 'mod', '.fr': 'mod' }[k] || '';
    const on = (k === '{shift}' && (this.shift || this.caps)) ? ' on' : '';
    return w + on;
  }
  shown() {
    if (this.field.type === 'password' && !this.reveal) return '•'.repeat(this.text.length);
    return this.text;
  }
  render() {
    const rows = this.rows();
    this.row = Math.min(this.row, rows.length - 1);
    this.col = Math.min(this.col, rows[this.row].length - 1);
    const shown = this.shown();
    const before = esc(shown.slice(0, this.caret)), after = esc(shown.slice(this.caret));
    const ph = !shown ? `<span class="ph">${esc(this.field.placeholder || this.field.label || 'Saisis ton texte')}</span>` : '';
    this.root.innerHTML = `
      <div class="osk">
        <div class="osk-field">
          ${this.field.label ? `<span class="label">${esc(this.field.label)}</span>` : ''}
          <div class="osk-text">${before}<span class="caret"></span>${after}${ph}</div>
          ${this.field.type === 'password' ? `<span class="label">${glyph('rs')} ${this.reveal ? 'masquer' : 'afficher'}</span>` : ''}
        </div>
        <div class="osk-rows">${rows.map((r, ri) => `<div class="osk-row">${r.map((k, ci) =>
          `<div class="osk-key ${this.keyClass(k)}${ri === this.row && ci === this.col ? ' focus' : ''}" data-r="${ri}" data-c="${ci}">${this.label(k)}</div>`).join('')}</div>`).join('')}</div>
        <div class="hints osk-hints">${hints([['a', 'Taper'], ['b', 'Effacer'], ['x', 'Espace'], ['y', 'Majuscule'],
          ['lb', 'Curseur'], ['lt', 'Symboles'], ['start', 'Terminer'], ['rt', 'Envoyer'], ['back', 'Annuler']])}</div>
      </div>`;
    $$('.osk-key .shift-ic svg', this.root).forEach(s => { s.style.transform = 'rotate(90deg)'; });
  }
  insert(s) {
    const max = this.field.maxlength || 0;
    if (max && this.text.length + s.length > max) return Sound.bump();
    this.text = this.text.slice(0, this.caret) + s + this.text.slice(this.caret);
    this.caret += s.length;
    if (this.shift && !this.caps) this.shift = false;
  }
  press(k) {
    Sound.key();
    switch (k) {
      case '{shift}':
        if (this.shift && !this.caps) { this.caps = true; } else if (this.caps) { this.caps = false; this.shift = false; } else this.shift = true;
        break;
      case '{bksp}': this.backspace(); break;
      case '{space}': this.insert(' '); break;
      case '{enter}': return this.commit(true);
      case '{sym}': this.page = this.page === 'sym' ? 'abc' : 'sym'; break;
      case '{abc}': this.page = 'abc'; break;
      case '{acc}': this.page = this.page === 'acc' ? 'abc' : 'acc'; break;
      default: this.insert((this.shift || this.caps) && k.length === 1 ? k.toUpperCase() : k);
    }
    this.render();
    const el = $(`.osk-key[data-r="${this.row}"][data-c="${this.col}"]`, this.root);
    if (el) { el.classList.add('pressed'); setTimeout(() => el.classList.remove('pressed'), 90); }
  }
  backspace() {
    if (this.caret > 0) { this.text = this.text.slice(0, this.caret - 1) + this.text.slice(this.caret); this.caret--; }
  }
  commit(submit) {
    Sound.select();
    this.opts.onCommit && this.opts.onCommit(this.text, submit);
  }
  move(dir) {
    const rows = this.rows();
    if (dir === 'left' || dir === 'right') {
      const n = rows[this.row].length;
      this.col = (this.col + (dir === 'left' ? -1 : 1) + n) % n;
    } else {
      const cur = $(`.osk-key[data-r="${this.row}"][data-c="${this.col}"]`, this.root);
      const x = cur ? cur.getBoundingClientRect().left + cur.getBoundingClientRect().width / 2 : 0;
      this.row = (this.row + (dir === 'up' ? -1 : 1) + rows.length) % rows.length;
      let best = 0, bestD = Infinity;
      $$(`.osk-key[data-r="${this.row}"]`, this.root).forEach((el, i) => {
        const q = el.getBoundingClientRect(), d = Math.abs(q.left + q.width / 2 - x);
        if (d < bestD) { bestD = d; best = i; }
      });
      this.col = best;
    }
    Sound.move();
    this.render();
  }
  handle(btn) {
    switch (btn) {
      case 'up': case 'down': case 'left': case 'right': return this.move(btn);
      case 'a': return this.press(this.rows()[this.row][this.col]);
      case 'b': this.backspace(); Sound.key(); return this.render();
      case 'x': this.insert(' '); Sound.key(); return this.render();
      case 'y': return this.press('{shift}');
      case 'lb': this.caret = Math.max(0, this.caret - 1); return this.render();
      case 'rb': this.caret = Math.min(this.text.length, this.caret + 1); return this.render();
      case 'lt': this.page = this.page === 'sym' ? 'abc' : 'sym'; return this.render();
      case 'rs': this.reveal = !this.reveal; return this.render();
      case 'start': return this.commit(false);
      case 'rt': return this.commit(true);
      case 'back': Sound.back(); return this.opts.onCancel && this.opts.onCancel();
    }
  }
  handleKey(e) {
    // Clavier physique branché : saisie directe.
    if (e.key === 'Escape') { this.handle('back'); return true; }
    if (e.key === 'Enter') { this.commit(true); return true; }
    if (e.key === 'Backspace') { this.backspace(); this.render(); return true; }
    if (e.key === 'ArrowLeft' && e.ctrlKey) { this.handle('lb'); return true; }
    if (e.key === 'ArrowRight' && e.ctrlKey) { this.handle('rb'); return true; }
    if (e.key.length === 1 && !e.ctrlKey && !e.altKey) { this.insert(e.key); this.render(); return true; }
    return false;
  }
}

/* ---------------------------------------- Clavier physique → boutons manette */
function keyToButton(e) {
  const map = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Enter: 'a', ' ': 'a',
    Escape: 'b', Backspace: 'b', Tab: 'rb', F1: 'start', F2: 'back', Home: 'guide', PageUp: 'lb', PageDown: 'rb' };
  if (e.key === 'y' || e.key === 'Y') return 'y';
  if (e.key === 'x' || e.key === 'X') return 'x';
  return map[e.key] || null;
}

/* ------------------------------------------------- Horloge et formats ----- */
function clock(now = new Date()) {
  return now.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}
function dateLine(now = new Date()) {
  const s = now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function greeting(now = new Date()) {
  const hr = now.getHours();
  return hr < 5 ? 'Bonne nuit' : hr < 12 ? 'Bonjour' : hr < 18 ? 'Bon après-midi' : 'Bonsoir';
}
function batteryLabel(p) {
  if (p === 'wired') return 'filaire';
  return typeof p === 'number' ? `${p} %` : '';
}
function initials(s) {
  return String(s || '?').split(/[\s\-_:]+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase();
}
