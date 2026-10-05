const apiBase = '/api';
const STORAGE_TOKEN = 'token';
const STORAGE_ROOM = 'selectedRoomId';

const state = {
  token: localStorage.getItem(STORAGE_TOKEN) || '',
  selectedRoomId: localStorage.getItem(STORAGE_ROOM) || '',
  room: null,
  rooms: [],
  me: null,
  socket: null,
  socketToken: '',
  socketRetryTimer: null,
  socketRetryAttempt: 0,
  pollTimer: null,
  actionPending: false,
  statusMessage: '',
  renderedRoomKey: '',
  equityWorker: null,
  equityRunKey: '',
  preciseEquity: null,
  audioUnlocked: false,
  audioContext: null,
  masterGain: null,
  effectsGain: null,
  musicGain: null,
  musicOscillators: [],
  audioSettings: { master: 0.35, effects: 0.45, music: 0 },
  cardSkin: 'classic',
};

const byId = (id) => document.getElementById(id);
const els = {
  username: byId('username'), email: byId('email'), password: byId('password'),
  roomName: byId('roomName'), maxPlayers: byId('maxPlayers'), smallBlind: byId('smallBlind'),
  roomList: byId('roomList'), roomCount: byId('roomCount'), selectedRoomLabel: byId('selectedRoomLabel'),
  tableHeading: byId('tableHeading'), blindLabel: byId('blindLabel'), playerCountLabel: byId('playerCountLabel'),
  playersArea: byId('playersArea'), roomJson: byId('roomJson'), statusArea: byId('statusArea'),
  boardArea: byId('boardArea'), potArea: byId('potArea'), deckOrigin: byId('deckOrigin'), userSummary: byId('userSummary'),
  raiseInput: byId('raiseInput'), raiseSlider: byId('raiseSlider'), raiseAmountLabel: byId('raiseAmountLabel'),
  callAmountLabel: byId('callAmountLabel'), actionHint: byId('actionHint'),
  actionLog: byId('actionLog'), handHistoryList: byId('handHistoryList'),
  analysisWin: byId('analysisWin'), analysisWinProbability: byId('analysisWinProbability'),
  analysisDraw: byId('analysisDraw'), analysisLose: byId('analysisLose'),
  analysisStage: byId('analysisStage'), equityTrackFill: byId('equityTrackFill'), analysisOuts: byId('analysisOuts'),
  analysisPotOdds: byId('analysisPotOdds'), analysisHand: byId('analysisHand'),
  analysisDrawType: byId('analysisDrawType'), analysisNote: byId('analysisNote'),
  analysisHandsAhead: byId('analysisHandsAhead'), analysisHandsAheadNote: byId('analysisHandsAheadNote'),
  analysisImpliedOdds: byId('analysisImpliedOdds'), analysisImpliedNote: byId('analysisImpliedNote'),
  themeSelect: byId('themeSelect'), cardSkinSelect: byId('cardSkinSelect'),
  masterVolume: byId('masterVolume'), effectsVolume: byId('effectsVolume'), musicVolume: byId('musicVolume'),
};

const numberFormat = new Intl.NumberFormat('cs-CZ');
const phaseNames = { waiting: 'ČEKÁNÍ', preflop: 'PREFLOP', flop: 'FLOP', turn: 'TURN', river: 'RIVER', showdown: 'SHOWDOWN' };

function clampVolume(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : fallback;
}

function loadAppearanceSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem('pokerAudioSettings') || '{}');
    state.audioSettings = {
      master: clampVolume(saved.master, 0.35),
      effects: clampVolume(saved.effects, 0.45),
      music: clampVolume(saved.music, 0),
    };
  } catch { state.audioSettings = { master: 0.35, effects: 0.45, music: 0 }; }
  const theme = localStorage.getItem('pokerTheme') || 'classic';
  applyTheme(theme);
  applyCardSkin(localStorage.getItem('pokerCardSkin') || 'classic');
  els.masterVolume.value = String(Math.round(state.audioSettings.master * 100));
  els.effectsVolume.value = String(Math.round(state.audioSettings.effects * 100));
  els.musicVolume.value = String(Math.round(state.audioSettings.music * 100));
  updateVolumeLabels();
}

function updateVolumeLabels() {
  byId('masterVolumeLabel').textContent = `${Math.round(state.audioSettings.master * 100)} %`;
  byId('effectsVolumeLabel').textContent = `${Math.round(state.audioSettings.effects * 100)} %`;
  byId('musicVolumeLabel').textContent = `${Math.round(state.audioSettings.music * 100)} %`;
}

function applyTheme(theme) {
  const allowed = new Set(['classic', 'midnight', 'casino', 'neon']);
  const selected = allowed.has(theme) ? theme : 'classic';
  document.body.dataset.theme = selected;
  if (els.themeSelect) els.themeSelect.value = selected;
  localStorage.setItem('pokerTheme', selected);
}

function applyCardSkin(skin) {
  const allowed = new Set(['classic', 'gold', 'midnight']);
  const selected = allowed.has(skin) ? skin : 'classic';
  state.cardSkin = selected;
  document.body.dataset.cardSkin = selected;
  if (els.cardSkinSelect) els.cardSkinSelect.value = selected;
  localStorage.setItem('pokerCardSkin', selected);
}

function saveAudioSettings() {
  localStorage.setItem('pokerAudioSettings', JSON.stringify(state.audioSettings));
  updateVolumeLabels();
  if (state.masterGain) state.masterGain.gain.setTargetAtTime(state.audioSettings.master, state.audioContext.currentTime, 0.04);
  if (state.effectsGain) state.effectsGain.gain.setTargetAtTime(state.audioSettings.effects, state.audioContext.currentTime, 0.04);
  if (state.musicGain) state.musicGain.gain.setTargetAtTime(state.audioSettings.music, state.audioContext.currentTime, 0.08);
  if (state.audioSettings.music > 0) startAmbientMusic();
  else stopAmbientMusic();
}

function ensureAudioContext() {
  if (state.audioContext) return true;
  const AudioContextType = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextType) return false;
  try {
    const context = new AudioContextType();
    const master = context.createGain(); master.gain.value = state.audioSettings.master;
    const effects = context.createGain(); effects.gain.value = state.audioSettings.effects;
    const music = context.createGain(); music.gain.value = state.audioSettings.music;
    effects.connect(master); music.connect(master); master.connect(context.destination);
    state.audioContext = context; state.masterGain = master; state.effectsGain = effects; state.musicGain = music;
    return true;
  } catch { return false; }
}

function primeAudio() {
  state.audioUnlocked = true;
  if (ensureAudioContext() && state.audioContext.state === 'suspended') state.audioContext.resume().catch(() => {});
  if (state.audioSettings.music > 0) startAmbientMusic();
}

function stopAmbientMusic() {
  state.musicOscillators.forEach(({ oscillator, gain }) => {
    try { gain.gain.setTargetAtTime(0, state.audioContext.currentTime, 0.15); oscillator.stop(state.audioContext.currentTime + 0.6); } catch { /* already stopped */ }
  });
  state.musicOscillators = [];
}

