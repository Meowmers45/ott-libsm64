import builtins
from direct.directnotify import DirectNotifyGlobal
from direct.showbase.DirectObject import DirectObject
from direct.task import Task
from direct.task.TaskManagerGlobal import taskMgr
from direct.showbase.MessengerGlobal import messenger
from panda3d.core import KeyboardButton
from libsm64 import SM64Globals

# Keys are polled (not event-driven) so held modifiers like Ctrl never swallow the arrow keys
BUTTON_A = (KeyboardButton.control(), KeyboardButton.lcontrol(), KeyboardButton.rcontrol())  # jump
BUTTON_B = (KeyboardButton._del(),)  # punch / dive
BUTTON_Z = (KeyboardButton.asciiKey('c'),)  # crouch
STICK_BUTTONS = ((KeyboardButton.left(), (1, 0)), (KeyboardButton.right(), (-1, 0)),
                 (KeyboardButton.up(), (0, 1)), (KeyboardButton.down(), (0, -1)),
                 (KeyboardButton.asciiKey('a'), (1, 0)), (KeyboardButton.asciiKey('d'), (-1, 0)),
                 (KeyboardButton.asciiKey('w'), (0, 1)), (KeyboardButton.asciiKey('s'), (0, -1)))
KEY_CHAT = 't'
CAMERA_DISTANCE = SM64Globals.CAMERA_DISTANCE
CAMERA_HEIGHT = SM64Globals.CAMERA_HEIGHT
CAMERA_LOOK_HEIGHT = 2.6  # roughly Mario's head


