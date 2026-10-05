from concurrent.futures import ThreadPoolExecutor
import random
import threading

import pytest

from app.services.game_logic import (
    ROOMS,
    _build_side_pots,
    apply_action,
    create_room,
    determine_showdown_winners,
    expire_timed_out_turns,
    evaluate_best_hand,
    get_room_snapshot,
    join_room,
    calculate_analytics,
    settle_showdown,
    start_hand,
)


def table(count=3, small_blind=10, stacks=None):
    room = create_room("Rules Test", 1, "P1", max_players=max(2, count), small_blind=small_blind)
    for seat in range(1, count):
        join_room(room["room_id"], seat + 1, f"P{seat + 1}")
    if stacks:
        for player, stack in zip(room["players"], stacks):
            player["chips"] = stack
    return room


def act(room, action, amount=None):
    seat = room["current_turn"]
    assert seat is not None
    return apply_action(room["room_id"], room["players"][seat]["id"], action, amount)


def test_hand_rank_categories_and_tiebreaks():
    royal_flush = evaluate_best_hand(["As", "Ks", "Qs", "Js", "10s"])
    wheel = evaluate_best_hand(["As", "2h", "3d", "4c", "5s"])
    six_high = evaluate_best_hand(["2s", "3h", "4d", "5c", "6s"])
    quads = evaluate_best_hand(["Ah", "Ad", "Ac", "As", "Kc"])
    full_house = evaluate_best_hand(["Kh", "Kd", "Kc", "2s", "2h"])
    flush = evaluate_best_hand(["Ah", "Jh", "8h", "5h", "2h"])
    straight = evaluate_best_hand(["9s", "8h", "7d", "6c", "5s"])
    trips = evaluate_best_hand(["Qs", "Qh", "Qd", "Ac", "9s"])
    two_pair = evaluate_best_hand(["Js", "Jh", "4d", "4c", "As"])
    pair = evaluate_best_hand(["Ts", "Th", "Ad", "8c", "3s"])
    high_card = evaluate_best_hand(["As", "Kd", "Jh", "8c", "3s"])

    scores = [royal_flush, quads, full_house, flush, straight, trips, two_pair, pair, high_card]
    assert all(left > right for left, right in zip(scores, scores[1:]))
    assert wheel == (4, 5)
    assert six_high == (4, 6)
    assert evaluate_best_hand(["Ah", "Ad", "Ks", "Qd", "Jc"]) > evaluate_best_hand(["As", "Ac", "Qs", "Jd", "Tc"])
    assert evaluate_best_hand(["As", "Ah", "Kd", "Kc", "Qs"]) > evaluate_best_hand(["Ks", "Kh", "Qd", "Qc", "As"])


@pytest.mark.parametrize("cards", [[], ["As"] * 5, ["1s", "2s", "3s", "4s", "5s"], ["As", "Ks", "Qs", "Js"]])
def test_evaluator_rejects_invalid_or_incomplete_hands(cards):
    with pytest.raises(ValueError):
        evaluate_best_hand(cards)


def test_heads_up_blinds_and_big_blind_option():
    room = table(count=2)
    start_hand(room["room_id"])
    assert room["dealer_index"] == room["small_blind_index"] == 0
    assert room["big_blind_index"] == 1
    assert room["current_turn"] == 0
    assert room["pot"] == 30
    act(room, "call")
    assert room["current_turn"] == 1  # The big blind still gets to check or raise.
    assert room["phase"] == "preflop"
    act(room, "check")
    assert room["phase"] == "flop"
    assert room["current_turn"] == 1  # Post-flop action starts left of the button.


def test_short_stacks_post_partial_blinds_then_run_out_correctly():
    room = table(count=2, small_blind=1000)
    room["players"][0]["chips"] = 1000
    room["players"][1]["chips"] = 1000
    start_hand(room["room_id"])
    assert room["players"][0]["all_in"] is True
    assert room["players"][1]["all_in"] is True
    assert room["phase"] == "showdown"
    assert len(room["board"]) == 5
    assert room["pot"] == 0
    assert sum(player["chips"] for player in room["players"]) == 2000