function startAmbientMusic() {
  if (!state.audioUnlocked || state.audioSettings.music <= 0 || !ensureAudioContext() || state.musicOscillators.length) return;
  if (state.audioContext.state === 'suspended') state.audioContext.resume().catch(() => {});
  [110, 164.81, 220].forEach((frequency, index) => {
    const oscillator = state.audioContext.createOscillator();
    const gain = state.audioContext.createGain();
    oscillator.type = 'sine'; oscillator.frequency.value = frequency;
    gain.gain.value = index === 0 ? 0.022 : 0.012;
    oscillator.connect(gain); gain.connect(state.musicGain); oscillator.start();
    state.musicOscillators.push({ oscillator, gain });
  });
}

function playEffect(effect = 'click') {
  if (!state.audioUnlocked || state.audioSettings.master <= 0 || state.audioSettings.effects <= 0 || !ensureAudioContext()) return;
  if (state.audioContext.state === 'suspended') state.audioContext.resume().catch(() => {});
  const tones = {
    click: [[420, 0.035, 'sine']], card: [[680, 0.055, 'triangle'], [520, 0.07, 'sine']],
    chip: [[300, 0.06, 'triangle'], [440, 0.05, 'sine']], fold: [[210, 0.09, 'triangle']],
    check: [[310, 0.045, 'sine']], call: [[350, 0.055, 'triangle']],
    bet: [[420, 0.06, 'triangle']], raise: [[475, 0.05, 'triangle'], [570, 0.075, 'sine']],
    all_in: [[180, 0.08, 'triangle'], [245, 0.11, 'sawtooth']],
    action: [[390, 0.045, 'sine']], showdown: [[392, 0.14, 'sine'], [523, 0.18, 'sine']],
    win: [[523.25, 0.3, 'sine'], [659.25, 0.34, 'sine'], [783.99, 0.42, 'sine']],
  }[effect] || [[420, 0.04, 'sine']];
  const now = state.audioContext.currentTime;
  tones.forEach(([frequency, duration, type], index) => {
    const oscillator = state.audioContext.createOscillator();
    const gain = state.audioContext.createGain();
    const start = now + index * 0.035;
    oscillator.type = type; oscillator.frequency.setValueAtTime(frequency, start);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.12, start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    oscillator.connect(gain); gain.connect(state.effectsGain);
    oscillator.start(start); oscillator.stop(start + duration + 0.015);
  });
}

function initializeAppearanceControls() {
  loadAppearanceSettings();
  els.themeSelect.addEventListener('change', () => {
    applyTheme(els.themeSelect.value); playEffect('click');
  });
  els.cardSkinSelect.addEventListener('change', () => {
    applyCardSkin(els.cardSkinSelect.value); playEffect('click');
  });
  [
    [els.masterVolume, 'master'], [els.effectsVolume, 'effects'], [els.musicVolume, 'music'],
  ].forEach(([input, key]) => input.addEventListener('input', () => {
    state.audioSettings[key] = clampVolume(Number(input.value) / 100, 0);
    saveAudioSettings();
  }));
}

function setStatus(message, tone = 'info') {
  state.statusMessage = String(message || '');
  els.statusArea.textContent = state.statusMessage;
  els.statusArea.dataset.tone = tone;
}

function formatChips(value) {
  return numberFormat.format(Math.max(0, Number(value) || 0));
}

function authHeaders() {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...authHeaders(), ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail) ? detail.map((item) => item.msg || item).join(', ')
      : (typeof detail === 'string' ? detail : 'Požadavek se nepodařilo dokončit.');
    if (response.status === 401) clearSession();
    throw new Error(message);
  }
  return data;
}

function clearSession() {
  stopEquitySimulation();
  state.token = '';
  state.me = null;
  state.room = null;
  state.renderedRoomKey = '';
  localStorage.removeItem(STORAGE_TOKEN);
  clearInterval(state.pollTimer);
  state.pollTimer = null;
  clearTimeout(state.socketRetryTimer);
  state.socketRetryTimer = null;
  if (state.socket) state.socket.close();
  state.socket = null;
  updateUserSummary();
  renderRoom(null);
  updateControls();
}

function ensureLoggedIn() {
  if (state.token && state.me) return true;
  setStatus('Nejdříve se přihlaste.', 'error');
  return false;
}

function updateUserSummary() {
  els.userSummary.textContent = state.me ? `${state.me.username} · ${formatChips(state.me.chips)} žetonů` : 'Nepřihlášen';
}

function currentPlayer() {
  return state.room?.players?.find((player) => Number(player.id) === Number(state.me?.id)) || null;
}

function turnInfo() {
  const player = currentPlayer();
  const room = state.room;
  const isMyTurn = Boolean(player && room && !player.folded && !player.all_in
    && Number(room.current_turn) === Number(player.seat));
  const call = player && room ? Math.max(0, Number(room.current_bet || 0) - Number(player.bet_this_round || 0)) : 0;
  const raiseCostLimit = player ? Math.max(0, Number(player.chips || 0) - (room?.current_bet ? call : 0)) : 0;
  const minimumRaise = Number(room?.last_full_raise || (room?.small_blind || 0) * 2);
  const canRaise = isMyTurn && !player?.raise_locked && raiseCostLimit >= minimumRaise;
  return { player, isMyTurn, call, canRaise, canCheck: isMyTurn && call === 0, canCall: isMyTurn && call > 0 };
}

function activeEquityKey(room = state.room) {
  if (!room || !state.me || !['preflop', 'flop', 'turn', 'river'].includes(room.phase)) return '';
  const hero = room.players?.find((player) => Number(player.id) === Number(state.me.id));
  const opponents = room.players?.filter((player) => player.in_hand && !player.folded && Number(player.id) !== Number(state.me.id)) || [];
  if (!hero?.in_hand || hero.folded || !Array.isArray(hero.hole_cards) || hero.hole_cards.length !== 2 || !opponents.length) return '';
  return JSON.stringify([hero.hole_cards, room.board || [], opponents.length]);
}

function updateSimulationProgress(percent, status) {
  const progress = Math.max(0, Math.min(100, Number(percent) || 0));
  const track = document.querySelector('.simulation-track');
  byId('simulationProgress').hidden = false;
  byId('simulationStatus').textContent = status;
  byId('simulationPercent').textContent = `${progress} %`;
  byId('simulationProgressFill').style.width = `${progress}%`;
  track?.setAttribute('aria-valuenow', String(progress));
}

function stopEquitySimulation({ clearResult = true, hideProgress = true } = {}) {
  state.equityWorker?.terminate();
  state.equityWorker = null;
  state.equityRunKey = '';
  if (clearResult) state.preciseEquity = null;
  const button = byId('simulateEquityBtn');
  if (button) button.textContent = 'Simulovat 100 000 hand';
  if (hideProgress && byId('simulationProgress')) byId('simulationProgress').hidden = true;
}

function syncEquityContext(room) {
  const nextKey = activeEquityKey(room);
  if (state.equityWorker && state.equityRunKey !== nextKey) {
    stopEquitySimulation();
  } else if (state.preciseEquity && state.preciseEquity.key !== nextKey) {
    state.preciseEquity = null;
    byId('simulationProgress').hidden = true;
    byId('simulateEquityBtn').textContent = 'Simulovat 100 000 hand';
  }
}

