"""
Event-sequence tests for the hotchocolate engine.

Each test drives the game with a scripted UI and asserts that every input
produces at most one state change (and exactly one UI notification where a
notification is expected), that unknown/dangling references are handled
without crashing, and that the main loop always terminates safely.

Run with: python3 -m unittest test_hotchocolate -v
"""

import os
import tempfile
import unittest

import hotchocolate.ui as ui
from hotchocolate.game import Game, GameNotRunningException


ROOMS_YAML = """
- !Room
    name: Study
    description: A quiet study.
    items:
        - !Item
          name: desk
          description: A plain white desk.
        - !Item
          name: pens
          article: some
          plural: True
          description: A collection of coloured pens.
        - !Item
          name: bed
          description: Surprisingly comfortable.
          takeable: False
    exits:
        - !Exit
          direction: west
          roomName: Hall
- !Room
    name: Hall
    description: A plain hallway.
    exits:
        - !Exit
          direction: east
          roomName: Study
    items:
        - !Item
          name: ping-pong ball
          description: Looks like a cat toy.
"""

# same rooms, but the Study has an extra exit pointing at a room that
# does not exist ("missing node")
DANGLING_YAML = ROOMS_YAML.replace(
    "roomName: Hall", "roomName: Hall\n        - !Exit\n"
    "          direction: north\n          roomName: Nowhere", 1)


class ScriptedUI(ui.AbstractUI):
    """A UI that replays a fixed script of inputs and records all output.

    Raises EOFError once the script is exhausted, which the game loop must
    treat as a safe end-of-input (no crash, no hang).
    """

    def __init__(self, inputs=()):
        self.inputs = list(inputs)
        self.outputs = []

    def getUserInput(self):
        if not self.inputs:
            raise EOFError
        return self.inputs.pop(0)

    def displayText(self, text):
        self.outputs.append(text)

    def askYesNo(self, question):
        self.outputs.append(question)
        return self.getUserInput().strip().lower() in ("y", "yes")


class GameTestCase(unittest.TestCase):
    def makeGame(self, inputs=(), yamlText=ROOMS_YAML):
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w") as f:
            f.write(yamlText)
        self.addCleanup(os.remove, path)
        game = Game(path, uiClass=lambda: ScriptedUI(inputs))
        game.running = True
        game.commandInterpreter = __import__(
            "hotchocolate.commands", fromlist=["CommandInterpreter"]
        ).CommandInterpreter(game)
        game.loadData()
        return game

    def parseAll(self, game):
        """Feed every scripted input through the interpreter, one at a time."""
        while game.ui.inputs:
            game.commandInterpreter.parse(game.ui.getUserInput())

    def stateSnapshot(self, game):
        return (
            game.currentRoom.name,
            sorted(game.inventory),
            {room: sorted(r.items) for room, r in game.rooms.items()},
        )


class EmptyCommandTest(GameTestCase):
    def test_empty_command_is_a_noop(self):
        game = self.makeGame(["", "   ", "\t"])
        before = self.stateSnapshot(game)
        self.parseAll(game)
        self.assertEqual(before, self.stateSnapshot(game))
        # no spurious "couldn't understand" output
        self.assertEqual([], game.ui.outputs)


class UnknownReferenceTest(GameTestCase):
    def test_unknown_item_examine_and_take(self):
        game = self.makeGame(["examine giraffe", "take giraffe"])
        before = self.stateSnapshot(game)
        self.parseAll(game)
        self.assertEqual(["That isn't here.", "That isn't here."],
                         game.ui.outputs)
        self.assertEqual(before, self.stateSnapshot(game))

    def test_unknown_direction_and_missing_args(self):
        game = self.makeGame(
            ["go", "examine", "take", "north", "go east", "west blah blah"])
        self.parseAll(game)
        self.assertEqual("Go where?", game.ui.outputs[0])
        self.assertEqual("Examine what?", game.ui.outputs[1])
        self.assertEqual("Take what?", game.ui.outputs[2])
        # Study has no north/east exit; extra words after a direction are
        # rejected. None of these may crash or move the player.
        self.assertEqual("You can't go that way.", game.ui.outputs[3])
        self.assertEqual("You can't go that way.", game.ui.outputs[4])
        self.assertIn("didn't understand", game.ui.outputs[5])
        self.assertEqual("Study", game.currentRoom.name)

    def test_dangling_exit_terminates_safely(self):
        # an exit whose target room is missing must not crash the game;
        # the player stays put and the game keeps running
        game = self.makeGame(["north", "look"], yamlText=DANGLING_YAML)
        self.parseAll(game)
        self.assertEqual("You can't go that way.", game.ui.outputs[0])
        self.assertEqual("Study", game.currentRoom.name)
        self.assertTrue(game.isRunning())
        self.assertIn("Study", game.ui.outputs[1])