def test_three_player_rounds_deal_burns_and_reach_showdown():
    room = table(count=3)
    start_hand(room["room_id"])
    assert room["current_turn"] == 0
    act(room, "call")
    act(room, "call")
    act(room, "check")
    assert room["phase"] == "flop" and len(room["board"]) == 3
    for expected_phase, board_size in [("turn", 4), ("river", 5)]:
        for _ in range(3):
            act(room, "check")
        assert room["phase"] == expected_phase
        assert len(room["board"]) == board_size
    for _ in range(3):
        act(room, "check")
    assert room["phase"] == "showdown"
    assert room["pot"] == 0
    assert sum(p["chips"] for p in room["players"]) == 3000


def test_minimum_raise_to_and_invalid_actions_leave_state_unchanged():
    room = table(count=3)
    start_hand(room["room_id"])
    actor = room["players"][room["current_turn"]]
    before = (actor["chips"], room["pot"], room["current_bet"], room["current_turn"])
    with pytest.raises(ValueError, match="Minimum raise"):
        act(room, "raise", 19)
    with pytest.raises(ValueError, match="Cannot check"):
        act(room, "check")
    with pytest.raises(ValueError, match="Invalid action"):
        act(room, "teleport")
    assert before == (actor["chips"], room["pot"], room["current_bet"], room["current_turn"])

    act(room, "raise", 20)
    assert room["current_bet"] == 40
    assert room["players"][0]["bet_this_round"] == 40


def test_short_all_in_does_not_reopen_raise_for_player_who_already_acted():
    room = table(count=3, stacks=[500, 45, 500])
    start_hand(room["room_id"])
    act(room, "raise", 20)
    act(room, "all_in")  # SB has 35 left: from 40 to 45, a short raise.
    assert room["current_bet"] == 45
    act(room, "call")  # BB calls 25.
    assert room["current_turn"] == 0
    assert room["players"][0]["raise_locked"] is True
    own_snapshot = get_room_snapshot(room, viewer_user_id=room["players"][0]["id"])
    assert own_snapshot["players"][0]["raise_locked"] is True
    assert own_snapshot["players"][1]["raise_locked"] is None
    with pytest.raises(ValueError, match="did not reopen"):
        act(room, "raise", 20)
    with pytest.raises(ValueError, match="did not reopen"):
        act(room, "all_in")
    act(room, "call")
    assert room["players"][0]["contributed"] == 45
    assert room["phase"] == "flop"


def test_multiple_short_all_ins_cumulatively_reopen_raise():
    room = table(count=4, stacks=[55, 60, 1000, 500])
    start_hand(room["room_id"])
    act(room, "raise", 20)  # Seat 3 raises to 40.
    act(room, "all_in")  # Seat 0 moves the bet to 55.
    assert room["players"][3]["raise_locked"] is True
    act(room, "all_in")  # Seat 1 moves it to 60; the two short raises total 20.
    assert room["players"][3]["raise_locked"] is False
    act(room, "call")  # Big blind calls to 60.
    assert room["current_turn"] == 3
    act(room, "raise", 20)
    assert room["current_bet"] == 80


def test_all_in_runout_builds_side_pots_and_preserves_every_chip():
    room = table(count=3, stacks=[100, 50, 100])
    start_hand(room["room_id"])
    act(room, "all_in")
    act(room, "all_in")
    act(room, "all_in")
    assert room["phase"] == "showdown"
    assert len(room["board"]) == 5
    assert room["pot"] == 0
    assert sum(p["chips"] for p in room["players"]) == 250
    dealt = room["board"] + [card for p in room["players"] for card in p["hole_cards"]]
    assert len(dealt) == len(set(dealt))


def test_all_in_call_is_not_marked_as_a_preflop_raise_and_replay_has_pot_steps():
    room = table(count=2, stacks=[50, 50])
    start_hand(room["room_id"])

    act(room, "all_in")  # The small blind shoves above the big blind.
    act(room, "all_in")  # The big blind can only call that shove.

    actions = [event for event in room["hand_history"] if event.get("action") == "all_in"]
    assert [event["is_aggressive"] for event in actions] == [True, False]
    pots = [event["pot"] for event in room["hand_history"]]
    assert pots == sorted(pots)
    assert pots[-1] == room["last_hand_summary"]["pot"] == 100