function simulateEquity() {
  if (state.equityWorker) {
    stopEquitySimulation();
    return;
  }
  const room = state.room;
  const key = activeEquityKey(room);
  const hero = currentPlayer();
  if (!key || !hero) return;
  if (!('Worker' in window)) {
    updateSimulationProgress(0, 'Tento prohlížeč nepodporuje výpočet v odděleném vlákně.');
    return;
  }
  stopEquitySimulation();
  state.equityRunKey = key;
  byId('simulateEquityBtn').textContent = 'Zrušit simulaci';
  updateSimulationProgress(0, 'Připravuji 100 000 rozdání…');
  let worker;
  try { worker = new Worker('/static/equity-worker.js?v=2026-10-04-equity'); }
  catch {
    stopEquitySimulation();
    updateSimulationProgress(0, 'Simulaci se nepodařilo spustit. Zkuste to znovu.');
    return;
  }
  state.equityWorker = worker;
  worker.onmessage = (event) => {
    if (state.equityWorker !== worker) return;
    const result = event.data || {};
    if (result.type === 'progress') {
      updateSimulationProgress(result.percent, `${numberFormat.format(result.completed)} / ${numberFormat.format(result.total)} simulací`);
      return;
    }
    if (result.type === 'error') {
      stopEquitySimulation({ clearResult: false, hideProgress: false });
      updateSimulationProgress(0, result.message || 'Simulaci se nepodařilo dokončit.');
      return;
    }
    if (result.type === 'complete') {
      worker.terminate();
      state.equityWorker = null;
      state.equityRunKey = '';
      state.preciseEquity = { key, stats: result };
      byId('simulateEquityBtn').textContent = 'Přepočítat 100 000 hand';
      updateSimulationProgress(100, `Hotovo · ${Number(result.duration_ms).toFixed(0)} ms · ${numberFormat.format(result.simulations)} simulací`);
      if (activeEquityKey(state.room) === key) renderAnalysis(state.room);
    }
  };
  worker.onerror = () => {
    if (state.equityWorker !== worker) return;
    stopEquitySimulation({ clearResult: false, hideProgress: false });
    updateSimulationProgress(0, 'Simulaci se nepodařilo dokončit. Zkuste to znovu.');
  };
  worker.postMessage({ holeCards: hero.hole_cards, board: room.board || [], opponents: room.players.filter((player) => player.in_hand && !player.folded && Number(player.id) !== Number(state.me.id)).length, iterations: 100000 });
}

function updateControls() {
  const loggedIn = Boolean(state.token && state.me);
  const room = state.room;
  const info = turnInfo();
  const waiting = room?.phase === 'waiting' || room?.phase === 'showdown';
  const eligibleCount = room?.players?.filter((player) => Number(player.chips) > 0).length || 0;
  byId('createRoomBtn').disabled = !loggedIn;
  byId('joinSelectedBtn').disabled = !loggedIn || !state.selectedRoomId || Boolean(currentPlayer());
  byId('startGameBtn').disabled = !loggedIn || !room || Number(room.owner_id) !== Number(state.me?.id)
    || !waiting || eligibleCount < 2 || state.actionPending;
  byId('foldBtn').disabled = !info.isMyTurn || state.actionPending;
  byId('checkBtn').disabled = !info.canCheck || state.actionPending;
  byId('callBtn').disabled = !info.canCall || state.actionPending;
  byId('allInBtn').disabled = !info.isMyTurn || Number(info.player?.chips || 0) <= 0 || state.actionPending;
  byId('raiseBtn').disabled = !info.canRaise || state.actionPending;
  els.raiseInput.disabled = !info.canRaise || state.actionPending;
  els.raiseSlider.disabled = !info.canRaise || state.actionPending;
  byId('simulateEquityBtn').disabled = !activeEquityKey(room);
  byId('raiseActionLabel').textContent = room?.current_bet ? 'Navýšit sázku' : 'Vsadit';
  document.querySelectorAll('.preset-btn').forEach((button) => {
    button.disabled = state.actionPending || (button.dataset.action === 'all_in' ? !info.isMyTurn : !info.canRaise);
  });
  els.callAmountLabel.textContent = info.canCall ? ` ${formatChips(Math.min(info.call, Number(info.player.chips)))}` : '';
  if (!info.isMyTurn) els.actionHint.textContent = currentPlayer() ? 'Vyčkejte na svůj tah' : 'Připojte se ke stolu';
  else if (info.canCheck) els.actionHint.textContent = 'Můžete checknout nebo vsadit';
  else els.actionHint.textContent = `Dorovnání ${formatChips(Math.min(info.call, info.player.chips))} žetonů`;
}

async function registerUser() {
  const username = els.username.value.trim();
  const email = els.email.value.trim();
  const password = els.password.value;
  if (username.length < 3) return setStatus('Přezdívka musí mít alespoň 3 znaky.', 'error');
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return setStatus('Zadejte platný e-mail.', 'error');
  if (password.length < 6 || new TextEncoder().encode(password).length > 72) {
    return setStatus('Heslo musí mít 6 až 72 bajtů.', 'error');
  }
  try {
    await fetchJson(`${apiBase}/auth/register`, { method: 'POST', body: JSON.stringify({ username, email, password }) });
    setStatus('Účet je vytvořen. Nyní se přihlaste.', 'success');
  } catch (error) { setStatus(error.message, 'error'); }
}

async function loginUser() {
  const email = els.email.value.trim();
  const password = els.password.value;
  if (!email || !password) return setStatus('Vyplňte e-mail a heslo.', 'error');
  try {
    const result = await fetchJson(`${apiBase}/auth/login`, { method: 'POST', body: JSON.stringify({ email, password }) });
    state.token = result.access_token;
    localStorage.setItem(STORAGE_TOKEN, state.token);
    state.me = await fetchJson(`${apiBase}/me`);
    updateUserSummary();
    connectSocket();
    await loadRooms();
    if (state.selectedRoomId) await getRoomDetails(state.selectedRoomId, false);
    updateControls();
    setStatus('Přihlášení proběhlo úspěšně.', 'success');
  } catch (error) { setStatus(error.message, 'error'); }
}

function selectRoomId(roomId) {
  stopEquitySimulation();
  state.selectedRoomId = String(roomId || '');
  if (state.selectedRoomId) localStorage.setItem(STORAGE_ROOM, state.selectedRoomId);
  else localStorage.removeItem(STORAGE_ROOM);
  state.room = null;
  state.renderedRoomKey = '';
  renderRooms();
  renderRoom(null);
  updateControls();
}

async function loadRooms() {
  try {
    const result = await fetchJson(`${apiBase}/rooms`);
    state.rooms = Array.isArray(result.rooms) ? result.rooms : [];
    renderRooms();
    if (state.selectedRoomId && state.token && !state.room) await getRoomDetails(state.selectedRoomId, false);
    if (state.selectedRoomId && !state.rooms.some((room) => String(room.room_id) === state.selectedRoomId)) {
      // An already-finished table can still be opened by its current members.
      if (!state.room) selectRoomId('');
    }
  } catch (error) { setStatus(error.message, 'error'); }
}

