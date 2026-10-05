import json

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import HandPlayerRecord, HandRecord, RoomRecord, User
from app.security import get_password_hash
from app.services.game_logic import evaluate_best_hand


def create_user(db: Session, username: str, email: str, password: str) -> User:
    user = User(
        username=username,
        email=email,
        password_hash=get_password_hash(password),
        chips=1000,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(func.lower(User.username) == username.lower()).first()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def create_room_record(db: Session, room_id: str, name: str, owner_id: int, max_players: int, small_blind: int) -> RoomRecord:
    room = RoomRecord(
        room_id=room_id,
        name=name,
        owner_id=owner_id,
        max_players=max_players,
        small_blind=small_blind,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def persist_completed_hand(db: Session, room: dict) -> bool:
    """Store one settled hand and per-player results exactly once."""
    if not room.get("hand_settled") or not room.get("hand_number"):
        return False
    existing = db.query(HandRecord.id).filter_by(
        room_id=room["room_id"], hand_number=room["hand_number"],
    ).first()
    if existing:
        return False

    started_at = room.get("hand_started_at")
    completed_at = room.get("hand_completed_at") or 0
    duration = max(0.0, completed_at - started_at) if started_at else 0.0
    awards = room.get("last_hand_summary", {}).get("awards", [])
    won_by_id: dict[int, int] = {}
    for award in awards:
        player_id = int(award.get("player_id", 0))
        won_by_id[player_id] = won_by_id.get(player_id, 0) + int(award.get("amount", 0))
    winner_labels = {
        int(winner["id"]): winner.get("hand_label")
        for winner in room.get("last_hand_summary", {}).get("winners", [])
    }
    actions_by_player: dict[int, list[dict]] = {}
    for event in room.get("hand_history", []):
        player_id = event.get("player_id")
        if player_id is not None and event.get("action"):
            actions_by_player.setdefault(int(player_id), []).append({
                key: event[key] for key in ("phase", "action", "amount", "message", "is_aggressive") if key in event
            })
    board = room.get("board", [])
    if len(board) == 5:
        live_scores = [
            evaluate_best_hand(list(player.get("hole_cards", [])) + board)
            for player in room.get("players", [])
            if player.get("in_hand") and not player.get("folded") and len(player.get("hole_cards", [])) == 2
        ]
        if live_scores:
            best_live_score = max(live_scores)
            for player in room.get("players", []):
                cards = list(player.get("hole_cards", []))
                player_id = int(player["id"])
                if player.get("folded") and len(cards) == 2 and evaluate_best_hand(cards + board) < best_live_score:
                    for action in actions_by_player.get(player_id, []):
                        if action.get("action") == "fold":
                            action["perfect_fold"] = True
                            break
    start_stacks = room.get("hand_start_stacks", {})
    public_players = []
    for player in room.get("players", []):
        player_id = int(player["id"])
        chips_before = int(start_stacks.get(player_id, start_stacks.get(str(player_id), player.get("chips", 0))))
        public_players.append({
            "id": player_id, "username": player["username"], "seat": player["seat"],
            "chips_before": chips_before, "chips_after": int(player["chips"]),
            "chips_net": int(player["chips"]) - chips_before,
            "contributed": int(player.get("contributed", 0)), "won": won_by_id.get(player_id, 0),
            "folded": bool(player.get("folded", False)), "all_in": bool(player.get("all_in", False)),
            "hole_cards": list(player.get("hole_cards", [])) if not player.get("folded") else ["XX", "XX"],
            "hand_label": winner_labels.get(player_id),
        })

    record = HandRecord(
        room_id=room["room_id"], hand_number=int(room["hand_number"]), room_name=room["name"],
        small_blind=int(room["small_blind"]), pot=int(room.get("last_hand_summary", {}).get("pot", 0)),
        started_at=started_at, completed_at=completed_at, duration_seconds=duration,
        board_json=json.dumps(room.get("board", []), ensure_ascii=False),
        events_json=json.dumps(room.get("hand_history", []), ensure_ascii=False),
        players_json=json.dumps(public_players, ensure_ascii=False),
        summary_json=json.dumps(room.get("last_hand_summary", {}), ensure_ascii=False),
    )
    db.add(record)
    try:
        db.flush()
        for player in room.get("players", []):
            player_id = int(player["id"])
            chips_before = int(start_stacks.get(player_id, start_stacks.get(str(player_id), player.get("chips", 0))))
            if chips_before <= 0:
                continue
            db.add(HandPlayerRecord(
                hand_id=record.id, user_id=player_id, username=player["username"],
                chips_before=chips_before, chips_after=int(player["chips"]),
                chips_net=int(player["chips"]) - chips_before,
                contributed=int(player.get("contributed", 0)), won=won_by_id.get(player_id, 0),
                folded=int(bool(player.get("folded", False))),
                hand_label=winner_labels.get(player_id),
                hole_cards_json=json.dumps(player.get("hole_cards", []), ensure_ascii=False),
                actions_json=json.dumps(actions_by_player.get(player_id, []), ensure_ascii=False),
            ))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
