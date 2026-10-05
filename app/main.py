from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc
from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError

from app.crud import create_room_record, create_user, get_user_by_email, get_user_by_id, get_user_by_username, persist_completed_hand
from app.database import Base, SessionLocal, engine, get_db
from app.models import HandPlayerRecord, HandRecord, User
from app.schemas import ActionPayload, RoomCreate, RoomJoinRequest, Token, UserCreate, UserLogin, UserOut
from app.security import create_access_token, get_current_user, get_user_by_token, verify_password
from app.services.game_logic import apply_action, create_room, expire_timed_out_turns, get_completed_room_record, get_room, get_room_broadcast_snapshots, get_room_list, get_room_snapshot, get_user_room_snapshots, join_room, refresh_room_analytics, start_hand

logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
SERVER_LOCK_PATH = Path(os.getenv("SERVER_LOCK_PATH", str(BASE_DIR / ".uvicorn.lock")))


def acquire_server_lock() -> None:
    try:
        fd = os.open(SERVER_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(f"{os.getpid()}\n")
    except FileExistsError:
        raise RuntimeError(
            "Jiná instance appky již běží. Zastavte starý uvicorn proces nebo smažte .uvicorn.lock, pokud je stale."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    acquire_server_lock()
    timeout_task = asyncio.create_task(_turn_timeout_watcher())
    try:
        yield
    finally:
        timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await timeout_task
        for task in analytics_tasks:
            task.cancel()
        if analytics_tasks:
            await asyncio.gather(*analytics_tasks, return_exceptions=True)
        analytics_tasks.clear()
        release_server_lock()


app = FastAPI(title="Poker Table Backend", version="0.1.0", lifespan=lifespan)


def release_server_lock() -> None:
    try:
        SERVER_LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
    ).split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "home.html")


@app.get("/table")
def table_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "table.html")


@app.get("/profile")
def profile_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "profile.html")

connected_clients: dict[int, set[WebSocket]] = {}
analytics_tasks: set[asyncio.Task] = set()


async def _turn_timeout_watcher() -> None:
    while True:
        await asyncio.sleep(0.2)
        expired_room_ids = await asyncio.to_thread(expire_timed_out_turns)
        for room_id in expired_room_ids:
            await asyncio.to_thread(_persist_completed_room_hand, room_id)
            await emit_room(room_id, {"type": "room_update", "reason": "turn_timeout"})
            schedule_room_analytics(room_id)


def _persist_completed_room_hand(room_id: str) -> bool:
    snapshot = get_completed_room_record(room_id)
    if snapshot is None:
        return False
    db = SessionLocal()
    try:
        return persist_completed_hand(db, snapshot)
    finally:
        db.close()


async def emit_room(room_id: str, payload: dict[str, Any]) -> None:
    for user_id, snapshot in get_room_broadcast_snapshots(room_id):
        for websocket in list(connected_clients.get(user_id, set())):
            player_payload = dict(payload)
            if payload.get("type") == "room_update" or isinstance(payload.get("room"), dict):
                player_payload["room"] = snapshot

            try:
                await websocket.send_json(player_payload)
            except Exception:
                clients = connected_clients.get(user_id)
                if clients is not None:
                    clients.discard(websocket)
                    if not clients:
                        connected_clients.pop(user_id, None)


async def _refresh_analytics_and_broadcast(room_id: str) -> None:
    try:
        await asyncio.sleep(0.08)  # Coalesce quick consecutive actions into the newest hand state.
        await asyncio.to_thread(refresh_room_analytics, room_id)
        await emit_room(room_id, {"type": "room_update", "reason": "analytics"})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Analytics refresh failed for room %s", room_id)


def schedule_room_analytics(room_id: str) -> None:
    task = asyncio.create_task(_refresh_analytics_and_broadcast(room_id))
    analytics_tasks.add(task)
    task.add_done_callback(analytics_tasks.discard)


@app.post("/api/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    if get_user_by_email(db, user_in.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if get_user_by_username(db, user_in.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    try:
        user = create_user(db, user_in.username, user_in.email, user_in.password)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already registered") from exc
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "chips": user.chips,
    }


@app.post("/api/auth/login", response_model=Token)
def login_user(form_data: UserLogin, db: Session = Depends(get_db)):
    user = get_user_by_email(db, form_data.email)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "chips": current_user.chips,
    }


def _player_hand_rows(db: Session, user_id: int, limit: int | None = None):
    query = (db.query(HandPlayerRecord, HandRecord)
             .join(HandRecord, HandPlayerRecord.hand_id == HandRecord.id)
             .filter(HandPlayerRecord.user_id == user_id)
             .order_by(desc(HandRecord.completed_at), desc(HandRecord.id)))
    if limit is not None:
        query = query.limit(limit)
    return query.all()


