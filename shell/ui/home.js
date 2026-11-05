/* Console UX481 — écran d'accueil */
'use strict';

const CORE = {
  running: { title: 'En cours', grad: ['#0ea5e9', '#1e3a8a'], icon: 'play' },
  moonlight: { title: 'Moonlight', grad: ['#7a4cff', '#1f4fff'], icon: 'stream' },
  games: { title: 'Jeux', grad: ['#ff7b1c', '#d3236f'], icon: 'gamepad' },
  brave: { title: 'Brave', grad: ['#ff6a3d', '#b6280f'], icon: 'globe' },
  add: { title: 'Ajouter un site', grad: ['#475569', '#1e293b'], icon: 'plus' },
};
const SYS_BUTTONS = [
  { id: 'pads', icon: 'gamepad', label: 'Manettes' },
  { id: 'net', icon: 'wifi', label: 'Réseau' },
  { id: 'settings', icon: 'settings', label: 'Réglages' },
  { id: 'power', icon: 'power', label: 'Veille / Arrêt' },
];

const A = {
  st: { tiles: [], apps: { running: [] }, pads: [], bt: {}, net: {}, moonlight: [], library: { systems: [], recent: [] },
    settings: {}, presets: [], sleep: {} },
  zone: 'row', ti: 0, si: 0, yi: 0, shelfMemo: {}, shelfItems: [], layers: [], moving: null,
  sig: {},
};

/* ------------------------------------------------------------- Couleurs ---- */
function hexToRgb(hex) {
  const m = String(hex || '').trim().match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!m) return null;
  let s = m[1]; if (s.length === 3) s = s.split('').map(c => c + c).join('');
  return [0, 2, 4].map(i => parseInt(s.slice(i, i + 2), 16));
}
const rgba = (hex, a) => { const c = hexToRgb(hex) || [124, 92, 255]; return `rgba(${c[0]},${c[1]},${c[2]},${a})`; };
function shade(hex, f) {
  const c = hexToRgb(hex) || [100, 100, 120];
  return '#' + c.map(v => Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f).toString(16).padStart(2, '0')).join('');
}
function hashColor(s) {
  let hsh = 0; for (const ch of String(s)) hsh = (hsh * 31 + ch.charCodeAt(0)) >>> 0;
  const hue = hsh % 360;
  return `hsl(${hue} 65% 45%)`;
}
function tileColors(t) {
  if (CORE[t.type]) return CORE[t.type].grad;
  const base = hexToRgb(t.color) ? t.color : null;
  if (!base) { const c = hashColor(t.title || t.url); return [c, c]; }
  return [shade(base, 0.08), shade(base, -0.45)];
}

/* --------------------------------------------------------------- Rendu ------ */
function tiles() {
  const known = new Set((A.st.tiles || []).map(t => t.id));
  const extra = ((A.st.apps || {}).running || []).filter(a => !known.has(a.id))
    .map(a => ({ id: a.id, type: 'running', title: a.title, running: true, art: (a.meta || {}).art }));
  return [...extra, ...(A.st.tiles || []), { id: '__add', type: 'add' }];
}
function isRunning(t) { return !!t.running; }

function renderTop() {
  const name = A.st.name || 'Nova';
  $('#avatar').textContent = initials(name).slice(0, 1) || 'N';
  $('#cname').textContent = name;
  $('#hello').textContent = greeting();
  const pads = A.st.pads || [];
  const gp = (A.st.bt && A.st.bt.gamepads) || [];
  const padHtml = pads.length
    ? pads.map((p, i) => {
      const bt = gp.find(g => g.connected && (g.name === p.joystick_name || g.name === p.name)) || (pads.length === 1 ? gp.find(g => g.connected) : null);
      const pct = bt && typeof bt.battery === 'number' ? bt.battery : (typeof p.power === 'number' ? p.power : null);
      const batt = pct == null ? '' : `<span class="batt${pct <= 20 ? ' low' : ''}"><i style="width:${Math.max(8, Math.min(100, pct)) * 0.85}%"></i></span>`;
      return `<span class="pill" title="${esc(p.name)}">${icon('gamepad')}${batt}</span>`;
    }).join('')
    : `<span class="pill dim">${icon('gamepad')}</span>`;
  const net = A.st.net || {};
  const netIcon = net.kind === 'ethernet' ? icon('ethernet') : net.connected ? icon('wifi') : icon('wifiOff');
  const now = new Date();
  setHTML($('#status'), `${padHtml}<span class="pill${net.connected ? '' : ' dim'}">${netIcon}</span>
    <div class="clock"><div class="time num">${clock(now)}</div><div class="date">${esc(dateLine(now))}</div></div>`);
}

function tileHtml(t, focused) {
  const core = CORE[t.type];
  const [c1, c2] = tileColors(t);
  const classes = ['tile', t.type === 'site' ? 'site' : '', t.type === 'add' ? 'add' : '', t.type === 'moonlight' ? 'hero' : '',
    focused ? 'focus' : '', A.moving === t.id ? 'moving' : ''].filter(Boolean).join(' ');
  let art;
  if (t.type === 'site') {
    art = t.icon ? `<img src="${esc(fileUrl(t.icon))}" alt="">` : `<span class="letter">${esc(initials(t.title).slice(0, 1))}</span>`;
  } else if (t.appIcon && t.type !== 'games') {
    art = `<img src="${esc(fileUrl(t.appIcon))}" alt="">`;
  } else {
    art = icon(core ? core.icon : 'globe');
  }
  const title = (t.type === 'site' || t.type === 'running') ? t.title : core.title;
  if (t.type === 'running' && t.art) art = `<img src="${esc(fileUrl(t.art))}" alt="" style="width:100%;height:100%;object-fit:cover;filter:none">`;
  const bg = t.type === 'add' ? '' : `background:linear-gradient(135deg, ${c1}, ${c2})`;
  let extra = '';
  if (isRunning(t)) extra += '<div class="badge"><i></i>EN COURS</div>';
  if (t.type === 'moonlight') {
    const hosts = A.st.moonlight || [];
    const on = hosts.some(h => h.online), busy = hosts.some(h => h.busy);
    if (hosts.length) extra += `<div class="dot ${busy ? 'busy' : on ? 'on' : ''}"></div>`;
  }
  return `<div class="${classes}" data-id="${esc(t.id)}" style="--glow:${rgba(c1.startsWith('#') ? c1 : '#7c5cff', .45)}">
    <div class="tile-bg" style="${bg}"></div><div class="tile-art">${art}</div>
    ${t.type === 'add' ? '' : `<div class="tile-label">${esc(title)}</div>`}${extra}</div>`;
}

function renderRow() {
  const list = tiles();
  A.ti = Math.max(0, Math.min(A.ti, list.length - 1));
  $('#row').innerHTML = list.map((t, i) => tileHtml(t, i === A.ti && A.zone === 'row' || i === A.ti)).join('');
  $$('#row .tile').forEach((el, i) => el.classList.toggle('focus', i === A.ti));
  scrollRow();
}
function scrollRow() {
  const els = $$('#row .tile'); const el = els[A.ti]; if (!el) return;
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
  const left = el.offsetLeft, right = left + el.offsetWidth, view = window.innerWidth - 8 * rem;
  const cur = A.rowShift || 0;
  let shift = cur;
  if (right - cur > view - 2 * rem) shift = right - view + 2 * rem;
  if (left - cur < 0) shift = Math.max(0, left - rem);
  A.rowShift = shift;
  $('#row').style.transform = `translateX(${-shift}px)`;
}

function focusedTile() { return tiles()[A.ti]; }

function captionFor(t) {
  const running = isRunning(t);
  const pre = running ? '<span class="live">● En cours</span> · ' : '';
  if (t.type === 'moonlight') {
    const hosts = A.st.moonlight || [];
    if (!hosts.length) return ['Moonlight', pre + 'Joue aux jeux de ton PC sur la TV — associe ton PC pour commencer'];
    const def = hosts.find(h => h.uuid === A.st.moonlight_default) || hosts[0];
    const target = (A.st.settings || {}).moonlight_tile_app || 'gui';
    const auth = ((A.st.pc_remote || {}).auth || []).includes(def.uuid);
    const state = def.online && def.sunshine === 'half' ? (auth ? 'Sunshine bloqué, relancé au lancement' : 'Sunshine bloqué')
      : def.busy && def.current ? `en jeu : ${esc(def.current)}` : def.online ? 'en ligne' : def.online === false ? (def.wol ? 'en veille, réveil automatique' : 'hors ligne') : '…';
    const what = target === 'gui' ? 'ouvre Moonlight' : `lance <b>${esc(target)}</b> sur ${esc(def.name)}`;
    return ['Moonlight', pre + `${glyph('a')} ${what} · ${state}`];
  }
  if (t.type === 'games') {
    const total = (A.st.library.systems || []).reduce((n, s) => n + (s.count || 0), 0);
    const names = (A.st.library.systems || []).filter(s => s.count).map(s => s.short).join(', ');
    return ['Jeux', pre + (total ? `${total} jeu${total > 1 ? 'x' : ''} · ${esc(names)}` : 'Bibliothèque d\'émulation — GBA, DS, 3DS, GameCube, Wii, PS1, PS2')];
  }
  if (t.type === 'brave') return ['Brave', pre + 'Navigateur web — stick gauche : pointeur, ⓧ : clavier'];
  if (t.type === 'add') return ['Ajouter un site', 'Épingle tes sites préférés sur l\'écran d\'accueil'];
  if (t.type === 'running') return [esc(t.title), '<span class="live">● En cours</span> · lancé depuis l\'accueil'];
  let host = ''; try { host = new URL(t.url).host.replace(/^www\./, ''); } catch (e) { host = t.url; }
  return [esc(t.title), pre + esc(host) + (t.control === 'tv' ? ' · mode TV' : '')];
}

function renderCaption() {
  const t = focusedTile(); if (!t) return;
  const [title, sub] = captionFor(t);
  setHTML($('#capTitle'), title);
  setHTML($('#capSub'), sub);
  // Le fond ne suit plus la tuile sélectionnée : c'est une animation d'ambiance continue (home.css).
}

