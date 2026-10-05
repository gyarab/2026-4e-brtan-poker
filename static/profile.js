const profileApi = '/api';
const token = localStorage.getItem('token') || '';
const chipFormatter = new Intl.NumberFormat('cs-CZ');
const state = { hand: null, replayIndex: 0, replayTimer: null, userId: null };
const byId = (id) => document.getElementById(id);

function chips(value) {
  const amount = Number(value) || 0;
  return `${amount > 0 ? '+' : ''}${chipFormatter.format(amount)}`;
}

function setStatus(message, error = false) {
  byId('profileStatus').textContent = message || '';
  byId('profileStatus').dataset.tone = error ? 'error' : 'info';
}

async function fetchJson(path) {
  const response = await fetch(`${profileApi}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Data profilu se nepodařilo načíst.');
  return data;
}

function setText(id, value) {
  byId(id).textContent = value;
}

function renderDecisionBars(stats) {
  const names = { fold: 'Fold', check: 'Check', call: 'Call', bet: 'Bet', raise: 'Raise', all_in: 'All-in' };
  const rows = Object.keys(names).map((action) => {
    const row = document.createElement('div'); row.className = 'decision-row';
    const label = document.createElement('span'); label.textContent = names[action];
    const track = document.createElement('span'); track.className = 'decision-track';
    const fill = document.createElement('span');
    fill.style.width = `${Math.max(0, Math.min(100, Number(stats.decision_percentages?.[action]) || 0))}%`;
    track.append(fill);
    const value = document.createElement('span'); value.className = 'decision-value';
    value.textContent = String(Number(stats.decisions?.[action]) || 0);
    row.append(label, track, value);
    return row;
  });
  byId('decisionBars').replaceChildren(...rows);
}

function renderChipChart(history) {
  const host = byId('chipsChart');
  host.replaceChildren();
  if (!Array.isArray(history) || !history.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-state';
    empty.textContent = 'Výsledky se zobrazí po dokončených handách.';
    host.append(empty);
    setText('chartCurrent', '0 žetonů');
    return;
  }
  const values = history.map((item) => Number(item.cumulative) || 0);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const spread = max - min || 1;
  const width = 600, height = 150, padding = 10;
  const points = values.map((value, index) => {
    const x = history.length === 1 ? width / 2 : padding + index * (width - padding * 2) / (history.length - 1);
    const y = height - padding - (value - min) / spread * (height - padding * 2);
    return `${x},${y}`;
  }).join(' ');
  const firstX = history.length === 1 ? width / 2 : padding;
  const lastX = history.length === 1 ? width / 2 : width - padding;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('preserveAspectRatio', 'none');
  const defs = document.createElementNS(svg.namespaceURI, 'defs');
  const gradient = document.createElementNS(svg.namespaceURI, 'linearGradient');
  gradient.id = 'chartFill'; gradient.setAttribute('x1', '0'); gradient.setAttribute('x2', '0');
  gradient.setAttribute('y1', '0'); gradient.setAttribute('y2', '1');
  const stopA = document.createElementNS(svg.namespaceURI, 'stop'); stopA.setAttribute('offset', '0%'); stopA.setAttribute('stop-color', '#cdb77a');
  const stopB = document.createElementNS(svg.namespaceURI, 'stop'); stopB.setAttribute('offset', '100%'); stopB.setAttribute('stop-color', '#cdb77a'); stopB.setAttribute('stop-opacity', '0');
  gradient.append(stopA, stopB); defs.append(gradient); svg.append(defs);
  const area = document.createElementNS(svg.namespaceURI, 'polygon');
  area.setAttribute('class', 'chart-area'); area.setAttribute('points', `${firstX},${height} ${points} ${lastX},${height}`);
  const line = document.createElementNS(svg.namespaceURI, 'polyline');
  line.setAttribute('class', 'chart-line'); line.setAttribute('points', points);
  const [lastPointX, lastPointY] = points.split(' ').at(-1).split(',');
  const dot = document.createElementNS(svg.namespaceURI, 'circle');
  dot.setAttribute('class', 'chart-dot'); dot.setAttribute('cx', lastPointX); dot.setAttribute('cy', lastPointY); dot.setAttribute('r', '4');
  svg.append(area, line, dot); host.append(svg);
  const net = values.at(-1) || 0;
  setText('chartCurrent', `${chips(net)} žetonů`);
  byId('chartCurrent').dataset.tone = net < 0 ? 'negative' : 'positive';
}

function renderAchievements(unlocked = []) {
  const catalog = [
    ['First Win', 'První vítězná handa', '♛'], ['First All-in', 'První all-in', '✦'],
    ['Royal Flush', 'Royal flush', '♠'], ['10 Hands Played', '10 odehraných hand', '10'],
    ['100 Hands Played', '100 odehraných hand', '100'], ['Biggest Pot', 'Největší vítězný pot', '◆'],
    ['Perfect Fold', 'Fold, který by prohrál', '◇'],
    ['Winning Session', 'Kladný výsledek', '＋'],
  ];
  const items = catalog.map(([key, label, symbol]) => {
    const item = document.createElement('div');
    item.className = `achievement${unlocked.includes(key) ? ' unlocked' : ''}`;
    const icon = document.createElement('span'); icon.className = 'achievement-icon'; icon.textContent = symbol;
    const text = document.createElement('span'); text.textContent = label;
    item.append(icon, text);
    return item;
  });
  byId('achievementList').replaceChildren(...items);
}

function renderStats(stats) {
  setText('profileName', stats.username || 'Hráč');
  setText('profileHeaderUser', stats.username || 'Profil hráče');
  setText('profileMonogram', String(stats.username || 'RH').slice(0, 2).toUpperCase());
  setText('profileMessage', stats.hands_played ? 'Osobní výsledky z dokončených herních hand.' : 'Zatím bez dokončených hand.');
  setText('statHands', chipFormatter.format(stats.hands_played || 0));
  setText('statHandsWon', `${chipFormatter.format(stats.hands_won || 0)} výher`);
  setText('statWinRate', `${Number(stats.win_rate || 0).toFixed(1)} %`);
  setText('statNetChips', chips(stats.total_chips_net || 0));
  byId('statNetChips').dataset.tone = Number(stats.total_chips_net) < 0 ? 'negative' : 'positive';
  setText('statBiggestPot', chipFormatter.format(stats.biggest_pot || 0));
  setText('statAveragePot', `Průměr ${chipFormatter.format(stats.average_pot || 0)}`);
  setText('statVpip', `${Number(stats.vpip || 0).toFixed(1)} %`);
  setText('statPfr', `${Number(stats.pfr || 0).toFixed(1)} %`);
  setText('statDuration', `${Number(stats.average_duration_seconds || 0).toFixed(1)} s`);
  renderDecisionBars(stats);
  renderChipChart(stats.chips_history || []);
  renderAchievements(stats.achievements || []);
}

function renderCard(card) {
  const element = document.createElement('div'); element.className = 'poker-card card-deal-in';
  element.setAttribute('role', 'img');
  if (!card || card === 'XX') {
    element.classList.add('back');
    element.setAttribute('aria-label', 'Skrytá karta');
    const back = document.createElement('span'); back.className = 'card-back'; back.textContent = '♠'; element.append(back);
    return element;
  }
  const suit = Array.from(String(card).slice(-1))[0];
  const rank = String(card).slice(0, -1) === 'T' ? '10' : String(card).slice(0, -1);
  const spokenRanks = { A: 'eso', K: 'král', Q: 'dáma', J: 'kluk', '10': 'desítka' };
  const spokenSuits = { '♠': 'piky', '♥': 'srdce', '♦': 'káry', '♣': 'kříže' };
  element.setAttribute('aria-label', `${spokenRanks[rank] || rank} ${spokenSuits[suit] || ''}`.trim());
  element.classList.add(['♥', '♦'].includes(suit) ? 'red' : 'black');
  const rankElement = document.createElement('span'); rankElement.className = 'card-rank'; rankElement.textContent = rank;
  const suitElement = document.createElement('span'); suitElement.className = 'card-suit'; suitElement.textContent = suit;
  element.append(rankElement, suitElement);
  return element;
}

function formatDate(timestamp) {
  if (!timestamp) return 'Datum neuvedeno';
  return new Date(Number(timestamp) * 1000).toLocaleString('cs-CZ', { dateStyle: 'medium', timeStyle: 'short' });
}

function renderReplayPlayers(index) {
  const hand = state.hand;
  const events = hand?.events || [];
  const players = hand?.players || [];
  const stacks = new Map(players.map((player) => [Number(player.id), Number(player.chips_before) || 0]));
  const folded = new Set();
  const allIn = new Set();
  const winners = new Set();
  const lastAction = new Map();
  const positions = new Map();
  let reachedShowdown = false;

  for (const event of events.slice(0, index + 1)) {
    if (event.message === 'Hand started') {
      const bySeat = (seat) => players.find((player) => Number(player.seat) === Number(seat));
      const addPosition = (player, label) => {
        if (!player) return;
        const id = Number(player.id);
        positions.set(id, [positions.get(id), label].filter(Boolean).join(' · '));
      };
      const dealer = bySeat(event.dealer_index);
      const smallBlind = bySeat(event.small_blind_index);
      const bigBlind = bySeat(event.big_blind_index);
      addPosition(dealer, 'BTN');
      if (smallBlind) {
        addPosition(smallBlind, 'SB');
        stacks.set(Number(smallBlind.id), Math.max(0, (stacks.get(Number(smallBlind.id)) || 0) - (Number(event.small_blind) || 0)));
      }
      if (bigBlind) {
        addPosition(bigBlind, 'BB');
        stacks.set(Number(bigBlind.id), Math.max(0, (stacks.get(Number(bigBlind.id)) || 0) - (Number(event.big_blind) || 0)));
      }
      if (smallBlind && stacks.get(Number(smallBlind.id)) === 0) allIn.add(Number(smallBlind.id));
      if (bigBlind && stacks.get(Number(bigBlind.id)) === 0) allIn.add(Number(bigBlind.id));
    }
    if (event.player_id != null && event.action) {
      const playerId = Number(event.player_id);
      stacks.set(playerId, Math.max(0, (stacks.get(playerId) || 0) - (Number(event.amount) || 0)));
      lastAction.set(playerId, event.action.replaceAll('_', ' '));
      if (event.action === 'fold') folded.add(playerId);
      if (event.action === 'all_in') allIn.add(playerId);
    }
    if (Array.isArray(event.winner_ids)) event.winner_ids.forEach((id) => winners.add(Number(id)));
    if (Array.isArray(event.awards)) event.awards.forEach((award) => {
      const playerId = Number(award.player_id);
      stacks.set(playerId, (stacks.get(playerId) || 0) + (Number(award.amount) || 0));
    });
    else if (Array.isArray(event.winner_ids) && event.winner_ids.length === 1 && Number(event.amount) > 0) {
      const winnerId = Number(event.winner_ids[0]);
      stacks.set(winnerId, (stacks.get(winnerId) || 0) + Number(event.amount));
    }
    if (event.phase === 'showdown') reachedShowdown = true;
  }

  const cardsMayBeRevealed = reachedShowdown;
  const nodes = players.map((player) => {
    const id = Number(player.id);
    const classes = ['replay-player'];
    if (folded.has(id)) classes.push('folded');
    if (allIn.has(id)) classes.push('all-in');
    if (winners.has(id)) classes.push('winner');
    const node = document.createElement('article'); node.className = classes.join(' ');
    const identity = document.createElement('div'); identity.className = 'replay-player-identity';
    const name = document.createElement('strong'); name.textContent = player.username;
    const stack = document.createElement('span'); stack.textContent = chipFormatter.format(stacks.get(id) || 0);
    identity.append(name, stack);
    const flags = document.createElement('div'); flags.className = 'replay-player-flags';
    const position = positions.get(id);
    if (position) { const badge = document.createElement('span'); badge.textContent = position; flags.append(badge); }
    if (folded.has(id)) { const badge = document.createElement('span'); badge.textContent = 'FOLD'; flags.append(badge); }
    if (allIn.has(id)) { const badge = document.createElement('span'); badge.textContent = 'ALL-IN'; flags.append(badge); }
    if (winners.has(id)) { const badge = document.createElement('span'); badge.textContent = 'VÍTĚZ'; flags.append(badge); }
    const action = document.createElement('small'); action.className = 'replay-player-action';
    action.textContent = lastAction.get(id) || '—';
    const holeCards = Array.isArray(player.hole_cards) ? player.hole_cards : [];
    const showCards = id === state.userId || cardsMayBeRevealed && !folded.has(id);
    const cards = document.createElement('div'); cards.className = 'replay-player-cards';
    const visibleCards = showCards ? holeCards : ['XX', 'XX'];
    cards.replaceChildren(...visibleCards.map((card) => renderCard(card)));
    node.append(identity, flags, action, cards);
    return node;
  });
  byId('replayPlayers').replaceChildren(...nodes);
}

function renderHands(hands) {
  if (!hands.length) {
    const empty = document.createElement('div'); empty.className = 'empty-state';
    empty.textContent = 'Po dokončené handě se zde objeví záznam a možnost přehrání.';
    byId('profileHands').replaceChildren(empty); return;
  }
  const buttons = hands.map((hand) => {
    const button = document.createElement('button'); button.className = 'profile-hand'; button.type = 'button';
    const main = document.createElement('span'); main.className = 'profile-hand-main';
    const title = document.createElement('span'); title.className = 'profile-hand-title'; title.textContent = `${hand.room_name} · Hand #${hand.hand_number}`;
    const meta = document.createElement('span'); meta.className = 'profile-hand-meta'; meta.textContent = `${formatDate(hand.completed_at)} · ${hand.players.length} hráči`;
    main.append(title, meta);
    const pot = document.createElement('span'); pot.className = 'profile-hand-pot'; pot.textContent = `Pot ${chipFormatter.format(hand.pot)}`;
    button.append(main, pot);
    button.addEventListener('click', () => openReplay(hand));
    return button;
  });
  byId('profileHands').replaceChildren(...buttons);
}