@app.get("/api/me/stats")
def read_my_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = _player_hand_rows(db, current_user.id)
    hands_played = len(rows)
    hands_won = sum(1 for player, _hand in rows if player.won > 0)
    total_chips_net = sum(player.chips_net for player, _hand in rows)
    total_won = sum(player.won for player, _hand in rows)
    pots = [hand.pot for _player, hand in rows]
    durations = [hand.duration_seconds for _player, hand in rows]
    decision_counts = {action: 0 for action in ("fold", "check", "call", "bet", "raise", "all_in")}
    vpip_hands = 0
    pfr_hands = 0
    all_in_seen = False
    perfect_fold_seen = False
    cumulative_chips = 0
    chip_history = []
    for player, hand in sorted(rows, key=lambda row: (row[1].completed_at, row[1].id)):
        actions = json.loads(player.actions_json or "[]")
        preflop = [event.get("action") for event in actions if event.get("phase") == "preflop"]
        if any(action in {"call", "bet", "raise", "all_in"} for action in preflop):
            vpip_hands += 1
        if any(
            event.get("phase") == "preflop"
            and (event.get("action") in {"bet", "raise"}
                 or event.get("action") == "all_in" and event.get("is_aggressive", True))
            for event in actions
        ):
            pfr_hands += 1
        for event in actions:
            action = event.get("action")
            if action in decision_counts:
                decision_counts[action] += 1
            all_in_seen = all_in_seen or action == "all_in"
            perfect_fold_seen = perfect_fold_seen or bool(event.get("perfect_fold"))
        cumulative_chips += player.chips_net
        chip_history.append({"hand_number": hand.hand_number, "net": player.chips_net, "cumulative": cumulative_chips})

    total_decisions = sum(decision_counts.values())
    decision_percentages = {
        action: round(count / total_decisions * 100, 1) if total_decisions else 0.0
        for action, count in decision_counts.items()
    }
    wins_with_royal = False
    for player_record, hand in rows:
        summary = json.loads(hand.summary_json or "{}")
        for winner in summary.get("winners", []):
            strength = winner.get("hand_strength", [])
            if (int(winner.get("id", -1)) == current_user.id
                    and len(strength) > 1 and strength[0] == 8 and strength[1] == 14):
                wins_with_royal = True
    achievements = []
    if hands_won:
        achievements.append("First Win")
    if all_in_seen:
        achievements.append("First All-in")
    if hands_played >= 10:
        achievements.append("10 Hands Played")
    if hands_played >= 100:
        achievements.append("100 Hands Played")
    biggest_pot = max(pots, default=0)
    if biggest_pot > 0 and any(player.won > 0 and hand.pot == biggest_pot for player, hand in rows):
        achievements.append("Biggest Pot")
    if wins_with_royal:
        achievements.append("Royal Flush")
    if perfect_fold_seen:
        achievements.append("Perfect Fold")
    if hands_played and total_chips_net > 0 and hands_won:
        achievements.append("Winning Session")

    return {
        "username": current_user.username,
        "hands_played": hands_played,
        "hands_won": hands_won,
        "win_rate": round(hands_won / hands_played * 100, 1) if hands_played else 0.0,
        "total_chips_net": total_chips_net,
        "total_won": total_won,
        "biggest_pot": biggest_pot,
        "average_pot": round(sum(pots) / len(pots), 1) if pots else 0.0,
        "average_duration_seconds": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "vpip": round(vpip_hands / hands_played * 100, 1) if hands_played else 0.0,
        "pfr": round(pfr_hands / hands_played * 100, 1) if hands_played else 0.0,
        "decisions": decision_counts,
        "decision_percentages": decision_percentages,
        "chips_history": chip_history,
        "achievements": achievements,
    }