/* ---- Étagère contextuelle ---- */
function shelfFor(t) {
  const items = [];
  const st = A.st;
  if (t.type === 'moonlight') {
    const hosts = st.moonlight || [];
    if (!hosts.length) {
      items.push({ html: `<div class="card wide">${icon('link')}<div><h3>Associer un PC</h3><p>Ouvre Moonlight : ton PC (Sunshine) apparaît tout seul, puis entre le code PIN sur le PC.</p></div></div>`,
        act: () => launch('moonlight') });
    }
    if (hosts.length) {
      items.push({ html: `<div class="card wide">${icon('settings')}<div><h3>Ouvrir Moonlight</h3><p>Choisir un autre PC, réglages du stream, appairage.</p></div></div>`,
        act: () => Shell.send('moonlight-open') });
    }
    hosts.forEach((hst, hi) => {
      if (hi) items.push({ sep: true });
      const half = hst.online && hst.sunshine === 'half';
      const state = half ? 'busy' : hst.busy ? 'busy' : hst.online ? 'on' : '';
      const line = half ? 'Sunshine bloqué' : hst.busy ? `En jeu${hst.current ? ' : ' + esc(hst.current) : ''}` : hst.online ? 'En ligne' : hst.online === false ? (hst.wol ? 'En veille' : 'Hors ligne') : 'Recherche…';
      const hint = half ? 'Ⓐ pour le relancer' : hst.online === false ? 'Ⓐ pour le réveiller' : 'Ⓐ pour gérer le PC';
      items.push({ html: `<div class="card wide">${icon('stream')}<div><h3>${esc(hst.name)}</h3><p><span class="status-dot ${state}"></span>&nbsp; ${line}<br>${hint}</p></div></div>`,
        act: () => pcMenu(hst) });
      (hst.apps || []).forEach(app => {
        const ph = `<div class="ph" style="background:linear-gradient(160deg, ${hashColor(app.name)}, #111827)">${esc(initials(app.name))}</div>`;
        items.push({ html: `<div class="card poster">${app.boxart ? `<img src="${esc(fileUrl(app.boxart))}" alt="">` : ph}<div class="cap">${esc(app.name)}<small>${esc(hst.name)}</small></div></div>`,
          act: () => stream(hst, app), art: app.boxart, label: app.name });
      });
    });
    return { title: hosts.length ? 'Jouer depuis ton PC' : 'Moonlight', items };
  }
  if (t.type === 'games') {
    const systems = st.library.systems || [], recent = st.library.recent || [];
    const total = systems.reduce((n, s) => n + (s.count || 0), 0);
    items.push({ html: `<div class="card wide">${icon('library')}<div><h3>Bibliothèque</h3><p>Tous tes jeux, jaquettes, favoris (ES-DE).</p></div></div>`, act: () => launch('games') });
    items.push({ html: `<div class="card wide">${icon('plus')}<div><h3>Ajouter des jeux</h3><p>Depuis ton téléphone ou ton PC (QR code), ou une clé USB.</p></div></div>`, act: () => openUpload(), label: 'Ajouter des jeux' });
    recent.forEach(g => {
      const ph = `<div class="ph" style="background:linear-gradient(160deg, ${g.color || '#555'}, #0b0f1a)">${esc(g.short)}</div>`;
      const resumes = g.resume && (A.st.settings || {}).resume_games !== false;
      items.push({ html: `<div class="card poster">${g.cover ? `<img src="${esc(fileUrl(g.cover))}" alt="">` : ph}<span class="sys">${esc(g.short)}</span><div class="cap">${esc(g.name)}<small>${esc(g.systemName)}</small></div></div>`,
        act: () => playGame(g), art: g.cover, label: g.name, aLabel: resumes ? 'Reprendre' : 'Jouer', opts: () => gameOptions(g, resumes) });
    });
    systems.filter(s => s.count).forEach(s => items.push({
      html: `<div class="card square" style="background:linear-gradient(160deg, ${rgba(s.color, .55)}, rgba(255,255,255,.04))"><b>${esc(s.short)}</b><span>${s.count} jeu${s.count > 1 ? 'x' : ''}</span></div>`,
      act: () => Shell.send('library-open', { system: s.id }), label: s.name }));
    if (!total) {
      const host = (st.net && st.net.hostname) || 'console';
      items.push({ html: `<div class="card tip" style="grid-template-columns:1fr">${icon('folder')}<div><b>Ajoute tes jeux</b>&nbsp;: « Ajouter des jeux » puis scanne le QR code avec ton téléphone, ou branche une clé USB. Sur un PC, tu peux aussi les déposer dans <b>\\\\${esc(host)}\\Jeux</b> (un dossier par console).</div></div>`, act: null });
    }
    return { title: recent.length ? 'Reprendre' : 'Émulation', items };
  }
  if (t.type === 'brave') {
    items.push({ html: `<div class="card tip">
      <div>${glyph('ls')} Pointeur</div><div>${glyph('rs')} Défiler</div>
      <div>${glyph('a')} Cliquer</div><div>${glyph('b')} Page précédente</div>
      <div>${glyph('x')} Clavier virtuel</div><div>${glyph('y')} Adresse / recherche</div>
      <div>${glyph('lb')}${glyph('rb')} Onglets</div><div>${glyph('lt')}${glyph('rt')} Zoom</div>
      <div>${glyph('start')} Menu du navigateur</div><div>${glyph('guide')} Accueil</div></div>`, act: () => launch('brave') });
    items.push({ html: `<div class="card wide">${icon('pin')}<div><h3>Épingler un site</h3><p>Dans Brave : ${glyph('start')} puis « Épingler à l'accueil ».</p></div></div>`, act: () => openAddSite() });
    return { title: 'Commandes à la manette', items };
  }
  if (t.type === 'running') {
    items.push({ html: `<div class="card wide">${icon('play')}<div><h3>Reprendre</h3><p>${esc(t.title)}</p></div></div>`, act: () => launch(t.id) });
    items.push({ html: `<div class="card wide">${icon('close')}<div><h3>Fermer</h3><p>Quitter ${esc(t.title)}</p></div></div>`, act: () => confirmClose(t.id, t.title) });
    return { title: 'Application ouverte', items };
  }
  if (t.type === 'add') {
    (st.presets || []).forEach(p => items.push({
      html: `<div class="card square" style="background:linear-gradient(160deg, ${rgba(p.color, .85)}, ${rgba(p.color, .35)})"><b style="font-size:1.05rem">${esc(p.title)}</b><span>${esc(p.note || new URL(p.url).host.replace('www.', ''))}</span></div>`,
      act: () => addSite(p), label: p.title }));
    items.push({ html: `<div class="card wide">${icon('keyboard')}<div><h3>Saisir une adresse</h3><p>N'importe quel site, avec le clavier virtuel.</p></div></div>`, act: () => openAddSite() });
    return { title: 'Suggestions', items };
  }
  // site épinglé
  items.push({ html: `<div class="card wide">${icon('play')}<div><h3>Ouvrir</h3><p>${esc(t.url)}</p></div></div>`, act: () => launch(t.id) });
  items.push({ html: `<div class="card wide">${icon(t.control === 'tv' ? 'tv' : 'pointer')}<div><h3>${t.control === 'tv' ? 'Mode TV' : 'Mode pointeur'}</h3><p>${t.control === 'tv' ? 'Croix directionnelle et Ⓐ, comme sur une TV connectée.' : 'Stick gauche pour viser, Ⓐ pour cliquer.'} ${glyph('y')} pour changer.</p></div></div>`, act: () => tileOptions(t) });
  return { title: 'Raccourci', items };
}

function renderShelf(immediate) {
  clearTimeout(A.shelfTimer);
  const go = () => {
    const t = focusedTile(); if (!t) return;
    const { title, items } = shelfFor(t);
    A.shelfItems = items.filter(i => !i.sep);
    $('#shelfTitle').textContent = title;
    const track = $('#shelfTrack');
    const sig = t.id + '|' + items.map(i => i.html).join('');
    if (sig !== A.sig.shelf) {
      A.sig.shelf = sig;
      track.classList.add('swap');
      track.innerHTML = items.map(i => i.sep ? '<div class="host-sep"></div>' : i.html).join('');
      void track.offsetWidth; track.classList.remove('swap');
    }
    const cards = $$('#shelfTrack > .card');
    cards.forEach((el, i) => { if (A.shelfItems[i] && A.shelfItems[i].act) el.dataset.focus = '1'; });
    A.si = Math.min(A.si, Math.max(0, A.shelfItems.length - 1));
    markShelf();
  };
  if (immediate) go(); else A.shelfTimer = setTimeout(go, 110);
}
function markShelf() {
  const cards = $$('#shelfTrack > .card');
  cards.forEach((el, i) => el.classList.toggle('focus', A.zone === 'shelf' && i === A.si));
  const el = cards[A.si];
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
  let shift = 0;
  if (A.zone === 'shelf' && el) {
    const right = el.offsetLeft + el.offsetWidth, view = window.innerWidth - 8 * rem;
    if (right > view) shift = right - view + rem;
  }
  $('#shelfTrack').style.transform = `translateX(${-shift}px)`;
  $('#main').classList.toggle('in-shelf', A.zone === 'shelf');
  $('#main').classList.toggle('in-sys', A.zone === 'sys');
}

function renderSys() {
  setHTML($('#sys'), SYS_BUTTONS.map((b, i) => `<div class="sysbtn${A.zone === 'sys' && i === A.yi ? ' focus' : ''}">${icon(b.id === 'net' && A.st.net && A.st.net.kind === 'ethernet' ? 'ethernet' : b.icon)}<span class="tip">${esc(b.label)}</span></div>`).join(''));
}

function renderHints() {
  let list;
  if (A.moving) list = [['left', null], ['a', 'Valider'], ['b', 'Annuler']].filter(x => x[1]);
  else if (A.zone === 'row') {
    const t = focusedTile();
    const running = t && isRunning(t);
    list = [['a', running ? 'Reprendre' : t && t.type === 'add' ? 'Ajouter' : 'Ouvrir'], running ? ['x', 'Fermer'] : null,
      t && !['add', 'running'].includes(t.type) ? ['y', 'Options'] : null, ['start', 'Alimentation']];
  } else if (A.zone === 'shelf') {
    const it = A.shelfItems && A.shelfItems[A.si];
    list = [['a', (it && it.aLabel) || 'Lancer'], it && it.opts ? ['y', 'Options'] : null, ['b', 'Retour']];
  }
  else list = [['a', 'Ouvrir'], ['b', 'Retour']];
  setHTML($('#hints'), hints(list));
}

function renderAll() {
  renderTop(); renderRow(); renderCaption(); renderShelf(true); renderSys(); renderHints();
}

/* ------------------------------------------------------------ Navigation ---- */
function setZone(z) {
  A.zone = z;
  $$('#row .tile').forEach((el, i) => el.classList.toggle('focus', i === A.ti));
  markShelf(); renderSys(); renderHints();
}

function homeButton(b) {
  if (A.moving) return moveButton(b);
  const list = tiles();
  switch (b) {
    case 'left': case 'right': {
      const d = b === 'left' ? -1 : 1;
      if (A.zone === 'row') {
        const n = A.ti + d;
        if (n < 0 || n >= list.length) return Sound.bump();
        A.ti = n; A.si = A.shelfMemo[list[n].id] || 0;
        $$('#row .tile').forEach((el, i) => el.classList.toggle('focus', i === A.ti));
        scrollRow(); renderCaption(); renderShelf(); renderHints(); Sound.move();
      } else if (A.zone === 'shelf') {
        const n = A.si + d;
        if (n < 0 || n >= A.shelfItems.length) return Sound.bump();
        A.si = n; A.shelfMemo[focusedTile().id] = n; markShelf(); renderHints(); Sound.move();
      } else {
        const n = A.yi + d;
        if (n < 0 || n >= SYS_BUTTONS.length) return Sound.bump();
        A.yi = n; renderSys(); Sound.move();
      }
      return;
    }
    case 'down':
      if (A.zone === 'row') { if (A.shelfItems.some(i => i.act)) { A.si = Math.min(A.si, A.shelfItems.length - 1); setZone('shelf'); } else setZone('sys'); Sound.move(); }
      else if (A.zone === 'shelf') { setZone('sys'); Sound.move(); }
      else Sound.bump();
      return;
    case 'up':
      if (A.zone === 'sys') { setZone(A.shelfItems.some(i => i.act) ? 'shelf' : 'row'); Sound.move(); }
      else if (A.zone === 'shelf') { setZone('row'); Sound.move(); }
      else Sound.bump();
      return;
    case 'a': return activate();
    case 'b':
      if (A.zone !== 'row') { setZone('row'); Sound.back(); }
      return;
    case 'x': {
      const t = focusedTile();
      if (A.zone === 'row' && t && isRunning(t)) confirmClose(t.id, CORE[t.type] ? CORE[t.type].title : t.title);
      return;
    }
    case 'y':
      if (A.zone === 'row' && !['add', 'running'].includes(focusedTile().type)) tileOptions(focusedTile());
      else if (A.zone === 'shelf' && A.shelfItems[A.si] && A.shelfItems[A.si].opts) { Sound.select(); A.shelfItems[A.si].opts(); }
      return;
    case 'start': return powerMenu();
    case 'back': return openSettings();
  }
}

function activate() {
  Sound.select();
  if (A.zone === 'row') {
    const t = focusedTile();
    if (t.type === 'add') return openAddSite();
    return launch(t.id);
  }
  if (A.zone === 'shelf') { const it = A.shelfItems[A.si]; if (it && it.act) it.act(); return; }
  const b = SYS_BUTTONS[A.yi];
  if (b.id === 'pads') openSettings('pads');
  else if (b.id === 'net') openSettings('net');
  else if (b.id === 'settings') openSettings();
  else powerMenu();
}

