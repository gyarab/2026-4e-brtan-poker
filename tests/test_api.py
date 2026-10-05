import os
from pathlib import Path
import subprocess
import sys
import uuid
import time
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import pytest

from app.main import SERVER_LOCK_PATH, acquire_server_lock, app, release_server_lock
from app.services.game_logic import create_room, determine_showdown_winners, evaluate_best_hand, get_room, start_hand

client = TestClient(app)


def test_production_config_rejects_weak_secrets_and_untrusted_algorithms():
    project_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["APP_ENV"] = "production"
    env.pop("SECRET_KEY", None)
    env.pop("JWT_ALGORITHM", None)
    missing = subprocess.run(
        [sys.executable, "-c", "import app.config"], cwd=project_dir, env=env,
        capture_output=True, text=True, check=False,
    )
    assert missing.returncode != 0
    assert "Production requires a private SECRET_KEY" in missing.stderr

    env["SECRET_KEY"] = "short-key"
    weak = subprocess.run(
        [sys.executable, "-c", "import app.config"], cwd=project_dir, env=env,
        capture_output=True, text=True, check=False,
    )
    assert weak.returncode != 0

    env["SECRET_KEY"] = "private-test-key-which-is-long-enough-123456"
    env.pop("JWT_ALGORITHM", None)
    strong_key = subprocess.run(
        [sys.executable, "-c", "import app.config"], cwd=project_dir, env=env,
        capture_output=True, text=True, check=False,
    )
    assert strong_key.returncode == 0, strong_key.stderr

    env["JWT_ALGORITHM"] = "none"
    unsafe_algorithm = subprocess.run(
        [sys.executable, "-c", "import app.config"], cwd=project_dir, env=env,
        capture_output=True, text=True, check=False,
    )
    assert unsafe_algorithm.returncode != 0
    assert "JWT_ALGORITHM must be" in unsafe_algorithm.stderr


def test_single_server_lock_prevents_duplicate_instance():
    acquire_server_lock()
    assert SERVER_LOCK_PATH.exists()

    with pytest.raises(RuntimeError, match="Jiná instance appky"):
        acquire_server_lock()

    release_server_lock()
    assert not SERVER_LOCK_PATH.exists()


def test_register_and_login():
    unique = uuid.uuid4().hex[:8]
    payload = {"username": f"alice_{unique}", "email": f"alice_{unique}@example.com", "password": "secret123"}
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text

    login = client.post(
        "/api/auth/login",
        json={"email": f"alice_{unique}@example.com", "password": "secret123"},
    )
    assert login.status_code == 200, login.text
    data = login.json()
    assert "access_token" in data
    duplicate_username = client.post("/api/auth/register", json={
        "username": payload["username"].upper(), "email": f"other_{unique}@example.com", "password": "secret123",
    })
    assert duplicate_username.status_code == 400
    whitespace_username = client.post("/api/auth/register", json={
        "username": "   ", "email": f"blank_{unique}@example.com", "password": "secret123",
    })
    assert whitespace_username.status_code == 422
    oversized_password = client.post("/api/auth/register", json={
        "username": f"long_{unique}", "email": f"long_{unique}@example.com", "password": "ž" * 37,
    })
    assert oversized_password.status_code == 422
    wrong_password = client.post("/api/auth/login", json={
        "email": payload["email"], "password": "incorrect",
    })
    assert wrong_password.status_code == 401
    oversized_login_password = client.post("/api/auth/login", json={
        "email": payload["email"], "password": "x" * 1000,
    })
    assert oversized_login_password.status_code == 401


