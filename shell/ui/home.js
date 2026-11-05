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
    const state = def.busy && def.current ? `en jeu : ${esc(def.current)}` : def.online ? 'en ligne' : def.online === false ? (def.wol ? 'en veille, réveil automatique' : 'hors ligne') : '…';
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
      const state = hst.busy ? 'busy' : hst.online ? 'on' : '';
      const line = hst.busy ? `En jeu${hst.current ? ' : ' + esc(hst.current) : ''}` : hst.online ? 'En ligne' : hst.online === false ? (hst.wol ? 'En veille — réveil automatique' : 'Hors ligne') : 'Recherche…';
      items.push({ html: `<div class="card wide">${icon('stream')}<div><h3>${esc(hst.name)}</h3><p><span class="status-dot ${state}"></span>&nbsp; ${line}<br>${(A.st.moonlight_pins || []).includes(hst.uuid) ? '🔒 code PIN Windows enregistré' : 'Réglages › Moonlight : code PIN Windows'}</p></div></div>`,
        act: () => openSettings('moonlight') });
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
    recent.forEach(g => {
      const ph = `<div class="ph" style="background:linear-gradient(160deg, ${g.color || '#555'}, #0b0f1a)">${esc(g.short)}</div>`;
      items.push({ html: `<div class="card poster">${g.cover ? `<img src="${esc(fileUrl(g.cover))}" alt="">` : ph}<span class="sys">${esc(g.short)}</span><div class="cap">${esc(g.name)}<small>${esc(g.systemName)}</small></div></div>`,
        act: () => playGame(g), art: g.cover, label: g.name });
    });
    systems.filter(s => s.count).forEach(s => items.push({
      html: `<div class="card square" style="background:linear-gradient(160deg, ${rgba(s.color, .55)}, rgba(255,255,255,.04))"><b>${esc(s.short)}</b><span>${s.count} jeu${s.count > 1 ? 'x' : ''}</span></div>`,
      act: () => Shell.send('library-open', { system: s.id }), label: s.name }));
    if (!total) {
      const host = (st.net && st.net.hostname) || 'console';
      items.push({ html: `<div class="card tip" style="grid-template-columns:1fr">${icon('folder')}<div><b>Ajoute tes jeux</b>&nbsp;: depuis ton PC, ouvre <b>\\\\${esc(host)}\\Jeux</b> et dépose-les dans le dossier de chaque console (gba, nds, n3ds, gc, wii, psx, ps2). BIOS PS1/PS2 dans <b>\\\\${esc(host)}\\BIOS</b>.</div></div>`, act: null });
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
  } else if (A.zone === 'shelf') list = [['a', 'Lancer'], ['b', 'Retour']];
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
        A.si = n; A.shelfMemo[focusedTile().id] = n; markShelf(); Sound.move();
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
    case 'y': if (A.zone === 'row' && !['add', 'running'].includes(focusedTile().type)) tileOptions(focusedTile()); return;
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
function stream(host, app) { Sound.launch(); Shell.send('moonlight-stream', { uuid: host.uuid, app: app.name }); }
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
  constructor(html, cls = '') {
    this.el = h(`<div class="layer ${cls}">${html}</div>`);
    $('#layers').appendChild(this.el);
    A.layers.push(this);
    document.body.classList.add('layers-open');      // fond animé en pause derrière le voile
  }
  close() {
    const i = A.layers.indexOf(this); if (i >= 0) A.layers.splice(i, 1);
    document.body.classList.toggle('layers-open', A.layers.length > 0);
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
  { id: 'display', icon: 'display', label: 'Image et son' },
  { id: 'sleep', icon: 'moon', label: 'Veille' },
  { id: 'browser', icon: 'keyboard', label: 'Navigateur et clavier' },
  { id: 'system', icon: 'chip', label: 'Système' },
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
  }
  close() { super.close(); A.settings = null; }
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
  const top = A.layers[A.layers.length - 1];
  if (top) { top.handle(b); renderHintsSoon(); return; }
  homeButton(b);
}
function renderHintsSoon() { clearTimeout(A.hintT); A.hintT = setTimeout(renderHints, 30); }

Shell.on('pad', ev => handleButton(ev.button));
Shell.on('state', partial => {
  Object.assign(A.st, partial || {});
  if (partial && partial.settings) Sound.enabled = partial.settings.ui_sounds !== false;
  if (partial && partial.pads && partial.pads.length) Pad.kind = partial.pads[0].kind === 'playstation' ? 'playstation' : 'xbox';
  scheduleRender(partial || {});
});
// Fond animé en pause quand l'accueil est caché (appli ou jeu au premier plan) : rien ne tourne pour rien.
const pauseBg = paused => document.body.classList.toggle('bg-paused', paused);
Shell.on('shown', () => { pauseBg(false); renderAll(); });
Shell.on('hidden', () => { pauseBg(true); Sound.sleep(); });
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
    confirm('Fermer le jeu en cours ?', 'Un autre jeu est déjà lancé. Le fermer pour lancer celui-ci ?', 'Fermer et lancer', () => {
      Shell.send('close-app', { app: d.app });
      setTimeout(() => Shell.send(d.next.cmd, d.next.args), 2500);
    }, true);
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
    if (A.settings && (k.has('bt') || k.has('net') || k.has('settings') || k.has('display') || k.has('sleep') || k.has('moonlight') || k.has('moonlight_pins'))) A.settings.render();
    if (A.wizard && A.layers.includes(A.wizard) && (k.has('pads') || k.has('net'))) A.wizard.refresh();
    if (A.st.settings && A.st.settings.first_run_done === false && !A.wizardShown) { A.wizardShown = true; startWizard(); }
  });
}

document.addEventListener('keydown', e => {
  const top = A.layers[A.layers.length - 1];
  if (top && top.key && top.key(e)) { e.preventDefault(); return; }
  const b = keyToButton(e);
  if (b) { e.preventDefault(); handleButton(b); }
});
setInterval(renderTop, 15000);

Shell.call('state').then(st => { if (st) { Object.assign(A.st, st); Sound.enabled = (st.settings || {}).ui_sounds !== false; A.sig = {}; renderAll(); scheduleRender(st); } });
renderAll();