function launch(id) {
  const el = $(`#row .tile[data-id="${CSS.escape(id)}"]`);
  if (el) { el.animate([{ transform: 'scale(1.1)' }, { transform: 'scale(1.18)' }, { transform: 'scale(1.1)' }], { duration: 320, easing: 'ease-out' }); }
  Sound.launch();
  const running = (A.st.apps.running || []).some(a => a.id === id);
  Shell.call(running ? 'resume' : 'launch', running ? { app: id } : { id }).catch(e => notice('Erreur', e.message));
}
/* ------------------------------------------------------------ PC distant --- */
function pcMenu(h) {
  const pr = A.st.pc_remote || {}, auth = (pr.auth || []).includes(h.uuid), half = h.online && h.sunshine === 'half';
  const act = (action, label) => () => Shell.call('pc-action', { uuid: h.uuid, action }).then(r => {
    if (r && r.ok === false && r.error) notice(label, r.error);
  });
  const state = half ? 'Sunshine ne répond plus correctement (Moonlight le dirait « injoignable »).'
    : h.busy ? `En jeu${h.current ? ' : ' + h.current : ''}.` : h.online ? 'En ligne, Sunshine répond.' : h.online === false ? 'Ne répond pas : en veille ou éteint.' : 'Recherche…';
  const items = [];
  if (!h.online) items.push({ icon: 'power', label: 'Réveiller le PC', sub: pr.relay ? `Wake-on-LAN + relais ${pr.relay}` : 'Wake-on-LAN', action: act('wake', 'Réveil') });
  if (h.online) items.push(auth ? { icon: 'restart', label: 'Relancer Sunshine', sub: half ? 'Recommandé : il est bloqué' : 'Si le stream refuse de démarrer', action: act('restart-sunshine', 'Sunshine') }
    : { icon: 'lock', label: 'Relancer Sunshine…', sub: 'Enregistre d\'abord ton identifiant Sunshine', action: () => openSettings('moonlight') });
  if (pr.ssh && h.online) {
    items.push({ icon: 'moon', label: 'Mettre le PC en veille', action: act('sleep', 'Veille') });
    items.push({ icon: 'restart', label: 'Redémarrer le PC', action: () => confirm(`Redémarrer ${h.name} ?`, 'Les jeux et applications ouverts sur le PC seront fermés.', 'Redémarrer', act('reboot', 'Redémarrage'), true) });
    items.push({ icon: 'power', label: 'Éteindre le PC', danger: true, action: () => confirm(`Éteindre ${h.name} ?`, 'Pour le rallumer à distance, le Wake-on-LAN devra fonctionner depuis l\'arrêt complet.', 'Éteindre', act('shutdown', 'Arrêt'), true) });
  } else if (!pr.ssh) {
    items.push({ icon: 'info', label: 'Veille et redémarrage à distance', sub: 'À activer : voir Réglages › Moonlight', action: () => openSettings('moonlight') });
  }
  items.push({ icon: 'settings', label: 'Ouvrir Moonlight', action: () => Shell.send('moonlight-open') });
  items.push({ icon: 'back', label: 'Retour' });
  menu({ title: h.name, text: esc(state), items });
}

function stream(host, app) { Sound.launch(); Shell.send('moonlight-stream', { uuid: host.uuid, app: app.name }); }
function gameOptions(g, resumes) {
  const items = [{ icon: 'play', label: resumes ? 'Reprendre la partie' : 'Jouer', sub: resumes ? 'Là où tu t\'étais arrêté' : '', action: () => playGame(g) }];
  if (resumes) items.push({ icon: 'restart', label: 'Recommencer depuis le début', sub: 'La partie mise de côté est oubliée (tes sauvegardes du jeu restent)',
    action: () => Shell.call('resume-forget', { path: g.path }).then(() => playGame(g)) });
  items.push({ icon: 'back', label: 'Annuler' });
  menu({ title: g.name, items });
}

function playGame(g) {
  Sound.launch();
  if (g.direct === false) return Shell.send('library-open', { system: g.system });
  Shell.send('game-launch', { system: g.system, path: g.path, name: g.name });
}

function moveButton(b) {
  const list = A.st.tiles; const i = list.findIndex(t => t.id === A.moving);
  if (b === 'left' || b === 'right') {
    const d = b === 'left' ? -1 : 1;
    if (i + d < 0 || i + d >= list.length) return Sound.bump();
    list.splice(i + d, 0, list.splice(i, 1)[0]); A.ti = i + d;
    Shell.send('tile-move', { id: A.moving, delta: d }); renderRow(); Sound.move();
  } else if (b === 'a' || b === 'b') {
    A.moving = null; renderRow(); renderHints(); Sound.select();
  }
}

/* ------------------------------------------------------------- Calques ------ */
class Layer {
  constructor(html, cls = '', opts = {}) {
    this.el = h(`<div class="layer ${cls}">${html}</div>`);
    this.keepBg = !!opts.keepBg;
    $('#layers').appendChild(this.el);
    A.layers.push(this);
    // Fond animé en pause derrière les voiles plein écran (pas pour le choix du thème, qui le montre).
    document.body.classList.toggle('layers-open', A.layers.some(l => !l.keepBg));
  }
  close() {
    const i = A.layers.indexOf(this); if (i >= 0) A.layers.splice(i, 1);
    document.body.classList.toggle('layers-open', A.layers.some(l => !l.keepBg));
    this.el.remove(); renderHints();
    this.onClose && this.onClose();
  }
  handle() {}
}

// Menu générique (boutons verticaux)
class MenuLayer extends Layer {
  constructor({ title, text, items, onCancel }) {
    super(`<div class="scrim"></div><div class="sheet dialog"><h2>${esc(title)}</h2>${text ? `<p>${text}</p>` : ''}
      <div class="actions">${items.map((it, i) => `<div class="btn${it.danger ? ' danger' : ''}" data-i="${i}">${icon(it.icon || 'chevron')}<span>${esc(it.label)}</span>${it.sub ? `<small>${esc(it.sub)}</small>` : ''}</div>`).join('')}</div>
      <div class="hints" style="margin-top:1.4rem">${hints([['a', 'Choisir'], ['b', 'Annuler']])}</div></div>`);
    this.items = items; this.i = 0; this.onCancel = onCancel; this.mark();
  }
  mark() { $$('.btn', this.el).forEach((b, i) => b.classList.toggle('focus', i === this.i)); }
  handle(b) {
    if (b === 'up' || b === 'down') {
      const n = this.i + (b === 'up' ? -1 : 1);
      if (n < 0 || n >= this.items.length) return Sound.bump();
      this.i = n; this.mark(); Sound.move();
    } else if (b === 'a') {
      Sound.select(); const it = this.items[this.i]; this.close(); it.action && it.action();
    } else if (b === 'b' || b === 'back') {
      Sound.back(); this.close(); this.onCancel && this.onCancel();
    }
  }
}
function menu(opts) { return new MenuLayer(opts); }
function notice(title, text) { return menu({ title, text: esc(text), items: [{ icon: 'check', label: 'OK' }] }); }
function confirm(title, text, okLabel, action, danger) {
  return menu({ title, text, items: [{ icon: danger ? 'close' : 'check', label: okLabel, action, danger }, { icon: 'back', label: 'Annuler' }] });
}
function confirmClose(appId, title) {
  confirm(`Fermer ${title} ?`, 'Ce qui n\'est pas sauvegardé sera perdu.', 'Fermer', () => Shell.send('close-app', { app: appId }), true);
}

function powerMenu() {
  if (A.layers.some(l => l instanceof MenuLayer && l.power)) return;
  const deep = (A.st.settings || {}).standby_mode !== 'light';
  const m = menu({
    title: 'Alimentation',
    text: deep ? 'La veille coupe tout ; appuie sur le bouton Xbox de la manette pour rallumer.' : 'Veille légère : écran coupé, réveil instantané avec la manette.',
    items: [
      { icon: 'moon', label: 'Mettre en veille', action: () => Shell.send('power', { action: 'standby' }) },
      ...(((A.st.bt || {}).gamepads || []).some(g => g.connected) ? [{ icon: 'gamepad', label: 'Éteindre la manette', sub: 'La console se met en veille 2 min après', action: () => Shell.send('pads-off') }] : []),
      { icon: 'restart', label: 'Redémarrer', action: () => confirm('Redémarrer ?', 'La console redémarre en une minute environ.', 'Redémarrer', () => Shell.send('power', { action: 'reboot' })) },
      { icon: 'power', label: 'Éteindre', danger: true, action: () => confirm('Éteindre complètement ?', 'Pour la rallumer, il faudra ouvrir le capot et appuyer sur le bouton d\'alimentation. Préfère la veille.', 'Éteindre', () => Shell.send('power', { action: 'poweroff' }), true) },
      { icon: 'back', label: 'Annuler' },
    ],
  });
  m.power = true;
}

// Clavier virtuel dans l'accueil
class OSKLayer extends Layer {
  constructor({ title, field, presets, onCommit, onCancel }) {
    super(`<div class="scrim"></div><div class="sheet osk-sheet"><div class="title">${icon(field.type === 'password' ? 'lock' : 'keyboard')}${esc(title)}</div><div class="osk-host"></div></div>`);
    this.osk = new OSK($('.osk-host', this.el), {
      layout: (A.st.settings || {}).osk_layout || 'azerty',
      onCommit: (text, submit) => { this.close(); onCommit && onCommit(text, submit); },
      onCancel: () => { this.close(); onCancel && onCancel(); },
    });
    this.osk.open(field);
  }
  handle(b) { this.osk.handle(b); }
  key(e) { return this.osk.handleKey(e); }
}
function keyboard(opts) { return new OSKLayer(opts); }

function openAddSite() {
  keyboard({ title: 'Ajouter un site à l\'accueil', field: { type: 'url', label: 'Adresse', placeholder: 'ex : youtube.com' },
    onCommit: (text) => addSite({ url: text }) });
}
function addSite(p) {
  Shell.call('site-add', { url: p.url, title: p.title, color: p.color, control: p.control, tv: p.tv }).then(res => {
    if (res && res.error) return notice('Adresse invalide', res.error);
    Sound.select();
    const list = A.st.tiles || [];
    A.ti = list.length; A.zone = 'row';
  }).catch(e => notice('Erreur', e.message));
}

function tileOptions(t) {
  if (!t || t.type === 'add') return;
  const items = [{ icon: 'move', label: 'Déplacer', action: () => { A.moving = t.id; A.zone = 'row'; renderRow(); renderHints(); } }];
  if (isRunning(t)) items.unshift({ icon: 'close', label: 'Fermer l\'application', action: () => confirmClose(t.id, CORE[t.type] ? CORE[t.type].title : t.title) });
  if (t.type === 'site') {
    items.push({ icon: 'edit', label: 'Renommer', action: () => keyboard({ title: 'Nom de la tuile', field: { value: t.title, label: 'Nom' },
      onCommit: (text) => text.trim() && Shell.send('site-update', { id: t.id, title: text.trim() }) }) });
    items.push({ icon: t.control === 'tv' ? 'pointer' : 'tv', label: t.control === 'tv' ? 'Passer en mode pointeur' : 'Passer en mode TV (croix)',
      sub: t.control === 'tv' ? 'souris au stick' : 'sites conçus pour la télé',
      action: () => Shell.send('site-update', { id: t.id, control: t.control === 'tv' ? 'pointer' : 'tv', tv: t.control !== 'tv' }) });
    items.push({ icon: 'trash', label: 'Retirer de l\'accueil', danger: true, action: () => Shell.send('site-remove', { id: t.id }) });
  }
  items.push({ icon: 'back', label: 'Annuler' });
  menu({ title: t.type === 'site' ? t.title : CORE[t.type].title, items });
}

/* ------------------------------------------------------------- Réglages ----- */
const SECTIONS = [
  { id: 'pads', icon: 'gamepad', label: 'Manettes' },
  { id: 'net', icon: 'wifi', label: 'Réseau' },
  { id: 'moonlight', icon: 'stream', label: 'Moonlight' },
  { id: 'games', icon: 'library', label: 'Jeux' },
  { id: 'look', icon: 'palette', label: 'Apparence' },
  { id: 'display', icon: 'display', label: 'Image et son' },
  { id: 'sleep', icon: 'moon', label: 'Veille' },
  { id: 'browser', icon: 'keyboard', label: 'Navigateur et clavier' },
  { id: 'system', icon: 'chip', label: 'Système' },
  { id: 'health', icon: 'pulse', label: 'Santé' },
];
function choiceRow(icon_, title, sub, key, options) {
  const cur = (A.st.settings || {})[key];
  const idx = Math.max(0, options.findIndex(o => o[0] === cur));
  return { icon: icon_, title, sub, value: `<span class="choice">${esc(options[idx][1])}</span>`,
    left: () => setSetting(key, options[(idx - 1 + options.length) % options.length][0]),
    right: () => setSetting(key, options[(idx + 1) % options.length][0]),
    act: () => setSetting(key, options[(idx + 1) % options.length][0]) };
}
function toggleRow(icon_, title, sub, key) {
  const on = !!(A.st.settings || {})[key];
  return { icon: icon_, title, sub, value: `<span class="switch${on ? ' on' : ''}"></span>`, act: () => setSetting(key, !on) };
}
function setSetting(key, value) {
  A.st.settings[key] = value;
  if (key === 'ui_sounds') Sound.enabled = !!value;
  Shell.send('settings-set', { key, value });
  if (A.settings) A.settings.render();
}