function renderRooms() {
  els.roomCount.textContent = String(state.rooms.length);
  if (!state.rooms.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Zatím tu nejsou žádné stoly. Vytvořte vlastní hru.';
    els.roomList.replaceChildren(empty);
    return;
  }
  const rows = state.rooms.map((room) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `room-item${String(room.room_id) === state.selectedRoomId ? ' active' : ''}`;
    button.setAttribute('aria-pressed', String(String(room.room_id) === state.selectedRoomId));
    const name = document.createElement('span');
    name.className = 'room-item-name';
    name.textContent = room.name;
    const meta = document.createElement('span');
    meta.className = 'room-item-meta';
    const count = document.createElement('span');
    count.textContent = `${room.player_count} / ${room.max_players} hráčů`;
    const blinds = document.createElement('span');
    blinds.textContent = `${formatChips(room.small_blind)} / ${formatChips(room.small_blind * 2)}`;
    meta.append(count, blinds);
    button.append(name, meta);
    button.addEventListener('click', async () => {
      selectRoomId(room.room_id);
      els.selectedRoomLabel.textContent = room.name;
      await getRoomDetails(room.room_id);
    });
    return button;
  });
  els.roomList.replaceChildren(...rows);
}

async function createRoom() {
  if (!ensureLoggedIn()) return;
  const name = els.roomName.value.trim();
  const maxPlayers = Number(els.maxPlayers.value);
  const smallBlind = Number(els.smallBlind.value);
  if (name.length < 3 || name.length > 100) return setStatus('Název stolu musí mít 3 až 100 znaků.', 'error');
  if (!Number.isInteger(maxPlayers) || maxPlayers < 2 || maxPlayers > 9) return setStatus('Stůl musí mít 2 až 9 míst.', 'error');
  if (!Number.isInteger(smallBlind) || smallBlind < 1 || smallBlind > 1000) return setStatus('Small blind musí být celé číslo od 1 do 1 000.', 'error');
  try {
    const result = await fetchJson(`${apiBase}/rooms`, {
      method: 'POST', body: JSON.stringify({ name, max_players: maxPlayers, small_blind: smallBlind }),
    });
    selectRoomId(result.room.room_id);
    applyRoomState(result.room);
    await loadRooms();
    setStatus('Stůl je připraven. Pozvěte dalšího hráče.', 'success');
  } catch (error) { setStatus(error.message, 'error'); }
}

async function getRoomDetails(roomId, reportError = true) {
  if (!state.token || !roomId) return;
  try {
    const result = await fetchJson(`${apiBase}/rooms/${encodeURIComponent(roomId)}`);
    if (String(roomId) === state.selectedRoomId) applyRoomState(result.room);
  } catch (error) {
    if (reportError) setStatus(error.message, 'error');
    else if (error.message.toLowerCase().includes('not found')) selectRoomId('');
  }
}

async function joinSelectedRoom() {
  if (!ensureLoggedIn() || !state.selectedRoomId) return;
  try {
    const result = await fetchJson(`${apiBase}/rooms/${encodeURIComponent(state.selectedRoomId)}/join`, { method: 'POST' });
    applyRoomState(result.room);
    await loadRooms();
    setStatus('Jste u stolu.', 'success');
  } catch (error) { setStatus(error.message, 'error'); }
}

async function startHand() {
  if (!ensureLoggedIn() || !state.selectedRoomId || state.actionPending) return;
  playEffect('card');
  state.actionPending = true;
  updateControls();
  try {
    const result = await fetchJson(`${apiBase}/rooms/${encodeURIComponent(state.selectedRoomId)}/start`, { method: 'POST' });
    applyRoomState(result.room);
    setStatus('Karty jsou rozdány.', 'success');
  } catch (error) { setStatus(error.message, 'error'); }
  finally { state.actionPending = false; updateControls(); }
}

function setRaiseAmount(value) {
  const room = state.room;
  const player = currentPlayer();
  if (!room || !player) return;
  const min = Number(room.last_full_raise || room.small_blind * 2);
  const call = Math.max(0, Number(room.current_bet || 0) - Number(player.bet_this_round || 0));
  const max = Math.max(min, Number(player.chips || 0) - (room.current_bet ? call : 0));
  const amount = Math.max(min, Math.min(max, Math.round(Number(value) || min)));
  els.raiseInput.value = String(amount);
  els.raiseAmountLabel.textContent = formatChips(amount);
  els.raiseSlider.min = String(min);
  els.raiseSlider.max = String(max);
  els.raiseSlider.step = String(Math.max(1, Number(room.small_blind || 1)));
  els.raiseSlider.value = String(amount);
  els.raiseInput.min = String(min);
  els.raiseInput.max = String(max);
}

function getRaiseAmount() {
  const value = Number(els.raiseInput.value);
  if (!Number.isSafeInteger(value) || value <= 0) return 0;
  return value;
}

function applyPreset(button) {
  const info = turnInfo();
  const room = state.room;
  if (!room || !info.player) return;
  const lastRaise = Number(room.last_full_raise || room.small_blind * 2);
  let amount = lastRaise;
  if (button.dataset.multiplier) amount = Math.round(lastRaise * Number(button.dataset.multiplier));
  if (button.dataset.pot) amount = Math.round(Math.max(lastRaise, Number(room.pot || 0) * Number(button.dataset.pot)));
  if (button.dataset.allin) amount = Number(info.player.chips);
  setRaiseAmount(amount);
}

async function sendAction(action) {
  if (!ensureLoggedIn() || !state.selectedRoomId || state.actionPending) return;
  const amount = action === 'raise' || action === 'bet' ? getRaiseAmount() : null;
  if ((action === 'raise' || action === 'bet') && !amount) return setStatus('Zadejte platnou výši sázky.', 'error');
  playEffect(action === 'all_in' || ['fold', 'check', 'call', 'bet', 'raise'].includes(action) ? action : 'action');
  state.actionPending = true;
  updateControls();
  try {
    const result = await fetchJson(`${apiBase}/rooms/${encodeURIComponent(state.selectedRoomId)}/action`, {
      method: 'POST',
      body: JSON.stringify({ room_id: state.selectedRoomId, action, amount }),
    });
    applyRoomState(result.room);
    setStatus(action === 'all_in' ? 'All-in byl odeslán.' : 'Akce byla provedena.', 'success');
    await loadRooms();
  } catch (error) { setStatus(error.message, 'error'); }
  finally { state.actionPending = false; updateControls(); }
}

function cardNode(card, hidden = false, animate = false, reveal = false, dealOrder = 0) {
  const node = document.createElement('div');
  node.className = 'poker-card';
  node.setAttribute('role', 'img');
  if (animate) {
    node.classList.add('card-deal-in');
    node.style.setProperty('--deal-delay', `${Math.max(0, dealOrder) * 75}ms`);
  }
  if (reveal) node.classList.add('card-reveal-in');
  if (hidden || !card || card === 'XX') {
    node.classList.add('back');
    node.setAttribute('aria-label', 'Skrytá karta');
    const back = document.createElement('span');
    back.className = 'card-back';
    back.textContent = '♠';
    node.append(back);
    return node;
  }
  const suit = Array.from(String(card).slice(-1))[0];
  const rank = String(card).slice(0, -1) === 'T' ? '10' : String(card).slice(0, -1);
  const spokenRanks = { A: 'eso', K: 'král', Q: 'dáma', J: 'kluk', '10': 'desítka' };
  const spokenSuits = { '♠': 'piky', '♥': 'srdce', '♦': 'káry', '♣': 'kříže' };
  node.setAttribute('aria-label', `${spokenRanks[rank] || rank} ${spokenSuits[suit] || ''}`.trim());
  node.classList.add(['♥', '♦'].includes(suit) ? 'red' : 'black');
  const rankNode = document.createElement('span');
  rankNode.className = 'card-rank';
  rankNode.textContent = rank;
  const suitNode = document.createElement('span');
  suitNode.className = 'card-suit';
  suitNode.textContent = suit;
  node.append(rankNode, suitNode);
  return node;
}