class TakeTest(GameTestCase):
    def test_item_can_only_be_taken_once(self):
        game = self.makeGame(["take pens", "take pens"])
        self.parseAll(game)
        self.assertEqual(["Taken.", "You're already carrying that."],
                         game.ui.outputs)
        self.assertEqual(["pens"], sorted(game.inventory))
        self.assertNotIn("pens", game.rooms["Study"].items)

    def test_take_all_does_not_duplicate_inventory(self):
        game = self.makeGame(["take pens", "take all", "take all"])
        pensBefore = game.rooms["Study"].items["pens"]
        self.parseAll(game)
        # the already-carried pens must not be silently overwritten, and
        # only the remaining takeable item (the desk) is picked up
        self.assertIs(pensBefore, game.inventory["pens"])
        self.assertEqual(["desk", "pens"], sorted(game.inventory))
        self.assertEqual("There is nothing here to take.",
                         game.ui.outputs[2])

    def test_untakeable_item_stays_put(self):
        game = self.makeGame(["take bed"])
        self.parseAll(game)
        self.assertEqual(["You can't take that."], game.ui.outputs)
        self.assertIn("bed", game.rooms["Study"].items)
        self.assertEqual({}, game.inventory)


class RoomSwitchTest(GameTestCase):
    def test_old_room_objects_not_operable_after_moving(self):
        game = self.makeGame(
            ["west", "examine desk", "take desk", "east", "examine desk"])
        self.parseAll(game)
        # after moving to the Hall, the Study's desk is out of scope
        self.assertEqual("That isn't here.", game.ui.outputs[1])
        self.assertEqual("That isn't here.", game.ui.outputs[2])
        self.assertEqual({}, game.inventory)
        # moving back restores access - state stayed consistent
        self.assertIn("plain white desk", game.ui.outputs[4])
        self.assertIn("desk", game.rooms["Study"].items)


class NotificationTest(GameTestCase):
    def test_each_input_produces_exactly_one_notification(self):
        inputs = ["look", "west", "east", "take pens", "take pens", "north"]
        game = self.makeGame(inputs)
        for inp in inputs:
            before = len(game.ui.outputs)
            game.commandInterpreter.parse(inp)
            self.assertEqual(before + 1, len(game.ui.outputs),
                             "input %r should notify the UI exactly once" % inp)

    def test_look_is_a_pure_refresh(self):
        # a UI refresh must not consume or mutate game state
        game = self.makeGame(["look", "look"])
        before = self.stateSnapshot(game)
        game.commandInterpreter.parse("look")
        first = game.ui.outputs[-1]
        game.commandInterpreter.parse("look")
        self.assertEqual(first, game.ui.outputs[-1])
        self.assertEqual(before, self.stateSnapshot(game))


class TerminationTest(GameTestCase):
    def test_cyclic_rooms_and_quit_terminate(self):
        # Study <-> Hall is a cycle: jumping back and forth must not loop
        # forever (each move is a single, input-driven state change), and
        # quit must end the loop cleanly
        game = self.makeGame(["west", "east", "west", "east", "quit", "y"])
        game.displayCurrentRoom()  # emulate run()'s initial display
        game.mainLoop()
        self.assertFalse(game.isRunning())
        self.assertEqual([], game.ui.inputs)
        # 1 initial display + 4 moves + 1 quit question
        self.assertEqual(6, len(game.ui.outputs))
        self.assertEqual("Study", game.currentRoom.name)

    def test_exhausted_input_terminates(self):
        # when the input stream ends (EOF / Ctrl-D) the loop stops instead
        # of spinning or crashing
        game = self.makeGame(["west"])
        game.mainLoop()
        self.assertFalse(game.isRunning())
        self.assertEqual("Hall", game.currentRoom.name)

    def test_quit_refused_keeps_game_running(self):
        game = self.makeGame(["quit", "n", "look"])
        game.mainLoop()
        self.assertIn("Study", game.ui.outputs[-1])

    def test_commands_require_a_running_game(self):
        game = self.makeGame([])
        game.running = False
        with self.assertRaises(GameNotRunningException):
            game.commandInterpreter.parse("look")


if __name__ == "__main__":
    unittest.main()
