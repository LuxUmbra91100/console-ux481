/* Faux shell pour prévisualiser l'interface dans un navigateur (hors console). */
'use strict';
(function () {
  const art = (title, c1, c2, w = 300, hh = 420) => 'data:image/svg+xml;utf8,' + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${hh}"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/></linearGradient>
    <radialGradient id="r" cx=".3" cy=".25" r=".8"><stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>
    <rect width="${w}" height="${hh}" fill="url(#g)"/><rect width="${w}" height="${hh}" fill="url(#r)"/>
    <circle cx="${w * .72}" cy="${hh * .32}" r="${w * .32}" fill="#fff" fill-opacity=".08"/>
    <circle cx="${w * .2}" cy="${hh * .78}" r="${w * .5}" fill="#000" fill-opacity=".12"/></svg>`);
  const S = {
    version: '1.0', name: 'Nova',
    settings: { console_name: 'Nova', standby_mode: 'deep', deep_sleep_verified: null, auto_standby_min: 15,
      controller_off_standby: true, resolution: '1080p', ui_sounds: false, osk_layout: 'azerty', browser_scale: 1.5,
      guide_hold_ms: 700, first_run_done: !/wizard/.test(location.hash),
      moonlight_host: '', moonlight_tile_app: 'Steam Big Picture', moonlight_pin_mode: 'wake',
      theme: 'aurora', bg_motion: 'full', ambient_min: 5, covers_auto: true, resume_games: true },
    tiles: [
      { id: 'moonlight', type: 'moonlight', running: false },
      { id: 'games', type: 'games', running: true },
      { id: 'brave', type: 'brave', running: false },
      { id: 'site-youtube', type: 'site', title: 'YouTube', url: 'https://www.youtube.com/', color: '#ff0033', control: 'pointer', icon: null },
      { id: 'site-netflix', type: 'site', title: 'Netflix', url: 'https://www.netflix.com/', color: '#e50914', control: 'pointer', icon: null },
      { id: 'site-twitch', type: 'site', title: 'Twitch', url: 'https://www.twitch.tv/', color: '#9146ff', control: 'pointer', icon: null },
    ],
    apps: { running: [{ id: 'games', title: 'Jeux', kind: 'esde' }], foreground: null, last: 'games' },
    pads: [{ id: 0, name: 'Xbox Series X Controller', kind: 'xbox', power: 90 }],
    bt: { available: true, pairing: false, gamepads: [{ path: '/org/bluez/hci0/dev_1', name: 'Xbox Wireless Controller', connected: true, battery: 80 }] },
    net: { kind: 'wifi', connected: true, name: 'Livebox-5G', signal: 82, ip: '192.168.1.42', hostname: 'console' },
    moonlight: [{ uuid: 'u1', name: 'PC-SALON', online: true, busy: false, current: null, wol: true, apps: [
      { id: 1, name: 'Bureau', boxart: art('Bureau', '#0ea5e9', '#1e3a8a') },
      { id: 2, name: 'Steam Big Picture', boxart: art('Steam', '#1e293b', '#0f172a') },
      { id: 3, name: 'Forza Horizon 5', boxart: art('Forza 5', '#f97316', '#7c2d12') },
      { id: 4, name: 'Elden Ring', boxart: art('Elden Ring', '#a16207', '#1c1917') },
      { id: 5, name: 'Hades II', boxart: art('Hades II', '#7c3aed', '#1e1b4b') },
      { id: 6, name: 'Baldur\'s Gate 3', boxart: null },
    ] }],
    library: {
      systems: [
        { id: 'gba', name: 'Game Boy Advance', short: 'GBA', color: '#7b5cff', count: 14 },
        { id: 'nds', name: 'Nintendo DS', short: 'DS', color: '#9aa4b5', count: 9 },
        { id: 'n3ds', name: 'Nintendo 3DS', short: '3DS', color: '#e5383b', count: 4 },
        { id: 'gc', name: 'GameCube', short: 'GC', color: '#6c4ee0', count: 7 },
        { id: 'wii', name: 'Wii', short: 'Wii', color: '#3fb6e8', count: 5 },
        { id: 'psx', name: 'PlayStation', short: 'PS1', color: '#b0b4bd', count: 11 },
        { id: 'ps2', name: 'PlayStation 2', short: 'PS2', color: '#2f6bff', count: 8 },
      ],
      recent: [
        { system: 'gc', systemName: 'GameCube', short: 'GC', color: '#6c4ee0', path: '/a', name: 'Metroid Prime', cover: art('Metroid Prime', '#ea580c', '#431407'), direct: true, resume: true },
        { system: 'ps2', systemName: 'PlayStation 2', short: 'PS2', color: '#2f6bff', path: '/b', name: 'Shadow of the Colossus', cover: art('Colossus', '#57534e', '#0c0a09'), direct: true },
        { system: 'gba', systemName: 'Game Boy Advance', short: 'GBA', color: '#7b5cff', path: '/c', name: 'Golden Sun', cover: art('Golden Sun', '#eab308', '#713f12'), direct: true },
        { system: 'nds', systemName: 'Nintendo DS', short: 'DS', color: '#9aa4b5', path: '/d', name: 'Phoenix Wright', cover: null, direct: true },
      ],
    },
    presets: [
      { title: 'YouTube TV', url: 'https://www.youtube.com/tv', color: '#ff0033', control: 'tv', tv: true, note: 'Interface télé' },
      { title: 'Netflix', url: 'https://www.netflix.com/', color: '#e50914' },
      { title: 'Prime Video', url: 'https://www.primevideo.com/', color: '#1a98ff' },
      { title: 'Disney+', url: 'https://www.disneyplus.com/', color: '#113ccf' },
      { title: 'Spotify', url: 'https://open.spotify.com/', color: '#1db954' },
      { title: 'Arte', url: 'https://www.arte.tv/fr/', color: '#fa481c' },
    ],
    sleep: { modes: ['s2idle', 'deep'], current: 's2idle' },
    moonlight_default: 'u1',
    covers: { running: false, last: Date.now() / 1000 - 3600, added: 12, missing: 3, failed: 0, offline: false },
    moonlight_pins: ['u1'],
    display: { name: 'HDMI-A-1', model: 'Samsung QE55Q60', width: 1920, height: 1080, refresh: 60 },
  };
  const later = (ms, fn) => setTimeout(fn, ms);
  window.MockShell = {
    state: S,
    call(cmd, args) {
      console.log('[mock]', cmd, JSON.stringify(args));
      switch (cmd) {
        case 'state': return Promise.resolve(JSON.parse(JSON.stringify(S)));
        case 'net-scan': return new Promise(r => later(500, () => r([
          { ssid: 'Livebox-5G', signal: 82, secure: true, active: true, known: true },
          { ssid: 'Livebox-2.4G', signal: 70, secure: true, active: false, known: false },
          { ssid: 'Freebox-Salon', signal: 41, secure: true, active: false, known: false },
          { ssid: 'Invités', signal: 30, secure: false, active: false, known: false }])));
        case 'net-connect': return new Promise(r => later(800, () => r({ ok: true })));
        case 'volume': return Promise.resolve({ volume: 80, muted: false });
        case 'info': return Promise.resolve({ version: '1.0', kernel: '6.12.94+deb13-amd64', disk: { free: 382e9, total: 476e9 } });
        case 'bt-pair-start':
          later(1500, () => Shell._emit('pairing', { state: 'pairing', name: 'Xbox Wireless Controller' }));
          later(3500, () => Shell._emit('pairing', { state: 'paired', name: 'Xbox Wireless Controller' }));
          return Promise.resolve(true);
        case 'site-add': {
          const t = { id: 'site-' + Math.random().toString(16).slice(2, 8), type: 'site', title: args.title || args.url, url: args.url, color: args.color || '#0ea5e9', control: args.control || 'pointer', icon: null };
          S.tiles.push(t); later(50, () => Shell._emit('state', { tiles: S.tiles }));
          return Promise.resolve({ tile: t });
        }
        case 'moonlight-pin':
          S.moonlight_pins = args.pin ? ['u1'] : []; later(30, () => Shell._emit('state', { moonlight_pins: S.moonlight_pins }));
          return Promise.resolve({ ok: true, set: !!args.pin });
        case 'covers-scan':
          S.covers = Object.assign({}, S.covers, { running: true }); later(30, () => Shell._emit('state', { covers: S.covers }));
          later(2500, () => { S.covers = Object.assign({}, S.covers, { running: false, added: 2, missing: 3, last: Date.now() / 1000 }); Shell._emit('state', { covers: S.covers }); });
          return Promise.resolve(true);
        case 'resume-forget': S.library.recent.forEach(g => { if (g.path === args.path) g.resume = false; });
          later(30, () => Shell._emit('state', { library: S.library })); return Promise.resolve(true);
        case 'settings-set': S.settings[args.key] = args.value; later(30, () => Shell._emit('state', { settings: S.settings })); return Promise.resolve(S.settings);
        default: return Promise.resolve(true);
      }
    },
  };
  const page = location.pathname.split('/').pop();
  const hash = location.hash.slice(1);
  if (page === 'overlay.html') {
    later(60, () => {
      if (hash === 'osk') Shell._emit('open', { mode: 'osk', data: { target: 'brave', field: { label: 'Rechercher', type: 'search', value: 'meilleurs jeux coop', host: 'www.youtube.com' } }, settings: { osk_layout: 'azerty', ui_sounds: false } });
      else if (hash === 'splash') Shell._emit('open', { mode: 'splash', data: { title: 'Forza Horizon 5', sub: 'PC-SALON', kind: 'moonlight', art: S.moonlight[0].apps[2].boxart }, settings: {} });
      else if (hash === 'sleep') Shell._emit('open', { mode: 'sleep', data: {}, settings: {} });
      else if (hash === 'menu-moonlight') Shell._emit('open', { mode: 'menu', data: { app: { id: 'moonlight', title: 'Steam Big Picture', kind: 'moonlight' }, profile: 'moonlight', title: 'Moonlight', is_moonlight: true, can_pin: true, volume: { volume: 80 }, pads: S.pads }, settings: {} });
      else if (hash === 'menu-game') Shell._emit('open', { mode: 'menu', data: { app: { id: 'games', title: 'Jeux', kind: 'esde' }, profile: 'dolphin', title: 'Dolphin', can_save: true, can_load: true, in_game: true, volume: { volume: 80 }, pads: S.pads }, settings: {} });
      else Shell._emit('open', { mode: 'menu', data: { app: { id: 'brave', title: 'Brave', kind: 'brave' }, profile: 'brave', title: 'Brave', is_brave: true, tabs: [{ id: 't1', title: 'YouTube', active: true }, { id: 't2', title: 'Wikipédia' }], volume: { volume: 80 }, pads: S.pads }, settings: {} });
    });
  }
  if (page === 'toast.html') {
    later(60, () => Shell._emit('toast', { text: 'Manette connectée', sub: 'Xbox Wireless Controller', icon: 'gamepad', ms: 600000 }));
  }
})();
