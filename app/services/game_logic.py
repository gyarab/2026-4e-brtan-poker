"""Authoritative Texas Hold'em rules and in-memory table state."""

from __future__ import annotations

import itertools
import math
import random
import threading
import time
import uuid
from copy import deepcopy
from collections import Counter
from functools import wraps
from typing import Any, Callable, TypeVar

ROOMS: dict[str, dict[str, Any]] = {}

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
RANK_VALUES = {rank: idx + 2 for idx, rank in enumerate(RANKS)}
_SUIT_ALIASES = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
_GAME_LOCK = threading.RLock()
TURN_TIMEOUT_SECONDS = 20
_T = TypeVar("_T")


def _locked(function: Callable[..., _T]) -> Callable[..., _T]:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> _T:
        with _GAME_LOCK:
            return function(*args, **kwargs)

    return wrapped


def _full_deck() -> list[str]:
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    random.SystemRandom().shuffle(deck)
    return deck


def _normalize_card_label(card: str) -> str:
    if not isinstance(card, str):
        raise ValueError("Cards must be strings")
    value = card.strip()
    if len(value) == 3 and value[:2] == "10":
        rank, suit = "T", value[2:]
    elif len(value) == 2:
        rank, suit = value[0].upper(), value[1:]
    else:
        raise ValueError(f"Invalid card: {card!r}")
    suit = _SUIT_ALIASES.get(suit.lower(), suit)
    if rank not in RANK_VALUES or suit not in SUITS:
        raise ValueError(f"Invalid card: {card!r}")
    return f"{rank}{suit}"


def _card_rank(card: str) -> int:
    return RANK_VALUES[_normalize_card_label(card)[0]]


def _card_suit(card: str) -> str:
    return _normalize_card_label(card)[1]


def _score_five(cards: tuple[str, ...]) -> tuple[int, ...]:
    values = sorted((_card_rank(card) for card in cards), reverse=True)
    counts = Counter(values)
    groups = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    flush = len({_card_suit(card) for card in cards}) == 1
    unique = sorted(set(values), reverse=True)
    straight_high = None
    if len(unique) == 5 and unique[0] - unique[-1] == 4:
        straight_high = unique[0]
    elif unique == [14, 5, 4, 3, 2]:
        straight_high = 5

    if flush and straight_high:
        return (8, straight_high)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if groups[0][0] == 3 and groups[1][0] == 2:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *values)
    if straight_high:
        return (4, straight_high)
    if groups[0][0] == 3:
        kickers = sorted((rank for rank, count in counts.items() if count == 1), reverse=True)
        return (3, groups[0][1], *kickers)
    pairs = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
    if len(pairs) == 2:
        kicker = max(rank for rank, count in counts.items() if count == 1)
        return (2, pairs[0], pairs[1], kicker)
    if len(pairs) == 1:
        kickers = sorted((rank for rank, count in counts.items() if count == 1), reverse=True)
        return (1, pairs[0], *kickers)
    return (0, *values)


def evaluate_best_hand(cards: list[str] | tuple[str, ...]) -> tuple[int, ...]:
    """Return a lexicographically comparable score for a 5, 6, or 7 card hand."""
    if not isinstance(cards, (list, tuple)) or not 5 <= len(cards) <= 7:
        raise ValueError("A Hold'em hand must contain between 5 and 7 cards")
    normalized = [_normalize_card_label(card) for card in cards]
    if len(set(normalized)) != len(normalized):
        raise ValueError("A hand cannot contain duplicate cards")
    return max(_score_five(combo) for combo in itertools.combinations(normalized, 5))


