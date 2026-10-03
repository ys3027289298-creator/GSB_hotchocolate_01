"""
Event-sequence tests for the hotchocolate engine.

Each test feeds a scripted sequence of input events into a Game and verifies
that every input produces at most one state change and one notification, and
that malformed input, dangling exits and exit loops terminate safely.
"""
import os
import unittest
from collections import deque

from hotchocolate.game import Game, GameNotRunningException
from hotchocolate.commands import CommandInterpreter
from hotchocolate.ui import AbstractUI

ROOMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "test_rooms.yaml")


class ScriptedUI(AbstractUI):
    """
    Plays back a fixed sequence of input events and records, per input event,
    exactly which texts the engine displayed in response.
    """

    def __init__(self, inputs, yesNoAnswers=()):
        self._inputs = deque(inputs)
        self._yesNoAnswers = deque(yesNoAnswers)
        # list of (input, [texts displayed in response]); an input of None
        # marks output produced before the first input event
        self.turns = []
        self._currentOutputs = None

    def beginTurn(self, inp):
        self._currentOutputs = []
        self.turns.append((inp, self._currentOutputs))

    def getUserInput(self):
        if not self._inputs:
            # event sequence exhausted: the game must terminate safely
            raise EOFError
        inp = self._inputs.popleft()
        self.beginTurn(inp)
        return inp

    def displayText(self, text):
        if self._currentOutputs is None:
            self.turns.append((None, [text]))
        else:
            self._currentOutputs.append(text)

    def askYesNo(self, question):
        if self._yesNoAnswers:
            return self._yesNoAnswers.popleft()
        return True


def playGame(inputs, yesNoAnswers=()):
    """Runs a full game over a scripted event sequence."""
    ui = ScriptedUI(inputs, yesNoAnswers)
    game = Game(ROOMS_PATH, uiClass=lambda: ui)
    game.run()
    return game, ui


def makeGame():
    """Creates a running game whose interpreter can be driven step by step."""
    ui = ScriptedUI([])
    game = Game(ROOMS_PATH, uiClass=lambda: ui)
    game.running = True
    game.commandInterpreter = CommandInterpreter(game)
    game.loadData()
    return game, ui


def snapshot(game):
    return (game.currentRoom.name,
            tuple(sorted(game.inventory)),
            tuple(sorted(game.currentRoom.items)))


def step(game, ui, inp):
    """Feeds one input event and returns (before, outputs, after)."""
    before = snapshot(game)
    ui.beginTurn(inp)
    game.commandInterpreter.parse(inp)
    return before, ui.turns[-1][1], snapshot(game)


def outputsFor(ui, inp):
    return [outputs for turnInp, outputs in ui.turns if turnInp == inp]


class EmptyAndUnknownInputTest(unittest.TestCase):
    def test_empty_command_produces_no_output_and_no_state_change(self):
        game, ui = playGame(["", "   ", "look"])
        for inp in ("", "   "):
            for outputs in outputsFor(ui, inp):
                self.assertEqual(outputs, [])
        # the game is still in the initial state afterwards
        self.assertEqual(snapshot(game), ("Start", (), ("candle", "coin")))

    def test_unknown_verb_produces_single_error_and_no_state_change(self):
        game, ui = playGame(["frobnicate the candle"])
        self.assertEqual(outputsFor(ui, "frobnicate the candle"),
                         [["I couldn't understand that."]])
        self.assertEqual(snapshot(game), ("Start", (), ("candle", "coin")))

    def test_unknown_item_reference(self):
        game, ui = playGame(["examine telescope", "take telescope"])
        self.assertEqual(outputsFor(ui, "examine telescope"),
                         [["That isn't here."]])
        self.assertEqual(outputsFor(ui, "take telescope"),
                         [["That isn't here."]])
        self.assertEqual(snapshot(game), ("Start", (), ("candle", "coin")))

    def test_missing_arguments_do_not_crash(self):
        game, ui = playGame(["examine", "take", "go"])
        self.assertEqual(outputsFor(ui, "examine"), [["Examine what?"]])
        self.assertEqual(outputsFor(ui, "take"), [["Take what?"]])
        self.assertEqual(outputsFor(ui, "go"), [["Go where?"]])
        self.assertEqual(snapshot(game), ("Start", (), ("candle", "coin")))


class InventoryTest(unittest.TestCase):
    def test_item_cannot_be_taken_twice(self):
        game, ui = playGame(["take coin", "take coin"])
        self.assertEqual(outputsFor(ui, "take coin"),
                         [["Taken."], ["You're already carrying that."]])
        self.assertEqual(snapshot(game), ("Start", ("coin",), ("candle",)))

    def test_take_all_does_not_duplicate_inventory(self):
        game, ui = playGame(["take coin", "take all"])
        # coin is already carried: take all must not duplicate or replace it
        self.assertEqual(snapshot(game), ("Start", ("coin",), ("candle",)))

    def test_untakeable_item_stays_in_room(self):
        game, ui = playGame(["take candle"])
        self.assertEqual(outputsFor(ui, "take candle"),
                         [["You can't take that."]])
        self.assertEqual(snapshot(game), ("Start", (), ("candle", "coin")))


