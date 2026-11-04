/* Console UX481 — superposition au-dessus des applications */
'use strict';

const O = { mode: null, data: {}, settings: {}, i: 0, sub: null, volume: null, osk: null };
const root = $('#root');
const KIND = {
  games: { c: ['#ff7b1c', '#d3236f'], icon: 'gamepad' },
  moonlight: { c: ['#7a4cff', '#1f4fff'], icon: 'stream' },
  brave: { c: ['#ff6a3d', '#b6280f'], icon: 'globe' },
  game: { c: ['#334155', '#0f172a'], icon: 'gamepad' },
  esde: { c: ['#ff7b1c', '#d3236f'], icon: 'gamepad' },
};

Shell.on('open', ({ mode, data, settings }) => {
  O.mode = mode; O.data = data || {}; O.settings = settings || {}; O.i = 0; O.sub = null;
  Sound.enabled = O.settings.ui_sounds !== false;
  root.classList.remove('closing');
  if (mode === 'menu') { O.volume = (O.data.volume || {}).volume; Sound.select(); }
  render();
});
Shell.on('close', () => {
  root.classList.add('closing');
  setTimeout(() => { if (root.classList.contains('closing')) { root.innerHTML = ''; O.mode = null; root.classList.remove('closing'); } }, 150);
});
Shell.on('pad', ev => handle(ev.button));
Shell.on('splash-update', d => {
  const p = $('.splash-card p', root);
  if (p && d && d.sub) p.textContent = d.sub;
});
document.addEventListener('keydown', e => {
  if (O.mode === 'osk' && O.osk && O.osk.handleKey(e)) { e.preventDefault(); return; }
  const b = keyToButton(e); if (b) { e.preventDefault(); handle(b); }
});

function render() {
  if (O.mode === 'menu') return renderMenu();
  if (O.mode === 'osk') return renderOSK();
  if (O.mode === 'splash') return renderSplash();
  if (O.mode === 'sleep') { root.innerHTML = `<div class="curtain">${icon('moon')}</div>`; return; }
  root.innerHTML = '';
}

/* ------------------------------------------------------------ Lancement ---- */
function renderSplash() {
  const d = O.data, k = KIND[d.kind] || KIND.game;
  const art = d.art ? `<div class="splash-art poster"><img src="${esc(fileUrl(d.art))}" alt=""></div>`
    : d.icon ? `<div class="splash-art" style="--c1:${k.c[0]};--c2:${k.c[1]}"><img class="logo" src="${esc(fileUrl(d.icon))}" alt=""></div>`
      : `<div class="splash-art" style="--c1:${k.c[0]};--c2:${k.c[1]}">${icon(k.icon)}</div>`;
  root.innerHTML = `<div class="splash" style="--glow:${hexA(k.c[0], .3)}">
    ${d.art ? `<div class="splash-bg" style="background-image:url('${esc(fileUrl(d.art))}')"></div>` : ''}<div class="splash-glow"></div>
    <div class="splash-card">${art}<h1>${esc(d.title || '')}</h1>${d.sub ? `<p>${esc(d.sub)}</p>` : ''}<div class="bar"><i></i></div></div></div>`;
}
function hexA(hex, a) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || ''); if (!m) return `rgba(124,92,255,${a})`;
  const n = parseInt(m[1], 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}

