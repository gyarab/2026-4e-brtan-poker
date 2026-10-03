const apiBase = '/api';
const state = {
  token: localStorage.getItem('token') || '',
  selectedRoomId: null,
  room: null,
  socket: null,
  me: null,
  refreshTimer: null,
};

const els = {
  username: document.getElementById('username'),
  email: document.getElementById('email'),
  password: document.getElementById('password'),
  roomName: document.getElementById('roomName'),
  maxPlayers: document.getElementById('maxPlayers'),
  smallBlind: document.getElementById('smallBlind'),
  roomList: document.getElementById('roomList'),
  selectedRoomLabel: document.getElementById('selectedRoomLabel'),
  playersArea: document.getElementById('playersArea'),
  roomJson: document.getElementById('roomJson'),
  statusArea: document.getElementById('statusArea'),
  boardArea: document.getElementById('boardArea'),
  potArea: document.getElementById('potArea'),
  userSummary: document.getElementById('userSummary'),
  raiseInput: document.getElementById('raiseInput'),
  actionLog: document.getElementById('actionLog'),
};

function setStatus(message, tone = 'info') {
  els.statusArea.textContent = message;
  els.statusArea.dataset.tone = tone;
}

function authHeaders() {
  return { Authorization: `Bearer ${state.token}` };
}

function validateUsername(value) {
  return value.trim().length >= 3 ? '' : 'Uživatelské jméno musí mít alespoň 3 znaky.';
}

function validateEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? '' : 'Email není ve správném tvaru.';
}

function validatePassword(value) {
  return value.length >= 6 ? '' : 'Heslo musí mít alespoň 6 znaků.';
}

function ensureLoggedIn() {
  if (!state.token) {
    setStatus('Nejdříve se přihlašte.', 'error');
    return false;
  }
  return true;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    if (typeof detail === 'string') {
      throw new Error(detail);
    }
    if (Array.isArray(detail)) {
      const message = detail.map((item) => item.msg || item).join(', ');
      throw new Error(message || 'Operace selhala.');
    }
    if (detail && typeof detail === 'object') {
      throw new Error(JSON.stringify(detail));
    }
    throw new Error('Operace selhala.');
  }
  return data;
}

function updateUserSummary() {
  if (state.me) {
    els.userSummary.textContent = `Přihlášen: ${state.me.username}`;
  } else {
    els.userSummary.textContent = 'Nepřihlášen';
  }
}

function getMySeatState() {
  if (!state.room || !state.me) {
    return { isMyTurn: false, callNeeded: 0, canCheck: false, canCall: false };
  }

  const myPlayer = (state.room.players || []).find((player) => player.id === state.me.id);
  if (!myPlayer) {
    return { isMyTurn: false, callNeeded: 0, canCheck: false, canCall: false };
  }

  const callNeeded = Number(state.room.current_bet || 0) - Number(myPlayer.bet_this_round || 0);
  const currentSeat = Number(state.room.current_turn ?? -1);
  const isMyTurn = Number(myPlayer.seat) === currentSeat;

  return {
    isMyTurn,
    callNeeded: Math.max(0, callNeeded),
    canCheck: isMyTurn && Math.max(0, Number(state.room.current_bet || 0) - Number(myPlayer.bet_this_round || 0)) === 0,
    canCall: isMyTurn && Math.max(0, Number(state.room.current_bet || 0) - Number(myPlayer.bet_this_round || 0)) > 0,
  };
}

function setButtonState() {
  const isLoggedIn = Boolean(state.token);
  const roomReady = isLoggedIn && Boolean(state.selectedRoomId);
  const myTurnInfo = getMySeatState();

  document.getElementById('createRoomBtn').disabled = !isLoggedIn;
  document.getElementById('joinSelectedBtn').disabled = !roomReady;
  document.getElementById('startGameBtn').disabled = !roomReady;
  document.getElementById('checkBtn').disabled = !roomReady || !myTurnInfo.canCheck;
  document.getElementById('callBtn').disabled = !roomReady || !myTurnInfo.canCall;
  document.getElementById('raiseBtn').disabled = !roomReady || !myTurnInfo.isMyTurn;
  document.getElementById('foldBtn').disabled = !roomReady || !myTurnInfo.isMyTurn;
  els.raiseInput.disabled = !roomReady || !myTurnInfo.isMyTurn;
}