function replayStop() {
  if (state.replayTimer) window.clearInterval(state.replayTimer);
  state.replayTimer = null;
  byId('replayPlayBtn').textContent = 'Přehrát';
}

function renderReplay() {
  const hand = state.hand;
  if (!hand) return;
  const events = hand.events || [];
  const index = Math.max(0, Math.min(state.replayIndex, events.length - 1));
  state.replayIndex = index;
  const event = events[index];
  const board = [];
  let latestBoard = [];
  for (let i = 0; i <= index; i += 1) if (Array.isArray(events[i].board)) latestBoard = events[i].board;
  board.push(...latestBoard);
  byId('replayBoard').replaceChildren(...board.map(renderCard));
  renderReplayPlayers(index);
  const replayPot = Number.isFinite(Number(event?.pot)) ? Number(event.pot) : Number(hand.pot) || 0;
  setText('replayPot', `POT · ${chipFormatter.format(replayPot)}`);
  setText('replayPhase', String(event?.phase || 'preflop').toUpperCase());
  setText('replayMessage', event?.message || 'Handa byla rozdána.');
  setText('replayStep', `${events.length ? index + 1 : 0} / ${events.length}`);
  byId('replayPrevBtn').disabled = index <= 0;
  byId('replayNextBtn').disabled = index >= events.length - 1;
  const rows = events.map((entry, eventIndex) => {
    const row = document.createElement('li'); if (eventIndex === index) row.classList.add('active');
    const phase = document.createElement('span'); phase.textContent = String(entry.phase || 'hand').toUpperCase();
    const message = document.createElement('span'); message.textContent = entry.message || 'Hand event';
    row.append(phase, message);
    row.addEventListener('click', () => { replayStop(); state.replayIndex = eventIndex; renderReplay(); });
    return row;
  });
  byId('replayTimeline').replaceChildren(...rows);
}