class SettingsLayer extends Layer {
  constructor(section) {
    super(`<div class="scrim"></div><div class="sheet settings"><nav></nav><div class="content"><div class="content-inner"></div></div><div class="hints settings-hints">${hints([['dpad', 'Naviguer'], ['a', 'Choisir'], ['b', 'Retour'], ['back', 'Fermer']])}</div></div>`);
    this.sec = Math.max(0, SECTIONS.findIndex(s => s.id === section));
    this.col = section ? 1 : 0; this.row = 0; this.wifi = null; this.wifiLoading = false;
    A.settings = this;
    this.render();
    if (SECTIONS[this.sec].id === 'net') this.scanWifi();
    if (SECTIONS[this.sec].id === 'health') this.loadHealth(true);
    if (SECTIONS[this.sec].id === 'games') this.loadBios();
  }
  loadBios() { Shell.call('bios-status').then(b => { this.bios = b; if (A.settings === this) this.render(); }); }
  close() { clearTimeout(this.healthTimer); super.close(); A.settings = null; }
  loadHealth(full) {
    clearTimeout(this.healthTimer);
    if (full) this.healthFull = Date.now();
    Shell.call('health', { full }).then(d => {
      if (!A.settings || SECTIONS[this.sec].id !== 'health') return;
      // Les infos SMART (lentes) ne sont relues qu'une fois par minute : on garde les dernières.
      if (!full && this.health) Object.assign(d, { ssd: this.health.ssd, io_errors: this.health.io_errors, privileged: this.health.privileged });
      this.health = d; this.render();
      const again = Date.now() - (this.healthFull || 0) > 60000;
      this.healthTimer = setTimeout(() => this.loadHealth(again), 5000);
    });
  }
  rows() {
    const st = A.st, s = st.settings || {}, id = SECTIONS[this.sec].id;
    const out = [];
    if (id === 'pads') {
      out.push({ group: 'Manettes associées' });
      const gp = (st.bt && st.bt.gamepads) || [];
      if (!gp.length) out.push({ static: true, icon: 'info', title: 'Aucune manette associée', sub: 'Associe ta manette Xbox ci-dessous' });
      gp.forEach(g => out.push({ icon: 'gamepad', title: g.name, sub: g.connected ? 'Connectée' : 'Déconnectée — appuie sur son bouton Xbox',
        value: typeof g.battery === 'number' ? `<span class="meter"><i style="width:${g.battery}%"></i></span> ${g.battery} %` : '',
        act: () => confirm(`Oublier ${g.name} ?`, 'Il faudra l\'associer de nouveau pour l\'utiliser.', 'Oublier', () => Shell.send('bt-forget', { path: g.path }), true) }));
      out.push({ group: 'Ajouter' });
      out.push({ icon: 'bluetooth', title: 'Associer une manette', sub: 'Maintiens 3 s le petit bouton d\'appairage, sur le dessus près du port USB', act: () => openPairing() });
      out.push({ group: 'Astuce' });
      out.push({ static: true, icon: 'info', title: 'Bouton Xbox', sub: 'Appui : menu de la console · Maintenu : menu, même dans Moonlight' });
    } else if (id === 'net') {
      const net = st.net || {};
      out.push({ group: 'Connexion' });
      out.push({ static: true, icon: net.kind === 'ethernet' ? 'ethernet' : 'wifi', title: net.connected ? (net.kind === 'ethernet' ? 'Câble Ethernet' : net.name) : 'Non connecté',
        sub: net.connected ? `Adresse IP : ${net.ip || '—'} · nom : ${net.hostname || ''}.local` : 'Choisis un réseau Wi-Fi ci-dessous',
        value: net.kind === 'wifi' && net.signal != null ? signalBars(net.signal) : '' });
      out.push({ group: 'Réseaux Wi-Fi' });
      if (this.wifiLoading && !this.wifi) out.push({ static: true, icon: 'wifi', title: 'Recherche des réseaux…' });
      (this.wifi || []).forEach(n => out.push({ icon: n.secure ? 'lock' : 'wifi', title: n.ssid, sub: n.active ? 'Connecté' : n.known ? 'Enregistré' : n.secure ? 'Sécurisé' : 'Ouvert',
        value: signalBars(n.signal), act: () => this.joinWifi(n) }));
      out.push({ icon: 'restart', title: 'Actualiser', act: () => this.scanWifi() });
      out.push({ group: 'Partage des jeux' });
      out.push({ static: true, icon: 'folder', title: `\\\\${net.hostname || 'console'}\\Jeux`, sub: 'Depuis Windows (ou smb://' + (net.hostname || 'console') + '.local/Jeux sur Mac/Linux)' });
      out.push({ static: true, icon: 'info', title: 'Pour Moonlight', sub: 'Un câble Ethernet ou un Wi-Fi 5 GHz proche de la box donnent la meilleure image.' });
    } else if (id === 'moonlight') {
      const hosts = st.moonlight || [];
      if (!hosts.length) {
        out.push({ static: true, icon: 'info', title: 'Aucun PC associé', sub: 'Installe Sunshine sur ton PC, puis associe-le dans Moonlight' });
        out.push({ icon: 'stream', title: 'Ouvrir Moonlight', act: () => { this.close(); Shell.send('moonlight-open'); } });
        return out;
      }
      const def = hosts.find(h => h.uuid === st.moonlight_default) || hosts[0];
      out.push({ group: 'Tuile Moonlight' });
      if (hosts.length > 1) out.push(choiceRow('stream', 'PC par défaut', 'Celui que lance la tuile', 'moonlight_host', hosts.map(h => [h.uuid, h.name])));
      const apps = (def.apps || []).map(a => [a.name, a.name]);
      const cur = s.moonlight_tile_app || 'gui';
      if (cur !== 'gui' && !apps.some(a => a[0] === cur)) apps.unshift([cur, cur]);
      out.push(choiceRow('play', 'La tuile Moonlight lance', 'Sinon : l\'interface Moonlight (choix du PC et du jeu)', 'moonlight_tile_app', [...apps, ['gui', 'Interface Moonlight']]));
      out.push({ group: `Déverrouillage de ${def.name}` });
      const hasPin = (st.moonlight_pins || []).includes(def.uuid);
      out.push({ icon: 'lock', title: 'Code PIN Windows Hello', sub: hasPin ? 'Enregistré sur la console (jamais affiché)' : 'Tapé pour toi sur l\'écran de verrouillage du PC',
        value: hasPin ? '●●●● ✓' : 'non défini', act: () => this.editPin(def, hasPin) });
      out.push(choiceRow('sparkle', 'Saisie automatique du code', s.moonlight_pin_mode === 'always' ? 'À chaque connexion (même si le PC était déjà allumé)' : s.moonlight_pin_mode === 'off' ? 'Jamais : bouton Xbox maintenu › « Saisir mon code PIN »' : 'Quand la console vient de réveiller le PC',
        'moonlight_pin_mode', [['wake', 'Après réveil du PC'], ['always', 'À chaque connexion'], ['off', 'Jamais (manuel)']]));
      out.push({ static: true, icon: 'info', title: 'Comment ça marche', sub: 'Dès que l\'image du PC arrive, la console tape le code (comme un copier-coller, quelle que soit la langue du clavier du PC).' });
      const pr = st.pc_remote || {}, hasAuth = (pr.auth || []).includes(def.uuid);
      out.push({ group: `${def.name} à distance` });
      out.push({ icon: 'lock', title: 'Identifiant Sunshine', sub: hasAuth ? 'Enregistré : la console peut relancer Sunshine' : 'Celui de la page web de Sunshine : la console pourra le relancer s\'il se bloque',
        value: hasAuth ? '✓' : 'non défini', act: () => this.editSunshine(def, hasAuth) });
      out.push(toggleRow('sparkle', 'Réparer Sunshine automatiquement', 'S\'il ne répond plus qu\'à moitié (Moonlight le dirait « injoignable »)', 'sunshine_auto_repair'));
      out.push({ static: true, icon: 'power', title: 'Relais de réveil', sub: pr.relay ? `${pr.relay} envoie le Wake-on-LAN depuis le réseau du PC` : 'Non configuré : console-pc-setup relais utilisateur@appareil (en SSH)' });
      out.push({ static: true, icon: 'moon', title: 'Veille et redémarrage du PC', sub: pr.ssh ? `Par SSH (${pr.ssh})` : 'Non configuré : serveur OpenSSH sur le PC, puis console-pc-setup pc utilisateur@PC' });
    } else if (id === 'games') {
      const cv = st.covers || {};
      out.push({ group: 'Ajouter des jeux et des BIOS' });
      out.push({ icon: 'plus', title: 'Depuis un téléphone ou un PC', sub: 'Un QR code à scanner : envoie tout en vrac, la console range', act: () => { this.close(); openUpload(); } });
      out.push(toggleRow('folder', 'Depuis une clé USB', 'Proposer d\'importer les jeux et BIOS d\'une clé ou d\'un disque dès qu\'il est branché', 'usb_import'));
      out.push({ group: 'BIOS' });
      biosRows(this.bios, out, () => { this.close(); openUpload(); });
      out.push({ group: 'Jaquettes' });
      out.push(toggleRow('library', 'Jaquettes automatiques', 'Ajoute celles qui manquent depuis la base libre de libretro, sans compte', 'covers_auto'));
      const last = cv.running ? 'Recherche en cours… (en pause pendant les jeux)' : !cv.last ? 'Pas encore lancée'
        : cv.offline ? 'Base libretro injoignable lors de la dernière recherche'
        : `Dernière recherche : ${cv.added || 0} ajoutée${cv.added > 1 ? 's' : ''}${cv.missing ? ` · ${cv.missing} jeu${cv.missing > 1 ? 'x' : ''} sans correspondance` : ''}`;
      out.push({ icon: 'search', title: 'Chercher maintenant', sub: last, act: () => { if (!cv.running) Shell.send('covers-scan'); } });
      out.push({ static: true, icon: 'info', title: 'Encore plus d\'images', sub: 'Dans Jeux, Menu › Scraper avec un compte ScreenScraper ajoute vidéos, logos et résumés.' });
      out.push({ group: 'Reprise des parties' });
      out.push(toggleRow('play', 'Reprendre là où tu t\'étais arrêté', 'En quittant un jeu, la partie est mise de côté ; elle reprend au lancement suivant', 'resume_games'));
      out.push({ static: true, icon: 'info', title: 'Pour que ça marche', sub: 'Quitte avec le bouton Xbox › Quitter le jeu (ou éteins la console). Pour repartir de zéro : Ⓨ sur le jeu dans l\'accueil.' });
    } else if (id === 'look') {
      const th = THEMES.find(x => x.id === s.theme) || THEMES[0];
      out.push({ group: 'Accueil' });
      out.push({ icon: 'palette', title: 'Thème', sub: th.sub, value: `<span class="choice">${esc(th.label)}</span>`, act: () => { this.close(); openThemes(() => openSettings('look')); } });
      out.push(choiceRow('sparkle', 'Animation du fond', s.bg_motion === 'off' ? 'Fond immobile : le plus économe' : s.bg_motion === 'calm' ? 'Mouvement très lent, sans particules' : 'Aurores et particules en mouvement',
        'bg_motion', [['full', 'Normale'], ['calm', 'Calme'], ['off', 'Immobile']]));
      out.push(choiceRow('moon', 'Mode ambiance', 'Sans activité sur l\'accueil : l\'interface s\'efface, il ne reste que le fond et l\'heure (protège les TV OLED)',
        'ambient_min', [[0, 'Jamais'], [2, '2 min'], [5, '5 min'], [10, '10 min']]));
    } else if (id === 'display') {
      const d = st.display;
      out.push({ group: 'Téléviseur' });
      out.push({ static: true, icon: 'tv', title: d ? (d.model || d.name) : 'Aucun téléviseur détecté', sub: d ? `${d.width}×${d.height} à ${d.refresh} Hz` : 'Branche le câble HDMI' });
      out.push(choiceRow('display', 'Résolution', '1080p recommandé : plus fluide sur ce PC', 'resolution', [['1080p', '1080p'], ['max', 'Maximum']]));
      out.push({ group: 'Son' });
      const v = this.volume ?? 100;
      out.push({ icon: 'volume', title: 'Volume', sub: '◀ ▶ pour régler (le volume de la TV reste prioritaire)',
        value: `<span class="meter"><i style="width:${v}%"></i></span> ${v} %`,
        left: () => this.setVolume(v - 5), right: () => this.setVolume(v + 5), act: () => this.setVolume(v >= 100 ? 50 : 100) });
      out.push(toggleRow('sparkle', 'Sons de l\'interface', 'Petits sons de navigation', 'ui_sounds'));
    } else if (id === 'sleep') {
      const ver = s.deep_sleep_verified;
      out.push({ group: 'Mode de veille' });
      out.push(choiceRow('moon', 'Veille', s.standby_mode === 'light' ? 'Écran coupé, réveil instantané (~4 W)' : 'Veille complète, réveil par le bouton Xbox (~1 W)',
        'standby_mode', [['deep', 'Profonde'], ['light', 'Légère']]));
      out.push({ icon: 'gamepad', title: 'Tester le réveil par la manette', sub: ver === true ? 'Dernier test : réussi ✓' : ver === false ? 'Dernier test : échec — veille légère conseillée' : 'Recommandé avant d\'utiliser la veille profonde',
        act: () => wakeTest() });
      out.push({ group: 'Automatique' });
      out.push(choiceRow('sun', 'Mise en veille automatique', 'Sans activité (pas pendant une vidéo ou un stream)', 'auto_standby_min',
        [[0, 'Jamais'], [10, '10 min'], [15, '15 min'], [30, '30 min'], [60, '1 h']]));
      out.push(toggleRow('power', 'Manette éteinte = veille', 'Éteindre la manette met la console en veille après 2 min', 'controller_off_standby'));
      const sl = st.sleep || {};
      if ((sl.modes || []).length > 1) {
        out.push({ group: 'Avancé' });
        const other = (sl.modes || []).find(m => m !== sl.current);
        out.push({ icon: 'chip', title: 'Mode de veille du noyau', sub: `Actuel : ${sl.current} — à essayer si le réveil manette échoue`, value: `<span class="choice">${esc(sl.current || '')}</span>`,
          act: () => Shell.call('mem-sleep', { mode: other }).then(() => Shell.call('state').then(st2 => { Object.assign(A.st, st2); this.render(); })) });
      }
    } else if (id === 'browser') {
      out.push({ group: 'Clavier virtuel' });
      out.push(choiceRow('keyboard', 'Disposition', 'Clavier affiché à l\'écran', 'osk_layout', [['azerty', 'AZERTY'], ['qwerty', 'QWERTY']]));
      out.push({ group: 'Brave' });
      out.push(choiceRow('globe', 'Taille d\'affichage', 'Agrandit les pages pour la lecture à distance (relance Brave)', 'browser_scale',
        [[1.25, '125 %'], [1.5, '150 %'], [1.75, '175 %'], [2, '200 %']]));
      out.push({ group: 'Bouton Xbox' });
      out.push(choiceRow('gamepad', 'Durée d\'un appui long', 'Appui long = menu de la console partout', 'guide_hold_ms',
        [[500, '0,5 s'], [700, '0,7 s'], [1000, '1 s']]));
    } else if (id === 'system') {
      out.push({ group: 'Console' });
      out.push({ icon: 'edit', title: 'Nom de la console', value: esc(s.console_name || 'Nova'),
        act: () => keyboard({ title: 'Nom de la console', field: { value: s.console_name || '', label: 'Nom' }, onCommit: (t) => t.trim() && setSetting('console_name', t.trim()) }) });
      out.push({ icon: 'sparkle', title: 'Relancer l\'assistant de démarrage', act: () => { this.close(); startWizard(); } });
      out.push({ group: 'Informations' });
      const info = this.info || {};
      out.push({ static: true, icon: 'info', title: `Version ${esc(st.version || '')}`, sub: info.kernel ? `Noyau ${info.kernel}` : '' });
      if (info.disk) out.push({ static: true, icon: 'folder', title: 'Stockage', sub: `${(info.disk.free / 1e9).toFixed(0)} Go libres sur ${(info.disk.total / 1e9).toFixed(0)} Go` });
      out.push({ group: 'Maintenance' });
      out.push({ icon: 'restart', title: 'Redémarrer l\'interface', sub: 'Les applications ouvertes restent ouvertes', act: () => Shell.send('power', { action: 'restart-ui' }) });
      out.push({ icon: 'power', title: 'Redémarrer la console', act: () => confirm('Redémarrer ?', '', 'Redémarrer', () => Shell.send('power', { action: 'reboot' })) });
    } else if (id === 'health') {
      healthRows(this.health, out, () => this.loadHealth(true));
    }
    return out;
  }
  render() {
    const nav = $('nav', this.el);
    setHTML(nav, `<h2>Réglages</h2>` + SECTIONS.map((s, i) => `<div class="nav-item${i === this.sec ? ' sel' : ''}${this.col === 0 && i === this.sec ? ' focus' : ''}">${icon(s.icon)}${esc(s.label)}</div>`).join(''));
    const rows = this.rows();
    this.focusables = rows.map((r, i) => (!r.group && !r.static) ? i : -1).filter(i => i >= 0);
    this.row = Math.min(this.row, Math.max(0, this.focusables.length - 1));
    const sec = SECTIONS[this.sec];
    setHTML($('.content-inner', this.el), `<h3>${esc(sec.label)}</h3>` + rows.map((r, i) => r.group ? `<div class="group">${esc(r.group)}</div>` :
      `<div class="srow${r.static ? ' static' : ''}${this.col === 1 && this.focusables[this.row] === i ? ' focus' : ''}" data-i="${i}">${icon(r.icon || 'chevron')}<div class="txt"><b>${esc(r.title)}</b>${r.sub ? `<span>${esc(r.sub)}</span>` : ''}</div><div class="val">${r.value || ''}</div></div>`).join(''));
    this._rows = rows;
    const inner = $('.content-inner', this.el), focusEl = $('.srow.focus', this.el);
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    let shift = 0;
    if (focusEl) { const bottom = focusEl.offsetTop + focusEl.offsetHeight; const avail = this.el.querySelector('.content').clientHeight - 4 * rem; if (bottom > avail) shift = bottom - avail; }
    inner.style.transform = `translateY(${-shift}px)`;
  }
  current() { return this._rows[this.focusables[this.row]]; }
  handle(b) {
    if (this.col === 0) {
      if (b === 'up' || b === 'down') {
        const n = this.sec + (b === 'up' ? -1 : 1);
        if (n < 0 || n >= SECTIONS.length) return Sound.bump();
        this.sec = n; this.row = 0; Sound.move(); this.render();
        if (SECTIONS[n].id === 'net' && !this.wifi) this.scanWifi();
        if (SECTIONS[n].id === 'system' && !this.info) Shell.call('info').then(i => { this.info = i; this.render(); });
        if (SECTIONS[n].id === 'games') this.loadBios();
        if (SECTIONS[n].id === 'health') this.loadHealth(!this.health || Date.now() - (this.healthFull || 0) > 60000);
        else clearTimeout(this.healthTimer);
        if (SECTIONS[n].id === 'display' && this.volume == null) Shell.call('volume', { delta: 0 }).then(v => { this.volume = v && v.volume; this.render(); });
      } else if (b === 'right' || b === 'a') { if (this.focusables.length) { this.col = 1; Sound.move(); this.render(); } }
      else if (b === 'b' || b === 'back') { Sound.back(); this.close(); }
      return;
    }
    const r = this.current();
    if (b === 'up' || b === 'down') {
      const n = this.row + (b === 'up' ? -1 : 1);
      if (n < 0 || n >= this.focusables.length) return Sound.bump();
      this.row = n; Sound.move(); this.render();
    } else if (b === 'left') { if (r && r.left) { r.left(); Sound.move(); } else { this.col = 0; Sound.move(); this.render(); } }
    else if (b === 'right') { if (r && r.right) { r.right(); Sound.move(); } }
    else if (b === 'a') { if (r && r.act) { Sound.select(); r.act(); this.render(); } }
    else if (b === 'b') { this.col = 0; Sound.back(); this.render(); }
    else if (b === 'back') { Sound.back(); this.close(); }
  }
  editPin(host, hasPin) {
    const ask = () => keyboard({ title: `Code PIN Windows de ${host.name}`, field: { type: 'password', label: 'Code PIN', inputmode: 'numeric' },
      onCommit: (pin) => { if (pin.trim()) Shell.call('moonlight-pin', { uuid: host.uuid, pin: pin.trim() }).then(() => notice('Code PIN enregistré', 'Il sera tapé sur l\'écran de verrouillage de Windows quand la console réveille le PC.')); } });
    if (!hasPin) return ask();
    menu({ title: 'Code PIN Windows', items: [
      { icon: 'edit', label: 'Modifier le code', action: ask },
      { icon: 'trash', label: 'Supprimer le code', danger: true, action: () => Shell.send('moonlight-pin', { uuid: host.uuid, pin: '' }) },
      { icon: 'back', label: 'Annuler' }] });
  }
  editSunshine(host, has) {
    const ask = () => keyboard({ title: `Sunshine de ${host.name} : identifiant`, field: { label: 'Identifiant' },
      onCommit: (user) => {
        if (!user.trim()) return;
        setTimeout(() => keyboard({ title: `Sunshine de ${host.name} : mot de passe`, field: { type: 'password', label: 'Mot de passe' },
          onCommit: (pw) => Shell.call('sunshine-auth', { uuid: host.uuid, user: user.trim(), password: pw }).then(r => {
            if (!r || !r.ok) return notice('Identifiant refusé', 'Sunshine n\'accepte pas cet identifiant ou ce mot de passe.');
            notice('Identifiant enregistré', r.result === 'offline'
              ? 'Le PC ne répond pas : il sera vérifié à la prochaine connexion.'
              : 'Vérifié auprès de Sunshine. La console pourra le relancer s\'il se bloque.');
          }) }), 250);
      } });
    if (!has) return ask();
    menu({ title: 'Identifiant Sunshine', items: [
      { icon: 'edit', label: 'Modifier', action: ask },
      { icon: 'trash', label: 'Supprimer', danger: true, action: () => Shell.send('sunshine-auth', { uuid: host.uuid, user: '' }) },
      { icon: 'back', label: 'Annuler' }] });
  }
  setVolume(v) {
    v = Math.max(0, Math.min(100, v)); this.volume = v; this.render();
    Shell.call('volume', { set: v }).then(r => { if (r && r.volume != null) { this.volume = r.volume; this.render(); } });
  }
  scanWifi() {
    this.wifiLoading = true; this.render();
    Shell.call('net-scan').then(list => { this.wifi = list || []; this.wifiLoading = false; if (A.settings === this) this.render(); })
      .catch(() => { this.wifiLoading = false; });
  }
  joinWifi(n) {
    if (n.active) return confirm(`Oublier « ${n.ssid} » ?`, 'La console ne s\'y connectera plus automatiquement.', 'Oublier', () => Shell.call('net-forget', { ssid: n.ssid }).then(() => this.scanWifi()), true);
    const go = (pw) => {
      const wait = menu({ title: `Connexion à ${n.ssid}…`, text: 'Quelques secondes…', items: [{ icon: 'back', label: 'Masquer' }] });
      Shell.call('net-connect', { ssid: n.ssid, password: pw }).then(res => {
        wait.close();
        if (res && res.ok) { notice('Connecté', `La console est connectée à ${n.ssid}.`); this.scanWifi(); }
        else notice('Connexion impossible', (res && res.error) || 'Vérifie le mot de passe.');
      });
    };
    if (n.secure && !n.known) keyboard({ title: `Mot de passe de « ${n.ssid} »`, field: { type: 'password', label: 'Mot de passe' }, onCommit: (t) => go(t) });
    else go(null);
  }
}
/* ---------------------------------------------------------------- Thèmes --- */
const THEMES = [
  { id: 'aurora', label: 'Aurore', sub: 'Aurores violettes et bleues, poussière d\'étoiles', c: ['#7c5cff', '#2b6cff', '#19bed2'] },
  { id: 'ocean', label: 'Océan', sub: 'Profondeurs turquoise, bulles qui remontent', c: ['#00aacd', '#195fd2', '#00e1aa'] },
  { id: 'sunset', label: 'Crépuscule', sub: 'Orange, rose et violet, poussière dorée', c: ['#ff783c', '#ff468c', '#8c3cdc'] },
  { id: 'forest', label: 'Forêt', sub: 'Émeraude et lucioles', c: ['#28c878', '#14785a', '#a0dc5a'] },
  { id: 'cosmos', label: 'Cosmos', sub: 'Nébuleuses et champ d\'étoiles', c: ['#a03cff', '#ff3caa', '#285aff'] },
  { id: 'ember', label: 'Braises', sub: 'Rouge et or, braises qui s\'envolent', c: ['#ff5a1e', '#c81e1e', '#ffa028'] },
  { id: 'sakura', label: 'Sakura', sub: 'Rose poudré, pétales qui tombent', c: ['#ff8cbe', '#c86eff', '#ffc8dc'] },
  { id: 'winter', label: 'Hiver', sub: 'Bleu glacier, neige', c: ['#96c8ff', '#5a8cff', '#c8f0ff'] },
  { id: 'retro', label: 'Rétro 80', sub: 'Soleil rayé, horizon quadrillé', c: ['#ff3cc8', '#5028ff', '#ffd166'] },
  { id: 'midnight', label: 'Minuit', sub: 'Sobre et sombre, presque immobile', c: ['#4658aa', '#283c82', '#0b1020'] },
  { id: 'oled', label: 'Noir OLED', sub: 'Noir absolu, aucune animation', c: ['#000000', '#111111', '#2a2a2a'] },
];
// Les particules défilent d'une hauteur de motif (--p-size, propre à chaque thème) : on relance leur
// animation au changement de thème pour que le moteur recalcule l'image clé avec la nouvelle taille.
function setTheme(id) {
  if (document.body.dataset.theme === id) return;
  document.body.dataset.theme = id;
  const d = $('#bg .dust');
  if (d) { d.style.animation = 'none'; void d.offsetWidth; d.style.animation = ''; }
}
function applyLook() {
  const s = A.st.settings || {};
  if (!document.body.classList.contains('previewing')) setTheme(s.theme || 'aurora');
  document.body.classList.toggle('motion-calm', s.bg_motion === 'calm');
  document.body.classList.toggle('motion-off', s.bg_motion === 'off');
}
class ThemeLayer extends Layer {
  constructor(back) {
    super(`<div class="theme-picker"><h2>Thème de l'accueil</h2><p class="tp-sub"></p><div class="tp-view"><div class="tp-track"></div></div>
      <div class="hints">${hints([['dpad', 'Essayer'], ['a', 'Choisir'], ['b', 'Annuler']])}</div></div>`, 'themes', { keepBg: true });
    this.back = back;                                    // rouvre Réglages › Apparence après le choix
    this.saved = (A.st.settings || {}).theme || 'aurora';
    this.i = Math.max(0, THEMES.findIndex(x => x.id === this.saved));
    $('.tp-track', this.el).innerHTML = THEMES.map(x => `<div class="tp-card"><i style="background:radial-gradient(70% 60% at 25% 20%, ${x.c[0]}, transparent 70%),
      radial-gradient(60% 60% at 80% 35%, ${x.c[1]}, transparent 70%), radial-gradient(80% 60% at 50% 110%, ${x.c[2]}, transparent 70%), #05070d"></i><b>${esc(x.label)}</b></div>`).join('');
    document.body.classList.add('previewing');
    this.show();
  }
  show() {
    const x = THEMES[this.i];
    setTheme(x.id);                                      // aperçu en direct sur le vrai fond
    $$('.tp-card', this.el).forEach((c, i) => c.classList.toggle('focus', i === this.i));
    $('.tp-sub', this.el).textContent = x.sub;
    const card = $$('.tp-card', this.el)[this.i], view = $('.tp-view', this.el);
    $('.tp-track', this.el).style.transform = `translateX(${Math.min(0, view.clientWidth / 2 - card.offsetLeft - card.offsetWidth / 2)}px)`;
  }
  handle(b) {
    if (b === 'left' || b === 'right') {
      const n = this.i + (b === 'left' ? -1 : 1);
      if (n < 0 || n >= THEMES.length) return Sound.bump();
      this.i = n; this.show(); Sound.move();
    } else if (b === 'a') {
      Sound.select(); this.done(THEMES[this.i].id);
    } else if (b === 'b' || b === 'back') {
      Sound.back(); this.done(this.saved);
    }
  }
  done(id) {
    document.body.classList.remove('previewing');
    setTheme(id);
    if (id !== this.saved) setSetting('theme', id);
    this.close();
    if (this.back) this.back();
  }
}
function openThemes(back) { if (!A.layers.some(l => l instanceof ThemeLayer)) new ThemeLayer(back); }

