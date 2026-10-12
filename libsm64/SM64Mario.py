import builtins
import ctypes as ct
from direct.directnotify import DirectNotifyGlobal
from panda3d.core import NodePath, GeomNode, Geom, GeomVertexFormat, GeomVertexArrayFormat, GeomVertexData, \
    GeomTriangles, InternalName, OmniBoundingVolume, Point3
from libsm64 import SM64Bindings, SM64Globals


class SM64Mario(NodePath):
    notify = DirectNotifyGlobal.directNotify.newCategory('SM64Mario')
    vformat = None

    @classmethod
    def getVertexFormat(cls):
        if cls.vformat is None:
            fmt = GeomVertexFormat()
            for name, count, contents in ((InternalName.getVertex(), 3, Geom.CPoint),
                                          (InternalName.getNormal(), 3, Geom.CNormal),
                                          (InternalName.getColor(), 3, Geom.CColor),
                                          (InternalName.getTexcoord(), 2, Geom.CTexcoord)):
                arr = GeomVertexArrayFormat()
                arr.addColumn(name, count, Geom.NTFloat32, contents)
                fmt.addArray(arr)
            cls.vformat = GeomVertexFormat.registerFormat(fmt)
        return cls.vformat

    def __init__(self, manager, pandaPos, isLocal):
        self.manager = manager
        self.lib = manager.lib
        self.isLocal = isLocal
        self.marioId = -1
        self.tickCount = 0
        self.inputs = SM64Bindings.SM64MarioInputs()
        self.state = SM64Bindings.SM64MarioState()
        self.geo = SM64Bindings.SM64MarioGeometryBuffers()
        self.spawnPos = Point3(pandaPos)
        self.netState = None
        self.netStateDirty = False
        self.lastAppliedAction = None
        self.lastAppliedAnim = None
        self.followNode = None
        self.inWater = False
        self.lastWaterLevel = SM64Globals.NO_WATER_LEVEL

        self.geomNode = GeomNode('mario')
        NodePath.__init__(self, self.geomNode)
        x, y, z = manager.toSM64(pandaPos)
        self.marioId = self.lib.sm64_mario_create(x, y + 1.0, z)
        if self.marioId < 0:
            self.notify.warning('Could not create Mario at %s (no floor)' % pandaPos)
            return
        self.__buildGeom()
        self.reparentTo(builtins.render)
        self.setMat(manager.getConversionMat())
        self.setTexture(manager.texture, 1)
        if manager.shader is not None:
            self.setShader(manager.shader)
        self.setLightOff(1)
        self.geomNode.setBounds(OmniBoundingVolume())
        self.geomNode.setFinal(True)
        manager.registerMario(self)

    def isValid(self):
        return self.marioId >= 0

    def __buildGeom(self):
        vdata = GeomVertexData('mario-vertex', self.getVertexFormat(), Geom.UHDynamic)
        vdata.setNumRows(SM64Bindings.SM64_GEO_MAX_TRIANGLES * 3)
        prim = GeomTriangles(Geom.UHDynamic)
        prim.closePrimitive()
        self.geom = Geom(vdata)
        self.geom.addPrimitive(prim)
        self.geomNode.addGeom(self.geom)

    def __updateGeom(self):
        vdata = self.geom.modifyVertexData()
        for idx, buf in enumerate((self.geo.positionData, self.geo.normalData, self.geo.colorData, self.geo.uvData)):
            vdata.modifyArray(idx).modifyHandle().setData(bytes(buf))
        prim = GeomTriangles(Geom.UHDynamic)
        prim.addConsecutiveVertices(0, int(self.geo.numTrianglesUsed) * 3)
        prim.closePrimitive()
        self.geom.setPrimitive(0, prim)

    # Public state
    def getPandaPos(self):
        p = self.state.position
        return self.manager.fromSM64(p[0], p[1], p[2])

    def getHeading(self):
        return SM64Globals.faceAngleToHeading(self.state.faceAngle)

    def warpTo(self, pandaPos, resetVelocity=True):
        x, y, z = self.manager.toSM64(pandaPos)
        self.lib.sm64_set_mario_position(self.marioId, x, y, z)
        self.state.position[0], self.state.position[1], self.state.position[2] = x, y, z
        if resetVelocity:
            self.lib.sm64_set_mario_velocity(self.marioId, 0, 0, 0)
            self.lib.sm64_set_mario_forward_velocity(self.marioId, 0)

    def setFaceAngle(self, faceAngle):
        self.lib.sm64_set_mario_faceangle(self.marioId, faceAngle)

    # Local control
    def setControllerInput(self, stickX, stickY, buttonA, buttonB, buttonZ):
        self.inputs.stickX = max(-1.0, min(1.0, stickX))
        self.inputs.stickY = max(-1.0, min(1.0, stickY))
        self.inputs.buttonA = int(bool(buttonA))
        self.inputs.buttonB = int(bool(buttonB))
        self.inputs.buttonZ = int(bool(buttonZ))

    def setCameraPos(self, camPandaPos):
        cx, cy, cz = self.manager.toSM64(camPandaPos)
        self.inputs.camLookX = self.state.position[0] - cx
        self.inputs.camLookZ = self.state.position[2] - cz

    # Remote control: Mario follows a node and mimics the networked state
    def setFollowNode(self, node):
        self.followNode = node

    def setNetState(self, action, animID, animFrame, faceAngle, forwardVel, velX, velY, velZ, stickX, stickY, buttons,
                    flags):
        self.netState = (action, animID, animFrame, faceAngle, forwardVel, velX, velY, velZ, stickX, stickY, buttons,
                         flags)
        self.netStateDirty = True

    def getNetState(self):
        s = self.state
        buttons = self.inputs.buttonA | (self.inputs.buttonB << 1) | (self.inputs.buttonZ << 2)
        return (int(s.action), int(s.animID), int(s.animFrame), float(s.faceAngle), float(s.forwardVelocity),
                float(s.velocity[0]), float(s.velocity[1]), float(s.velocity[2]),
                float(self.inputs.stickX), float(self.inputs.stickY), buttons, int(s.flags))

    # Caps (wing / metal / vanish / normal)
    def giveCap(self, capName):
        capName = capName.lower()
        if capName in ('normal', 'none', 'off'):
            flags = (self.state.flags & ~SM64Bindings.MARIO_SPECIAL_CAPS) | SM64Bindings.MARIO_NORMAL_CAP | \
                SM64Bindings.MARIO_CAP_ON_HEAD
            self.lib.sm64_set_mario_state(self.marioId, flags)
            self.state.flags = flags
            return "Mario's cap is back to normal."
        capFlag = SM64Bindings.CAP_FLAGS.get(capName)
        if capFlag is None:
            return 'Unknown cap "%s". Choose wing, metal, vanish or normal.' % capName
        playMusic = 1 if self.manager.audioEnabled else 0
        self.lib.sm64_mario_interact_cap(self.marioId, capFlag, 0, playMusic)
        return 'Mario put on the %s cap!' % capName

    def __applyRemoteState(self):
        if self.followNode is not None and not self.followNode.isEmpty():
            self.warpTo(self.followNode.getPos(builtins.render), resetVelocity=False)
        if self.netState is None:
            return
        action, animID, animFrame, faceAngle, forwardVel, velX, velY, velZ, stickX, stickY, buttons, flags = \
            self.netState
        self.setControllerInput(stickX, stickY, buttons & 1, buttons & 2, buttons & 4)
        self.lib.sm64_set_mario_faceangle(self.marioId, faceAngle)
        self.lib.sm64_set_mario_velocity(self.marioId, velX, velY, velZ)
        self.lib.sm64_set_mario_forward_velocity(self.marioId, forwardVel)
        if action != self.state.action or action != self.lastAppliedAction:
            self.lib.sm64_set_mario_action(self.marioId, action)
            self.lastAppliedAction = action
        if self.netStateDirty:
            if flags != self.state.flags:
                self.lib.sm64_set_mario_state(self.marioId, flags)
            if animID != self.state.animID or animID != self.lastAppliedAnim:
                self.lib.sm64_set_mario_animation(self.marioId, animID)
                self.lastAppliedAnim = animID
            self.lib.sm64_set_mario_anim_frame(self.marioId, animFrame)
            self.netStateDirty = False

    def tick(self):
        if self.marioId < 0:
            return
        if not self.isLocal:
            self.__applyRemoteState()
        waterLevel = self.manager.getWaterLevelSM64(self.getPandaPos())
        self.lib.sm64_set_mario_water_level(self.marioId, waterLevel)
        self.lib.sm64_mario_tick(self.marioId, ct.byref(self.inputs), ct.byref(self.state), ct.byref(self.geo))
        self.tickCount += 1
        self.__checkWaterTransition(waterLevel)
        if self.isLocal:
            if self.state.position[1] < self.manager.lowestY - 2000.0:
                self.notify.info('Mario fell out of the world, respawning')
                self.warpTo(self.spawnPos)
                self.lib.sm64_set_mario_action(self.marioId, SM64Bindings.ACT_FREEFALL)
            if self.state.health < 0x300:
                # Toontown has no 1-ups; keep Mario alive
                self.lib.sm64_set_mario_health(self.marioId, 0x880)
        self.__updateGeom()

    def __checkWaterTransition(self, waterLevel):
        # SM64 counts Mario as submerged once he is 100 units under the surface
        inWater = waterLevel != SM64Globals.NO_WATER_LEVEL and self.state.position[1] < waterLevel - 100
        if inWater and not self.inWater:
            self.manager.onMarioEnteredWater(self, waterLevel)
        elif self.inWater and not inWater and self.lastWaterLevel != SM64Globals.NO_WATER_LEVEL:
            self.manager.onMarioLeftWater(self, self.lastWaterLevel)
        self.inWater = inWater
        self.lastWaterLevel = waterLevel

    def destroy(self):
        self.manager.unregisterMario(self)
        if self.marioId >= 0:
            self.lib.sm64_mario_delete(self.marioId)
            self.marioId = -1
        if not self.isEmpty():
            self.removeNode()
