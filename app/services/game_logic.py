import random
import uuid
from collections import Counter
from typing import Any, Dict, List, Tuple

ROOMS: Dict[str, Dict[str, Any]] = {}

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
RANK_VALUES = {rank: idx for idx, rank in enumerate(RANKS)}


def _full_deck() -> List[str]:
    cards = []
    for suit in SUITS:
        for rank in RANKS:
            cards.append(f"{rank}{suit}")
    random.shuffle(cards)
    return cards


def _normalize_cards(cards: List[str]) -> List[str]:
    return [card for card in cards if card]


def _normalize_card_label(card: str) -> str:
    value = card.strip()
    if len(value) == 2:
        return value
    if len(value) == 1:
        return f"{value}♠"
    if value.endswith(tuple("♠♥♦♣")):
        rank = value[:-1]
        suit = value[-1]
        return f"{rank}{suit}"
    return value


def _card_rank(card: str) -> int:
    clean = _normalize_card_label(card)
    rank = clean[:-1]
    rank_map = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
    return rank_map[rank]


def _card_suit(card: str) -> str:
    clean = _normalize_card_label(card)
    return clean[-1]


def _find_straight_high(values: List[int]) -> int | None:
    unique = sorted(set(values), reverse=True)
    for index in range(len(unique) - 4, -1, -1):
        window = unique[index:index + 5]
        if len(window) < 5:
            continue
        if max(window) - min(window) == 4 and len(set(window)) == 5:
            return max(window)

    if {14, 5, 4, 3, 2}.issubset(set(values)):
        return 5
    return None


def evaluate_best_hand(cards: List[str]) -> Tuple[int, ...]:
    normalized = [_normalize_card_label(card) for card in cards]
    values = [_card_rank(card) for card in normalized]
    suits = [_card_suit(card) for card in normalized]
    counts = Counter(values)
    ordered_values = sorted(values, reverse=True)
    flush = len(set(suits)) == 1
    straight_high = _find_straight_high(values)

    if flush and straight_high is not None:
        if straight_high == 5 and set(values) >= {14, 5, 4, 3, 2}:
            return (8, 5)
        return (8, straight_high)

    if 4 in counts.values():
        quad_rank = max(rank for rank, count in counts.items() if count == 4)
        kicker = max((rank for rank, count in counts.items() if count == 1), default=0)
        return (7, quad_rank, kicker)

    if sorted(counts.values()) == [2, 3]:
        triple_rank = max(rank for rank, count in counts.items() if count == 3)
        pair_rank = max(rank for rank, count in counts.items() if count == 2)
        return (6, triple_rank, pair_rank)

    if flush:
        return (5, *sorted(ordered_values, reverse=True)[:5])

    if straight_high is not None:
        return (4, straight_high)

    if 3 in counts.values():
        triple_rank = max(rank for rank, count in counts.items() if count == 3)
        kickers = sorted((rank for rank, count in counts.items() if count == 1), reverse=True)[:2]
        return (3, triple_rank, *kickers)

    if sorted(counts.values()) == [1, 2, 2]:
        pair_ranks = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
        kicker = max((rank for rank, count in counts.items() if count == 1), default=0)
        return (2, *pair_ranks, kicker)

    if 2 in counts.values():
        pair_rank = max(rank for rank, count in counts.items() if count == 2)
        kickers = sorted((rank for rank, count in counts.items() if count == 1), reverse=True)[:3]
        return (1, pair_rank, *kickers)

    return (0, *sorted(ordered_values, reverse=True)[:5])


def get_room_snapshot(room: Dict[str, Any], viewer_user_id: int | None = None) -> Dict[str, Any]:
    players = []
    for player in room["players"]:
        public_player = {
            "id": player["id"],
            "username": player["username"],
            "seat": player["seat"],
            "chips": player["chips"],
            "folded": player.get("folded", False),
            "in_hand": player.get("in_hand", True),
            "hole_cards": player.get("hole_cards", []),
            "bet_this_round": player.get("bet_this_round", 0),
            "last_bet": player.get("last_bet", 0),
        }
        if viewer_user_id is not None and player["id"] != viewer_user_id:
            public_player["hole_cards"] = ["XX", "XX"] if public_player["hole_cards"] else []
        players.append(public_player)

    return {
        "room_id": room["room_id"],
        "name": room["name"],
        "owner_id": room["owner_id"],
        "max_players": room["max_players"],
        "small_blind": room["small_blind"],
        "phase": room["phase"],
        "dealer_index": room.get("dealer_index", 0),
        "small_blind_index": room.get("small_blind_index"),
        "big_blind_index": room.get("big_blind_index"),
        "players": [
            {
                **player,
                "is_dealer": player["seat"] == room.get("dealer_index", 0),
                "is_small_blind": player["seat"] == room.get("small_blind_index"),
                "is_big_blind": player["seat"] == room.get("big_blind_index"),
            }
            for player in players
        ],
        "board": room["board"],
        "pot": room["pot"],
        "current_bet": room.get("current_bet", 0),
        "current_turn": room.get("current_turn"),
        "history": room.get("history", []),
        "analytics": room.get("analytics", {}),
    }