// Mode ambiance : après quelques minutes sans rien toucher sur l'accueil, seuls le fond et l'heure restent.
const Ambient = {
  last: Date.now(), on: false, timer: null,
  touch() { this.last = Date.now(); if (this.on) { this.exit(); return true; } return false; },
  check() {
    const min = (A.st.settings || {}).ambient_min || 0;
    if (this.on || !min || A.layers.length || A.covered || document.hidden || document.body.classList.contains('bg-paused')) return;
    if (Date.now() - this.last >= min * 60000) this.enter();
  },
  enter() {
    this.on = true; this.tick(true);
    document.body.classList.add('ambient');
    Shell.send('ambient', { on: true });
    this.timer = setInterval(() => this.tick(false), 30000);
  },
  exit() {
    this.on = false; clearInterval(this.timer);
    document.body.classList.remove('ambient');
    Shell.send('ambient', { on: false });
  },
  tick(move) {
    const now = new Date(), el = $('#ambient .amb-clock');
    $('#ambient .t').textContent = clock(now);
    $('#ambient .d').textContent = dateLine(now);
    if (move || now.getSeconds() < 30) {                 // l'heure change de place chaque minute
      const x = 8 + Math.random() * 62, y = 12 + Math.random() * 58;
      el.style.transform = `translate(${x}vw, ${y}vh)`;
    }
  },
};
setInterval(() => Ambient.check(), 5000);