def test_side_pot_winner_does_not_win_chips_they_did_not_match():
    room = table(count=3)
    room["phase"] = "river"
    room["board"] = ["2c", "3d", "7h", "8s", "9c"]
    room["pot"] = 250
    room["hand_start_chips"] = 250
    room["players"][0].update(chips=0, contributed=100, in_hand=True, hole_cards=["Ks", "Kh"])
    room["players"][1].update(chips=0, contributed=50, in_hand=True, hole_cards=["As", "Ah"])
    room["players"][2].update(chips=0, contributed=100, in_hand=True, hole_cards=["Qs", "Qh"])

    pots = _build_side_pots(room["players"])
    assert [(pot["amount"], pot["eligible_ids"]) for pot in pots] == [(150, [1, 2, 3]), (100, [1, 3])]
    winners = settle_showdown(room)
    assert {winner["id"] for winner in winners} == {1, 2}
    assert [p["chips"] for p in room["players"]] == [100, 150, 0]
    assert sum(p["chips"] for p in room["players"]) == 250


def test_split_pot_distributes_odd_chip_by_seat_order():
    room = table(count=3)
    room["phase"] = "river"
    room["board"] = ["As", "Ks", "Qs", "Js", "Ts"]
    room["pot"] = 3
    room["hand_start_chips"] = 3
    for player, hole in zip(room["players"], [["2d", "3d"], ["4c", "5c"], ["6h", "7h"]]):
        player.update(chips=0, contributed=1, in_hand=True, hole_cards=hole)
    room["players"][2]["folded"] = True
    # The three-chip pot is tied between two players; the odd chip goes to seat 0.
    settle_showdown(room)
    assert [p["chips"] for p in room["players"]] == [2, 1, 0]
    assert sum(p["chips"] for p in room["players"]) == 3


def test_uncalled_excess_forms_a_single_winner_side_pot():
    room = table(count=2)
    room["phase"] = "river"
    room["board"] = ["2c", "3d", "7h", "8s", "9c"]
    room["pot"] = 170
    room["hand_start_chips"] = 170
    room["players"][0].update(chips=0, contributed=100, in_hand=True, hole_cards=["As", "Ah"])
    room["players"][1].update(chips=0, contributed=70, in_hand=True, hole_cards=["Ks", "Kh"])
    settle_showdown(room)
    assert room["players"][0]["chips"] == 170
    assert room["players"][1]["chips"] == 0
    assert room["last_hand_summary"]["pot"] == 170
    assert any(award["amount"] == 30 and award["pot_cap"] == 100
               for award in room["last_hand_summary"]["awards"])


def test_fold_awards_pot_without_showing_other_players_cards():
    room = table(count=2)
    start_hand(room["room_id"])
    actor = room["current_turn"]
    winner_id = room["players"][1 - actor]["id"]
    act(room, "fold")
    assert room["phase"] == "showdown"
    assert room["last_hand_summary"]["winner_ids"] == [winner_id]
    snapshot = get_room_snapshot(room, viewer_user_id=winner_id)
    folded = next(p for p in snapshot["players"] if p["folded"])
    assert folded["hole_cards"] == ["XX", "XX"]
    assert sum(p["chips"] for p in room["players"]) == 2000


def test_duplicate_click_is_rejected_atomically():
    room = table(count=2)
    start_hand(room["room_id"])
    actor_id = room["players"][room["current_turn"]]["id"]
    before_pot = room["pot"]

    def call_once():
        try:
            apply_action(room["room_id"], actor_id, "call")
            return "accepted"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call_once(), range(2)))
    assert results.count("accepted") == 1
    assert results.count("rejected") == 1
    assert room["pot"] == before_pot + 10


def test_reconnect_keeps_seat_stack_and_game_state():
    room = table(count=2)
    room["players"][1]["chips"] = 427
    join_room(room["room_id"], 2, "P2")
    assert len(room["players"]) == 2
    assert room["players"][1]["seat"] == 1
    assert room["players"][1]["chips"] == 427