function renderCards(container, cards, placeholder, hidden = false, animatedStartIndex = Number.POSITIVE_INFINITY) {
  if (!Array.isArray(cards) || cards.length === 0) {
    const empty = document.createElement('span');
    empty.className = 'board-empty';
    empty.textContent = placeholder;
    container.replaceChildren(empty);
    return;
  }
  container.replaceChildren(...cards.map((card, index) => {
    const animate = index >= animatedStartIndex;
    return cardNode(card, hidden, animate, false, animate ? index - animatedStartIndex : 0);
  }));
}

function setDealOrigins(container) {
  const origin = els.deckOrigin.getBoundingClientRect();
  if (!origin.width || !origin.height) return;
  const originX = origin.left + origin.width / 2;
  const originY = origin.top + origin.height / 2;
  container.querySelectorAll('.card-deal-in').forEach((card) => {
    const target = card.getBoundingClientRect();
    const deltaX = originX - (target.left + target.width / 2);
    const deltaY = originY - (target.top + target.height / 2);
    card.style.setProperty('--deal-x', `${deltaX.toFixed(1)}px`);
    card.style.setProperty('--deal-y', `${deltaY.toFixed(1)}px`);
    card.style.setProperty('--deal-mid-x', `${(deltaX * 0.38).toFixed(1)}px`);
    card.style.setProperty('--deal-mid-y', `${(deltaY * 0.38).toFixed(1)}px`);
  });
}

function makeBadge(label, cssClass = '') {
  const badge = document.createElement('span');
  badge.className = `badge${cssClass ? ` ${cssClass}` : ''}`;
  badge.textContent = label;
  return badge;
}

function renderSeats(room, previousRoom = null, newHand = false, showdownReveal = false) {
  if (!room) { els.playersArea.replaceChildren(); return; }
  const players = [...(room.players || [])].sort((a, b) => Number(a.seat) - Number(b.seat));
  const heroPosition = Math.max(0, players.findIndex((p) => Number(p.id) === Number(state.me?.id)));
  const count = Math.max(players.length, 1);
  const compactSeatRing = count >= 7;
  const seatHorizontalRadius = compactSeatRing ? 40 : 38;
  const seatVerticalRadius = compactSeatRing ? 38 : 31;
  els.playersArea.dataset.seatCount = String(players.length);
  const dealerPosition = players.findIndex((player) => player.is_dealer
    || Number(player.seat) === Number(room.dealer_index));
  const summary = room.last_hand_summary || {};
  const winnerIds = new Set((summary.winner_ids || []).map(Number));
  const previousById = new Map((previousRoom?.players || []).map((player) => [Number(player.id), player]));
  const nodes = players.map((player, index) => {
    const hero = Number(player.id) === Number(state.me?.id);
    const isTurn = Number(room.current_turn) === Number(player.seat) && !player.folded && !player.all_in;
    const relativeIndex = (index - heroPosition + count) % count;
    const angle = Math.PI / 2 + relativeIndex * 2 * Math.PI / count;
    const seat = document.createElement('article');
    seat.className = 'seat-card';
    if (hero) seat.classList.add('hero');
    if (isTurn) seat.classList.add('current-turn');
    if (player.folded) seat.classList.add('folded');
    if (winnerIds.has(Number(player.id)) && room.phase === 'showdown') seat.classList.add('winner');
    seat.style.setProperty('--seat-x', `${50 + seatHorizontalRadius * Math.cos(angle)}%`);
    seat.style.setProperty('--seat-y', `${50 + seatVerticalRadius * Math.sin(angle)}%`);

    const header = document.createElement('div'); header.className = 'seat-header';
    const username = document.createElement('span'); username.className = 'seat-name'; username.textContent = player.username;
    const chips = document.createElement('span'); chips.className = 'seat-chips'; chips.textContent = formatChips(player.chips);
    const previousPlayer = previousById.get(Number(player.id));
    if (previousPlayer && Number(previousPlayer.chips) !== Number(player.chips)) chips.classList.add('stack-change');
    header.append(username, chips);
    const badges = document.createElement('div'); badges.className = 'seat-badges';
    if (player.is_dealer || Number(room.dealer_index) === Number(player.seat)) badges.append(makeBadge('D'));
    if (player.is_small_blind || Number(room.small_blind_index) === Number(player.seat)) badges.append(makeBadge('SB', 'small-blind'));
    if (player.is_big_blind || Number(room.big_blind_index) === Number(player.seat)) badges.append(makeBadge('BB', 'big-blind'));
    if (player.all_in) badges.append(makeBadge('All-in', 'all-in'));
    if (player.folded) badges.append(makeBadge('Fold', 'fold'));
    if (isTurn) badges.append(makeBadge('Na tahu', 'turn'));
    const meta = document.createElement('div'); meta.className = 'seat-meta';
    meta.textContent = `Místo ${Number(player.seat) + 1}${hero ? ' · Vy' : ''}`;
    const action = document.createElement('div'); action.className = 'seat-action';
    const toCall = Math.max(0, Number(room.current_bet || 0) - Number(player.bet_this_round || 0));
    action.textContent = player.folded ? 'Složeno' : player.all_in ? 'All-in' : isTurn ? (toCall ? `Dorovnat ${formatChips(toCall)}` : 'Na tahu') : '';
    const cards = document.createElement('div'); cards.className = 'seat-cards';
    const holeCards = Array.isArray(player.hole_cards) ? player.hole_cards : [];
    const reveal = hero || room.phase === 'showdown';
    const dealCards = newHand || (!hero && showdownReveal && reveal);
    const visibleShowdownHand = !hero && showdownReveal && holeCards.some((card) => card && card !== 'XX');
    const dealSeatOrder = (index - (dealerPosition >= 0 ? dealerPosition : -1) - 1 + count) % count;
    if (holeCards.length) cards.replaceChildren(...holeCards.map((card, cardIndex) => cardNode(
      card, !reveal, dealCards, visibleShowdownHand, cardIndex * count + dealSeatOrder,
    )));
    const children = [header, badges, meta, action, cards];
    const bet = Number(player.bet_this_round || 0);
    if (bet > 0) {
      const betNode = document.createElement('div'); betNode.className = 'seat-bet';
      betNode.textContent = `Sázka ${formatChips(bet)}`;
      children.push(betNode);
    }
    if (isTurn && room.turn_deadline_at && room.server_time) {
      const timer = document.createElement('div');
      timer.className = 'seat-timer active';
      timer.dataset.deadlineMs = String(Date.now() + (Number(room.turn_deadline_at) - Number(room.server_time)) * 1000);
      timer.setAttribute('role', 'timer');
      timer.setAttribute('aria-label', 'Zbývající čas na tah');
      const ring = document.createElement('span'); ring.className = 'timer-ring';
      const value = document.createElement('span'); value.className = 'timer-value';
      timer.append(ring, value);
      children.push(timer);
    }
    seat.replaceChildren(...children);
    return seat;
  });
  els.playersArea.replaceChildren(...nodes);
}