def create_room(name: str, owner_id: int, owner_name: str, max_players: int = 6, small_blind: int = 10) -> Dict[str, Any]:
    room_id = str(uuid.uuid4())
    room = {
        "room_id": room_id,
        "name": name,
        "owner_id": owner_id,
        "max_players": max_players,
        "small_blind": small_blind,
        "players": [
            {
                "id": owner_id,
                "username": owner_name,
                "seat": 0,
                "chips": 1000,
                "hole_cards": [],
                "folded": False,
                "in_hand": True,
                "last_bet": 0,
            }
        ],
        "board": [],
        "deck": [],
        "pot": 0,
        "phase": "waiting",
        "dealer_index": 0,
        "small_blind_index": 0,
        "big_blind_index": 0,
        "next_dealer_index": 0,
        "current_turn": 0,
        "history": [f"Room {name} created."],
        "analytics": {},
    }
    ROOMS[room_id] = room
    return room


def get_room(room_id: str) -> Dict[str, Any] | None:
    return ROOMS.get(room_id)


def get_room_list() -> List[Dict[str, Any]]:
    return [
        {
            "room_id": room["room_id"],
            "name": room["name"],
            "owner_id": room["owner_id"],
            "max_players": room["max_players"],
            "small_blind": room["small_blind"],
            "player_count": len(room["players"]),
            "phase": room["phase"],
        }
        for room in ROOMS.values()
    ]


def join_room(room_id: str, user_id: int, username: str) -> Dict[str, Any]:
    room = ROOMS[room_id]
    if len(room["players"]) >= room["max_players"]:
        raise ValueError("Room is full")
    if any(player["id"] == user_id for player in room["players"]):
        raise ValueError("User already in room")

    seat = len(room["players"])
    room["players"].append(
        {
            "id": user_id,
            "username": username,
            "seat": seat,
            "chips": 1000,
            "hole_cards": [],
            "folded": False,
            "in_hand": True,
            "last_bet": 0,
        }
    )
    room["history"].append(f"{username} joined the table.")
    return room


def _deal_hole_cards(room: Dict[str, Any]) -> None:
    deck = _full_deck()
    room["deck"] = deck
    for player in room["players"]:
        player["hole_cards"] = [deck.pop(), deck.pop()]
        player["folded"] = False
        player["in_hand"] = True
        player["last_bet"] = 0


def _advance_phase(room: Dict[str, Any]) -> None:
    if room["phase"] == "waiting":
        room["phase"] = "preflop"
    elif room["phase"] == "preflop":
        room["phase"] = "flop"
        room["board"] = room["deck"][:3]
        room["deck"] = room["deck"][3:]
    elif room["phase"] == "flop":
        room["phase"] = "turn"
        room["board"].append(room["deck"][0])
        room["deck"] = room["deck"][1:]
    elif room["phase"] == "turn":
        room["phase"] = "river"
        room["board"].append(room["deck"][0])
        room["deck"] = room["deck"][1:]
    elif room["phase"] == "river":
        room["phase"] = "showdown"

    for player in room["players"]:
        if player.get("in_hand", True) and not player.get("folded", False):
            player["bet_this_round"] = 0
            player["last_bet"] = 0
    room["current_bet"] = 0
    if room["phase"] != "showdown":
        room["current_turn"] = _next_live_player_index(room, room["dealer_index"])
    room["history"].append(f"Phase advanced to {room['phase']}.")


def _next_live_player_index(room: Dict[str, Any], start_index: int) -> int:
    player_count = len(room["players"])
    for offset in range(1, player_count + 1):
        idx = (start_index + offset) % player_count
        player = room["players"][idx]
        if player.get("in_hand", True) and not player.get("folded", False):
            return idx
    return start_index


def _is_round_complete(room: Dict[str, Any]) -> bool:
    active_players = [player for player in room["players"] if player.get("in_hand", True) and not player.get("folded", False)]
    if not active_players:
        return True
    highest_bet = max(player.get("bet_this_round", 0) for player in active_players)
    return all(player.get("bet_this_round", 0) == highest_bet for player in active_players)