@_locked
def get_room_snapshot(room: dict[str, Any], viewer_user_id: int | None = None) -> dict[str, Any]:
    reveal_hands = room.get("phase") == "showdown"
    players = []
    for player in room["players"]:
        hole_cards = player.get("hole_cards", [])
        if player["id"] != viewer_user_id and not reveal_hands:
            hole_cards = ["XX", "XX"] if hole_cards else []
        elif player.get("folded", False) and player["id"] != viewer_user_id:
            hole_cards = ["XX", "XX"] if hole_cards else []
        players.append({
            "id": player["id"],
            "username": player["username"],
            "seat": player["seat"],
            "chips": player["chips"],
            "folded": player.get("folded", False),
            "all_in": player.get("all_in", False),
            "in_hand": player.get("in_hand", False),
            "hole_cards": list(hole_cards),
            "bet_this_round": player.get("bet_this_round", 0),
            "last_bet": player.get("last_bet", 0),
            # Only show this private action constraint to the player affected by it.
            "raise_locked": bool(player.get("raise_locked", False)) if player["id"] == viewer_user_id else None,
            "is_dealer": player["seat"] == room.get("dealer_index"),
            "is_small_blind": player["seat"] == room.get("small_blind_index"),
            "is_big_blind": player["seat"] == room.get("big_blind_index"),
        })
    return {
        "room_id": room["room_id"],
        "name": room["name"],
        "owner_id": room["owner_id"],
        "max_players": room["max_players"],
        "small_blind": room["small_blind"],
        "phase": room["phase"],
        "hand_number": room.get("hand_number", 0),
        "dealer_index": room.get("dealer_index", 0),
        "small_blind_index": room.get("small_blind_index"),
        "big_blind_index": room.get("big_blind_index"),
        "players": players,
        "board": list(room["board"]),
        "pot": room["pot"],
        "current_bet": room.get("current_bet", 0),
        "last_full_raise": room.get("last_full_raise", room["small_blind"] * 2),
        "current_turn": room.get("current_turn"),
        "turn_deadline_at": room.get("turn_deadline_at"),
        "turn_timeout_seconds": TURN_TIMEOUT_SECONDS,
        "server_time": time.time(),
        "history": list(room.get("history", [])),
        "hand_history": list(room.get("hand_history", [])),
        "last_hand_summary": dict(room.get("last_hand_summary", {})),
        "analytics": dict(room.get("analytics", {})),
    }


@_locked
def create_room(name: str, owner_id: int, owner_name: str, max_players: int = 6, small_blind: int = 10) -> dict[str, Any]:
    if not isinstance(name, str) or not 3 <= len(name.strip()) <= 100:
        raise ValueError("Room name must be between 3 and 100 characters")
    if isinstance(max_players, bool) or not isinstance(max_players, int) or not 2 <= max_players <= 9:
        raise ValueError("A table must have between 2 and 9 seats")
    if isinstance(small_blind, bool) or not isinstance(small_blind, int) or small_blind < 1:
        raise ValueError("Small blind must be a positive whole number")
    room_id = str(uuid.uuid4())
    room = {
        "room_id": room_id,
        "name": name.strip(),
        "owner_id": owner_id,
        "max_players": max_players,
        "small_blind": small_blind,
        "players": [_new_player(owner_id, owner_name, 0)],
        "board": [],
        "deck": [],
        "pot": 0,
        "phase": "waiting",
        "dealer_index": 0,
        "small_blind_index": None,
        "big_blind_index": None,
        "next_dealer_index": 0,
        "current_turn": None,
        "turn_deadline_at": None,
        "current_bet": 0,
        "last_full_raise": small_blind * 2,
        "hand_number": 0,
        "hand_started_at": None,
        "hand_completed_at": None,
        "hand_start_stacks": {},
        "action_version": 0,
        "hand_settled": False,
        "hand_start_chips": 1000,
        "history": [f"Room {name.strip()} created."],
        "hand_history": [],
        "last_hand_summary": {},
        "analytics": {},
    }
    ROOMS[room_id] = room
    return room


def _new_player(user_id: int, username: str, seat: int) -> dict[str, Any]:
    return {
        "id": user_id,
        "username": username,
        "seat": seat,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": False,
        "all_in": False,
        "contributed": 0,
        "bet_this_round": 0,
        "last_bet": 0,
        "acted_this_round": False,
        "raise_locked": False,
        "bet_when_last_acted": 0,
        "raise_reopen_at": None,
    }


@_locked
def get_room(room_id: str) -> dict[str, Any] | None:
    return ROOMS.get(room_id) if isinstance(room_id, str) else None


@_locked
def get_completed_room_record(room_id: str) -> dict[str, Any] | None:
    room = ROOMS.get(room_id) if isinstance(room_id, str) else None
    if room is None or not room.get("hand_settled"):
        return None
    return deepcopy(room)


@_locked
def get_room_broadcast_snapshots(room_id: str) -> list[tuple[int, dict[str, Any]]]:
    room = ROOMS.get(room_id) if isinstance(room_id, str) else None
    if room is None:
        return []
    return [(player["id"], get_room_snapshot(room, player["id"])) for player in room["players"]]


@_locked
def get_user_room_snapshots(user_id: int) -> list[dict[str, Any]]:
    return [get_room_snapshot(room, user_id) for room in ROOMS.values()
            if any(player["id"] == user_id for player in room["players"])]