function renderHistory(room) {
  const actionRows = (room.history || []).slice(-7).reverse();
  els.actionLog.replaceChildren(...actionRows.map((text) => {
    const item = document.createElement('li'); item.textContent = text; return item;
  }));
  if (!actionRows.length) {
    const item = document.createElement('li'); item.textContent = 'Zatím bez akcí.'; els.actionLog.append(item);
  }
  const handRows = (room.hand_history || []).slice(-5).reverse();
  els.handHistoryList.replaceChildren(...handRows.map((entry) => {
    const item = document.createElement('li'); item.className = 'hand-history-item';
    const phase = document.createElement('span'); phase.className = 'hand-phase'; phase.textContent = String(entry.phase || 'hand').toUpperCase();
    const message = document.createElement('span'); message.className = 'hand-message'; message.textContent = entry.message || entry.hand_label || 'Hand update';
    item.append(phase, message); return item;
  }));
  if (!handRows.length) {
    const item = document.createElement('li'); item.className = 'hand-history-item empty'; item.textContent = 'Zatím bez historie.';
    els.handHistoryList.append(item);
  }
}

function renderAnalysis(room) {
  const serverStats = state.me && room.analytics ? room.analytics[state.me.username] : null;
  const equityKey = activeEquityKey(room);
  const precise = state.preciseEquity?.key === equityKey ? state.preciseEquity.stats : null;
  const stats = precise ? { ...(serverStats || {}), ...precise } : serverStats;
  const win = Number(stats?.win_probability);
  const equity = Number(stats?.equity);
  const draw = Number(stats?.tie_probability);
  const lose = Number(stats?.lose_probability);
  els.analysisWin.textContent = Number.isFinite(equity) ? `${(equity * 100).toFixed(1)} %`
    : Number.isFinite(win) ? `${(win * 100).toFixed(1)} %` : '—';
  els.analysisWinProbability.textContent = Number.isFinite(win) ? `${(win * 100).toFixed(1)} %` : '—';
  els.analysisDraw.textContent = Number.isFinite(draw) ? `${(draw * 100).toFixed(1)} %` : '—';
  els.analysisLose.textContent = Number.isFinite(lose) ? `${(lose * 100).toFixed(1)} %` : '—';
  els.analysisOuts.textContent = Number.isFinite(Number(stats?.outs)) ? String(stats.outs) : '—';
  els.analysisPotOdds.textContent = stats?.pot_odds != null && Number.isFinite(Number(stats.pot_odds))
    ? `${(Number(stats.pot_odds) * 100).toFixed(1)} %` : '—';
  const handNames = {
    'high card': 'Vysoká karta', 'one pair': 'Jeden pár', 'two pair': 'Dva páry',
    'three of a kind': 'Trojice', 'straight': 'Postupka', 'flush': 'Barva',
    'full house': 'Full house', 'four of a kind': 'Poker', 'straight flush': 'Postupka v barvě',
  };
  const label = String(stats?.current_hand || '');
  const preflopLabel = label.match(/^(pocket pair|high card) (\d+)$/);
  const rankNames = { 14: 'eso', 13: 'král', 12: 'dáma', 11: 'kluk', 10: 'desítka' };
  els.analysisHand.textContent = preflopLabel
    ? `${preflopLabel[1] === 'pocket pair' ? 'Pár' : 'Vysoká karta'} ${rankNames[Number(preflopLabel[2])] || preflopLabel[2]}`
    : (handNames[label] || (label ? label : '—'));
  const drawNames = (stats?.draws || []).map((draw) => ({ 'flush draw': 'Draw do barvy', 'straight draw': 'Draw do postupky' }[draw] || draw));
  els.analysisDrawType.textContent = drawNames.length ? drawNames.join(' · ') : 'Bez výrazného draw';
  const possibleHands = (stats?.possible_hands_ahead || []).map((hand) => handNames[hand] || hand);
  els.analysisHandsAhead.textContent = room.phase === 'showdown' ? 'Showdown'
    : room.board.length < 3 ? 'Zobrazí se po flopu'
      : !stats ? 'Počítám…'
        : possibleHands.length ? possibleHands.join(' · ') : 'Žádná možná silnější handa';
  els.analysisHandsAheadNote.textContent = room.phase === 'showdown'
    ? 'Výsledek handy je známý.'
    : 'Možnosti podle neznámých karet, nejde o odhalené karty soupeřů.';
  const hero = currentPlayer();
  const callAmount = hero ? Math.max(0, Number(room.current_bet || 0) - Number(hero.bet_this_round || 0)) : 0;
  if (!callAmount) {
    els.analysisImpliedOdds.textContent = '—';
    els.analysisImpliedNote.textContent = 'Zobrazí se, když je potřeba dorovnat.';
  } else if (!Number.isFinite(equity) || equity <= 0) {
    els.analysisImpliedOdds.textContent = 'Nedostupné';
    els.analysisImpliedNote.textContent = 'Při nulové odhadované equity další pot nepomůže.';
  } else {
    const potAfterCall = Number(room.pot || 0) + callAmount;
    const additionalNeeded = Math.max(0, Math.ceil(callAmount / equity - potAfterCall));
    const opponentStacks = (room.players || []).filter((player) => player.in_hand && !player.folded
      && Number(player.id) !== Number(state.me?.id)).reduce((sum, player) => sum + Number(player.chips || 0), 0);
    const effectiveFutureStack = Math.min(Math.max(0, Number(hero.chips || 0) - callAmount), opponentStacks);
    els.analysisImpliedOdds.textContent = additionalNeeded === 0 ? 'Pot stačí'
      : additionalNeeded > effectiveFutureStack ? `> ${formatChips(effectiveFutureStack)}`
        : `≈ ${formatChips(additionalNeeded)}`;
    els.analysisImpliedNote.textContent = `Dodatečný budoucí pot pro break-even při equity ${(equity * 100).toFixed(1)} %; dostupný efektivní stack ${formatChips(effectiveFutureStack)}.`;
  }
  const simulations = Number(stats?.simulations || 0);
  const uncertainty = Number(stats?.confidence95);
  const durationMs = Number(stats?.duration_ms);
  els.analysisNote.textContent = simulations > 1
    ? `Monte Carlo · ${formatChips(simulations)} simulací · ${Number.isFinite(durationMs) ? `${durationMs.toFixed(0)} ms` : '—'} · 95% odchylka ±${Number.isFinite(uncertainty) ? (uncertainty * 100).toFixed(1) : '—'} p. b.`
    : room.phase === 'showdown' ? 'Výsledek handy je známý; pravděpodobnost je vyhodnocena přesně.'
      : 'Odhad podle dostupných karet. Outs popisují karty, které mohou vytvořit postupku nebo barvu.';
  els.equityTrackFill.style.width = `${Number.isFinite(equity) ? Math.max(0, Math.min(100, equity * 100)) : 0}%`;
  els.analysisStage.textContent = phaseNames[room.phase] || 'ČEKÁNÍ';
}