function openReplay(hand) {
  replayStop();
  state.hand = hand;
  state.replayIndex = 0;
  byId('replayTitle').textContent = `${hand.room_name} · Hand #${hand.hand_number}`;
  byId('replayCard').hidden = false;
  renderReplay();
  byId('replayCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function moveReplay(delta) {
  replayStop();
  if (!state.hand) return;
  state.replayIndex = Math.max(0, Math.min((state.hand.events || []).length - 1, state.replayIndex + delta));
  renderReplay();
}

byId('closeReplayBtn').addEventListener('click', () => {
  replayStop(); byId('replayCard').hidden = true; state.hand = null;
});
byId('replayPrevBtn').addEventListener('click', () => moveReplay(-1));
byId('replayNextBtn').addEventListener('click', () => moveReplay(1));
byId('replayPlayBtn').addEventListener('click', () => {
  if (!state.hand) return;
  if (state.replayTimer) { replayStop(); return; }
  if (state.replayIndex >= state.hand.events.length - 1) state.replayIndex = 0;
  byId('replayPlayBtn').textContent = 'Pozastavit';
  state.replayTimer = window.setInterval(() => {
    if (state.replayIndex >= state.hand.events.length - 1) { replayStop(); return; }
    state.replayIndex += 1; renderReplay();
    byId('replayPlayBtn').textContent = 'Pozastavit';
  }, 1050);
  renderReplay(); byId('replayPlayBtn').textContent = 'Pozastavit';
});

async function initializeProfile() {
  if (!token) {
    setText('profileName', 'Nejste přihlášeni');
    setText('profileMessage', 'Pro zobrazení soukromých statistik se přihlaste u pokerového stolu.');
    setStatus('Chybí přihlašovací token.', true);
    return;
  }
  try {
    const [me, stats, history] = await Promise.all([
      fetchJson('/me'), fetchJson('/me/stats'), fetchJson('/me/hands?limit=50'),
    ]);
    state.userId = Number(me.id);
    byId('profileHeaderUser').textContent = `${me.username} · ${chipFormatter.format(me.chips)} žetonů`;
    renderStats(stats);
    renderHands(history.hands || []);
    setStatus('Statistiky se počítají z uložených dokončených hand.');
  } catch (error) {
    setStatus(error.message, true);
    setText('profileMessage', 'Přihlášení mohlo vypršet. Vraťte se ke stolu a přihlaste se znovu.');
  }
}

document.addEventListener('DOMContentLoaded', initializeProfile);