@app.get("/api/me/hands")
def read_my_hands(
    limit: int = Query(30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hands = []
    for player_record, hand in _player_hand_rows(db, current_user.id, limit):
        players = json.loads(hand.players_json)
        for player in players:
            if int(player["id"]) == current_user.id:
                player["hole_cards"] = json.loads(player_record.hole_cards_json or "[]")
                break
        hands.append({
            "id": hand.id,
            "room_id": hand.room_id,
            "room_name": hand.room_name,
            "hand_number": hand.hand_number,
            "small_blind": hand.small_blind,
            "pot": hand.pot,
            "board": json.loads(hand.board_json),
            "players": players,
            "events": json.loads(hand.events_json),
            "summary": json.loads(hand.summary_json),
            "completed_at": hand.completed_at,
            "duration_seconds": hand.duration_seconds,
        })
    return {"hands": hands}


@app.get("/api/rooms")
def list_rooms():
    return {"rooms": get_room_list()}


@app.post("/api/rooms", status_code=status.HTTP_201_CREATED)
def create_room_endpoint(room_in: RoomCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room = create_room(room_in.name, current_user.id, current_user.username, room_in.max_players, room_in.small_blind)
    create_room_record(db, room["room_id"], room["name"], current_user.id, room["max_players"], room["small_blind"])
    return {"room": get_room_snapshot(room, current_user.id)}


@app.post("/api/rooms/{room_id}/join")
async def join_room_endpoint(room_id: str, current_user: User = Depends(get_current_user)):
    room = get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    try:
        join_room(room_id, current_user.id, current_user.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await emit_room(room_id, {"type": "room_update"})
    return {"room": get_room_snapshot(room, current_user.id)}


@app.get("/api/rooms/{room_id}")
def room_detail(room_id: str, current_user: User = Depends(get_current_user)):
    room = get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"room": get_room_snapshot(room, current_user.id)}


@app.post("/api/rooms/{room_id}/start")
async def start_hand_endpoint(room_id: str, current_user: User = Depends(get_current_user)):
    room = get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if room["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Only the table owner can start a hand")
    try:
        start_hand(room_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await asyncio.to_thread(_persist_completed_room_hand, room_id)
    room = get_room(room_id)
    await emit_room(room_id, {"type": "room_update"})
    schedule_room_analytics(room_id)
    return {"room": get_room_snapshot(room, current_user.id)}


@app.post("/api/rooms/{room_id}/action")
async def room_action(payload: ActionPayload, current_user: User = Depends(get_current_user)):
    room = get_room(payload.room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    try:
        room = apply_action(payload.room_id, current_user.id, payload.action, payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await asyncio.to_thread(_persist_completed_room_hand, payload.room_id)
    room = get_room(payload.room_id)
    await emit_room(payload.room_id, {"type": "room_update"})
    schedule_room_analytics(payload.room_id)
    return {"room": get_room_snapshot(room, current_user.id)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    protocols = [value.strip() for value in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    token = next((value.removeprefix("auth.") for value in protocols if value.startswith("auth.")), None)
    if "poker.v1" not in protocols or not token:
        await websocket.close(code=1008)
        return
    user = get_user_by_token(token)
    if user is None:
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    try:
        db_user = get_user_by_id(db, user.id)
        if db_user is None:
            await websocket.close(code=1008)
            return
    finally:
        db.close()

    await websocket.accept(subprotocol="poker.v1")
    connected_clients.setdefault(user.id, set()).add(websocket)
    await websocket.send_json({"type": "welcome", "user_id": user.id, "username": db_user.username})
    for room_snapshot in get_user_room_snapshots(user.id):
        await websocket.send_json({"type": "room_update", "room": room_snapshot})

    try:
        while True:
            try:
                message = await websocket.receive_json()
            except ValueError:
                await websocket.send_json({"type": "error", "detail": "Malformed JSON message"})
                continue
            if not isinstance(message, dict):
                await websocket.send_json({"type": "error", "detail": "Message must be an object"})
                continue
            msg_type = message.get("type")
            if msg_type == "rooms":
                await websocket.send_json({"type": "rooms", "rooms": get_room_list()})
                continue

            if msg_type == "create_room":
                room_data = message.get("room", {})
                if not isinstance(room_data, dict):
                    await websocket.send_json({"type": "error", "detail": "Room must be an object"})
                    continue
                try:
                    validated = RoomCreate(**room_data)
                    room = create_room(validated.name, user.id, db_user.username,
                                       validated.max_players, validated.small_blind)
                except (ValueError, TypeError) as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                db = SessionLocal()
                try:
                    create_room_record(db, room["room_id"], room["name"], user.id,
                                       room["max_players"], room["small_blind"])
                finally:
                    db.close()
                await websocket.send_json({"type": "room_created", "room": get_room_snapshot(room, user.id)})
                await emit_room(room["room_id"], {"type": "room_update"})
                continue

            if msg_type == "join_room":
                room_id = message.get("room_id")
                try:
                    join_room(room_id, user.id, db_user.username)
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                room = get_room(room_id)
                await emit_room(room_id, {"type": "room_update"})
                continue

            if msg_type == "start_game":
                room_id = message.get("room_id")
                room = get_room(room_id)
                if room is None:
                    await websocket.send_json({"type": "error", "detail": "Room not found"})
                    continue
                if room["owner_id"] != user.id:
                    await websocket.send_json({"type": "error", "detail": "Only the table owner can start a hand"})
                    continue
                try:
                    start_hand(room_id)
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                await asyncio.to_thread(_persist_completed_room_hand, room_id)
                room = get_room(room_id)
                await emit_room(room_id, {"type": "room_update"})
                schedule_room_analytics(room_id)
                continue

            if msg_type == "action":
                payload = message.get("payload", {})
                if not isinstance(payload, dict):
                    await websocket.send_json({"type": "error", "detail": "Action payload must be an object"})
                    continue
                try:
                    room = apply_action(payload.get("room_id"), user.id, payload.get("action", "check"), payload.get("amount"))
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                await asyncio.to_thread(_persist_completed_room_hand, payload.get("room_id"))
                room = get_room(payload.get("room_id"))
                await emit_room(payload.get("room_id"), {"type": "room_update"})
                schedule_room_analytics(payload.get("room_id"))
                continue

            await websocket.send_json({"type": "unsupported", "message": "Unsupported message type"})
    except WebSocketDisconnect:
        pass
    finally:
        clients = connected_clients.get(user.id)
        if clients is not None:
            clients.discard(websocket)
            if not clients:
                connected_clients.pop(user.id, None)
