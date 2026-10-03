from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.crud import create_room_record, create_user, get_user_by_email, get_user_by_id
from app.database import Base, SessionLocal, engine, get_db
from app.models import User
from app.schemas import ActionPayload, RoomCreate, RoomJoinRequest, Token, UserCreate, UserLogin, UserOut
from app.security import create_access_token, get_current_user, get_user_by_token, verify_password
from app.services.game_logic import ROOMS, apply_action, create_room, get_room, get_room_list, get_room_snapshot, join_room, start_hand

Base.metadata.create_all(bind=engine)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
SERVER_LOCK_PATH = BASE_DIR / ".uvicorn.lock"


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
    try:
        yield
    finally:
        release_server_lock()


app = FastAPI(title="Poker Table Backend", version="0.1.0", lifespan=lifespan)


def release_server_lock() -> None:
    try:
        SERVER_LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

connected_clients: dict[int, WebSocket] = {}


def emit_room(room_id: str, payload: dict[str, Any]) -> None:
    room = get_room(room_id)
    if not room:
        return

    for player in room["players"]:
        websocket = connected_clients.get(player["id"])
        if websocket is None:
            continue

        player_payload = dict(payload)
        if isinstance(payload.get("room"), dict):
            player_payload["room"] = get_room_snapshot(room, player["id"])

        try:
            asyncio.create_task(websocket.send_json(player_payload))
        except Exception:
            pass


@app.post("/api/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    if get_user_by_email(db, user_in.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = create_user(db, user_in.username, user_in.email, user_in.password)
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


@app.get("/api/rooms")
def list_rooms():
    return {"rooms": get_room_list()}


@app.post("/api/rooms", status_code=status.HTTP_201_CREATED)
def create_room_endpoint(room_in: RoomCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room = create_room(room_in.name, current_user.id, current_user.username, room_in.max_players, room_in.small_blind)
    create_room_record(db, room["room_id"], room["name"], current_user.id, room["max_players"], room["small_blind"])
    return {"room": get_room_snapshot(room, current_user.id)}


@app.post("/api/rooms/{room_id}/join")
def join_room_endpoint(room_id: str, current_user: User = Depends(get_current_user)):
    room = get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    try:
        join_room(room_id, current_user.id, current_user.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    emit_room(room_id, {"type": "room_update", "room": get_room_snapshot(room, current_user.id)})
    return {"room": get_room_snapshot(room, current_user.id)}


@app.get("/api/rooms/{room_id}")
def room_detail(room_id: str, current_user: User = Depends(get_current_user)):
    room = get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"room": get_room_snapshot(room, current_user.id)}


@app.post("/api/rooms/{room_id}/start")
def start_hand_endpoint(room_id: str, current_user: User = Depends(get_current_user)):
    room = get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    try:
        start_hand(room_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    emit_room(room_id, {"type": "room_update", "room": get_room_snapshot(room, current_user.id)})
    return {"room": get_room_snapshot(room, current_user.id)}


@app.post("/api/rooms/{room_id}/action")
def room_action(payload: ActionPayload, current_user: User = Depends(get_current_user)):
    room = get_room(payload.room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    try:
        room = apply_action(payload.room_id, current_user.id, payload.action, payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    emit_room(payload.room_id, {"type": "room_update", "room": get_room_snapshot(room, current_user.id)})
    return {"room": get_room_snapshot(room, current_user.id)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
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

    await websocket.accept()
    connected_clients[user.id] = websocket
    await websocket.send_json({"type": "welcome", "user_id": user.id, "username": db_user.username})

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type == "rooms":
                await websocket.send_json({"type": "rooms", "rooms": get_room_list()})
                continue

            if msg_type == "create_room":
                room_data = message.get("room", {})
                room = create_room(room_data.get("name"), user.id, db_user.username, room_data.get("max_players", 6), room_data.get("small_blind", 10))
                create_room_record(
                    SessionLocal(),
                    room["room_id"],
                    room["name"],
                    user.id,
                    room["max_players"],
                    room["small_blind"],
                )
                await websocket.send_json({"type": "room_created", "room": get_room_snapshot(room, user.id)})
                emit_room(room["room_id"], {"type": "room_update", "room": get_room_snapshot(room, user.id)})
                continue

            if msg_type == "join_room":
                room_id = message.get("room_id")
                try:
                    join_room(room_id, user.id, db_user.username)
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                room = get_room(room_id)
                emit_room(room_id, {"type": "room_update", "room": get_room_snapshot(room, user.id)})
                continue

            if msg_type == "start_game":
                room_id = message.get("room_id")
                try:
                    start_hand(room_id)
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                room = get_room(room_id)
                emit_room(room_id, {"type": "room_update", "room": get_room_snapshot(room, user.id)})
                continue

            if msg_type == "action":
                payload = message.get("payload", {})
                try:
                    room = apply_action(payload.get("room_id"), user.id, payload.get("action", "check"), payload.get("amount"))
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                emit_room(payload.get("room_id"), {"type": "room_update", "room": get_room_snapshot(room, user.id)})
                continue

            await websocket.send_json({"type": "unsupported", "message": "Unsupported message type"})
    except WebSocketDisconnect:
        connected_clients.pop(user.id, None)