@_locked
def get_room_list() -> list[dict[str, Any]]:
    return [{
        "room_id": room["room_id"],
        "name": room["name"],
        "owner_id": room["owner_id"],
        "max_players": room["max_players"],
        "small_blind": room["small_blind"],
        "player_count": len(room["players"]),
        "phase": room["phase"],
    } for room in ROOMS.values()]


def _append_hand_event(room: dict[str, Any], phase: str, message: str, **extra: Any) -> dict[str, Any]:
    entry = {"phase": phase, "message": message, "pot": int(room.get("pot", 0)), **extra}
    room.setdefault("hand_history", []).append(entry)
    return entry


@_locked
def join_room(room_id: str, user_id: int, username: str) -> dict[str, Any]:
    room = ROOMS.get(room_id) if isinstance(room_id, str) else None
    if room is None:
        raise ValueError("Room not found")
    existing = next((player for player in room["players"] if player["id"] == user_id), None)
    if existing is not None:
        return room  # A reconnect keeps the player's original seat and stack.
    if room["phase"] not in {"waiting", "showdown"}:
        raise ValueError("Cannot join while a hand is in progress")
    if len(room["players"]) >= room["max_players"]:
        raise ValueError("Room is full")
    player = _new_player(user_id, username, len(room["players"]))
    room["players"].append(player)
    room["history"].append(f"{username} joined the table.")
    return room


def _active_players(room: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in room["players"] if p.get("in_hand") and not p.get("folded")]


def _can_act(player: dict[str, Any]) -> bool:
    return bool(player.get("in_hand") and not player.get("folded") and not player.get("all_in") and player["chips"] > 0)


def _next_actor_index(room: dict[str, Any], start_index: int) -> int | None:
    players = room["players"]
    if not players:
        return None
    for offset in range(1, len(players) + 1):
        index = (start_index + offset) % len(players)
        if _can_act(players[index]):
            return index
    return None


def _post_chips(room: dict[str, Any], player: dict[str, Any], amount: int) -> int:
    posted = min(amount, player["chips"])
    player["chips"] -= posted
    player["contributed"] += posted
    player["bet_this_round"] += posted
    player["last_bet"] = posted
    room["pot"] += posted
    if player["chips"] == 0:
        player["all_in"] = True
    return posted


def _get_blind_indexes(active_indices: list[int], dealer_index: int, player_count: int) -> tuple[int, int, int]:
    if len(active_indices) == 2:
        small_blind = dealer_index
        big_blind = next(index for index in active_indices if index != dealer_index)
        return dealer_index, small_blind, big_blind
    position = active_indices.index(dealer_index)
    small_blind = active_indices[(position + 1) % len(active_indices)]
    big_blind = active_indices[(position + 2) % len(active_indices)]
    return dealer_index, small_blind, big_blind


def _refresh_turn_deadline(room: dict[str, Any]) -> None:
    if (room.get("phase") in {"preflop", "flop", "turn", "river"}
            and room.get("current_turn") is not None):
        room["turn_deadline_at"] = time.time() + TURN_TIMEOUT_SECONDS
    else:
        room["turn_deadline_at"] = None


@_locked
def start_hand(room_id: str) -> dict[str, Any]:
    room = ROOMS.get(room_id) if isinstance(room_id, str) else None
    if room is None:
        raise ValueError("Room not found")
    if room["phase"] not in {"waiting", "showdown"}:
        raise ValueError("A hand is already in progress")
    active_indices = [i for i, player in enumerate(room["players"]) if player["chips"] > 0]
    if len(active_indices) < 2:
        raise ValueError("At least 2 players with chips are needed to start a hand")

    player_count = len(room["players"])
    desired_dealer = room.get("next_dealer_index", 0) % player_count
    dealer_index = next((i for i in ((desired_dealer + offset) % player_count for offset in range(player_count)) if i in active_indices), active_indices[0])
    dealer_index, small_blind_index, big_blind_index = _get_blind_indexes(active_indices, dealer_index, player_count)
    room["hand_number"] += 1
    room["action_version"] += 1
    room["hand_settled"] = False
    room["hand_start_chips"] = sum(player["chips"] for player in room["players"])
    room["hand_start_stacks"] = {player["id"]: player["chips"] for player in room["players"]}
    room["hand_started_at"] = time.time()
    room["hand_completed_at"] = None
    room["dealer_index"] = dealer_index
    room["small_blind_index"] = small_blind_index
    room["big_blind_index"] = big_blind_index
    room["next_dealer_index"] = (dealer_index + 1) % player_count
    room["phase"] = "preflop"
    room["board"] = []
    room["deck"] = _full_deck()
    room["pot"] = 0
    room["current_bet"] = 0
    room["last_full_raise"] = room["small_blind"] * 2
    room["analytics"] = {}
    room["last_hand_summary"] = {}
    room["hand_history"] = []

    for player in room["players"]:
        player.update({
            "hole_cards": [], "folded": False, "in_hand": player["chips"] > 0,
            "all_in": False, "contributed": 0, "bet_this_round": 0,
            "last_bet": 0, "acted_this_round": False, "raise_locked": False,
            "bet_when_last_acted": 0, "raise_reopen_at": None,
        })
    for index in active_indices:
        room["players"][index]["hole_cards"] = [room["deck"].pop(), room["deck"].pop()]

    sb = room["players"][small_blind_index]
    bb = room["players"][big_blind_index]
    posted_sb = _post_chips(room, sb, room["small_blind"])
    posted_bb = _post_chips(room, bb, room["small_blind"] * 2)
    room["current_bet"] = max(posted_sb, posted_bb)
    room["history"].append(f"Hand {room['hand_number']} started.")
    _append_hand_event(room, "preflop", "Hand started", dealer_index=dealer_index,
                       small_blind_index=small_blind_index, big_blind_index=big_blind_index,
                       small_blind=posted_sb, big_blind=posted_bb)
    room["current_turn"] = _next_actor_index(room, big_blind_index)
    _refresh_turn_deadline(room)
    _assert_invariants(room)
    if len(_active_players(room)) == 1:
        _award_uncontested(room)
    elif room["current_turn"] is None:
        _run_out_board(room)
    return room


