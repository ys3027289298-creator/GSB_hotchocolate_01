import hotchocolate.game

# Note: this module is imported by hotchocolate.game, so we cannot do
# ``from hotchocolate.game import GameNotRunningException`` here - the name
# may not exist yet at import time. Referencing it through the module at
# call time is safe regardless of import order.

class CommandInterpreter():
	"""
	Parses user input and executes appropriate command, if any.

	:param game: object representing currently running game
	:type game: Game
	:param commandDict: map from a command's text to the function that text
		should trigger. Will use the commands implemented in BasicCommands by
		default.
	:type commandDict: dict(string, function)
	"""
	def __init__(self, game, commandDict=None):
		self.game = game
		if commandDict is None:
			self.commandDict = BasicCommands.basicCommandDict
		else:
			self.commandDict = commandDict

	def parse(self, inp):
		"""
		Very simple parser for commands. Will look for a known command at the
			beginning of the input, and execute the corresponding function (if
			this exists) with the remaining input as arguments

		:param inp: the input to parser
		:type inp: string
		"""
		if inp is None or not inp.strip():
			# an empty command is a no-op: it must not be reported as an
			# unknown command and it must not change any game state
			return

		wordList = inp.split()

		verbSoFar = ""
		verbIdx = -1
		for word in wordList:
			if verbSoFar + word not in self.commandDict:
				break
			verbSoFar += word
			verbIdx += 1

		if verbIdx == -1:
			# didn't recognise verb
			self.game.ui.displayText("I couldn't understand that.")
			return

		verb = verbSoFar

		if verbIdx == (len(wordList) -1):
			# no words apart from verb in command, so no command has no
			# arguments that need to be passed to its parser function
			self.commandDict[verb](self.game, verb)
		else:
			args = wordList[verbIdx+1:]
			self.commandDict[verb](self.game, verb, args)

class BasicCommands():
	"""
	Container class for implementations of some basic, core commands.
	"""

	def look(game, verb):
		"""
		Displays the room text

		:param game: the object representing the game
		:type game: Game
		:param verb: the verb the command was called with
		:type verb: string
		"""
		if not game.isRunning():
			raise hotchocolate.game.GameNotRunningException()
		else:
			game.displayCurrentRoom()

	def go(game, verb, args=[]):
		"""
		Moves the player into an adjacent room

		Can be called with ``go <direction>`` or just ``<direction>``.
		Also recognises common abbreviations of directions like "ne" (northeast)
		and "d" (down).

		:param game: the object representing the game
		:type game: Game
		:param verb: the verb the command was called with
		:type verb: string
		:param args: the arguments the command was called with
		:type args: list(string)
		"""
		if not game.isRunning():
			raise hotchocolate.game.GameNotRunningException()

		if verb == "go": # there is a "go" in front of the direction
			if len(args) == 0:
				game.ui.displayText("Go where?")
				return
			elif len(args) > 1:
				game.ui.displayText("I understood that as far as you wanting to"
					"go somewhere, but I didn't recognise the direction.")
				return
			else:
				direction = args[0]
		else: # the input was just a direction
			direction = verb
			if len(args) > 0:
				game.ui.displayText("I understood that as far as you wanting to"
					"go {}, but I didn't understand what you said after that."
					" Try just typing in \"{}\"".format(direction, direction))
				return

		if direction == "n":
			direction = "north"
		elif direction == "s":
			direction = "south"
		elif direction == "e":
			direction = "east"
		elif direction == "w":
			direction = "west"
		elif direction == "ne":
			direction = "northeast"
		elif direction == "se":
			direction = "southeast"
		elif direction == "sw":
			direction = "southwest"
		elif direction == "ne":
			direction = "northeast"
		elif direction == "u":
			direction = "up"
		elif direction == "d":
			direction = "down"

		roomName = None
		for e in game.currentRoom.exits:
			if e.direction == direction:
				roomName = e.roomName
				break

		if roomName is None or roomName not in game.rooms:
			# either there is no exit in that direction, or the exit points
			# at a room that doesn't exist - either way, stay put instead
			# of crashing
			game.ui.displayText("You can't go that way.")
			return
		else:
			game.currentRoom = game.rooms[roomName]
			game.displayCurrentRoom()

	def examine(game, verb, args=[]):
		if not game.isRunning():
			raise hotchocolate.game.GameNotRunningException()

		if len(args) == 0:
			game.ui.displayText("Examine what?")
			return

		itemName = " ".join(args)
		item = game.getItem(itemName)

		if item is None:
			game.ui.displayText("That isn't here.")
		else:
			game.ui.displayText(item.outputText())

	def take(game, verb, args=[]):
		if not game.isRunning():
			raise hotchocolate.game.GameNotRunningException()

		if len(args) == 0:
			game.ui.displayText("Take what?")
			return

		itemName = " ".join(args)

		if itemName == "all":
			# we're going to be removing items from this dictionary, so we need
			# to copy it so we can iterate through them safely
			items = game.currentRoom.items.copy()
			tookAnything = False
			for name, item in items.items():
				if item.takeable:
					if name in game.inventory:
						# already carrying an item with this name - leave
						# the room's copy alone rather than silently
						# replacing the one in the inventory
						continue
					game.currentRoom.removeItem(name)
					game.addToInventory(item)
					tookAnything = True
			if tookAnything:
				game.ui.displayText("Taken.")
			else:
				game.ui.displayText("There is nothing here to take.")
			return

		item = game.getItem(itemName)
		if item is None:
			game.ui.displayText("That isn't here.")
		elif item.name in game.inventory:
			game.ui.displayText("You're already carrying that.")
		elif item.takeable == False:
			game.ui.displayText("You can't take that.")
		else:
			game.removeItem(item.name)
			game.addToInventory(item)
			game.ui.displayText("Taken.")

	def quit(game, verb):
		assent = game.ui.askYesNo("Do you really want to quit?")
		if assent:
			# flag-based shutdown: lets mainLoop terminate cleanly (and lets
			# non-command-line UIs and tests observe the end of the game)
			# instead of killing the whole process with sys.exit()
			game.running = False

	basicCommandDict = {"look": look,
				"l": look,
				"north": go,
				"n": go,
				"east": go,
				"e": go,
				"south": go,
				"s": go,
				"west": go,
				"w": go,
				"northeast": go,
				"ne": go,
				"southeast": go,
				"se": go,
				"southwest": go,
				"sw": go,
				"northwest": go,
				"nw": go,
				"up": go,
				"u": go,
				"down": go,
				"d": go,
				"go": go,
				"examine": examine,
				"x": examine,
				"take": take,
				"quit": quit,
				"q": quit
				}
