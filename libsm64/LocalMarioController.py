import builtins
from direct.directnotify import DirectNotifyGlobal
from direct.showbase.DirectObject import DirectObject
from direct.task import Task
from direct.task.TaskManagerGlobal import taskMgr
from direct.showbase.ShowBaseGlobal import globalClock
from libsm64 import SM64Globals

# Matches the libsm64-panda example controls
KEY_A = 'z'
KEY_B = 'x'
KEY_Z = 'c'
KEY_STICK = {'arrow_left': (1, 0), 'arrow_right': (-1, 0), 'arrow_up': (0, 1), 'arrow_down': (0, -1)}
KEY_CAM_LEFT = 'a'
KEY_CAM_RIGHT = 'd'
CAMERA_FOLLOW_SPEED = 60.0
CAMERA_TURN_SPEED = 120.0


class LocalMarioController(DirectObject):
    notify = DirectNotifyGlobal.directNotify.newCategory('LocalMarioController')

    def __init__(self, toon, mario, manager):
        self.toon = toon
        self.mario = mario
        self.manager = manager
        self.controlling = False
        self.keys = {}
        self.lastSentTick = -1
        self.lastSentAction = None
        self.lastSentAnim = None
        self.lastSentFlags = None
        self.taskName = toon.uniqueName('marioController')
        for key in [KEY_A, KEY_B, KEY_Z, KEY_CAM_LEFT, KEY_CAM_RIGHT] + list(KEY_STICK.keys()):
            self.keys[key] = False
            self.accept(key, self.__setKey, [key, True])
            self.accept(key + '-up', self.__setKey, [key, False])
        taskMgr.add(self.__update, self.taskName, sort=31)

    def __setKey(self, key, value):
        self.keys[key] = value

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

    def releaseControls(self):
        if not self.controlling:
            return
        self.controlling = False
        self.mario.setControllerInput(0, 0, 0, 0, 0)
        toon = self.toon
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

        dt = globalClock.getDt()
        if self.__chatIsActive():
            stickX = stickY = 0
            a = b = z = camLeft = camRight = False
        else:
            stickX = sum(KEY_STICK[k][0] for k in KEY_STICK if self.keys[k])
            stickY = sum(KEY_STICK[k][1] for k in KEY_STICK if self.keys[k])
            a, b, z = self.keys[KEY_A], self.keys[KEY_B], self.keys[KEY_Z]
            camLeft, camRight = self.keys[KEY_CAM_LEFT], self.keys[KEY_CAM_RIGHT]
        mario.setControllerInput(stickX, stickY, a, b, z)
        mario.setCameraPos(builtins.base.camera.getPos(render))

        # The hidden toon node follows Mario, so the Toontown camera and nametag follow him too
        marioPos = mario.getPandaPos()
        toon.setPos(render, marioPos)
        self.manager.recenterIfNeeded(marioPos)
        heading = toon.getH(render)
        if camLeft:
            heading += CAMERA_TURN_SPEED * dt
        if camRight:
            heading -= CAMERA_TURN_SPEED * dt
        if (stickX or stickY) and mario.state.forwardVelocity > 8.0:
            diff = (mario.getHeading() - heading + 180.0) % 360.0 - 180.0
            step = CAMERA_FOLLOW_SPEED * dt
            heading += max(-step, min(step, diff))
        toon.setH(render, heading)

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