/* -------------------------------------------------------- Ajout de jeux --- */
const SYS_SHORT = { gba: 'GBA', nds: 'DS', n3ds: '3DS', gc: 'GameCube', wii: 'Wii', psx: 'PS1', ps2: 'PS2' };
const gbSize = n => n >= 1e9 ? `${(n / 1e9).toFixed(1).replace('.', ',')} Go` : `${Math.max(1, Math.round(n / 1e6))} Mo`;

// Écran « Ajouter des jeux » : QR code à scanner, adresse et code pour un ordinateur, arrivées en direct.
class UploadLayer extends Layer {
  constructor() {
    super(`<div class="scrim"></div><div class="sheet upload">
      <div class="up-main">
        <div class="up-qr"><div class="spinner"></div></div>
        <div class="up-text">
          <h2>Ajouter des jeux</h2>
          <ol class="up-steps">
            <li>Scanne ce code avec l'appareil photo de ton téléphone (même Wi-Fi que la console)</li>
            <li>Choisis tes jeux et tes BIOS, en vrac, même en .zip</li>
            <li>La console les range toute seule, jaquettes comprises</li>
          </ol>
          <div class="up-manual"></div>
        </div>
      </div>
      <div class="up-feed"><div class="up-now">En attente de fichiers…</div><div class="up-list"></div></div>
      <div class="hints">${hints([['b', 'Fermer']])}</div></div>`, 'uploads');
    this.items = [];
    Shell.call('upload-start').then(info => this.show(info || {}));
  }
  show(info) {
    $('.up-qr', this.el).innerHTML = info.qr || `<div class="up-noqr">${icon('wifi')}</div>`;
    const lines = [];
    if (!info.url) lines.push('La console n\'est pas connectée au réseau.');
    else lines.push(`Sur un ordinateur : <b>${esc(info.url)}</b>`);
    lines.push(`Code : <b class="up-code num">${esc(String(info.code || '').replace(/^(\d{3})(\d{3})$/, '$1 $2'))}</b>`);
    if (info.remote) lines.push(`À distance (Tailscale) : <b>${esc(info.remote)}</b>`);
    $('.up-manual', this.el).innerHTML = lines.map(l => `<div>${l}</div>`).join('');
  }
  event(ev) {
    const now = $('.up-now', this.el);
    if (ev.type === 'progress') {
      const pct = ev.total ? Math.floor(ev.done * 100 / ev.total) : 100;
      setHTML(now, `<span class="up-name">${icon('load')} ${esc(ev.name.split('/').pop())}</span><span class="num">${pct} %</span><span class="bar"><i style="transform:scaleX(${pct / 100})"></i></span>`);
    } else if (ev.type === 'sorting') {
      setHTML(now, `<span class="up-name">${icon('sparkle')} Rangement…</span>`);
    } else if (ev.type === 'done') {
      setHTML(now, 'En attente de fichiers…');
      const res = (ev.results || []).filter(r => ['game', 'bios', 'to_sort'].includes(r.kind) && ['added', 'present'].includes(r.status));
      this.items = res.map(r => r.kind === 'game' ? { cls: r.status === 'added' ? 'ok' : '', tag: SYS_SHORT[r.system] || r.system, label: r.label }
        : r.kind === 'bios' ? { cls: 'bios', tag: 'BIOS', label: r.label } : { cls: 'warn', tag: 'À trier', label: r.label }).concat(this.items).slice(0, 12);
      $('.up-list', this.el).innerHTML = this.items.map(i => `<div class="chip ${i.cls}"><b>${esc(i.tag)}</b>${esc(i.label)}</div>`).join('');
      if (res.some(r => r.status === 'added')) Sound.select();
    }
  }
  handle(b) { if (b === 'b' || b === 'back' || b === 'a') { Sound.back(); this.close(); } }
  close() { Shell.send('upload-stop'); super.close(); }
}
function openUpload() { if (!A.layers.some(l => l instanceof UploadLayer)) new UploadLayer(); }
Shell.on('upload', ev => { const l = A.layers.find(x => x instanceof UploadLayer); if (l) l.event(ev); });

// Clé USB : proposition, progression, fin.
class UsbProgressLayer extends Layer {
  constructor(label) {
    super(`<div class="scrim"></div><div class="sheet dialog usbprog"><h2>Importation depuis « ${esc(label)} »</h2>
      <p class="usb-cur">Préparation…</p><div class="bar big"><i></i></div><p class="usb-pct num"></p>
      <div class="hints">${hints([['x', 'Annuler'], ['b', 'Masquer']])}</div></div>`);
    this.finished = false;
  }
  update(ev) {
    if (this.finished) return;
    const pct = ev.total ? Math.min(100, Math.floor(ev.done * 100 / ev.total)) : 0;
    $('.usb-cur', this.el).textContent = ev.label || '';
    $('.bar i', this.el).style.transform = `scaleX(${pct / 100})`;
    $('.usb-pct', this.el).textContent = `${pct} % · ${gbSize(ev.done)} sur ${gbSize(ev.total)}`;
  }
  done(ev) {
    this.finished = true;
    $('h2', this.el).textContent = ev.removed ? 'Clé retirée pendant la copie' : ev.cancelled ? 'Importation arrêtée' : 'Importation terminée';
    $('.usb-cur', this.el).textContent = usbDoneText(ev);
    $('.bar i', this.el).style.transform = 'scaleX(1)';
    $('.usb-pct', this.el).textContent = ev.removed ? '' : 'Tu peux retirer la clé.';
    setHTML($('.hints', this.el), hints([['a', 'OK']]));
  }
  handle(b) {
    if (this.finished) { if (['a', 'b', 'back'].includes(b)) { Sound.select(); this.close(); } return; }
    if (b === 'x') confirm('Arrêter l\'importation ?', 'Les jeux déjà copiés restent sur la console.', 'Arrêter', () => Shell.send('usb-cancel'), true);
    else if (b === 'b' || b === 'back') { Sound.back(); A.usbHidden = true; this.close(); }
  }
}
function usbDoneText(ev) {
  const parts = [];
  if (ev.games) parts.push(`${ev.games} jeu${ev.games > 1 ? 'x' : ''}`);
  if (ev.bios) parts.push(`${ev.bios} BIOS`);
  let t = parts.length ? `${parts.join(' et ')} ajouté${ev.games + ev.bios > 1 ? 's' : ''}.` : 'Rien de nouveau ajouté.';
  if (ev.to_sort) t += ` ${ev.to_sort} fichier${ev.to_sort > 1 ? 's' : ''} non reconnu${ev.to_sort > 1 ? 's' : ''} dans « _À trier ».`;
  if (ev.errors && ev.errors.length) t += ` Problème : ${ev.errors[0]}.`;
  return t;
}
Shell.on('usb', ev => {
  const prog = A.layers.find(l => l instanceof UsbProgressLayer);
  if (ev.type === 'found') {
    const s = ev.summary, n = Object.values(s.games).reduce((a, b) => a + b, 0), lines = [];
    if (n) lines.push(`<b>${n} jeu${n > 1 ? 'x' : ''}</b> : ${Object.entries(s.games).map(([k, v]) => `${esc(SYS_SHORT[k] || k)} ${v}`).join(' · ')}`);
    if (s.bios.length) lines.push(`<b>BIOS</b> : ${s.bios.map(esc).join(', ')}`);
    if (s.archives) lines.push(`${s.archives} archive${s.archives > 1 ? 's' : ''} à décompresser`);
    if (s.to_sort) lines.push(`${s.to_sort} fichier${s.to_sort > 1 ? 's' : ''} non reconnu${s.to_sort > 1 ? 's' : ''} : laissé${s.to_sort > 1 ? 's' : ''} sur la clé`);
    if (s.present) lines.push(`${s.present} déjà sur la console : ignoré${s.present > 1 ? 's' : ''}`);
    Sound.select();
    menu({ title: `Clé USB « ${ev.label} »`, text: lines.join('<br>'), onCancel: () => Shell.send('usb-dismiss'), items: [
      { icon: 'check', label: 'Importer', sub: gbSize(s.size), action: () => { A.usbHidden = false; Shell.send('usb-import'); new UsbProgressLayer(ev.label); } },
      { icon: 'back', label: 'Ne rien faire', action: () => Shell.send('usb-dismiss') }] });
  } else if (ev.type === 'progress') {
    if (prog) prog.update(ev);
  } else if (ev.type === 'done') {
    if (prog) prog.done(ev);
    else notice(ev.cancelled ? 'Importation arrêtée' : 'Importation terminée', `${usbDoneText(ev)} ${ev.removed ? '' : 'Tu peux retirer la clé.'}`);
  } else if (ev.type === 'removed') {
    A.layers.filter(l => l instanceof MenuLayer && /^Clé USB/.test($('h2', l.el).textContent)).forEach(l => l.close());
  }
});