async function registerUser() {
  const usernameError = validateUsername(els.username.value);
  const emailError = validateEmail(els.email.value.trim());
  const passwordError = validatePassword(els.password.value);

  if (usernameError || emailError || passwordError) {
    setStatus([usernameError, emailError, passwordError].filter(Boolean)[0], 'error');
    return;
  }

  try {
    const payload = {
      username: els.username.value.trim(),
      email: els.email.value.trim(),
      password: els.password.value,
    };
    await fetchJson(`${apiBase}/auth/register`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    setStatus('Registrace OK. Nyní se přihlašte.', 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

async function loginUser() {
  const emailError = validateEmail(els.email.value.trim());
  const passwordError = validatePassword(els.password.value);

  if (emailError || passwordError) {
    setStatus([emailError, passwordError].filter(Boolean)[0], 'error');
    return;
  }

  try {
    const payload = {
      email: els.email.value.trim(),
      password: els.password.value,
    };
    const data = await fetchJson(`${apiBase}/auth/login`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    state.token = data.access_token;
    localStorage.setItem('token', state.token);
    const me = await fetchJson(`${apiBase}/me`, { headers: authHeaders() });
    state.me = me;
    updateUserSummary();
    setButtonState();
    await loadRooms();
    connectSocket();
    setStatus('Přihlášení OK.', 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

async function loadRooms() {
  if (!state.token) {
    renderRooms([]);
    return;
  }

  try {
    const data = await fetchJson(`${apiBase}/rooms`, { headers: authHeaders() });
    renderRooms(data.rooms || []);
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

function renderRooms(rooms) {
  els.roomList.innerHTML = '';

  if (!rooms.length) {
    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state';
    emptyState.textContent = 'Žádné místnosti. Vytvořte novou hru.';
    els.roomList.appendChild(emptyState);
    return;
  }

  rooms.forEach((room) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `room-item ${state.selectedRoomId === room.room_id ? 'active' : ''}`;
    item.textContent = `${room.name} (${room.player_count}/${room.max_players}) – ${room.phase}`;
    item.addEventListener('click', () => {
      state.selectedRoomId = room.room_id;
      els.selectedRoomLabel.textContent = room.name;
      renderRooms(rooms);
      getRoomDetails(room.room_id);
      setButtonState();
    });
    els.roomList.appendChild(item);
  });
}

async function createRoom() {
  if (!ensureLoggedIn()) return;

  const roomName = els.roomName.value.trim();
  if (!roomName) {
    setStatus('Název místnosti je povinný.', 'error');
    return;
  }

  const maxPlayers = Number(els.maxPlayers.value);
  const smallBlind = Number(els.smallBlind.value);

  if (!Number.isFinite(maxPlayers) || maxPlayers < 2 || maxPlayers > 9) {
    setStatus('Počet hráčů musí být v rozmezí 2 až 9.', 'error');
    return;
  }

  if (!Number.isFinite(smallBlind) || smallBlind < 1 || smallBlind > 1000) {
    setStatus('Small blind musí být v rozmezí 1 až 1000.', 'error');
    return;
  }

  try {
    const payload = {
      name: roomName,
      max_players: maxPlayers,
      small_blind: smallBlind,
    };
    console.log('Create room payload:', payload);
    const result = await fetchJson(`${apiBase}/rooms`, {
      method: 'POST',
      headers: {
        ...authHeaders(),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    state.selectedRoomId = result.room.room_id;
    els.selectedRoomLabel.textContent = result.room.name;
    await getRoomDetails(result.room.room_id);
    await loadRooms();
    setStatus('Místnost vytvořena.', 'success');
    setButtonState();
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

async function getRoomDetails(roomId) {
  try {
    const data = await fetchJson(`${apiBase}/rooms/${roomId}`, { headers: authHeaders() });
    applyRoomState(data.room);
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

async function joinSelectedRoom() {
  if (!ensureLoggedIn()) return;
  if (!state.selectedRoomId) {
    setStatus('Vyber místnost, ke které se chceš připojit.', 'error');
    return;
  }

  try {
    const data = await fetchJson(`${apiBase}/rooms/${state.selectedRoomId}/join`, {
      method: 'POST',
      headers: authHeaders(),
    });
    applyRoomState(data.room);
    setStatus('Připojeno k místnosti.', 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

async function startGame() {
  if (!ensureLoggedIn()) return;
  if (!state.selectedRoomId) {
    setStatus('Vyber místnost pro zahájení hry.', 'error');
    return;
  }

  try {
    const data = await fetchJson(`${apiBase}/rooms/${state.selectedRoomId}/start`, {
      method: 'POST',
      headers: authHeaders(),
    });
    applyRoomState(data.room);
    setStatus('Nový hand byl spuštěn.', 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

function getRaiseAmount() {
  const value = Number(els.raiseInput.value);
  if (!Number.isFinite(value) || value < 10) {
    return 10;
  }
  return value;
}

function renderCard(card) {
  if (!card || card === 'XX') {
    return '<div class="poker-card back"><span class="card-back">♠</span></div>';
  }

  const suit = card.slice(-1);
  const rank = card.slice(0, -1);
  const isRed = ['♥', '♦'].includes(suit);
  return `
    <div class="poker-card ${isRed ? 'red' : 'black'}">
      <span class="card-rank">${rank}</span>
      <span class="card-suit">${suit}</span>
    </div>
  `;
}

function renderCards(cards = []) {
  return cards.map((card) => renderCard(card)).join('');
}

async function sendAction(action, amount = null) {
  if (!ensureLoggedIn()) return;
  if (!state.selectedRoomId) {
    setStatus('Vyber místnost pro akci.', 'error');
    return;
  }

  const finalAmount = action === 'raise' ? getRaiseAmount() : amount;

  try {
    const payload = {
      room_id: state.selectedRoomId,
      action,
      amount: finalAmount,
    };
    const data = await fetchJson(`${apiBase}/rooms/${state.selectedRoomId}/action`, {
      method: 'POST',
      headers: {
        ...authHeaders(),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    applyRoomState(data.room);
    if (action === 'raise') {
      setStatus(`Raise ${finalAmount} byl odeslán.`, 'success');
    } else {
      setStatus(`Akce ${action} byla odeslána.`, 'success');
    }
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

function renderActionLog(history = []) {
  if (!els.actionLog) return;
  const entries = Array.isArray(history) ? history.slice(-8).reverse() : [];
  els.actionLog.innerHTML = entries.length
    ? entries.map((entry) => `<li>${entry}</li>`).join('')
    : '<li>Akce ještě nebyly zapsány.</li>';
}

function getPlayerCallAmount(player, room) {
  if (!player) return 0;
  const currentBet = Number(room?.current_bet || 0);
  const playerBet = Number(player.bet_this_round || 0);
  return Math.max(0, currentBet - playerBet);
}

function applyRoomState(room) {
  state.room = room;
  els.selectedRoomLabel.textContent = room.name || state.selectedRoomId || '-';
  const boardCards = Array.isArray(room.board) ? room.board : [];
  els.boardArea.innerHTML = `Board: ${boardCards.length ? renderCards(boardCards) : '<span class="board-empty">žádné karty</span>'}`;
  els.potArea.textContent = `Pot: ${room.pot || 0}`;
  renderActionLog(room.history || []);
  els.roomJson.textContent = JSON.stringify(room, null, 2);

  const playerCards = (room.players || []).map((player) => {
    const isCurrent = player.id === state.me?.id;
    const isTurn = Number(room.current_turn) === Number(player.seat);
    const holeCards = Array.isArray(player.hole_cards) ? player.hole_cards : [];
    const cardMarkup = isCurrent ? renderCards(holeCards) : renderCards(['XX', 'XX']);
    const status = player.folded ? 'Fold' : player.in_hand ? 'V hře' : 'Mimo hru';
    const badges = [];
    if (Number(room.dealer_index) === Number(player.seat)) badges.push('<span class="badge dealer">Dealer</span>');
    if (Number(room.small_blind_index) === Number(player.seat)) badges.push('<span class="badge small-blind">SB</span>');
    if (Number(room.big_blind_index) === Number(player.seat)) badges.push('<span class="badge big-blind">BB</span>');
    if (isTurn) badges.push('<span class="badge turn">Na tahu</span>');

    const callNeeded = getPlayerCallAmount(player, room);
    const actionText = isTurn
      ? callNeeded > 0
        ? `Call: ${callNeeded}`
        : 'Check / bet'
      : callNeeded > 0
        ? `Call ${callNeeded}`
        : 'V klidu';

    return `
      <div class="seat-card ${isTurn ? 'current-turn' : ''}">
        <div class="seat-header">
          <span class="seat-name">${player.username}</span>
          <span class="seat-chips">${player.chips}</span>
        </div>
        <div class="seat-badges">${badges.join('')}</div>
        <div class="seat-meta">Seat ${player.seat} · ${status}</div>
        <div class="seat-action">${actionText}</div>
        <div class="seat-cards">${cardMarkup}</div>
        ${Number(player.bet_this_round || 0) > 0 ? `<div class="seat-bet">Bet: ${player.bet_this_round}</div>` : ''}
        ${isCurrent ? '<div class="seat-self">Ty</div>' : ''}
      </div>
    `;
  }).join('');
  els.playersArea.innerHTML = playerCards;

  const mePlayer = (room.players || []).find((player) => player.id === state.me?.id);
  if (mePlayer) {
    const amountToCall = getPlayerCallAmount(mePlayer, room);
    const isMyTurn = Number(room.current_turn) === Number(mePlayer.seat);
    if (isMyTurn) {
      setStatus(amountToCall > 0 ? `Na tahu jsi. Musíš dorovnat ${amountToCall}.` : 'Na tahu jsi. Můžeš check / bet / raise.', 'success');
    } else if (room.current_turn !== null && room.current_turn !== undefined) {
      const currentPlayer = (room.players || []).find((player) => Number(player.seat) === Number(room.current_turn));
      const nextText = currentPlayer ? `Na tahu je ${currentPlayer.username}.` : 'Hraje se.';
      setStatus(nextText, 'info');
    }
  }

  setButtonState();
}

function startPolling() {
  if (state.refreshTimer) {
    clearInterval(state.refreshTimer);
  }

  state.refreshTimer = setInterval(async () => {
    if (!state.token) return;
    if (!state.selectedRoomId) return;
    try {
      const data = await fetchJson(`${apiBase}/rooms/${state.selectedRoomId}`, { headers: authHeaders() });
      applyRoomState(data.room);
    } catch (error) {
      console.warn('Room polling failed:', error.message);
    }
  }, 4000);
}

function connectSocket() {
  if (!state.token) return;
  if (state.socket) {
    state.socket.close();
  }
  const ws = new WebSocket(`ws://127.0.0.1:8000/ws?token=${encodeURIComponent(state.token)}`);
  state.socket = ws;

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'room_update' && message.room) {
      applyRoomState(message.room);
      if (state.selectedRoomId) {
        startPolling();
      }
    }
  };

  ws.onopen = () => {
    setStatus('WebSocket připojen.', 'success');
    startPolling();
  };

  ws.onclose = () => {
    setStatus('WebSocket uzavřen. Zkus obnovit stránku.', 'error');
  };
}

document.getElementById('registerBtn').addEventListener('click', registerUser);
document.getElementById('loginBtn').addEventListener('click', loginUser);
document.getElementById('refreshRoomsBtn').addEventListener('click', () => loadRooms());
document.getElementById('createRoomBtn').addEventListener('click', createRoom);
document.getElementById('joinSelectedBtn').addEventListener('click', joinSelectedRoom);
document.getElementById('startGameBtn').addEventListener('click', startGame);
document.getElementById('checkBtn').addEventListener('click', () => sendAction('check'));
document.getElementById('callBtn').addEventListener('click', () => sendAction('call'));
document.getElementById('raiseBtn').addEventListener('click', () => sendAction('raise', getRaiseAmount()));
document.getElementById('foldBtn').addEventListener('click', () => sendAction('fold'));

window.addEventListener('DOMContentLoaded', async () => {
  updateUserSummary();
  setButtonState();

  if (state.token) {
    try {
      const me = await fetchJson(`${apiBase}/me`, { headers: authHeaders() });
      state.me = me;
      updateUserSummary();
      connectSocket();
      await loadRooms();
    } catch (error) {
      localStorage.removeItem('token');
      state.token = '';
      updateUserSummary();
      setStatus('Relace přihlášení vypršela. Přihlašte se znovu.', 'error');
    }
  }

  await loadRooms();
  setButtonState();
});