/* ---------------------------------------------------------- Menu rapide ---- */
function menuItems() {
  const d = O.data, it = [];
  if (O.sub === 'tabs') {
    (d.tabs || []).forEach(t => it.push({ id: 'brave-tab', arg: t.id, icon: t.active ? 'check' : 'tabs', label: t.title, right: t.active ? 'actif' : '' }));
    it.push({ id: '__back', icon: 'back', label: 'Retour' });
    return it;
  }
  it.push({ id: 'resume', icon: 'play', label: 'Reprendre' });
  if (d.in_game) {
    if (d.can_save) it.push({ id: 'save-state', icon: 'save', label: 'Sauvegarder l\'état' });
    if (d.can_load) it.push({ id: 'load-state', icon: 'load', label: 'Charger l\'état' });
    if (d.emu_menu) it.push({ id: 'emu-menu', icon: 'settings', label: 'Menu de l\'émulateur' });
    it.push({ id: 'quit-game', icon: 'close', label: 'Quitter le jeu' });
  }
  if (d.is_moonlight) {
    if (d.can_pin) it.push({ id: 'type-pin', icon: 'lock', label: 'Saisir mon code PIN Windows', right: 'déverrouille le PC' });
    it.push({ id: 'quit-stream', icon: 'close', label: 'Arrêter le streaming', right: 'le jeu continue sur le PC' });
    it.push({ id: 'quit-host-app', icon: 'power', label: 'Fermer le jeu sur le PC' });
  }
  if (d.is_brave) {
    it.push({ id: 'brave-osk', icon: 'keyboard', label: 'Clavier virtuel' });
    it.push({ id: 'brave-url', icon: 'search', label: 'Adresse ou recherche' });
    if ((d.tabs || []).length) it.push({ id: '__tabs', icon: 'tabs', label: 'Onglets', right: String(d.tabs.length) });
    it.push({ id: 'brave-newtab', icon: 'plus', label: 'Nouvel onglet' });
    it.push({ id: 'brave-closetab', icon: 'close', label: 'Fermer l\'onglet' });
    it.push({ id: 'brave-reload', icon: 'restart', label: 'Recharger la page' });
    it.push({ id: 'brave-tv', icon: 'tv', label: 'Mode TV (croix + Ⓐ)', right: 'pour YouTube TV…' });
    it.push({ id: 'brave-pin', icon: 'pin', label: 'Épingler à l\'accueil' });
  }
  it.push({ sep: true });
  it.push({ id: '__volume', icon: O.volume === 0 ? 'volumeMute' : 'volume', label: 'Volume', volume: true });
  it.push({ id: 'screenshot', icon: 'camera', label: 'Capture d\'écran' });
  it.push({ id: 'home', icon: 'home', label: 'Accueil', right: 'l\'appli reste ouverte' });
  if (d.app) it.push({ id: 'close-app', icon: 'power', label: `Fermer ${d.app.title}`, danger: true });
  it.push({ id: 'standby', icon: 'moon', label: 'Mettre en veille' });
  return it;
}
function renderMenu() {
  const d = O.data, items = menuItems();
  const sel = items.filter(x => !x.sep);
  O.i = Math.max(0, Math.min(O.i, sel.length - 1));
  const k = KIND[(d.app || {}).kind] || KIND.game;
  document.documentElement.style.setProperty('--accent', k.c[0]);
  document.documentElement.style.setProperty('--accent-2', k.c[1]);
  let n = -1;
  const rows = items.map(x => {
    if (x.sep) return '<div class="qi sep"></div>';
    n++;
    const right = x.volume ? `<span class="meter"><i style="width:${O.volume ?? 0}%"></i></span>${O.volume ?? '–'} %`
      : x.right ? esc(x.right) : '';
    return `<div class="qi${x.danger ? ' danger' : ''}${n === O.i ? ' focus' : ''}">${icon(x.icon)}<span>${esc(x.label)}</span><span class="right">${right}</span></div>`;
  }).join('');
  const pads = (d.pads || []).map(p => `${icon('gamepad')} ${typeof p.power === 'number' ? p.power + ' %' : ''}`).join(' ');
  root.innerHTML = `<div class="dim"></div><div class="qm">
    <div class="qm-head"><div class="app-ic">${icon(k.icon)}</div>
      <div><h1>${esc(d.title || (d.app || {}).title || 'Console')}</h1><p>${O.sub === 'tabs' ? 'Onglets ouverts' : d.app ? 'En cours' : ''}</p></div>
      <div class="time num">${clock()}</div></div>
    <div class="qm-list"><div class="inner">${rows}</div></div>
    <div class="qm-foot"><span>${pads}</span><span class="hints">${hints([['a', 'OK'], ['b', 'Retour']])}</span></div></div>`;
  const list = $('.qm-list', root), focus = $('.qi.focus', root), inner = $('.inner', root);
  if (focus && list) {
    const over = focus.offsetTop + focus.offsetHeight - list.clientHeight + 16;
    inner.style.transform = `translateY(${-Math.max(0, over)}px)`;
  }
}
function menuHandle(b) {
  const sel = menuItems().filter(x => !x.sep), cur = sel[O.i];
  switch (b) {
    case 'up': case 'down': {
      const n = O.i + (b === 'up' ? -1 : 1);
      if (n < 0 || n >= sel.length) return Sound.bump();
      O.i = n; Sound.move(); return renderMenu();
    }
    case 'left': case 'right':
      if (cur && cur.volume) {
        const delta = b === 'left' ? -5 : 5;
        O.volume = Math.max(0, Math.min(100, (O.volume ?? 50) + delta)); renderMenu(); Sound.move();
        Shell.call('volume', { delta }).then(v => { if (v && v.volume != null) { O.volume = v.volume; renderMenu(); } });
      }
      return;
    case 'a': {
      if (!cur) return;
      if (cur.volume) return;
      Sound.select();
      if (cur.id === '__tabs') { O.sub = 'tabs'; O.i = 0; return renderMenu(); }
      if (cur.id === '__back') { O.sub = null; O.i = 0; return renderMenu(); }
      return Shell.send('menu-action', { action: cur.id, id: cur.arg });
    }
    case 'b':
      Sound.back();
      if (O.sub) { O.sub = null; O.i = 0; return renderMenu(); }
      return Shell.send('menu-action', { action: 'resume' });
    case 'start': Sound.back(); return Shell.send('menu-action', { action: 'resume' });
  }
}

/* -------------------------------------------------------- Clavier virtuel -- */
function renderOSK() {
  const f = O.data.field || {};
  const title = O.data.target === 'brave-url' ? 'Adresse ou recherche' : (f.label || (f.type === 'password' ? 'Mot de passe' : 'Saisie de texte'));
  root.innerHTML = `<div class="osk-dim"></div><div class="osk-panel"><div class="title">${icon(f.type === 'password' ? 'lock' : O.data.target === 'brave-url' ? 'search' : 'keyboard')}${esc(title)}${f.host ? `<small>${esc(f.host)}</small>` : ''}</div><div class="osk-host"></div></div>`;
  O.osk = new OSK($('.osk-host', root), {
    layout: O.settings.osk_layout || 'azerty',
    onCommit: (text, submit) => Shell.send('osk-commit', { text, submit }),
    onCancel: () => Shell.send('osk-cancel'),
  });
  O.osk.open(Object.assign({}, f, { label: '' }));
  if (f.selectAll) { O.osk.caret = O.osk.text.length; }
}

function handle(b) {
  if (O.mode === 'menu') return menuHandle(b);
  if (O.mode === 'osk' && O.osk) return O.osk.handle(b);
}