function animateChipTransfers(previousRoom, room) {
  document.querySelectorAll('.chip-flight').forEach((node) => node.remove());
  if (!previousRoom || !room) return;
  const oldPlayers = new Map((previousRoom.players || []).map((player) => [Number(player.id), player]));
  const players = [...(room.players || [])].sort((a, b) => Number(a.seat) - Number(b.seat));
  const heroPosition = Math.max(0, players.findIndex((player) => Number(player.id) === Number(state.me?.id)));
  const count = Math.max(1, players.length);
  const payout = room.phase === 'showdown' && previousRoom.phase !== 'showdown';
  players.forEach((player, index) => {
    const before = oldPlayers.get(Number(player.id));
    if (!before) return;
    const stackDelta = Number(player.chips || 0) - Number(before.chips || 0);
    const betDelta = Number(player.bet_this_round || 0) - Number(before.bet_this_round || 0);
    const paidOut = payout && stackDelta > 0;
    if (!paidOut && betDelta <= 0) return;
    const angle = Math.PI / 2 + ((index - heroPosition + count) % count) * 2 * Math.PI / count;
    const startX = `${50 + 38 * Math.cos(angle)}%`;
    const startY = `${50 + 31 * Math.sin(angle)}%`;
    const targetX = startX;
    const targetY = startY;
    const quantity = Math.min(4, Math.max(1, Math.ceil((paidOut ? stackDelta : betDelta) / Math.max(1, Number(room.small_blind || 10) * 3))));
    for (let i = 0; i < quantity; i += 1) {
      const chip = document.createElement('span');
      chip.className = `chip-flight${paidOut ? ' payout' : ''}`;
      chip.setAttribute('aria-hidden', 'true');
      chip.style.setProperty('--start-x', startX);
      chip.style.setProperty('--start-y', startY);
      chip.style.setProperty('--target-x', targetX);
      chip.style.setProperty('--target-y', targetY);
      chip.style.setProperty('--flight-delay', `${i * 50}ms`);
      byId('tableSurface').append(chip);
      window.setTimeout(() => chip.remove(), 1000);
    }
  });
}

function launchWinnerVfx(royalFlush = false) {
  const layer = document.createElement('div');
  layer.className = `victory-vfx${royalFlush ? ' royal' : ''}`;
  layer.setAttribute('aria-hidden', 'true');
  const colors = royalFlush ? ['#fff1b5', '#f8e6a1', '#f2f0d5', '#d9bc72'] : ['#ead28d', '#f2e7c4', '#a7c58c', '#bd9659'];
  const particleCount = royalFlush ? 46 : 28;
  for (let index = 0; index < particleCount; index += 1) {
    const particle = document.createElement('span');
    particle.className = 'victory-particle';
    particle.style.setProperty('--particle-x', `${Math.round(Math.cos(index * 2.399) * (75 + (index % 5) * 25))}px`);
    particle.style.setProperty('--particle-y', `${Math.round(-80 - (index % 6) * 24)}px`);
    particle.style.setProperty('--particle-delay', `${index % 7 * 23}ms`);
    particle.style.setProperty('--particle-color', colors[index % colors.length]);
    layer.append(particle);
  }
  byId('tableSurface').append(layer);
  window.setTimeout(() => layer.remove(), 1800);
  if (royalFlush) {
    const surface = byId('tableSurface');
    surface.classList.remove('royal-flush-moment');
    void surface.offsetWidth;
    surface.classList.add('royal-flush-moment');
    window.setTimeout(() => surface.classList.remove('royal-flush-moment'), 1900);
  }
}

function renderRoom(room, previousRoom = null) {
  if (!room) {
    els.tableHeading.textContent = 'Vyberte stůl v lobby';
    els.selectedRoomLabel.textContent = 'Vyberte stůl';
    els.blindLabel.textContent = '—';
    els.playerCountLabel.textContent = '0 / 0';
    els.potArea.innerHTML = '<span class="pot-label">POT</span><strong>0</strong><small>žetonů</small>';
    renderCards(els.boardArea, [], 'Společné karty se objeví zde');
    renderSeats(null);
    els.actionLog.replaceChildren();
    els.handHistoryList.replaceChildren();
    els.roomJson.textContent = '{}';
    els.analysisWin.textContent = '—'; els.analysisDraw.textContent = '—'; els.analysisLose.textContent = '—';
    els.analysisWinProbability.textContent = '—';
    els.analysisOuts.textContent = '—'; els.analysisPotOdds.textContent = '—';
    els.analysisImpliedOdds.textContent = '—';
    els.analysisImpliedNote.textContent = 'Zobrazí se, když je potřeba dorovnat.';
    els.analysisHand.textContent = '—'; els.analysisDrawType.textContent = 'Bez výrazného draw';
    els.analysisHandsAhead.textContent = 'Zobrazí se po flopu';
    els.analysisHandsAheadNote.textContent = 'Hypotetické kombinace z neznámých karet.';
    els.analysisNote.textContent = 'Odhad podle dostupných karet.';
    els.equityTrackFill.style.width = '0%'; els.analysisStage.textContent = 'ČEKÁNÍ';
    return;
  }
  els.tableHeading.textContent = room.name;
  els.selectedRoomLabel.textContent = room.name;
  els.blindLabel.textContent = `${formatChips(room.small_blind)} / ${formatChips(room.small_blind * 2)}`;
  els.playerCountLabel.textContent = `${room.players.length} / ${room.max_players}`;
  const pot = room.phase === 'showdown' ? Number(room.last_hand_summary?.pot ?? room.pot) : Number(room.pot);
  els.potArea.replaceChildren();
  const label = document.createElement('span'); label.className = 'pot-label'; label.textContent = 'POT';
  const total = document.createElement('strong'); total.textContent = formatChips(pot);
  const units = document.createElement('small'); units.textContent = 'žetonů';
  els.potArea.append(label, total, units);
  const newHand = Boolean(previousRoom && Number(room.hand_number || 0) > Number(previousRoom.hand_number || 0));
  const boardGrew = Boolean(previousRoom && previousRoom.board.length < room.board.length);
  const showdownReveal = Boolean(previousRoom && previousRoom.phase !== 'showdown' && room.phase === 'showdown');
  const animatedBoardStart = newHand && room.board.length > 0 ? 0 : boardGrew ? previousRoom.board.length : Number.POSITIVE_INFINITY;
  renderCards(els.boardArea, room.board, 'Společné karty se objeví zde', false, animatedBoardStart);
  renderSeats(room, previousRoom, newHand, showdownReveal);
  setDealOrigins(els.playersArea);
  setDealOrigins(els.boardArea);
  animateChipTransfers(previousRoom, room);
  els.potArea.classList.remove('pot-change');
  if (previousRoom && Number(previousRoom.pot) !== Number(room.pot)) {
    void els.potArea.offsetWidth;
    els.potArea.classList.add('pot-change');
  }
  renderHistory(room);
  renderAnalysis(room);
  els.roomJson.textContent = JSON.stringify(room, null, 2);
}