def test_private_cards_are_hidden_except_at_showdown():
    room = table(count=2)
    room["phase"] = "flop"
    room["board"] = ["2c", "3d", "7h"]
    room["players"][0]["hole_cards"] = ["As", "Ah"]
    room["players"][1]["hole_cards"] = ["Ks", "Kh"]
    viewer_snapshot = get_room_snapshot(room, 1)
    assert viewer_snapshot["players"][1]["hole_cards"] == ["XX", "XX"]
    assert viewer_snapshot["players"][0]["raise_locked"] is False
    assert viewer_snapshot["players"][1]["raise_locked"] is None
    room["phase"] = "showdown"
    assert get_room_snapshot(room, 1)["players"][1]["hole_cards"] == ["Ks", "Kh"]


def test_server_turn_timer_auto_checks_and_refreshes_for_next_actor():
    room = table(count=2)
    assert room["turn_deadline_at"] is None
    start_hand(room["room_id"])
    original_deadline = room["turn_deadline_at"]
    assert original_deadline is not None

    act(room, "call")
    check_deadline = room["turn_deadline_at"]
    assert check_deadline > original_deadline
    assert room["current_bet"] == room["players"][room["current_turn"]]["bet_this_round"]

    assert expire_timed_out_turns(now=check_deadline + 0.01) == [room["room_id"]]
    assert room["phase"] == "flop"
    assert room["turn_deadline_at"] > check_deadline
    assert any("timed out; automatic check." in entry for entry in room["history"])


def test_server_turn_timer_auto_folds_when_call_is_owed_and_clears_deadline():
    room = table(count=2)
    start_hand(room["room_id"])
    expired_player = room["players"][room["current_turn"]]
    winner_id = room["players"][1 - room["current_turn"]]["id"]
    assert room["current_bet"] > expired_player["bet_this_round"]

    assert expire_timed_out_turns(now=room["turn_deadline_at"] + 0.01) == [room["room_id"]]
    assert room["phase"] == "showdown"
    assert room["last_hand_summary"]["winner_ids"] == [winner_id]
    assert room["turn_deadline_at"] is None
    assert any("timed out; automatic fold." in entry for entry in room["history"])


def test_expired_timeout_races_player_action_without_double_applying():
    room = table(count=2)
    start_hand(room["room_id"])
    actor = room["players"][room["current_turn"]]
    expired_at = room["turn_deadline_at"] + 0.001
    gate = threading.Barrier(2)

    def act_at_deadline():
        gate.wait()
        try:
            apply_action(room["room_id"], actor["id"], "call")
            return "accepted"
        except ValueError:
            return "rejected"

    def expire_at_deadline():
        gate.wait()
        return expire_timed_out_turns(now=expired_at)

    with ThreadPoolExecutor(max_workers=2) as pool:
        action_result = pool.submit(act_at_deadline)
        timeout_result = pool.submit(expire_at_deadline)
        action_status = action_result.result()
        expired = timeout_result.result()

    assert (action_status == "accepted" and expired == []) or (
        action_status == "rejected" and expired == [room["room_id"]]
    )
    assert sum(player["chips"] for player in room["players"]) + room["pot"] == room["hand_start_chips"]


def test_equity_estimates_are_valid_probabilities_and_are_published_off_lock():
    room = table(count=2)
    start_hand(room["room_id"])
    estimates = calculate_analytics(room)
    for player in room["players"]:
        values = estimates[player["username"]]
        assert all(0 <= values[key] <= 1 for key in ("win_probability", "tie_probability", "lose_probability", "equity"))
        assert sum(values[key] for key in ("win_probability", "tie_probability", "lose_probability")) == pytest.approx(1, abs=0.002)
        assert values["simulations"] == 1000
        assert 0 <= values["confidence95"] <= 1


def test_hand_analytics_reports_flush_outs_pot_odds_and_sample_count():
    room = table(count=2)
    hero = room["players"][0]
    hero["in_hand"] = True
    hero["hole_cards"] = ["As", "Ks"]
    room["players"][1]["in_hand"] = True
    room["phase"] = "flop"
    room["board"] = ["2s", "7s", "Jd"]
    room["pot"] = 100
    room["current_bet"] = 20
    hero["bet_this_round"] = 10

    stats = calculate_analytics(room)[hero["username"]]
    assert "flush draw" in stats["draws"]
    assert stats["outs"] == 9
    assert stats["pot_odds"] == pytest.approx(10 / 110, abs=0.001)
    assert stats["current_hand"] == "high card"
    assert stats["simulations"] == 1000
    assert stats["duration_ms"] > 0
    assert 0 <= stats["confidence95"] <= 1
    assert "two pair" in stats["possible_hands_ahead"]


