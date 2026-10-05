/* Advisory Monte Carlo equity simulation; this never participates in game decisions. */
const RANKS = { 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, T: 10, J: 11, Q: 12, K: 13, A: 14 };
const SUITS = { s: 0, '♠': 0, h: 1, '♥': 1, d: 2, '♦': 2, c: 3, '♣': 3 };

function parseCard(card) {
  const value = String(card || '').trim();
  const rankToken = value.startsWith('10') ? 'T' : value.slice(0, -1).toUpperCase();
  const suitToken = value.slice(-1);
  if (!(rankToken in RANKS) || !(suitToken in SUITS)) throw new Error(`Neplatná karta: ${value || '?'}`);
  return (RANKS[rankToken] - 2) * 4 + SUITS[suitToken];
}

function straightHigh(present) {
  for (let high = 14; high >= 6; high -= 1) {
    if (present[high] && present[high - 1] && present[high - 2] && present[high - 3] && present[high - 4]) return high;
  }
  return present[14] && present[5] && present[4] && present[3] && present[2] ? 5 : 0;
}

function scoreHand(cards) {
  const counts = new Uint8Array(15);
  const present = new Uint8Array(15);
  const suitRanks = [[], [], [], []];
  for (const card of cards) {
    const rank = (card >> 2) + 2;
    const suit = card & 3;
    counts[rank] += 1;
    present[rank] = 1;
    suitRanks[suit].push(rank);
  }

  let flushRanks = null;
  for (const ranks of suitRanks) if (ranks.length >= 5) flushRanks = ranks.sort((a, b) => b - a);
  if (flushRanks) {
    const suitedPresent = new Uint8Array(15);
    flushRanks.forEach((rank) => { suitedPresent[rank] = 1; });
    const sf = straightHigh(suitedPresent);
    if (sf) return [8, sf];
  }

  const quads = [];
  const trips = [];
  const pairs = [];
  const singles = [];
  for (let rank = 14; rank >= 2; rank -= 1) {
    if (counts[rank] === 4) quads.push(rank);
    else if (counts[rank] === 3) trips.push(rank);
    else if (counts[rank] === 2) pairs.push(rank);
    else if (counts[rank] === 1) singles.push(rank);
  }
  if (quads.length) return [7, quads[0], ...[...trips, ...pairs, ...singles].sort((a, b) => b - a).slice(0, 1)];
  const housePair = [...trips.slice(1), ...pairs].sort((a, b) => b - a)[0];
  if (trips.length && housePair) return [6, trips[0], housePair];
  if (flushRanks) return [5, ...flushRanks.slice(0, 5)];
  const straight = straightHigh(present);
  if (straight) return [4, straight];
  if (trips.length) return [3, trips[0], ...[...trips.slice(1), ...pairs, ...singles].sort((a, b) => b - a).slice(0, 2)];
  if (pairs.length >= 2) return [2, pairs[0], pairs[1], ...[...pairs.slice(2), ...singles].sort((a, b) => b - a).slice(0, 1)];
  if (pairs.length === 1) return [1, pairs[0], ...[...trips.slice(1), ...singles].sort((a, b) => b - a).slice(0, 3)];
  return [0, ...Array.from(present).map((count, rank) => count ? rank : 0).filter(Boolean).sort((a, b) => b - a).slice(0, 5)];
}

function compare(left, right) {
  const size = Math.max(left.length, right.length);
  for (let i = 0; i < size; i += 1) {
    const delta = (left[i] || 0) - (right[i] || 0);
    if (delta) return Math.sign(delta);
  }
  return 0;
}

function simulate(data) {
  const hole = (data.holeCards || []).map(parseCard);
  const board = (data.board || []).map(parseCard);
  const opponents = Math.trunc(Number(data.opponents));
  const iterations = Math.max(1, Math.min(100000, Math.trunc(Number(data.iterations) || 100000)));
  if (hole.length !== 2 || board.length > 5 || opponents < 1 || opponents > 8) throw new Error('Neúplné údaje pro simulaci.');
  const known = [...hole, ...board];
  if (new Set(known).size !== known.length) throw new Error('Karty se v zadání opakují.');
  const knownSet = new Set(known);
  const deck = Array.from({ length: 52 }, (_, card) => card).filter((card) => !knownSet.has(card));
  const missingBoard = 5 - board.length;
  const draws = missingBoard + opponents * 2;
  if (draws > deck.length) throw new Error('Nedostatek karet pro daný počet soupeřů.');

  const swaps = new Uint8Array(draws);
  let wins = 0, ties = 0, losses = 0, equityTotal = 0, equitySquaredTotal = 0;
  const startedAt = performance.now();
  const reportEvery = Math.max(250, Math.floor(iterations / 100));
  for (let run = 1; run <= iterations; run += 1) {
    for (let i = 0; i < draws; i += 1) {
      const target = i + Math.floor(Math.random() * (deck.length - i));
      swaps[i] = target;
      [deck[i], deck[target]] = [deck[target], deck[i]];
    }
    const completeBoard = board.concat(Array.from(deck.slice(0, missingBoard)));
    const heroScore = scoreHand(hole.concat(completeBoard));
    let bestOpponent = null, bestOpponentCount = 0;
    for (let player = 0, offset = missingBoard; player < opponents; player += 1, offset += 2) {
      const score = scoreHand([deck[offset], deck[offset + 1], ...completeBoard]);
      const comparison = bestOpponent === null ? 1 : compare(score, bestOpponent);
      if (comparison > 0) { bestOpponent = score; bestOpponentCount = 1; }
      else if (comparison === 0) bestOpponentCount += 1;
    }
    const result = compare(heroScore, bestOpponent);
    let share;
    if (result > 0) { wins += 1; share = 1; }
    else if (result < 0) { losses += 1; share = 0; }
    else {
      ties += 1;
      share = 1 / (bestOpponentCount + 1);
    }
    equityTotal += share;
    equitySquaredTotal += share * share;
    for (let i = draws - 1; i >= 0; i -= 1) {
      const target = swaps[i];
      [deck[i], deck[target]] = [deck[target], deck[i]];
    }
    if (run === iterations || run % reportEvery === 0) {
      self.postMessage({ type: 'progress', completed: run, total: iterations, percent: Math.floor(run / iterations * 100) });
    }
  }
  const durationMs = performance.now() - startedAt;
  const winProbability = wins / iterations;
  const equity = equityTotal / iterations;
  const variance = Math.max(0, (equitySquaredTotal - iterations * equity * equity) / Math.max(1, iterations - 1));
  return {
    type: 'complete', simulations: iterations,
    win_probability: winProbability, tie_probability: ties / iterations, lose_probability: losses / iterations,
    equity, confidence95: 1.96 * Math.sqrt(variance / iterations),
    duration_ms: durationMs,
  };
}

self.addEventListener('message', (event) => {
  try { self.postMessage(simulate(event.data || {})); }
  catch (error) { self.postMessage({ type: 'error', message: error instanceof Error ? error.message : 'Simulaci se nepodařilo spustit.' }); }
});