def _advance_phase(room: dict[str, Any]) -> None:
    old_phase = room["phase"]
    if old_phase == "preflop":
        room["deck"].pop()  # burn card
        room["board"].extend(room["deck"][-3:])
        del room["deck"][-3:]
        room["phase"] = "flop"
    elif old_phase == "flop":
        room["deck"].pop()
        room["board"].append(room["deck"].pop())
        room["phase"] = "turn"
    elif old_phase == "turn":
        room["deck"].pop()
        room["board"].append(room["deck"].pop())
        room["phase"] = "river"
    elif old_phase == "river":
        room["phase"] = "showdown"
        return
    else:
        raise ValueError(f"Cannot advance from phase {old_phase}")

    for player in room["players"]:
        player["bet_this_round"] = 0
        player["last_bet"] = 0
        player["acted_this_round"] = False
        player["raise_locked"] = False
        player["bet_when_last_acted"] = 0
        player["raise_reopen_at"] = None
    room["current_bet"] = 0
    room["current_turn"] = _next_actor_index(room, room["dealer_index"])
    message = f"Phase advanced to {room['phase']}."
    room["history"].append(message)
    _append_hand_event(room, room["phase"], message, board=list(room["board"]))


def _is_round_complete(room: dict[str, Any]) -> bool:
    actors = [player for player in room["players"] if _can_act(player)]
    return all(player["acted_this_round"] and player["bet_this_round"] == room["current_bet"] for player in actors)