// Réglages › Jeux : état des BIOS (Ⓐ sur une ligne ouvre « Ajouter des jeux »)
function biosRows(b, out, open) {
  if (!b) { out.push({ static: true, icon: 'chip', title: 'Vérification des BIOS…' }); return; }
  const val = (cls, t) => `<span class="hval ${cls}">${t}</span>`;
  const R = { eu: 'Europe', us: 'USA', jp: 'Japon' }, F = { eu: 'scph5502', us: 'scph5501', jp: 'scph5500' };
  const p2 = b.ps2.have;
  out.push({ icon: 'chip', title: 'PlayStation 2', act: open,
    sub: p2.length ? p2.map(x => `${x.zone} v${x.version} (${x.date.slice(-4)})`).join(' · ') : 'Obligatoire pour jouer : le BIOS de ta PS2, n\'importe quel nom',
    value: p2.length ? val('ok', 'Prêt') : val(b.ps2.games ? 'bad' : 'warn', 'Manquant') });
  const have = Object.keys(b.psx.have).filter(k => R[k]).map(k => R[k]);
  const miss = b.psx.missing.map(r => `${R[r]} (${F[r]}.bin)`);
  out.push({ icon: 'chip', title: 'PlayStation', act: open,
    sub: miss.length ? `Il manque ${miss.join(', ')} pour tes jeux de ${miss.length > 1 ? 'ces régions' : 'cette région'}`
      : have.length ? `Présents : ${have.join(', ')}` : 'Conseillé : un par région (scph5502 Europe, scph5501 USA, scph5500 Japon)',
    value: miss.length ? val('warn', 'Incomplet') : have.length ? val('ok', 'Prêt') : val('', 'Conseillé') });
  out.push({ icon: 'chip', title: 'Nintendo DS', act: open, sub: b.nds.length ? b.nds.join(', ') : 'Facultatif : bios7.bin, bios9.bin',
    value: b.nds.length ? val('ok', 'Présent') : val('', 'Facultatif') });
  out.push({ icon: 'chip', title: 'Game Boy Advance', act: open, sub: b.gba.length ? 'gba_bios.bin' : 'Facultatif : gba_bios.bin',
    value: b.gba.length ? val('ok', 'Présent') : val('', 'Facultatif') });
  out.push({ icon: 'info', title: '3DS, GameCube et Wii', sub: 'Aucun BIOS nécessaire', act: open });
  if (b.unknown.length) out.push({ icon: 'warning', title: `${b.unknown.length} fichier${b.unknown.length > 1 ? 's' : ''} non reconnu${b.unknown.length > 1 ? 's' : ''} dans BIOS`,
    sub: b.unknown.slice(0, 3).join(', ') + (b.unknown.length > 3 ? '…' : ''), act: open });
}

/* ------------------------------------------------------------- Santé ----- */
function healthRows(d, out, refresh) {
  if (!d) { out.push({ icon: 'pulse', title: 'Analyse en cours…' }); return; }
  // Lignes sélectionnables (sans action) : c'est ce qui permet de faire défiler la page à la manette.
  const go = v => (v / 1e9).toFixed(v >= 100e9 ? 0 : 1) + ' Go';
  const deg = v => (v == null ? '—' : `${Math.round(v)} °C`);
  const tag = (txt, cls) => `<span class="hval ${cls || ''}">${esc(txt)}</span>`;
  const warn = d.warnings || [];
  out.push({ group: 'État général' });
  if (!warn.length) out.push({ icon: 'check', title: 'Tout va bien', sub: 'Aucun problème détecté', value: tag('OK', 'ok') });
  warn.forEach(w => out.push({ icon: 'warning', title: w.level === 'bad' ? 'Problème' : 'Attention', sub: w.text, value: tag(w.level === 'bad' ? '!' : '•', w.level) }));

  const s = d.ssd || {};
  out.push({ group: 'Disque (SSD)' });
  if (d.privileged === false || !d.ssd) {
    out.push({ icon: 'disk', title: s.model || 'SSD', sub: d.privileged === false ? 'Détails indisponibles : mets la console à jour (update.sh)' : 'Lecture de l\'état SMART…' });
  } else {
    out.push({ icon: 'disk', title: s.model || 'SSD', sub: s.power_on_hours != null ? `${s.power_on_hours} h d'utilisation · ${s.unsafe_shutdowns ?? '—'} coupures brusques` : '',
      value: tag(s.passed === false || s.critical_warning ? 'Problème' : 'Sain', s.passed === false || s.critical_warning ? 'bad' : 'ok') });
    out.push({ icon: 'pulse', title: 'Erreurs depuis le démarrage', sub: 'Décrochages ou erreurs de lecture/écriture vus par le système',
      value: tag(String(d.io_errors ?? '—'), d.io_errors ? 'bad' : 'ok') });
    if (s.percentage_used != null) out.push({ icon: 'chip', title: 'Usure', sub: `Réserve disponible : ${s.available_spare ?? '—'} %`,
      value: tag(`${s.percentage_used} %`, s.percentage_used >= 90 ? 'warn' : 'ok') });
  }
  if (d.disk) out.push({ icon: 'folder', title: 'Espace libre', sub: `sur ${go(d.disk.total)}`, value: tag(go(d.disk.free), d.disk.free < 10e9 ? 'warn' : '') });
  if (d.readonly) out.push({ icon: 'warning', title: 'Disque en lecture seule', sub: 'Redémarre la console', value: tag('!', 'bad') });

  const t = d.temps || {};
  out.push({ group: 'Températures' });
  out.push({ icon: 'thermo', title: 'Processeur', value: tag(deg(t.cpu), (t.cpu || 0) >= 90 ? 'warn' : '') });
  out.push({ icon: 'thermo', title: 'SSD', value: tag(deg(t.ssd ?? s.temperature), ((t.ssd ?? s.temperature) || 0) >= 70 ? 'warn' : '') });

  const m = d.memory || {};
  out.push({ group: 'Système' });
  if (m.total) out.push({ icon: 'chip', title: 'Mémoire disponible', sub: `sur ${go(m.total)}`, value: tag(go(m.available || 0), (m.available || 0) < 300e6 ? 'warn' : '') });
  const up = Math.floor((d.uptime || 0) / 60);
  out.push({ icon: 'power', title: 'Allumée depuis', sub: `charge : ${d.load ?? '—'}`, value: tag(up >= 1440 ? `${Math.floor(up / 1440)} j ${Math.floor(up % 1440 / 60)} h` : `${Math.floor(up / 60)} h ${String(up % 60).padStart(2, '0')}`) });

  out.push({ group: 'Réseau et PC distant' });
  const ts = d.tailscale;
  out.push({ icon: 'link', title: 'Tailscale', sub: ts == null ? 'Non installé' : ts.running ? `Connecté · ${ts.ip || ''}` : 'Déconnecté',
    value: tag(ts == null ? '—' : ts.running ? 'OK' : 'Hors ligne', ts == null ? '' : ts.running ? 'ok' : 'warn') });
  (d.pcs || []).forEach(pc => out.push({ icon: 'stream', title: pc.name,
    sub: pc.online ? (pc.sunshine === 'half' ? 'Sunshine bloqué' : 'Sunshine répond') : 'Ne répond pas (en veille ou éteint)',
    value: tag(pc.online ? (pc.latency != null ? `${pc.latency} ms` : 'en ligne') : 'hors ligne', pc.online ? (pc.sunshine === 'half' ? 'warn' : 'ok') : '') }));
  if ((d.pads || []).length) {
    out.push({ group: 'Manettes' });
    d.pads.forEach(p => out.push({ icon: 'battery', title: p.name, value: tag(typeof p.battery === 'number' ? `${p.battery} %` : '—', p.battery <= 20 ? 'warn' : 'ok') }));
  }
  out.push({ group: ' ' });
  out.push({ icon: 'restart', title: 'Actualiser', sub: 'Relit aussi l\'état SMART du disque', act: refresh });
}

function openSettings(section) { if (!A.settings) new SettingsLayer(section); }
function signalBars(s) {
  const n = s >= 75 ? 4 : s >= 50 ? 3 : s >= 25 ? 2 : 1;
  return `<span class="signal">${[1, 2, 3, 4].map(i => `<i class="${i <= n ? 'on' : ''}" style="height:${i * 25}%"></i>`).join('')}</span>`;
}

/* ------------------------------------------------------ Appairage manette --- */
const PAD_SVG = `<svg class="pad-illus" viewBox="0 0 240 150" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round">
  <path d="M70 30h100c22 0 37 13 41 34l9 46c4 22-23 34-38 17l-17-19H75l-17 19c-15 17-42 5-38-17l9-46c4-21 19-34 41-34z"/>
  <circle cx="120" cy="52" r="10"/><circle class="halo" cx="120" cy="52" r="18" stroke-opacity=".5"/>
  <circle cx="165" cy="70" r="6"/><circle cx="180" cy="56" r="6"/><circle cx="150" cy="56" r="6"/><circle cx="165" cy="42" r="6"/>
  <path d="M68 52v26M55 65h26"/><rect x="104" y="18" width="32" height="8" rx="4" stroke-opacity=".9"/></svg>`;