class LocalMarioController(DirectObject):
    notify = DirectNotifyGlobal.directNotify.newCategory('LocalMarioController')

    def __init__(self, toon, mario, manager):
        self.toon = toon
        self.mario = mario
        self.manager = manager
        self.controlling = False
        self.restoreSmartCamera = False
        self.savedNoSleep = 0
        self.lastSentTick = -1
        self.lastSentAction = None
        self.lastSentAnim = None
        self.lastSentFlags = None
        self.taskName = toon.uniqueName('marioController')
        self.accept(KEY_CHAT, self.__openChat)
        taskMgr.add(self.__update, self.taskName, sort=31)

    def __anyDown(self, buttons):
        mw = builtins.base.mouseWatcherNode
        return any(mw.isButtonDown(b) for b in buttons)

    def __readKeyboard(self):
        stickX = stickY = 0
        for button, (dx, dy) in STICK_BUTTONS:
            if self.__anyDown((button,)):
                stickX += dx
                stickY += dy
        return stickX, stickY, self.__anyDown(BUTTON_A), self.__anyDown(BUTTON_B), self.__anyDown(BUTTON_Z)

    def __getChatEntry(self):
        chatMgr = getattr(self.toon, 'chatMgr', None)
        inputNormal = getattr(chatMgr, 'chatInputNormal', None)
        return getattr(inputNormal, 'chatEntry', None)

    def __suppressTypeToChat(self):
        # Toontown opens the chat box on any keystroke ("background focus"); keep the keyboard for Mario
        entry = self.__getChatEntry()
        if entry is not None and entry['backgroundFocus']:
            entry['backgroundFocus'] = 0

    def __restoreTypeToChat(self):
        chatMgr = getattr(self.toon, 'chatMgr', None)
        entry = self.__getChatEntry()
        if entry is None or not getattr(chatMgr, 'wantBackgroundFocus', 0):
            return
        if chatMgr.fsm.getCurrentState().getName() == 'mainMenu':
            entry['backgroundFocus'] = 1

    def __openChat(self):
        if self.controlling and not self.__chatIsActive():
            messenger.send('enterNormalChat')

    def destroy(self):
        self.releaseControls()
        self.ignoreAll()
        taskMgr.remove(self.taskName)
        self.toon = None
        self.mario = None

    def grabControls(self):
        if self.controlling:
            return
        self.controlling = True
        toon = self.toon
        toon.controlManager.disable()
        toon.controlManager.collisionsOff()
        # keep the event sphere alive so cogs, doors and tunnels still react to Mario
        walk = self.__getWalkControls()
        if walk is not None:
            builtins.base.cTrav.addCollider(walk.cEventSphereNodePath, walk.event)
        toon.stopGlitchKiller()
        pos = toon.getPos(builtins.render)
        if not self.manager.recenterIfNeeded(pos):
            self.manager.loadSurfaces()
        self.mario.warpTo(pos)
        self.mario.spawnPos = pos
        self.mario.setFaceAngle(SM64Globals.headingToFaceAngle(toon.getH(builtins.render)))
        self.__suppressTypeToChat()
        # take over the camera: it sits behind Mario's head no matter what Toontown's smart camera wants
        self.restoreSmartCamera = bool(getattr(toon, '_smartCamEnabled', False))
        if self.restoreSmartCamera:
            toon.stopUpdateSmartCamera()
        self.__placeCamera()

    def __placeCamera(self):
        toon = self.toon
        camera = builtins.base.camera
        if camera.getParent() != toon:
            camera.reparentTo(toon)
        camera.setPos(0, -CAMERA_DISTANCE, CAMERA_HEIGHT)
        camera.lookAt(toon, 0, 0, CAMERA_LOOK_HEIGHT)

    def releaseControls(self):
        if not self.controlling:
            return
        self.controlling = False
        self.mario.setControllerInput(0, 0, 0, 0, 0)
        self.__restoreTypeToChat()
        toon = self.toon
        if toon is not None and not toon.isEmpty():
            toon.noSleep = self.savedNoSleep
            toon.wakeUp()
        if self.restoreSmartCamera and toon is not None and not toon.isEmpty() and not toon._smartCamEnabled:
            toon.startUpdateSmartCamera()
        self.restoreSmartCamera = False
        walk = self.__getWalkControls()
        if walk is not None:
            builtins.base.cTrav.removeCollider(walk.cEventSphereNodePath)
        if toon is not None and not toon.isEmpty() and toon.avatarControlsEnabled:
            toon.controlManager.enable()
            toon.controlManager.collisionsOn()
            toon.startGlitchKiller()

    def __getWalkControls(self):
        toon = self.toon
        if toon is None or toon.isEmpty():
            return None
        walk = toon.controlManager.controls.get('walk')
        if walk is None or not hasattr(walk, 'cEventSphereNodePath'):
            return None
        return walk

    def __chatIsActive(self):
        chatMgr = getattr(self.toon, 'chatMgr', None)
        if chatMgr is None or not hasattr(chatMgr, 'fsm'):
            return False
        return chatMgr.fsm.getCurrentState().getName() != 'mainMenu'

    def __update(self, task):
        toon, mario = self.toon, self.mario
        if toon is None or mario is None or not mario.isValid():
            return Task.done
        render = builtins.render
        if not self.controlling:
            mario.warpTo(toon.getPos(render))
            return Task.cont

        if self.__chatIsActive():
            stickX = stickY = 0
            a = b = z = False
        else:
            self.__suppressTypeToChat()
            stickX, stickY, a, b, z = self.__readKeyboard()
        # keyboard drives Mario only: make sure nothing re-enabled the Toon's walk controls
        if toon.controlManager.isEnabled:
            toon.controlManager.disable()
        if stickX or stickY or a or b or z:
            toon.wakeUp()
        if getattr(toon, 'sleepFlag', 0):
            toon.wakeUp()
        mario.setControllerInput(stickX, stickY, a, b, z)
        mario.setCameraPos(builtins.base.camera.getPos(render))

        # The hidden toon node follows Mario, so the Toontown camera and nametag follow him too.
        # Heading is locked to Mario's facing: the camera always sits behind him.
        marioPos = mario.getPandaPos()
        toon.setPos(render, marioPos)
        toon.setH(render, mario.getHeading())
        self.__placeCamera()
        self.manager.recenterIfNeeded(marioPos)

        self.__maybeSendNetState()
        return Task.cont

    def __maybeSendNetState(self):
        mario = self.mario
        if mario.tickCount == self.lastSentTick:
            return
        state = mario.state
        changed = state.action != self.lastSentAction or state.animID != self.lastSentAnim or \
            state.flags != self.lastSentFlags
        if not changed and mario.tickCount - self.lastSentTick < SM64Globals.NET_SEND_EVERY_TICKS:
            return
        self.lastSentTick = mario.tickCount
        self.lastSentAction = state.action
        self.lastSentAnim = state.animID
        self.lastSentFlags = state.flags
        self.toon.d_setMarioState(*mario.getNetState())