def _build_side_pots(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    levels = sorted({p.get("contributed", 0) for p in players if p.get("contributed", 0) > 0})
    pots = []
    previous = 0
    for level in levels:
        contributors = [p for p in players if p.get("contributed", 0) >= level]
        amount = (level - previous) * len(contributors)
        eligible = [p for p in contributors if p.get("in_hand") and not p.get("folded")]
        pots.append({"amount": amount, "eligible_ids": [p["id"] for p in eligible],
                     "contributor_ids": [p["id"] for p in contributors], "cap": level})
        previous = level
    return pots


def _scores_for_active(room: dict[str, Any]) -> list[dict[str, Any]]:
    scored = []
    for player in _active_players(room):
        strength = evaluate_best_hand(player["hole_cards"] + room["board"])
        scored.append({"id": player["id"], "username": player["username"], "seat": player["seat"],
                       "hand_strength": strength, "hand_label": _describe_hand(strength)})
    return scored


def _describe_hand(score: tuple[int, ...]) -> str:
    return {
        8: "straight flush", 7: "four of a kind", 6: "full house", 5: "flush",
        4: "straight", 3: "three of a kind", 2: "two pair", 1: "one pair", 0: "high card",
    }.get(score[0], "high card")


def determine_showdown_winners(room: dict[str, Any]) -> list[dict[str, Any]]:
    scored = _scores_for_active(room)
    if not scored:
        return []
    best = max(player["hand_strength"] for player in scored)
    winners = [player for player in scored if player["hand_strength"] == best]
    room["analytics"] = calculate_analytics(room)
    return winners


def _distribute_pot(room: dict[str, Any], scored: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    score_by_id = {player["id"]: player for player in scored}
    awards = []
    winners_by_id: dict[int, dict[str, Any]] = {}
    for side_pot in _build_side_pots(room["players"]):
        eligible = [score_by_id[user_id] for user_id in side_pot["eligible_ids"] if user_id in score_by_id]
        if not eligible:
            # A layer made only from folded contributions goes to the surviving hand.
            eligible = list(scored)
        if not eligible:
            continue
        best = max(player["hand_strength"] for player in eligible)
        winners = sorted((p for p in eligible if p["hand_strength"] == best), key=lambda p: p["seat"])
        share, remainder = divmod(side_pot["amount"], len(winners))
        for index, winner in enumerate(winners):
            amount = share + (1 if index < remainder else 0)
            target = next(p for p in room["players"] if p["id"] == winner["id"])
            target["chips"] += amount
            winners_by_id[winner["id"]] = winner
            awards.append({"player_id": winner["id"], "username": winner["username"],
                           "amount": amount, "pot_cap": side_pot["cap"],
                           "hand_label": winner["hand_label"]})
    return list(winners_by_id.values()), awards


def settle_showdown(room: dict[str, Any]) -> list[dict[str, Any]]:
    if room.get("hand_settled"):
        return list(room.get("last_hand_summary", {}).get("winners", []))
    room["phase"] = "showdown"
    scored = _scores_for_active(room)
    if not scored:
        raise ValueError("Cannot settle a hand without a live player")
    pot_total = room["pot"]
    winners, awards = _distribute_pot(room, scored)
    winner_names = list(dict.fromkeys(winner["username"] for winner in winners))
    label = winners[0]["hand_label"] if len(winners) == 1 else "split pot"
    message = f"Showdown: {', '.join(winner_names)} won {pot_total} with {label}."
    room["history"].append(message)
    room["last_hand_summary"] = {
        "phase": "showdown", "pot": pot_total,
        "winner_ids": [winner["id"] for winner in winners], "winner_names": winner_names,
        "hand_label": label, "message": message, "awards": awards,
        "winners": winners,
    }
    _append_hand_event(room, "showdown", message, winner_ids=room["last_hand_summary"]["winner_ids"],
                       winner_names=winner_names, hand_label=label, awards=awards)
    room["pot"] = 0
    room["current_turn"] = None
    room["turn_deadline_at"] = None
    room["hand_settled"] = True
    room["hand_completed_at"] = time.time()
    _assert_invariants(room)
    room["analytics"] = calculate_analytics(room)
    return winners


def _award_uncontested(room: dict[str, Any]) -> None:
    if room.get("hand_settled"):
        return
    active = _active_players(room)
    if len(active) != 1:
        return
    winner = active[0]
    amount = room["pot"]
    winner["chips"] += amount
    message = f"{winner['username']} won {amount} uncontested."
    room["history"].append(message)
    _append_hand_event(room, "showdown", message, winner_ids=[winner["id"]], amount=amount)
    room["last_hand_summary"] = {
        "phase": "showdown", "pot": amount, "winner_ids": [winner["id"]],
        "winner_names": [winner["username"]], "hand_label": "Uncontested",
        "message": message, "awards": [{"player_id": winner["id"], "username": winner["username"],
                                            "amount": amount, "hand_label": "Uncontested"}],
        "winners": [{"id": winner["id"], "username": winner["username"], "seat": winner["seat"],
                     "hand_label": "Uncontested"}],
    }
    room["pot"] = 0
    room["phase"] = "showdown"
    room["current_turn"] = None
    room["turn_deadline_at"] = None
    room["hand_settled"] = True
    room["hand_completed_at"] = time.time()
    _assert_invariants(room)


def _run_out_board(room: dict[str, Any]) -> None:
    while room["phase"] != "showdown":
        _advance_phase(room)
    settle_showdown(room)


def _progress_hand(room: dict[str, Any]) -> None:
    if len(_active_players(room)) == 1:
        _award_uncontested(room)
        return
    if _is_round_complete(room):
        if room["phase"] == "river":
            room["phase"] = "showdown"
            settle_showdown(room)
            return
        _advance_phase(room)
        if room["current_turn"] is None:
            _run_out_board(room)
            return
    _assert_invariants(room)


def _simulate_equity(room: dict[str, Any], player: dict[str, Any], iterations: int = 1000) -> dict[str, Any]:
    started_at = time.perf_counter()
    opponents = [p for p in _active_players(room) if p["id"] != player["id"]]
    if not player.get("hole_cards"):
        return {"win_probability": 0.0, "lose_probability": 0.0, "tie_probability": 0.0, "equity": 0.0}
    if not opponents:
        return {"win_probability": 1.0, "lose_probability": 0.0, "tie_probability": 0.0, "equity": 1.0}
    known = {_normalize_card_label(card) for card in room["board"] + player["hole_cards"]}
    remaining = [card for card in _full_deck() if card not in known]
    missing_board = 5 - len(room["board"])
    wins = losses = ties = 0
    equity_total = equity_squared_total = 0.0
    trials = min(iterations, 1000)
    for _ in range(trials):
        sample = random.sample(remaining, missing_board + 2 * len(opponents))
        board = room["board"] + sample[:missing_board]
        cursor = missing_board
        hero_score = evaluate_best_hand(player["hole_cards"] + board)
        opponent_scores = []
        for _opponent in opponents:
            hole = sample[cursor:cursor + 2]
            cursor += 2
            opponent_scores.append(evaluate_best_hand(hole + board))
        best_opponent = max(opponent_scores)
        if hero_score > best_opponent:
            wins += 1
            share = 1.0
        elif hero_score < best_opponent:
            losses += 1
            share = 0.0
        else:
            ties += 1
            share = 1.0 / (1 + sum(score == hero_score for score in opponent_scores))
        equity_total += share
        equity_squared_total += share * share
    total = wins + losses + ties or 1
    win_probability = wins / total
    equity = equity_total / total
    variance = max(0.0, (equity_squared_total - total * equity * equity) / max(1, total - 1))
    confidence95 = 1.96 * math.sqrt(variance / total)
    return {"win_probability": round(win_probability, 3), "lose_probability": round(losses / total, 3),
            "tie_probability": round(ties / total, 3), "simulations": total,
            "equity": round(equity, 3), "confidence95": round(confidence95, 3),
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 1)}


def _player_hand_metrics(room: dict[str, Any], player: dict[str, Any]) -> dict[str, Any]:
    hole_cards = list(player.get("hole_cards", []))
    board = list(room.get("board", []))
    visible = hole_cards + board
    current_hand = None
    current_score = None
    if len(visible) >= 5:
        current_score = evaluate_best_hand(visible)
        current_hand = _describe_hand(current_score)
    elif len(hole_cards) == 2:
        ranks = sorted((_card_rank(card) for card in hole_cards), reverse=True)
        current_hand = f"pocket pair {ranks[0]}" if ranks[0] == ranks[1] else f"high card {ranks[0]}"

    call_amount = max(0, int(room.get("current_bet", 0)) - int(player.get("bet_this_round", 0)))
    pot_after_call = int(room.get("pot", 0)) + call_amount
    pot_odds = round(call_amount / pot_after_call, 4) if call_amount and pot_after_call else None

    straight_outs: set[str] = set()
    flush_outs: set[str] = set()
    improved_cards: set[str] = set()
    possible_hands_ahead: set[int] = set()
    if current_score is not None and 0 < len(board) < 5:
        known = {_normalize_card_label(card) for card in visible}
        for candidate in _full_deck():
            if candidate in known:
                continue
            candidate_score = evaluate_best_hand(visible + [candidate])
            if candidate_score > current_score:
                improved_cards.add(candidate)
            if current_score[0] < 4 and candidate_score[0] in {4, 8}:
                straight_outs.add(candidate)
            if current_score[0] < 5 and candidate_score[0] in {5, 8}:
                flush_outs.add(candidate)

    if current_score is not None and len(board) >= 3 and room.get("phase") != "showdown":
        known = {_normalize_card_label(card) for card in visible}
        unseen = [card for card in _full_deck() if card not in known]
        for opponent_hole in itertools.combinations(unseen, 2):
            opponent_score = evaluate_best_hand(list(opponent_hole) + board)
            if opponent_score > current_score:
                possible_hands_ahead.add(opponent_score[0])

    draws = []
    if flush_outs:
        draws.append("flush draw")
    if straight_outs:
        draws.append("straight draw")
    return {
        "current_hand": current_hand,
        "draws": draws,
        "outs": len(straight_outs | flush_outs),
        "improving_cards": len(improved_cards),
        "possible_hands_ahead": [
            _describe_hand((category,)) for category in sorted(possible_hands_ahead, reverse=True)
        ],
        "pot_odds": pot_odds,
    }


def calculate_analytics(room: dict[str, Any]) -> dict[str, Any]:
    analytics: dict[str, Any] = {}
    if room.get("phase") == "showdown":
        scored = _scores_for_active(room) if len(room.get("board", [])) == 5 else []
        if scored:
            best = max(player["hand_strength"] for player in scored)
            tied_ids = {player["id"] for player in scored if player["hand_strength"] == best}
            for player in scored:
                if player["id"] in tied_ids and len(tied_ids) > 1:
                    stats = {"win_probability": 0.0, "lose_probability": 0.0,
                             "tie_probability": 1.0, "equity": 1 / len(tied_ids), "simulations": 1}
                elif player["id"] in tied_ids:
                    stats = {"win_probability": 1.0, "lose_probability": 0.0,
                             "tie_probability": 0.0, "equity": 1.0, "simulations": 1}
                else:
                    stats = {"win_probability": 0.0, "lose_probability": 1.0,
                             "tie_probability": 0.0, "equity": 0.0, "simulations": 1}
                analytics[player["username"]] = stats
                analytics[player["username"]].update(_player_hand_metrics(room, next(
                    p for p in room["players"] if p["id"] == player["id"]
                )))
            analytics["hand_matchups"] = {
                player["username"]: "wins" if player["hand_strength"] == best
                else "loses"
                for player in scored
            }
        else:
            analytics["hand_matchups"] = {}
        return analytics

    for player in room["players"]:
        if player.get("hole_cards") and player.get("in_hand") and not player.get("folded"):
            stats = _simulate_equity(room, player)
            stats.update(_player_hand_metrics(room, player))
            analytics[player["username"]] = stats
    analytics["hand_matchups"] = {}
    return analytics


def refresh_room_analytics(room_id: str) -> dict[str, Any]:
    """Calculate advisory equity off-lock, then publish only if the hand is unchanged."""
    with _GAME_LOCK:
        room = ROOMS.get(room_id)
        if room is None:
            return {}
        version = (room.get("hand_number"), room.get("action_version"))
        snapshot = deepcopy(room)
    analytics = calculate_analytics(snapshot)
    with _GAME_LOCK:
        current = ROOMS.get(room_id)
        if current is not None and version == (current.get("hand_number"), current.get("action_version")):
            current["analytics"] = analytics
    return analytics


def _assert_invariants(room: dict[str, Any]) -> None:
    assert room["pot"] >= 0
    assert all(player["chips"] >= 0 for player in room["players"])
    assert len({player["id"] for player in room["players"]}) == len(room["players"])
    assert len({player["seat"] for player in room["players"]}) == len(room["players"])
    if room.get("hand_settled"):
        assert room["pot"] == 0
        assert sum(player["chips"] for player in room["players"]) == room["hand_start_chips"]
    elif room.get("phase") not in {"waiting", "showdown"}:
        assert room["pot"] == sum(player.get("contributed", 0) for player in room["players"])
        assert sum(player["chips"] for player in room["players"]) + room["pot"] == room["hand_start_chips"]


@_locked
def apply_action(room_id: str, user_id: int, action: str, amount: int | None = None) -> dict[str, Any]:
    room = ROOMS.get(room_id) if isinstance(room_id, str) else None
    if room is None:
        raise ValueError("Room not found")
    if room["phase"] not in {"preflop", "flop", "turn", "river"} or room.get("hand_settled"):
        raise ValueError("There is no active hand")
    player_index = next((i for i, p in enumerate(room["players"]) if p["id"] == user_id), None)
    if player_index is None:
        raise ValueError("Player not in room")
    player = room["players"][player_index]
    if not _can_act(player):
        raise ValueError("Player cannot act")
    if room.get("current_turn") != player_index:
        raise ValueError("It's not your turn")
    if not isinstance(action, str):
        raise ValueError("Invalid action")
    action = action.strip().lower().replace("-", "_")
    if action == "allin":
        action = "all_in"
    if action not in {"fold", "check", "call", "bet", "raise", "all_in"}:
        raise ValueError(f"Invalid action: {action}")

    call_amount = max(0, room["current_bet"] - player["bet_this_round"])
    amount_to_pay = 0
    raise_increment = 0
    if action == "check":
        if call_amount:
            raise ValueError("Cannot check while there is a bet to call")
    elif action == "call":
        amount_to_pay = min(call_amount, player["chips"])
        if amount_to_pay == 0:
            action = "check"
    elif action == "fold":
        pass
    elif action == "bet":
        if room["current_bet"] != 0:
            raise ValueError("Use raise when there is already a bet")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("Bet amount must be a positive whole number")
        if amount > player["chips"]:
            raise ValueError("Not enough chips")
        if amount < room["last_full_raise"] and amount != player["chips"]:
            raise ValueError(f"Minimum bet is {room['last_full_raise']} chips")
        amount_to_pay = amount
        raise_increment = amount
    elif action == "raise":
        if room["current_bet"] <= 0:
            raise ValueError("Use bet when there is no outstanding bet")
        if player.get("raise_locked"):
            raise ValueError("A short all-in did not reopen raising")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("Raise amount must be a positive whole number")
        if amount < room["last_full_raise"]:
            raise ValueError(f"Minimum raise is {room['last_full_raise']} chips")
        amount_to_pay = call_amount + amount
        if amount_to_pay > player["chips"]:
            raise ValueError("Not enough chips")
        raise_increment = amount
    elif action == "all_in":
        if player["chips"] <= 0:
            raise ValueError("Player has no chips")
        amount_to_pay = player["chips"]
        raise_increment = max(0, player["bet_this_round"] + amount_to_pay - room["current_bet"])
        if player.get("raise_locked") and raise_increment > 0:
            raise ValueError("A short all-in did not reopen raising")

    old_bet = room["current_bet"]
    room["action_version"] = room.get("action_version", 0) + 1
    if action == "fold":
        player["folded"] = True
        player["acted_this_round"] = True
        message = f"{player['username']} folded."
        room["history"].append(message)
        _append_hand_event(room, room["phase"], message, player_id=user_id, action="fold")
    else:
        if amount_to_pay:
            _post_chips(room, player, amount_to_pay)
        player["acted_this_round"] = True
        if action in {"bet", "raise", "all_in"} and raise_increment > 0:
            new_bet = player["bet_this_round"]
            if new_bet > old_bet:
                raise_increment = new_bet - old_bet
                room["current_bet"] = new_bet
                if raise_increment >= room["last_full_raise"]:
                    room["last_full_raise"] = raise_increment
                    for other in room["players"]:
                        if other is not player and _can_act(other):
                            other["acted_this_round"] = False
                            other["raise_locked"] = False
                            other["raise_reopen_at"] = None
                else:
                    for other in room["players"]:
                        if other is not player and _can_act(other) and other["acted_this_round"]:
                            other["raise_locked"] = True
                            if other.get("raise_reopen_at") is None:
                                other["raise_reopen_at"] = other.get("bet_when_last_acted", other["bet_this_round"]) + room["last_full_raise"]
                            if new_bet >= other["raise_reopen_at"]:
                                other["raise_locked"] = False
        player["bet_when_last_acted"] = player["bet_this_round"]
        player["raise_reopen_at"] = player["bet_this_round"] + room["last_full_raise"]
        action_text = "checked" if action == "check" else action.replace("_", " ")
        message = f"{player['username']} {action_text}" + (f" for {amount_to_pay}." if amount_to_pay else ".")
        room["history"].append(message)
        _append_hand_event(room, room["phase"], message, player_id=user_id, action=action,
                           amount=amount_to_pay, current_bet=room["current_bet"],
                           is_aggressive=raise_increment > 0)

    room["current_turn"] = _next_actor_index(room, player_index)
    _progress_hand(room)
    _refresh_turn_deadline(room)
    return room


@_locked
def expire_timed_out_turns(now: float | None = None) -> list[str]:
    """Apply deterministic check/fold actions to active tables past their deadlines."""
    timestamp = time.time() if now is None else now
    expired_rooms: list[str] = []
    for room in ROOMS.values():
        deadline = room.get("turn_deadline_at")
        turn_index = room.get("current_turn")
        if (deadline is None or deadline > timestamp or turn_index is None
                or room.get("phase") not in {"preflop", "flop", "turn", "river"}):
            continue
        if not 0 <= turn_index < len(room["players"]):
            room["current_turn"] = None
            _refresh_turn_deadline(room)
            continue
        player = room["players"][turn_index]
        if not _can_act(player):
            room["current_turn"] = _next_actor_index(room, turn_index)
            _refresh_turn_deadline(room)
            continue
        timed_out_action = "fold" if room["current_bet"] > player["bet_this_round"] else "check"
        previous_message = f"{player['username']} {'folded' if timed_out_action == 'fold' else 'checked'}."
        apply_action(room["room_id"], player["id"], timed_out_action)
        timeout_message = f"{player['username']} timed out; automatic {timed_out_action}."
        for history_index in range(len(room["history"]) - 1, -1, -1):
            if room["history"][history_index] == previous_message:
                room["history"][history_index] = timeout_message
                break
        for event in reversed(room["hand_history"]):
            if event.get("message") == previous_message:
                event["message"] = timeout_message
                break
        expired_rooms.append(room["room_id"])
    return expired_rooms