def start_hand(room_id: str) -> Dict[str, Any]:
    room = ROOMS[room_id]
    if len(room["players"]) < 2:
        raise ValueError("At least 2 players are needed to start a hand")

    player_count = len(room["players"])
    dealer_index = room.get("next_dealer_index", room.get("dealer_index", 0)) % player_count
    small_blind_index = (dealer_index + 1) % player_count
    big_blind_index = (dealer_index + 2) % player_count
    room["dealer_index"] = dealer_index
    room["small_blind_index"] = small_blind_index
    room["big_blind_index"] = big_blind_index
    room["next_dealer_index"] = (dealer_index + 1) % player_count

    for player in room["players"]:
        player["contributed"] = 0
        player["bet_this_round"] = 0
        player["last_bet"] = 0
        player["folded"] = False
        player["in_hand"] = True

    room["phase"] = "preflop"
    room["pot"] = 0
    room["board"] = []
    room["current_bet"] = room["small_blind"] * 2
    room["analytics"] = {}
    _deal_hole_cards(room)

    small_blind_player = room["players"][small_blind_index]
    big_blind_player = room["players"][big_blind_index]
    small_blind_amount = room["small_blind"]
    big_blind_amount = room["small_blind"] * 2

    small_blind_player["chips"] -= small_blind_amount
    small_blind_player["contributed"] = small_blind_amount
    small_blind_player["bet_this_round"] = small_blind_amount
    small_blind_player["last_bet"] = small_blind_amount
    room["pot"] += small_blind_amount

    big_blind_player["chips"] -= big_blind_amount
    big_blind_player["contributed"] = big_blind_amount
    big_blind_player["bet_this_round"] = big_blind_amount
    big_blind_player["last_bet"] = big_blind_amount
    room["pot"] += big_blind_amount

    room["history"].append("New hand started.")
    room["current_turn"] = (big_blind_index + 1) % player_count
    return room


def _describe_hand(score: Tuple[int, ...]) -> str:
    categories = {
        8: "straight flush",
        7: "four of a kind",
        6: "full house",
        5: "flush",
        4: "straight",
        3: "three of a kind",
        2: "two pair",
        1: "one pair",
        0: "high card",
    }
    return categories.get(score[0], "high card")


def _build_side_pots(players: List[Dict[str, Any]]) -> List[int]:
    contributions = sorted(player.get("contributed", 0) for player in players if player.get("in_hand", True) and not player.get("folded", False))
    if not contributions:
        return [0]
    unique_levels = sorted(set(contributions))
    pots = []
    previous = 0
    for level in unique_levels:
        if level <= previous:
            continue
        pots.append(level - previous)
        previous = level
    return pots


def determine_showdown_winners(room: Dict[str, Any]) -> List[Dict[str, Any]]:
    active_players = [player for player in room["players"] if player.get("in_hand", True) and not player.get("folded", False)]
    if not active_players:
        return []

    scored_players: List[Dict[str, Any]] = []
    for player in active_players:
        cards = player["hole_cards"] + room["board"]
        hand_strength = evaluate_best_hand(cards)
        scored_players.append(
            {
                "id": player["id"],
                "username": player["username"],
                "seat": player["seat"],
                "hand_strength": hand_strength,
                "hand_label": _describe_hand(hand_strength),
            }
        )

    best_strength = max(player["hand_strength"] for player in scored_players)
    winners = [player for player in scored_players if player["hand_strength"] == best_strength]
    room["analytics"] = calculate_analytics(room)
    return winners


def settle_showdown(room: Dict[str, Any]) -> List[Dict[str, Any]]:
    winners = determine_showdown_winners(room)
    if not winners:
        room["history"].append("No active players remained for showdown.")
        return []

    total_pot = room.get("pot", 0)
    split_amount = total_pot // len(winners)
    remainder = total_pot % len(winners)

    for player in room["players"]:
        player["contributed"] = player.get("contributed", 0)

    for winner in winners:
        player = next((p for p in room["players"] if p["id"] == winner["id"]), None)
        if player is not None:
            player["chips"] += split_amount + (1 if remainder and winner["id"] == winners[0]["id"] else 0)

    room["history"].append(
        f"Showdown: {', '.join(winner['username'] for winner in winners)} wins with {winners[0]['hand_label']}."
    )
    room["pot"] = 0
    room["phase"] = "showdown"
    return winners