def test_websocket_reconnect_restores_member_room_and_rejects_bad_token():
    unique = uuid.uuid4().hex[:8]
    email = f"socket_{unique}@example.com"
    client.post("/api/auth/register", json={
        "username": f"socket_{unique}", "email": email, "password": "secret123",
    })
    token = client.post("/api/auth/login", json={"email": email, "password": "secret123"}).json()["access_token"]
    room_response = client.post(
        "/api/rooms", json={"name": "Reconnect Room", "max_players": 2, "small_blind": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    room_id = room_response.json()["room"]["room_id"]
    protocols = ["poker.v1", f"auth.{token}"]
    with client.websocket_connect("/ws", subprotocols=protocols) as first_socket:
        assert first_socket.receive_json()["type"] == "welcome"
        first_room = first_socket.receive_json()
        assert first_room["type"] == "room_update"
        assert first_room["room"]["room_id"] == room_id
        first_socket.send_json({"type": "join_room", "room_id": room_id})
        repeated_join = first_socket.receive_json()
        assert repeated_join["room"]["players"][0]["seat"] == 0
        first_socket.send_text("{not-json")
        malformed = first_socket.receive_json()
        assert malformed["type"] == "error"

    with client.websocket_connect("/ws", subprotocols=protocols) as resumed_socket:
        assert resumed_socket.receive_json()["type"] == "welcome"
        resumed_room = resumed_socket.receive_json()
        assert resumed_room["type"] == "room_update"
        assert resumed_room["room"]["room_id"] == room_id

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", subprotocols=["poker.v1", "auth.invalid-token"]) as _socket:
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws?token={token}") as _socket:
            pass


def test_lifespan_timeout_watcher_folds_and_broadcasts_room_state():
    unique = uuid.uuid4().hex[:8]
    with TestClient(app) as live_client:
        users = []
        for label in ("timeout_owner", "timeout_guest"):
            email = f"{label}_{unique}@example.com"
            registered = live_client.post("/api/auth/register", json={
                "username": f"{label}_{unique}", "email": email, "password": "secret123",
            })
            assert registered.status_code == 201
            token = live_client.post("/api/auth/login", json={
                "email": email, "password": "secret123",
            }).json()["access_token"]
            users.append(token)
        owner_headers = {"Authorization": f"Bearer {users[0]}"}
        guest_headers = {"Authorization": f"Bearer {users[1]}"}
        created = live_client.post("/api/rooms", json={
            "name": f"Timeout_{unique}", "max_players": 2, "small_blind": 10,
        }, headers=owner_headers)
        room_id = created.json()["room"]["room_id"]
        assert live_client.post(f"/api/rooms/{room_id}/join", headers=guest_headers).status_code == 200
        started = live_client.post(f"/api/rooms/{room_id}/start", headers=owner_headers)
        assert started.status_code == 200

        get_room(room_id)["turn_deadline_at"] = time.time() - 1
        end = time.monotonic() + 2
        result = None
        while time.monotonic() < end:
            result = live_client.get(f"/api/rooms/{room_id}", headers=owner_headers).json()["room"]
            if result["phase"] == "showdown":
                break
            time.sleep(0.05)
        assert result["phase"] == "showdown"
        assert result["turn_deadline_at"] is None
        assert any("timed out; automatic fold." in event for event in result["history"])


def test_create_and_join_room():
    unique = uuid.uuid4().hex[:8]
    client.post(
        "/api/auth/register",
        json={"username": f"bob_{unique}", "email": f"bob_{unique}@example.com", "password": "secret123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": f"bob_{unique}@example.com", "password": "secret123"},
    ).json()["access_token"]

    room = client.post(
        "/api/rooms",
        json={"name": "Lobby One", "max_players": 4, "small_blind": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert room.status_code == 201, room.text
    room_id = room.json()["room"]["room_id"]

    second_unique = uuid.uuid4().hex[:8]
    client.post(
        "/api/auth/register",
        json={"username": f"charlie_{second_unique}", "email": f"charlie_{second_unique}@example.com", "password": "secret123"},
    )
    second_token = client.post(
        "/api/auth/login",
        json={"email": f"charlie_{second_unique}@example.com", "password": "secret123"},
    ).json()["access_token"]

    join = client.post(
        f"/api/rooms/{room_id}/join",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert join.status_code == 200, join.text
    duplicate_join = client.post(
        f"/api/rooms/{room_id}/join",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert duplicate_join.status_code == 200
    assert len(duplicate_join.json()["room"]["players"]) == 2

    forbidden_start = client.post(
        f"/api/rooms/{room_id}/start",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert forbidden_start.status_code == 403
    started = client.post(
        f"/api/rooms/{room_id}/start",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert started.status_code == 200
    assert started.json()["room"]["phase"] == "preflop"
    assert started.json()["room"]["pot"] == 30
    out_of_turn = client.post(
        f"/api/rooms/{room_id}/action",
        json={"room_id": room_id, "action": "call"},
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert out_of_turn.status_code == 400
    assert get_room(room_id)["pot"] == 30
    third_unique = uuid.uuid4().hex[:8]
    third_email = f"late_{third_unique}@example.com"
    client.post("/api/auth/register", json={
        "username": f"late_{third_unique}", "email": third_email, "password": "secret123",
    })
    third_token = client.post("/api/auth/login", json={"email": third_email, "password": "secret123"}).json()["access_token"]
    late_join = client.post(
        f"/api/rooms/{room_id}/join", headers={"Authorization": f"Bearer {third_token}"},
    )
    assert late_join.status_code == 400


def test_settled_hand_is_persisted_for_private_history_and_profile_stats():
    unique = uuid.uuid4().hex[:8]
    tokens = []
    for name in ("profile_owner", "profile_guest"):
        email = f"{name}_{unique}@example.com"
        assert client.post("/api/auth/register", json={
            "username": f"{name}_{unique}", "email": email, "password": "secret123",
        }).status_code == 201
        tokens.append(client.post("/api/auth/login", json={
            "email": email, "password": "secret123",
        }).json()["access_token"])
    owner_headers = {"Authorization": f"Bearer {tokens[0]}"}
    guest_headers = {"Authorization": f"Bearer {tokens[1]}"}
    owner_id = client.get("/api/me", headers=owner_headers).json()["id"]
    guest_id = client.get("/api/me", headers=guest_headers).json()["id"]
    created = client.post("/api/rooms", json={
        "name": f"Profile_{unique}", "max_players": 2, "small_blind": 10,
    }, headers=owner_headers).json()["room"]
    room_id = created["room_id"]
    assert client.post(f"/api/rooms/{room_id}/join", headers=guest_headers).status_code == 200
    assert client.post(f"/api/rooms/{room_id}/start", headers=owner_headers).status_code == 200

    room = get_room(room_id)
    actor = room["players"][room["current_turn"]]
    actor_headers = owner_headers if actor["id"] == room["owner_id"] else guest_headers
    settled = client.post(f"/api/rooms/{room_id}/action", json={
        "room_id": room_id, "action": "fold",
    }, headers=actor_headers)
    assert settled.status_code == 200
    assert settled.json()["room"]["phase"] == "showdown"

    owner_hands = client.get("/api/me/hands", headers=owner_headers).json()["hands"]
    guest_hands = client.get("/api/me/hands", headers=guest_headers).json()["hands"]
    assert len(owner_hands) == len(guest_hands) == 1
    assert owner_hands[0]["pot"] == 30
    owner_self = next(player for player in owner_hands[0]["players"] if player["id"] == owner_id)
    guest_view_of_folded_owner = next(player for player in guest_hands[0]["players"] if player["id"] == owner_id)
    # The folded player can review their own cards; the other player's folded cards stay hidden.
    assert len(owner_self["hole_cards"]) == 2
    assert guest_view_of_folded_owner["hole_cards"] == ["XX", "XX"]
    guest_stats = client.get("/api/me/stats", headers=guest_headers).json()
    assert guest_stats["hands_played"] == 1
    assert guest_stats["hands_won"] == 1
    assert guest_stats["total_chips_net"] == 10
    assert guest_stats["biggest_pot"] == 30
    assert guest_id in [player["id"] for player in guest_hands[0]["players"]]
    from app.main import _persist_completed_room_hand
    from app.database import SessionLocal
    from app.models import HandPlayerRecord, HandRecord
    assert _persist_completed_room_hand(room_id) is False
    db = SessionLocal()
    try:
        assert db.query(HandRecord).filter_by(room_id=room_id, hand_number=1).count() == 1
        assert db.query(HandPlayerRecord).filter_by(user_id=guest_id).count() == 1
    finally:
        db.close()


def test_profile_preflop_raises_excludes_an_all_in_call():
    unique = uuid.uuid4().hex[:8]
    tokens = []
    for label in ("pfr_owner", "pfr_guest"):
        email = f"{label}_{unique}@example.com"
        assert client.post("/api/auth/register", json={
            "username": f"{label}_{unique}", "email": email, "password": "secret123",
        }).status_code == 201
        tokens.append(client.post("/api/auth/login", json={
            "email": email, "password": "secret123",
        }).json()["access_token"])
    headers = [{"Authorization": f"Bearer {token}"} for token in tokens]
    owner_id = client.get("/api/me", headers=headers[0]).json()["id"]
    created = client.post("/api/rooms", json={
        "name": f"PFR_{unique}", "max_players": 2, "small_blind": 10,
    }, headers=headers[0]).json()["room"]
    room_id = created["room_id"]
    assert client.post(f"/api/rooms/{room_id}/join", headers=headers[1]).status_code == 200
    room = get_room(room_id)
    for player in room["players"]:
        player["chips"] = 50
    assert client.post(f"/api/rooms/{room_id}/start", headers=headers[0]).status_code == 200

    for _ in range(2):
        actor = get_room(room_id)["players"][get_room(room_id)["current_turn"]]
        actor_headers = headers[0] if actor["id"] == owner_id else headers[1]
        response = client.post(f"/api/rooms/{room_id}/action", json={
            "room_id": room_id, "action": "all_in",
        }, headers=actor_headers)
        assert response.status_code == 200, response.text
    assert get_room(room_id)["phase"] == "showdown"

    owner_stats = client.get("/api/me/stats", headers=headers[0]).json()
    guest_stats = client.get("/api/me/stats", headers=headers[1]).json()
    assert owner_stats["vpip"] == guest_stats["vpip"] == 100.0
    assert owner_stats["pfr"] == 100.0
    assert guest_stats["pfr"] == 0.0


def test_perfect_fold_achievement_uses_private_folded_cards_without_revealing_them():
    unique = uuid.uuid4().hex[:8]
    tokens = []
    for label in ("fold_owner", "fold_guest", "fold_third"):
        email = f"{label}_{unique}@example.com"
        assert client.post("/api/auth/register", json={
            "username": f"{label}_{unique}", "email": email, "password": "secret123",
        }).status_code == 201
        tokens.append(client.post("/api/auth/login", json={
            "email": email, "password": "secret123",
        }).json()["access_token"])
    headers = [{"Authorization": f"Bearer {token}"} for token in tokens]
    created = client.post("/api/rooms", json={
        "name": f"PerfectFold_{unique}", "max_players": 3, "small_blind": 10,
    }, headers=headers[0]).json()["room"]
    room_id = created["room_id"]
    assert client.post(f"/api/rooms/{room_id}/join", headers=headers[1]).status_code == 200
    assert client.post(f"/api/rooms/{room_id}/join", headers=headers[2]).status_code == 200
    assert client.post(f"/api/rooms/{room_id}/start", headers=headers[0]).status_code == 200

    room = get_room(room_id)
    room["phase"] = "river"
    room["board"] = ["As", "Ks", "Qs", "Js", "2d"]
    room["pot"] = 300
    room["current_bet"] = 0
    room["hand_start_chips"] = 3000
    room["current_turn"] = 0
    for player, cards in zip(room["players"], (["3c", "4d"], ["Ah", "Ad"], ["Kh", "Kd"])):
        player.update(chips=900, contributed=100, hole_cards=list(cards), bet_this_round=0,
                      folded=False, all_in=False, in_hand=True, acted_this_round=False)

    for action in ("fold", "check", "check"):
        current = get_room(room_id)
        actor = current["players"][current["current_turn"]]
        actor_index = next(index for index, candidate in enumerate(current["players"]) if candidate["id"] == actor["id"])
        response = client.post(f"/api/rooms/{room_id}/action", json={
            "room_id": room_id, "action": action,
        }, headers=headers[actor_index])
        assert response.status_code == 200, response.text
    assert get_room(room_id)["phase"] == "showdown"

    owner_stats = client.get("/api/me/stats", headers=headers[0]).json()
    owner_history = client.get("/api/me/hands", headers=headers[0]).json()["hands"]
    guest_history = client.get("/api/me/hands", headers=headers[1]).json()["hands"]
    assert "Perfect Fold" in owner_stats["achievements"]
    assert owner_history[0]["players"][0]["hole_cards"] == ["3c", "4d"]
    assert guest_history[0]["players"][0]["hole_cards"] == ["XX", "XX"]
    assert owner_history[0]["events"][-1]["pot"] == 300


def test_profile_page_is_served():
    response = client.get("/profile")
    assert response.status_code == 200
    assert "/static/profile.js" in response.text


def test_hand_evaluation_and_game_start_state():
    room = create_room("Eval Test", 1, "owner", max_players=2, small_blind=10)
    room["players"].append({
        "id": 2,
        "username": "guest",
        "seat": 1,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })

    start_hand(room["room_id"])
    assert room["phase"] == "preflop"
    assert all(len(player["hole_cards"]) == 2 for player in room["players"])
    assert evaluate_best_hand(["As", "Ah", "Kd", "Qd", "2c", "3s", "9h"]) > evaluate_best_hand(["Ks", "Kh", "Ad", "Qd", "2c", "3s", "9h"])
    assert get_room(room["room_id"])["players"][0]["hole_cards"]


def test_showdown_winner_resolution_and_matchups():
    room = create_room("Showdown Test", 1, "owner", max_players=2, small_blind=10)
    room["players"][0]["in_hand"] = True
    room["players"][0]["hole_cards"] = ["Ah", "Kd"]
    room["players"].append({
        "id": 2,
        "username": "guest",
        "seat": 1,
        "chips": 1000,
        "hole_cards": ["Js", "Jd"],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })
    room["board"] = ["As", "Ks", "Qd", "7c", "2h"]
    room["phase"] = "showdown"
    winners = determine_showdown_winners(room)

    assert [player["id"] for player in winners] == [1]
    assert winners[0]["hand_strength"] > (0,)
    assert room["analytics"]["hand_matchups"]["owner"].startswith("wins")


def test_emit_room_sends_player_specific_snapshot_to_each_client():
    room = create_room("Broadcast Test", 1, "owner", max_players=2, small_blind=10)
    room["players"].append({
        "id": 2,
        "username": "guest",
        "seat": 1,
        "chips": 1000,
        "hole_cards": ["Ah", "Kd"],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })
    room["players"][0]["hole_cards"] = ["Qs", "Jc"]
    room["board"] = ["2s", "7d", "9h"]
    room["phase"] = "flop"

    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def send_json(self, payload):
            self.sent.append(payload)

    owner_ws = FakeSocket()
    owner_second_tab_ws = FakeSocket()
    guest_ws = FakeSocket()

    from app.main import connected_clients, emit_room

    connected_clients.clear()
    connected_clients[1] = {owner_ws, owner_second_tab_ws}
    connected_clients[2] = {guest_ws}

    async def trigger():
        await emit_room(room["room_id"], {"type": "room_update"})
        await __import__("asyncio").sleep(0.05)

    __import__("asyncio").run(trigger())

    owner_payload = owner_ws.sent[-1]
    owner_second_tab_payload = owner_second_tab_ws.sent[-1]
    guest_payload = guest_ws.sent[-1]

    assert owner_payload["room"]["players"][0]["hole_cards"] == ["Qs", "Jc"]
    assert owner_second_tab_payload["room"]["players"][0]["hole_cards"] == ["Qs", "Jc"]
    assert guest_payload["room"]["players"][0]["hole_cards"] == ["XX", "XX"]
    assert guest_payload["room"]["players"][1]["hole_cards"] == ["Ah", "Kd"]


def test_emit_room_removes_a_disconnected_socket_without_leaving_registry_entry():
    room = create_room("Broken Socket Room", 1, "owner", max_players=2)

    class BrokenSocket:
        async def send_json(self, _payload):
            raise RuntimeError("socket closed")

    from app.main import connected_clients, emit_room

    connected_clients[1] = {BrokenSocket()}
    __import__("asyncio").run(emit_room(room["room_id"], {"type": "room_update"}))
    assert 1 not in connected_clients


def test_blinds_and_button_are_set_on_hand_start():
    room = create_room("Blind Test", 1, "owner", max_players=3, small_blind=10)
    room["players"].append({
        "id": 2,
        "username": "guest",
        "seat": 1,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })
    room["players"].append({
        "id": 3,
        "username": "third",
        "seat": 2,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })

    start_hand(room["room_id"])

    assert room["dealer_index"] == 0
    assert room["small_blind_index"] == 1
    assert room["big_blind_index"] == 2
    assert room["current_turn"] == 0
    assert room["pot"] == 30
    assert room["players"][1]["chips"] == 990
    assert room["players"][2]["chips"] == 980


def test_heads_up_blinds_and_turn_order_are_standard():
    room = create_room("Heads Up Blind Test", 1, "owner", max_players=2, small_blind=10)
    room["players"].append({
        "id": 2,
        "username": "guest",
        "seat": 1,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })

    start_hand(room["room_id"])

    assert room["dealer_index"] == 0
    assert room["small_blind_index"] == 0
    assert room["big_blind_index"] == 1
    assert room["current_turn"] == 0
    assert room["players"][0]["bet_this_round"] == 10
    assert room["players"][1]["bet_this_round"] == 20
    assert room["pot"] == 30


def test_raising_requires_minimum_amount_and_call_matches_current_bet():
    room = create_room("Raise Validation", 1, "owner", max_players=3, small_blind=10)
    room["players"].append({
        "id": 2,
        "username": "guest",
        "seat": 1,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })
    room["players"].append({
        "id": 3,
        "username": "third",
        "seat": 2,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })

    start_hand(room["room_id"])
    room = __import__("app.services.game_logic", fromlist=["apply_action"]).apply_action(room["room_id"], 1, "raise", 20)

    assert room["current_bet"] >= 40

    room = __import__("app.services.game_logic", fromlist=["apply_action"]).apply_action(room["room_id"], 2, "call")
    assert room["players"][1]["bet_this_round"] >= 30
    assert room["pot"] >= 80
    assert room["players"][2]["bet_this_round"] == 20


def test_hand_history_tracks_rounds_and_winners():
    room = create_room("History Test", 1, "owner", max_players=2, small_blind=10)
    room["players"][0]["in_hand"] = True
    room["players"].append({
        "id": 2,
        "username": "guest",
        "seat": 1,
        "chips": 1000,
        "hole_cards": ["Ah", "Kd"],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })
    room["players"][0]["hole_cards"] = ["Qh", "Js"]
    room["board"] = ["As", "Ks", "Qd", "7c", "2h"]
    room["phase"] = "showdown"
    winners = determine_showdown_winners(room)
    room["hand_history"] = [{
        "phase": "showdown",
        "winner_ids": [winner["id"] for winner in winners],
        "winner_names": [winner["username"] for winner in winners],
        "hand_label": winners[0]["hand_label"],
        "message": "Showdown summary",
    }]

    assert room["hand_history"][0]["phase"] == "showdown"
    assert room["hand_history"][0]["winner_ids"] == [winner["id"] for winner in winners]
    assert room["hand_history"][0]["winner_names"] == [winner["username"] for winner in winners]
    assert room["hand_history"][0]["hand_label"] == winners[0]["hand_label"]
    assert "message" in room["hand_history"][0]


def test_call_matches_current_bet_and_advances_turn():
    room = create_room("Call Test", 1, "owner", max_players=3, small_blind=10)
    room["players"].append({
        "id": 2,
        "username": "guest",
        "seat": 1,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })
    room["players"].append({
        "id": 3,
        "username": "third",
        "seat": 2,
        "chips": 1000,
        "hole_cards": [],
        "folded": False,
        "in_hand": True,
        "last_bet": 0,
    })

    start_hand(room["room_id"])
    room = room
    updated_room = __import__("app.services.game_logic", fromlist=["apply_action"]).apply_action(room["room_id"], 1, "call")

    assert updated_room["pot"] == 50
    assert updated_room["players"][0]["chips"] == 980
    assert updated_room["current_turn"] == 1