def test_possible_hands_ahead_never_treats_the_royal_board_as_beatable():
    room = table(count=2)
    hero = room["players"][0]
    hero.update(in_hand=True, hole_cards=["2h", "3d"])
    room["players"][1].update(in_hand=True, hole_cards=["4h", "5d"])
    room["phase"] = "river"
    room["board"] = ["As", "Ks", "Qs", "Js", "Ts"]

    stats = calculate_analytics(room)[hero["username"]]

    assert stats["current_hand"] == "straight flush"
    assert stats["possible_hands_ahead"] == []


def test_showdown_equity_is_expected_share_for_a_board_tie():
    room = table(count=2)
    room["phase"] = "showdown"
    room["board"] = ["As", "Ks", "Qs", "Js", "Ts"]
    room["players"][0].update(in_hand=True, folded=False, hole_cards=["2h", "3d"])
    room["players"][1].update(in_hand=True, folded=False, hole_cards=["4h", "5d"])

    estimates = calculate_analytics(room)

    for player in room["players"]:
        stats = estimates[player["username"]]
        assert stats["win_probability"] == 0
        assert stats["tie_probability"] == 1
        assert stats["lose_probability"] == 0
        assert stats["equity"] == pytest.approx(0.5)


def test_start_hand_rejects_duplicate_start_and_broke_seats_are_skipped():
    room = table(count=3, stacks=[1000, 0, 1000])
    start_hand(room["room_id"])
    assert room["dealer_index"] == 0
    assert room["players"][1]["in_hand"] is False
    with pytest.raises(ValueError, match="already in progress"):
        start_hand(room["room_id"])


def test_randomized_hands_preserve_chip_total_and_reach_a_valid_end():
    rng = random.Random(72401)
    room = table(count=6, stacks=[300] * 6)
    initial_total = sum(player["chips"] for player in room["players"])
    for _hand in range(1000):
        start_hand(room["room_id"])
        actions = 0
        while room["phase"] != "showdown" and actions < 150:
            player = room["players"][room["current_turn"]]
            to_call = max(0, room["current_bet"] - player["bet_this_round"])
            if to_call:
                choices = ["call", "fold"]
                if not player["raise_locked"] or player["chips"] <= to_call:
                    choices.append("all_in")
                if player["chips"] >= to_call + room["last_full_raise"] and not player["raise_locked"]:
                    choices.append("raise")
                action = rng.choice(choices)
                amount = room["last_full_raise"] if action == "raise" else None
            else:
                choices = ["check"]
                if not player["raise_locked"]:
                    choices.append("all_in")
                if room["current_bet"]:
                    if player["chips"] >= room["last_full_raise"] and not player["raise_locked"]:
                        choices.append("raise")
                elif player["chips"] >= room["last_full_raise"]:
                    choices.append("bet")
                action = rng.choice(choices)
                amount = room["last_full_raise"] if action in {"bet", "raise"} else None
            apply_action(room["room_id"], player["id"], action, amount)
            actions += 1
            assert sum(p["chips"] for p in room["players"]) + room["pot"] == initial_total
        assert room["phase"] == "showdown", f"Hand {room['hand_number']} did not finish"
        assert room["pot"] == 0
        assert sum(p["chips"] for p in room["players"]) == initial_total
        assert sum(pot["amount"] for pot in _build_side_pots(room["players"])) == room["last_hand_summary"]["pot"]
        if len(room["board"]) == 5:
            cards = room["board"] + [card for p in room["players"] for card in p["hole_cards"]]
            assert len(cards) == len(set(cards))
        if min(player["chips"] for player in room["players"]) == 0:
            # Rebuy only to keep the randomized table playable; this starts a new table stack.
            for player in room["players"]:
                player["chips"] = 300
            initial_total = sum(player["chips"] for player in room["players"])
