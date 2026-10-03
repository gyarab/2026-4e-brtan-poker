import uuid
from pathlib import Path

Path("poker.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient

import pytest

from app.main import SERVER_LOCK_PATH, acquire_server_lock, app, release_server_lock
from app.services.game_logic import create_room, determine_showdown_winners, evaluate_best_hand, get_room, start_hand

client = TestClient(app)


def test_single_server_lock_prevents_duplicate_instance():
    try:
        SERVER_LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass

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
    assert winners[0]["hand_strength"] >= winners[0]["hand_strength"]
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
    guest_ws = FakeSocket()

    from app.main import connected_clients, emit_room

    connected_clients.clear()
    connected_clients[1] = owner_ws
    connected_clients[2] = guest_ws

    async def trigger():
        emit_room(room["room_id"], {"type": "room_update", "room": room})
        await __import__("asyncio").sleep(0.05)

    __import__("asyncio").run(trigger())

    owner_payload = owner_ws.sent[-1]
    guest_payload = guest_ws.sent[-1]

    assert owner_payload["room"]["players"][0]["hole_cards"] == ["Qs", "Jc"]
    assert guest_payload["room"]["players"][0]["hole_cards"] == ["XX", "XX"]
    assert guest_payload["room"]["players"][1]["hole_cards"] == ["Ah", "Kd"]


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