def _simulate_equity(room: Dict[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
    if not player["hole_cards"]:
        return {"win_probability": 0.0, "lose_probability": 0.0, "tie_probability": 0.0}

    known_cards = _normalize_cards(room["board"] + player["hole_cards"])
    remaining_cards = [card for card in _full_deck() if card not in known_cards]
    if len(remaining_cards) < 5:
        return {"win_probability": 0.5, "lose_probability": 0.5, "tie_probability": 0.0}

    wins = 0
    losses = 0
    ties = 0
    iterations = 200
    for _ in range(iterations):
        sample = random.sample(remaining_cards, 5)
        opponent_cards = random.sample([card for card in remaining_cards if card not in sample], 2)
        candidate = player["hole_cards"] + room["board"] + sample
        opp_candidate = opponent_cards + room["board"] + sample
        if len(candidate) >= 7 and len(opp_candidate) >= 7:
            player_score = evaluate_best_hand(candidate)
            opp_score = evaluate_best_hand(opp_candidate)
            if player_score > opp_score:
                wins += 1
            elif player_score < opp_score:
                losses += 1
            else:
                ties += 1

    total = wins + losses + ties or 1
    return {
        "win_probability": round(wins / total, 3),
        "lose_probability": round(losses / total, 3),
        "tie_probability": round(ties / total, 3),
    }


def calculate_analytics(room: Dict[str, Any]) -> Dict[str, Any]:
    analytics: Dict[str, Any] = {}
    for player in room["players"]:
        if player["hole_cards"]:
            analytics[player["username"]] = _simulate_equity(room, player)

    active_players = [player for player in room["players"] if not player.get("folded", False)]
    matchup_text: Dict[str, str] = {}
    if room.get("phase") == "showdown" and active_players:
        scored_players = []
        for player in active_players:
            cards = player["hole_cards"] + room["board"]
            scored_players.append({
                "id": player["id"],
                "username": player["username"],
                "strength": evaluate_best_hand(cards),
            })
        best_strength = max(item["strength"] for item in scored_players)
        for player in scored_players:
            comparison = [
                opp["username"]
                for opp in scored_players
                if opp["id"] != player["id"] and opp["strength"] < player["strength"]
            ]
            if comparison:
                matchup_text[player["username"]] = f"wins against {', '.join(comparison)}"
            else:
                matchup_text[player["username"]] = "ties or trails"
    analytics["hand_matchups"] = matchup_text
    room["analytics"] = analytics
    return analytics


def apply_action(room_id: str, user_id: int, action: str, amount: int | None = None) -> Dict[str, Any]:
    room = ROOMS[room_id]
    player = next((p for p in room["players"] if p["id"] == user_id), None)
    if player is None:
        raise ValueError("Player not in room")

    if room["phase"] == "waiting":
        room["phase"] = "preflop"

    if room["current_turn"] is None:
        room["current_turn"] = 0

    active_players = [p for p in room["players"] if p.get("in_hand", True) and not p.get("folded", False)]
    if not active_players:
        room["phase"] = "showdown"
        settle_showdown(room)
        return room

    current_turn_player = room["players"][room["current_turn"]]
    if current_turn_player["id"] != user_id:
        raise ValueError("It's not your turn")

    action = action.lower()
    if action == "fold":
        player["folded"] = True
        player["in_hand"] = False
        room["history"].append(f"{player['username']} folded.")
        room["current_turn"] = _next_live_player_index(room, room["current_turn"])
    elif action == "check":
        if room.get("current_bet", 0) > player.get("bet_this_round", 0):
            raise ValueError("Cannot check while there is a bet to call")
        room["history"].append(f"{player['username']} checked.")
        room["current_turn"] = _next_live_player_index(room, room["current_turn"])
    elif action in {"call", "bet", "raise", "all_in"}:
        if action == "call":
            call_amount = max(0, room.get("current_bet", 0) - player.get("bet_this_round", 0))
            if call_amount == 0:
                room["history"].append(f"{player['username']} checked.")
                room["current_turn"] = _next_live_player_index(room, room["current_turn"])
                calculate_analytics(room)
                return room
            bet = call_amount
        elif action == "all_in":
            bet = player["chips"]
        else:
            bet = amount if amount is not None else room["small_blind"]
            if bet <= 0:
                raise ValueError("Bet amount must be positive")
            if room.get("current_bet", 0) > 0 and bet <= room["current_bet"]:
                raise ValueError("Raise must exceed the current bet")

        if bet > player["chips"]:
            raise ValueError("Not enough chips")

        player["chips"] -= bet
        player["contributed"] = player.get("contributed", 0) + bet
        player["bet_this_round"] = player.get("bet_this_round", 0) + bet
        player["last_bet"] = bet
        room["pot"] += bet
        room["current_bet"] = max(room.get("current_bet", 0), player["bet_this_round"])
        room["history"].append(f"{player['username']} {action} for {bet}.")
        room["current_turn"] = _next_live_player_index(room, room["current_turn"])
    else:
        raise ValueError(f"Invalid action: {action}")

    if room["phase"] in {"preflop", "flop", "turn", "river"} and _is_round_complete(room):
        _advance_phase(room)

    if room["phase"] == "river" and all(player["folded"] for player in room["players"][1:]):
        room["phase"] = "showdown"
        room["history"].append("Showdown reached.")

    if room["phase"] == "showdown":
        settle_showdown(room)

    calculate_analytics(room)
    return room