function applyRoomState(room) {
  if (!room || String(room.room_id) !== state.selectedRoomId) return;
  const { server_time: _serverTime, ...stableRoom } = room;
  const nextKey = JSON.stringify(stableRoom);
  const previousRoom = state.room;
  syncEquityContext(room);
  state.room = room;
  if (state.renderedRoomKey !== nextKey) {
    if (previousRoom && (Number(room.hand_number) > Number(previousRoom.hand_number)
        || room.board.length > previousRoom.board.length)) playEffect('card');
    if (previousRoom && Number(room.pot) > Number(previousRoom.pot)) playEffect('chip');
    if (previousRoom && previousRoom.phase !== 'showdown' && room.phase === 'showdown') {
      const winnerIds = (room.last_hand_summary?.winner_ids || []).map(Number);
      const heroWon = winnerIds.includes(Number(state.me?.id));
      playEffect(heroWon ? 'win' : 'showdown');
      if (heroWon) {
        const royalFlush = (room.last_hand_summary?.winners || []).some((winner) =>
          Number(winner.id) === Number(state.me?.id)
          && Number(winner.hand_strength?.[0]) === 8 && Number(winner.hand_strength?.[1]) === 14);
        launchWinnerVfx(royalFlush);
      }
    }
    if (previousRoom && room.players?.some((player, index) => player.all_in && !previousRoom.players?.[index]?.all_in)) {
      const surface = byId('tableSurface');
      surface.classList.remove('all-in-moment');
      void surface.offsetWidth;
      surface.classList.add('all-in-moment');
      window.setTimeout(() => surface.classList.remove('all-in-moment'), 420);
    }
    renderRoom(room, previousRoom);
    state.renderedRoomKey = nextKey;
  }
  const info = turnInfo();
  if (info.isMyTurn) setStatus(info.canCall ? `Jste na tahu. Dorovnání ${formatChips(info.call)}.` : 'Jste na tahu.', 'success');
  else if (room.current_turn !== null && room.current_turn !== undefined) {
    const acting = room.players.find((player) => Number(player.seat) === Number(room.current_turn));
    if (acting) setStatus(`Na tahu je ${acting.username}.`, 'info');
  }
  updateControls();
  renderRooms();
  if (document.activeElement !== els.raiseInput && document.activeElement !== els.raiseSlider) {
    setRaiseAmount(Number(els.raiseInput.value) || Number(room.last_full_raise || room.small_blind * 2));
  }
}

function startPolling() {
  clearInterval(state.pollTimer);
  if (!state.token) return;
  state.pollTimer = setInterval(() => {
    if (state.selectedRoomId) getRoomDetails(state.selectedRoomId, false);
    loadRooms();
  }, 5000);
}

function scheduleSocketReconnect() {
  if (!state.token || state.socketRetryTimer) return;
  const delay = Math.min(30000, 800 * (2 ** Math.min(state.socketRetryAttempt, 5)));
  state.socketRetryAttempt += 1;
  state.socketRetryTimer = setTimeout(() => { state.socketRetryTimer = null; connectSocket(); }, delay);
}

function connectSocket() {
  if (!state.token || !('WebSocket' in window)) return;
  if (state.socket && state.socketToken === state.token
      && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.socket.readyState)) return;
  if (state.socket) { const old = state.socket; state.socket = null; old.close(); }
  clearTimeout(state.socketRetryTimer); state.socketRetryTimer = null;
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${scheme}//${location.host}/ws`, ['poker.v1', `auth.${state.token}`]);
  state.socket = socket; state.socketToken = state.token;
  socket.onopen = () => {
    if (state.socket !== socket) return;
    state.socketRetryAttempt = 0;
    if (state.selectedRoomId) getRoomDetails(state.selectedRoomId, false);
  };
  socket.onmessage = (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === 'room_update' && message.room && String(message.room.room_id) === state.selectedRoomId) applyRoomState(message.room);
    if (message.type === 'room_created' && message.room) {
      selectRoomId(message.room.room_id); applyRoomState(message.room); loadRooms();
    }
    if (message.type === 'error' && message.detail) setStatus(message.detail, 'error');
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => {
    if (state.socket !== socket) return;
    state.socket = null; state.socketToken = ''; scheduleSocketReconnect();
  };
  startPolling();
}

function startTurnTicker() {
  window.setInterval(() => {
    document.querySelectorAll('.seat-timer.active').forEach((timer) => {
      const deadline = Number(timer.dataset.deadlineMs);
      const remainingMs = Math.max(0, deadline - Date.now());
      const seconds = Math.ceil(remainingMs / 1000);
      const duration = Number(state.room?.turn_timeout_seconds || 20);
      timer.style.setProperty('--turn-progress', `${Math.max(0, Math.min(100, remainingMs / (duration * 1000) * 100))}%`);
      timer.classList.toggle('urgent', seconds <= 5);
      const value = timer.querySelector('.timer-value');
      if (value && timer.dataset.seconds !== String(seconds)) {
        value.textContent = String(seconds);
        timer.dataset.seconds = String(seconds);
        timer.setAttribute('aria-label', `${seconds} sekund do automatické akce`);
      }
    });
  }, 250);
}

byId('registerBtn').addEventListener('click', registerUser);
byId('loginBtn').addEventListener('click', loginUser);
byId('refreshRoomsBtn').addEventListener('click', loadRooms);
byId('createRoomBtn').addEventListener('click', createRoom);
byId('joinSelectedBtn').addEventListener('click', joinSelectedRoom);
byId('startGameBtn').addEventListener('click', startHand);
byId('foldBtn').addEventListener('click', () => sendAction('fold'));
byId('checkBtn').addEventListener('click', () => sendAction('check'));
byId('callBtn').addEventListener('click', () => sendAction('call'));
byId('allInBtn').addEventListener('click', () => sendAction('all_in'));
byId('raiseBtn').addEventListener('click', () => sendAction(state.room?.current_bet ? 'raise' : 'bet'));
byId('simulateEquityBtn').addEventListener('click', simulateEquity);
els.raiseInput.addEventListener('input', () => setRaiseAmount(els.raiseInput.value));
els.raiseSlider.addEventListener('input', () => setRaiseAmount(els.raiseSlider.value));
document.querySelectorAll('.preset-btn').forEach((button) => button.addEventListener('click', () => {
  if (button.dataset.action) sendAction(button.dataset.action);
  else applyPreset(button);
}));
els.password.addEventListener('keydown', (event) => { if (event.key === 'Enter') loginUser(); });
document.addEventListener('pointerdown', primeAudio, { once: true });
document.addEventListener('keydown', primeAudio, { once: true });

async function initialize() {
  initializeAppearanceControls();
  renderRooms();
  renderRoom(null);
  updateUserSummary();
  updateControls();
  startTurnTicker();
  await loadRooms();
  if (!state.token) return;
  try {
    state.me = await fetchJson(`${apiBase}/me`);
    updateUserSummary();
    if (state.room) {
      state.renderedRoomKey = '';
      applyRoomState(state.room);
    }
    connectSocket();
    if (state.selectedRoomId) await getRoomDetails(state.selectedRoomId, false);
  } catch (error) {
    clearSession();
    setStatus('Přihlášení vypršelo. Přihlaste se znovu.', 'error');
  }
  updateControls();
}

document.addEventListener('DOMContentLoaded', initialize);