class PairingLayer extends Layer {
  constructor(onDone) {
    super(`<div class="scrim" style="background:rgba(3,5,10,.9)"></div><div class="center-stage"><div class="stage">
      ${PAD_SVG}<h2>Associer une manette Xbox</h2>
      <p>Allume la manette (bouton Xbox), puis <b>maintiens 3 secondes le petit bouton d'appairage</b> sur le dessus, près du port USB, jusqu'à ce que le logo clignote rapidement.</p>
      <div class="state-line"><span class="spinner" style="width:1.2rem;height:1.2rem;border-width:.15rem"></span><span class="txt">Recherche…</span></div>
      <div class="hints" style="justify-content:center;margin-top:2rem">${hints([['b', 'Annuler']])}</div></div></div>`);
    this.onDone = onDone;
    Shell.call('bt-pair-start', { seconds: 120 }).then(ok => { if (ok === false) this.state({ state: 'failed', error: 'Bluetooth indisponible' }); });
  }
  state(ev) {
    const line = $('.state-line', this.el), txt = $('.txt', this.el);
    line.classList.remove('ok', 'bad');
    if (ev.state === 'pairing') txt.textContent = `Association de ${ev.name}…`;
    else if (ev.state === 'paired') {
      line.classList.add('ok'); line.innerHTML = `${icon('check')}<span>${esc(ev.name)} est prête !</span>`;
      setTimeout(() => { this.close(); this.onDone && this.onDone(true); }, 1600);
    } else if (ev.state === 'failed') { line.classList.add('bad'); line.innerHTML = `${icon('warning')}<span>Échec${ev.error ? ' : ' + esc(ev.error) : ''} — réessaie l'appui long</span>`; }
    else if (ev.state === 'stopped' && !line.classList.contains('ok')) { txt.textContent = 'Recherche terminée. Ⓑ pour fermer, ou relance l\'appairage.'; }
  }
  handle(b) {
    if (b === 'b' || b === 'back') { Shell.send('bt-pair-stop'); Sound.back(); this.close(); this.onDone && this.onDone(false); }
  }
}
function openPairing(onDone) { return new PairingLayer(onDone); }

/* --------------------------------------------------------- Test du réveil -- */
function wakeTest() {
  confirm('Tester le réveil par la manette', 'La console va se mettre en veille. Quand l\'écran est noir, attends 10 secondes puis appuie sur le bouton Xbox de la manette. Sans réaction, elle se rallumera seule au bout d\'environ 75 secondes.',
    'Lancer le test', () => {
      const wait = menu({ title: 'Mise en veille…', text: 'Attends que l\'écran soit noir, puis 10 secondes, puis bouton Xbox.', items: [{ icon: 'back', label: 'OK' }] });
      Shell.call('wake-test').then(ok => { if (ok === false) { wait.close(); notice('Test impossible', 'L\'horloge de réveil n\'est pas disponible.'); } });
    });
}
function wakeTestResult(r) {
  A.layers.slice().forEach(l => l instanceof MenuLayer && l.close());
  if (r.ok) notice('Réveil par la manette : OK ✓', 'Parfait : la veille profonde est utilisable. La console se rallumera quand tu appuieras sur le bouton Xbox.');
  else {
    const why = r.by_rtc ? 'La manette n\'a pas réussi à réveiller la console (c\'est le minuteur de secours qui l\'a fait).' : r.lid_open ? 'La console semble avoir été réveillée par l\'ouverture du capot.' : 'Le réveil ne venait pas de la manette.';
    const items = [{ icon: 'check', label: 'Utiliser la veille légère', sub: 'réveil instantané, fiable' }];
    if ((r.other_modes || []).length) items.unshift({ icon: 'restart', label: `Réessayer avec le mode « ${r.other_modes[0]} »`, action: () => Shell.call('mem-sleep', { mode: r.other_modes[0] }).then(() => { setSetting('standby_mode', 'deep'); wakeTest(); }) });
    menu({ title: 'Le réveil par la manette n\'a pas marché', text: esc(why) + ' La console passe en veille légère (écran coupé, réveil instantané).', items });
  }
}

/* -------------------------------------------------------------- Assistant -- */
class Wizard extends Layer {
  constructor() {
    super(`<div class="scrim" style="background:rgba(3,5,10,.94)"></div><div class="center-stage"><div class="stage"></div></div>`);
    this.step = 0; this.i = 0; this.render();
  }
  steps() { return ['welcome', 'pad', 'net', 'sleep', 'done']; }
  render() {
    const step = this.steps()[this.step], st = A.st, stage = $('.stage', this.el);
    const dots = `<div class="steps">${this.steps().map((_, i) => `<i class="${i <= this.step ? 'on' : ''}"></i>`).join('')}</div>`;
    let body = '', actions = [];
    if (step === 'welcome') {
      body = `<div class="logo">${icon('gamepad')}</div><h1>Bienvenue sur ${esc(st.name || 'Nova')}</h1>
        <p>Ta console est presque prête. Quelques réglages rapides et c'est parti.</p>`;
      actions = [{ label: 'Commencer', act: () => this.next() }];
    } else if (step === 'pad') {
      const has = (st.pads || []).length > 0;
      body = `${PAD_SVG}<h2>La manette</h2>` + (has
        ? `<p>Une manette est connectée : <b>${esc(st.pads[0].name)}</b>.</p><div class="state-line ok">${icon('check')}<span>Prête</span></div>`
        : `<p>Associe ta manette Xbox : allume-la, puis maintiens 3 s le bouton d'appairage (sur le dessus) jusqu'à ce que le logo clignote vite.</p>`);
      actions = has ? [{ label: 'Continuer', act: () => this.next() }, { label: 'Associer une autre manette', act: () => openPairing(() => this.render()) }]
        : [{ label: 'Associer la manette', act: () => openPairing(ok => ok ? this.next() : this.render()) }, { label: 'Passer', act: () => this.next() }];
    } else if (step === 'net') {
      const net = st.net || {};
      body = `<div class="logo">${icon(net.kind === 'ethernet' ? 'ethernet' : 'wifi')}</div><h2>Réseau</h2>` + (net.connected
        ? `<p>Connectée en ${net.kind === 'ethernet' ? 'Ethernet' : 'Wi-Fi (' + esc(net.name) + ')'}. Pour Moonlight, l'Ethernet ou le Wi-Fi 5 GHz sont idéaux.</p><div class="state-line ok">${icon('check')}<span>${esc(net.ip || '')}</span></div>`
        : `<p>Pas de connexion. Choisis un réseau Wi-Fi dans les réglages.</p>`);
      actions = net.connected ? [{ label: 'Continuer', act: () => this.next() }] : [{ label: 'Choisir un Wi-Fi', act: () => openSettings('net') }, { label: 'Passer', act: () => this.next() }];
    } else if (step === 'sleep') {
      body = `<div class="logo">${icon('moon')}</div><h2>Veille et réveil</h2>
        <p>Comme une vraie console : mets-la en veille avec le menu ${glyph('start')}, ou éteins simplement la manette. Un appui sur le bouton Xbox la rallume.</p>
        <p>Teste maintenant si ta manette peut réveiller la console (1 minute).</p>`;
      actions = [{ label: 'Tester le réveil', act: () => { this.next(); wakeTest(); } }, { label: 'Plus tard', act: () => this.next() }];
    } else {
      body = `<div class="logo">${icon('check')}</div><h1>Tout est prêt</h1>
        <p>${glyph('guide')} bouton Xbox : menu de la console (maintenu : partout, même en streaming).<br>${glyph('start')} Menu sur l'accueil : veille et arrêt.</p>`;
      actions = [{ label: 'C\'est parti', act: () => { Shell.send('settings-set', { key: 'first_run_done', value: true }); this.close(); } }];
    }
    this.actions = actions; this.i = Math.min(this.i, actions.length - 1);
    stage.innerHTML = dots + body + `<div class="actions">${actions.map((a, i) => `<div class="btn${i === this.i ? ' focus' : ''}">${esc(a.label)}</div>`).join('')}</div>`;
  }
  next() { this.step = Math.min(this.step + 1, this.steps().length - 1); this.i = 0; Sound.select(); this.render(); }
  handle(b) {
    if (b === 'left' || b === 'right') { const n = this.i + (b === 'left' ? -1 : 1); if (n >= 0 && n < this.actions.length) { this.i = n; Sound.move(); this.render(); } else Sound.bump(); }
    else if (b === 'a') { Sound.select(); this.actions[this.i].act(); }
    else if (b === 'b' && this.step > 0) { this.step--; this.i = 0; Sound.back(); this.render(); }
  }
  refresh() { this.render(); }
}
function startWizard() { if (!A.layers.some(l => l instanceof Wizard)) A.wizard = new Wizard(); }

/* --------------------------------------------------------------- Entrées --- */
function handleButton(b) {
  if (Ambient.touch()) return;                           // sortie du mode ambiance : rien d'autre
  const top = A.layers[A.layers.length - 1];
  if (top) { top.handle(b); renderHintsSoon(); return; }
  homeButton(b);
}
function renderHintsSoon() { clearTimeout(A.hintT); A.hintT = setTimeout(renderHints, 30); }

Shell.on('pad', ev => handleButton(ev.button));
Shell.on('state', partial => {
  Object.assign(A.st, partial || {});
  if (partial && partial.settings) { Sound.enabled = partial.settings.ui_sounds !== false; applyLook(); }
  if (partial && partial.pads && partial.pads.length) Pad.kind = partial.pads[0].kind === 'playstation' ? 'playstation' : 'xbox';
  scheduleRender(partial || {});
});
// Fond animé en pause quand l'accueil est caché (appli ou jeu au premier plan) : rien ne tourne pour rien.
const pauseBg = paused => document.body.classList.toggle('bg-paused', paused);
Shell.on('shown', () => { A.covered = false; Ambient.last = Date.now(); pauseBg(false); renderAll(); });
Shell.on('covered', () => { A.covered = true; Ambient.touch(); });
Shell.on('hidden', () => { pauseBg(true); Sound.sleep(); if (Ambient.on) Ambient.exit(); });
Shell.on('wake-ui', () => Ambient.touch());
document.addEventListener('visibilitychange', () => pauseBg(document.hidden));
Shell.on('power-menu', () => powerMenu());
Shell.on('pairing', ev => { A.layers.forEach(l => l instanceof PairingLayer && l.state(ev)); });
Shell.on('wake-test', r => wakeTestResult(r));
Shell.on('wake', () => {
  document.body.appendChild(h('<div class="welcome-back"></div>'));
  setTimeout(() => $$('.welcome-back').forEach(e => e.remove()), 2000);
  const run = (A.st.apps && A.st.apps.last) ? tiles().findIndex(t => t.id === A.st.apps.last) : -1;
  if (run >= 0) { A.ti = run; A.zone = 'row'; }
  renderAll();
});
Shell.on('dialog', d => {
  if (d.kind === 'close-first') {
    // Le jeu en cours est d'abord mis de côté et fermé ; le shell lance l'autre une fois la fenêtre partie.
    confirm('Fermer le jeu en cours ?', 'Un autre jeu est déjà lancé. Sa partie sera mise de côté avant de lancer celui-ci.', 'Fermer et lancer',
      () => Shell.send('close-app', { app: d.app, next: d.next }), true);
  }
});

function scheduleRender(partial) {
  if (A.renderPending) { A.renderKeys = new Set([...A.renderKeys, ...Object.keys(partial)]); return; }
  A.renderPending = true; A.renderKeys = new Set(Object.keys(partial));
  requestAnimationFrame(() => {
    A.renderPending = false;
    const k = A.renderKeys;
    const all = k.has('tiles') || k.has('version');
    renderTop();
    if (all || k.has('apps') || k.has('moonlight')) {
      const sig = JSON.stringify(tiles()) + JSON.stringify((A.st.moonlight || []).map(h => [h.online, h.busy]));
      if (sig !== A.sig.row) { A.sig.row = sig; renderRow(); }
    }
    renderCaption();
    if (all || k.has('moonlight') || k.has('library') || k.has('presets') || k.has('net')) renderShelf(true);
    renderSys(); renderHints();
    if (A.settings && k.has('bios_changed') && SECTIONS[A.settings.sec].id === 'games') A.settings.loadBios();
    if (A.settings && ['bt', 'net', 'settings', 'display', 'sleep', 'moonlight', 'moonlight_pins', 'pc_remote', 'covers'].some(x => k.has(x))) A.settings.render();
    if (A.wizard && A.layers.includes(A.wizard) && (k.has('pads') || k.has('net'))) A.wizard.refresh();
    if (A.st.settings && A.st.settings.first_run_done === false && !A.wizardShown) { A.wizardShown = true; startWizard(); }
  });
}

document.addEventListener('keydown', e => {
  if (Ambient.touch()) { e.preventDefault(); return; }
  const top = A.layers[A.layers.length - 1];
  if (top && top.key && top.key(e)) { e.preventDefault(); return; }
  const b = keyToButton(e);
  if (b) { e.preventDefault(); handleButton(b); }
});
setInterval(renderTop, 15000);

Shell.call('state').then(st => { if (st) { Object.assign(A.st, st); Sound.enabled = (st.settings || {}).ui_sounds !== false; applyLook(); A.sig = {}; renderAll(); scheduleRender(st); } });
renderAll();