class RoomSwitchingTest(unittest.TestCase):
    def test_objects_from_previous_room_are_not_accessible(self):
        game, ui = playGame(["east", "examine candle", "take candle",
                             "examine coin", "take coin"])
        for inp in ("examine candle", "take candle",
                    "examine coin", "take coin"):
            self.assertEqual(outputsFor(ui, inp), [["That isn't here."]])
        self.assertEqual(snapshot(game), ("East Room", (), ("key",)))

    def test_current_room_objects_remain_accessible(self):
        game, ui = playGame(["east", "examine key", "take key"])
        self.assertEqual(outputsFor(ui, "examine key"), [["A brass key."]])
        self.assertEqual(outputsFor(ui, "take key"), [["Taken."]])
        self.assertEqual(snapshot(game), ("East Room", ("key",), ()))

    def test_carried_items_travel_with_player(self):
        game, ui = playGame(["take coin", "east", "examine coin"])
        self.assertEqual(outputsFor(ui, "examine coin"), [["A shiny coin."]])
        self.assertEqual(snapshot(game), ("East Room", ("coin",), ("key",)))


class SafeTerminationTest(unittest.TestCase):
    def test_exit_to_missing_room_stays_put_and_game_continues(self):
        # East Room has an exit "down" to "Nowhere", which is not defined
        game, ui = playGame(["east", "down", "look"])
        self.assertEqual(outputsFor(ui, "down"), [["That way leads nowhere."]])
        self.assertEqual(game.currentRoom.name, "East Room")
        # the game is still alive: "look" produced the room text afterwards
        self.assertEqual(len(outputsFor(ui, "look")), 1)
        self.assertIn("East Room", outputsFor(ui, "look")[0][0])

    def test_exit_loop_terminates_with_one_notification_per_move(self):
        # Start <-> East Room form a cycle; each hop must display the new
        # room exactly once and the sequence must terminate at end of input
        moves = ["east", "west", "east", "west"]
        game, ui = playGame(moves)
        for inp, outputs in ui.turns:
            if inp in moves:
                self.assertEqual(len(outputs), 1, inp)
        self.assertEqual(game.currentRoom.name, "Start")
        self.assertFalse(game.isRunning())

    def test_game_stops_when_input_stream_ends(self):
        game, ui = playGame(["look"])
        self.assertFalse(game.isRunning())

    def test_quit_stops_the_main_loop(self):
        game, ui = playGame(["quit", "look"], yesNoAnswers=[True])
        self.assertFalse(game.isRunning())
        # "look" was never consumed after the game stopped
        self.assertEqual(outputsFor(ui, "look"), [])

    def test_declining_quit_keeps_game_running(self):
        game, ui = playGame(["quit", "look"], yesNoAnswers=[False])
        self.assertEqual(len(outputsFor(ui, "look")), 1)

    def test_command_after_stop_raises_game_not_running(self):
        game, ui = makeGame()
        game.stop()
        with self.assertRaises(GameNotRunningException):
            game.commandInterpreter.parse("look")

    def test_running_flag_is_not_shared_between_instances(self):
        game1, _ = makeGame()
        game2, _ = makeGame()
        game1.stop()
        self.assertFalse(game1.isRunning())
        self.assertTrue(game2.isRunning())


class SingleStateChangeTest(unittest.TestCase):
    """
    Drives the interpreter one input at a time and verifies that each input
    produces exactly one state change (or none, for read-only commands) and
    at most one notification.
    """

    def test_each_input_produces_exactly_one_state_change(self):
        game, ui = makeGame()

        # take: inventory gains coin, room loses coin, one notification
        before, outputs, after = step(game, ui, "take coin")
        self.assertEqual(outputs, ["Taken."])
        self.assertEqual(after, ("Start", ("coin",), ("candle",)))

        # examine: read-only, state identical before and after
        before, outputs, after = step(game, ui, "examine coin")
        self.assertEqual(outputs, ["A shiny coin."])
        self.assertEqual(before, after)

        # move: only the current room changes, one room display
        before, outputs, after = step(game, ui, "east")
        self.assertEqual(len(outputs), 1)
        self.assertIn("East Room", outputs[0])
        self.assertEqual(after, ("East Room", ("coin",), ("key",)))

        # look: refresh must not consume or alter state
        before, outputs, after = step(game, ui, "look")
        self.assertEqual(len(outputs), 1)
        self.assertEqual(before, after)

        # take in the new room: exactly one inventory change
        before, outputs, after = step(game, ui, "take key")
        self.assertEqual(outputs, ["Taken."])
        self.assertEqual(after, ("East Room", ("coin", "key"), ()))

        # moving back: cycle terminates, state consistent
        before, outputs, after = step(game, ui, "west")
        self.assertEqual(len(outputs), 1)
        self.assertEqual(after, ("Start", ("coin", "key"), ("candle",)))

        # every input produced at most one notification
        for inp, outputs in ui.turns:
            self.assertLessEqual(len(outputs), 1, inp)


if __name__ == "__main__":
    unittest.main()
