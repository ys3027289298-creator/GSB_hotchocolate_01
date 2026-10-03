import hotchocolate.ui as ui
import hotchocolate.worldobjects as worldobjects

class GameNotRunningException(Exception):
	def __init__(self, msg=None):
		if msg is None:
			msg = "A Game instance is not currently running."
		super(GameNotRunningException, self).__init__(msg)

import hotchocolate.commands as commands
import yaml

class Game():
	def __init__(self, roomFilePath, uiClass=ui.CommandLineUI):
		self.running = False
		self.currentRoom = None
		self.rooms = {}
		self.ui = uiClass()
		self.roomFilePath = roomFilePath
		self.inventory = {}

	def isRunning(self):
		return self.running

	def stop(self):
		self.running = False

	def loadData(self):
		with open(self.roomFilePath) as f:
			roomsAsList = yaml.safe_load(f)

		# make a dictionary from the room list, with the room name as the key
		for room in roomsAsList:
			self.rooms[room.name] = room

		self.currentRoom = roomsAsList[0] #TODO: make this configurable from file

	def mainLoop(self):
		while self.isRunning():
			try:
				inp = self.ui.getUserInput()
			except (EOFError, KeyboardInterrupt):
				# input stream ended (eg. Ctrl-D): terminate safely
				self.stop()
				break
			self.commandInterpreter.parse(inp)

	def displayCurrentRoom(self):
		roomDesc = self.currentRoom.outputText()
		self.ui.displayText(roomDesc)

	def run(self):
		self.running = True
		self.commandInterpreter = commands.CommandInterpreter(self)
		self.loadData()
		self.displayCurrentRoom()
		self.mainLoop()

	def getItem(self, itemName):
		if itemName in self.inventory:
			item = self.inventory[itemName]
		else:
			# it's not in our inventory, so check the current room
			item = self.currentRoom.getItem(itemName)

		return item

	def removeItem(self, itemName):
		if itemName in self.inventory:
			del self.inventory[itemName]
		else:
			self.currentRoom.removeItem(itemName)

	def addToInventory(self, item):
		if item.name in self.inventory:
			# never silently replace an already carried item
			return False
		self.inventory[item.name] = item
		return True
