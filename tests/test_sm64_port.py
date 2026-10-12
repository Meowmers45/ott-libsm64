"""Headless smoke test for the libsm64 Toontown port using a stub libsm64 (tests/sm64_stub.c).
Run from the repo root:  python3 tests/test_sm64_port.py
"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

STUB_DIR = os.path.join(ROOT, 'tests', 'sm64_stub_build')
os.makedirs(STUB_DIR, exist_ok=True)
subprocess.check_call(['gcc', '-shared', '-fPIC', '-o', os.path.join(STUB_DIR, 'libsm64.so'), 'tests/sm64_stub.c'])
romPath = os.path.join(STUB_DIR, 'sm64.z64')
with open(romPath, 'wb') as f:
    f.write(b'\x80\x37\x12\x40' + b'\x00' * 1020)

from panda3d.core import loadPrcFileData, Point3, Mat4, CollisionNode, CollisionPolygon
loadPrcFileData('', 'window-type none')
loadPrcFileData('', 'audio-library-name null')
loadPrcFileData('', 'sm64-lib-dir %s' % STUB_DIR)
loadPrcFileData('', 'sm64-rom-path %s' % romPath)
from direct.showbase.ShowBase import ShowBase
base = ShowBase()

# the Toontown Panda3D fork ships panda3d.otp; stub just enough of it for the magic word import below
import types
fakeOtp = types.ModuleType('panda3d.otp')
for name in ('NametagGroup', 'WhisperPopup', 'CFSpeech', 'CFThought', 'CFTimeout', 'CFQuicktalker'):
    setattr(fakeOtp, name, type(name, (), {}))
sys.modules['panda3d.otp'] = fakeOtp
import panda3d
panda3d.otp = fakeOtp

from libsm64 import SM64Globals, SM64Manager, SM64Bindings
from libsm64.SM64Mario import SM64Mario

# coordinate round trip
origin = Point3(10, -20, 5)
p = Point3(13, -24, 9)
x, y, z = SM64Globals.toSM64(p, origin)
assert (x, y, z) == (150, 200, 200), (x, y, z)
back = SM64Globals.fromSM64(x, y, z, origin)
assert (back - p).length() < 1e-5, back
mat = SM64Globals.makeConversionMat(origin)
viaMat = mat.xformPoint(Point3(x, y, z))
assert (viaMat - p).length() < 1e-4, viaMat
assert abs(SM64Globals.faceAngleToHeading(SM64Globals.headingToFaceAngle(37.0)) - 37.0) < 1e-6

# build a fake level: a floor quad with the Toontown floor mask + an intangible trigger (must be skipped)
floor = base.render.attachNewNode(CollisionNode('floor'))
floor.node().setIntoCollideMask(SM64Globals.FloorBitmask)
floor.node().addSolid(CollisionPolygon(Point3(-50, -50, 0), Point3(50, -50, 0), Point3(50, 50, 0), Point3(-50, 50, 0)))
floor.setPos(0, 0, 2)
trigger = base.render.attachNewNode(CollisionNode('trigger'))
trigger.node().setIntoCollideMask(SM64Globals.WallBitmask)
poly = CollisionPolygon(Point3(-5, 0, 0), Point3(5, 0, 0), Point3(0, 0, 5))
poly.setTangible(False)
trigger.node().addSolid(poly)

manager = SM64Manager.get()
assert manager.isAvailable(), manager.getMissingMessage()
assert manager.ensureInit()
assert manager.texture.getXSize() == SM64Bindings.SM64_TEXTURE_WIDTH
manager.recenter(Point3(0, 0, 2))
assert manager.surfaceCount == 2, manager.surfaceCount  # quad -> 2 triangles, trigger skipped
assert abs(manager.lowestY - 0) < 1e-6
assert abs(manager.findFloorZ(Point3(0, 0, 3)) - 2.0) < 1e-6

mario = SM64Mario(manager, Point3(0, 0, 2), isLocal=True)
assert mario.isValid()
assert len(manager.marios) == 1 and base.taskMgr.hasTaskNamed(SM64Manager.SM64Manager.TaskName)
mario.setControllerInput(1, 0, True, False, False)
mario.setCameraPos(Point3(0, -10, 4))
assert mario.inputs.camLookZ < 0  # camera is behind (-Y panda == +Z sm64)
mario.tick()
assert mario.state.action == 0x03000880
pos = mario.getPandaPos()
assert abs(pos.x - (-10 / SM64Globals.SCALE)) < 1e-5, pos
geom = mario.geomNode.getGeom(0)
assert geom.getPrimitive(0).getNumVertices() == 6
assert geom.getVertexData().getNumRows() == SM64Bindings.SM64_GEO_MAX_TRIANGLES * 3
net = mario.getNetState()
assert len(net) == 12 and net[10] == 1

# caps
assert 'Unknown cap' in mario.giveCap('propeller')
mario.giveCap('wing')
mario.tick()
assert mario.state.flags & SM64Bindings.MARIO_WING_CAP
mario.giveCap('normal')
mario.tick()
assert not (mario.state.flags & SM64Bindings.MARIO_SPECIAL_CAPS) and mario.state.flags & SM64Bindings.MARIO_NORMAL_CAP

# moving platform: a collision node under an "elevator" prop becomes a libsm64 surface object that follows the node
import ctypes as ct
lib = manager.lib
lib.stub_object_alive_count.restype = ct.c_int
lib.stub_object_pos_x.argtypes = [ct.c_uint32]
lib.stub_object_pos_x.restype = ct.c_float
elevator = base.render.attachNewNode('elevator_prop')
elevator.setPos(20, 0, 2)
elevFloor = elevator.attachNewNode(CollisionNode('elevFloor'))
elevFloor.node().setIntoCollideMask(SM64Globals.FloorBitmask)
elevFloor.node().addSolid(CollisionPolygon(Point3(-2, -2, 0), Point3(2, -2, 0), Point3(2, 2, 0), Point3(-2, 2, 0)))
manager.loadSurfaces()
assert manager.surfaceCount == 2  # elevator polygons are NOT in the static set
assert len(manager.dynamicObjects) == 1 and lib.stub_object_alive_count() == 1
dyn = list(manager.dynamicObjects.values())[0]
assert abs(lib.stub_object_pos_x(dyn.objectId) - 20 * SM64Globals.SCALE) < 1e-3
elevator.setPos(25, 0, 2)
mario.tick()  # ticks don't move objects; the manager's tick task does
manager._SM64Manager__updateDynamicObjects()
assert abs(lib.stub_object_pos_x(dyn.objectId) - 25 * SM64Globals.SCALE) < 1e-3

# smooth rotation: rotating the prop streams euler angles instead of rebuilding the object
import math
import random
from panda3d.core import Vec3
from libsm64.SM64Manager import sm64EulerFromHpr


def sm64_rotate_zxy(point, euler):
    # mirror of libsm64: CONVERT_ANGLE negates degrees, then mtxf_rotate_zxy_and_translate (row vectors)
    rx, ry, rz = [math.radians(-e) for e in euler]
    sx, cx = math.sin(rx), math.cos(rx)
    sy, cy = math.sin(ry), math.cos(ry)
    sz, cz = math.sin(rz), math.cos(rz)
    m = [[cy * cz + sx * sy * sz, cx * sz, -sy * cz + sx * cy * sz],
         [-cy * sz + sx * sy * cz, cx * cz, sy * sz + sx * cy * cz],
         [cx * sy, -sx, cx * cy]]
    x, y, z = point
    return (x * m[0][0] + y * m[1][0] + z * m[2][0],
            x * m[0][1] + y * m[1][1] + z * m[2][1],
            x * m[0][2] + y * m[1][2] + z * m[2][2])


random.seed(7)
for _ in range(50):
    hpr = Vec3(random.uniform(-180, 180), random.uniform(-89, 89), random.uniform(-180, 180))
    scale = Vec3(random.uniform(0.5, 2), random.uniform(0.5, 2), random.uniform(0.5, 2))
    probe = base.render.attachNewNode('probe')
    probe.setHpr(hpr)
    probe.setScale(scale)
    local = Point3(3, -1, 2)
    expected = probe.getMat(base.render).xformPoint(local)
    scaled = Mat4.scaleMat(scale).xformPoint(local)
    sm = SM64Globals.toSM64(scaled, Point3(0, 0, 0))
    rotated = sm64_rotate_zxy(sm, sm64EulerFromHpr(hpr))
    got = SM64Globals.fromSM64(rotated[0], rotated[1], rotated[2], Point3(0, 0, 0))
    assert (got - expected).length() < 1e-3, (hpr, got, expected)
    probe.removeNode()

lib.stub_object_euler_y.argtypes = [ct.c_uint32]
lib.stub_object_euler_y.restype = ct.c_float
objBefore = dyn.objectId
elevator.setH(90)
manager._SM64Manager__updateDynamicObjects()
assert dyn.objectId == objBefore, 'rotation must not rebuild the surface object'
assert abs(abs(lib.stub_object_euler_y(dyn.objectId)) - 90) < 0.01, lib.stub_object_euler_y(dyn.objectId)
elevator.setScale(2)
manager._SM64Manager__updateDynamicObjects()
assert dyn.objectId is not None and lib.stub_object_alive_count() == 1  # scale change re-bakes
elevator.removeNode()
manager._SM64Manager__updateDynamicObjects()
assert len(manager.dynamicObjects) == 0 and lib.stub_object_alive_count() == 0

# remote mario follows a node & applies net state
follow = base.render.attachNewNode('remoteToon')
follow.setPos(5, 5, 2)
remote = SM64Mario(manager, Point3(5, 5, 2), isLocal=False)
assert remote.isValid()
remote.setFollowNode(follow)
remote.setNetState(0x03000880, 7, 3, 1.0, 20.0, 1, 2, 3, 0.5, -0.5, 2, SM64Bindings.MARIO_METAL_CAP | 0x10)
remote.tick()
assert remote.state.animID == 7 and remote.state.action == 0x03000880
assert remote.state.flags & SM64Bindings.MARIO_METAL_CAP
assert remote.inputs.buttonB == 1 and remote.inputs.buttonA == 0
rp = remote.getPandaPos()
assert abs(rp.x - 4.9) < 1e-4 and abs(rp.y - 4.9) < 1e-4, rp

# recentering keeps Marios in place
before = mario.getPandaPos()
manager.recenter(Point3(100, 100, 2))
assert (mario.getPandaPos() - before).length() < 1e-3
assert manager.surfaceCount == 2  # floor is 141 units from the new origin, inside COLLISION_RADIUS
manager.recenter(Point3(1000, 1000, 2))
assert manager.surfaceCount == 0  # now culled
assert (mario.getPandaPos() - before).length() < 1e-3
manager.recenter(Point3(0, 0, 2))

mario.destroy()
remote.destroy()
assert not manager.marios and not base.taskMgr.hasTaskNamed(SM64Manager.SM64Manager.TaskName)

# Magic word registration + DC fields
from toontown.spellbook import MagicWordIndex
assert 'mario' in MagicWordIndex.magicWordIndex and 'toon' in MagicWordIndex.magicWordIndex
dc = open('etc/toon.dc').read()
assert 'setMarioMode(uint8) broadcast ram ownsend;' in dc
assert 'setMarioState(uint32, int32, int16, int16/1000, int16/10, int16/10, int16/10, int16/10, int8/100, int8/100, uint8, uint32) broadcast ownsend;' in dc

# audio plumbing (null audio manager in this headless run)
assert manager.audioEnabled, 'audio should initialise with the stub'
mario2 = SM64Mario(manager, Point3(0, 0, 2), isLocal=True)
pushedBefore = manager.audioSamplesPushed
manager._SM64Manager__tickAudio()
assert manager.audioSamplesPushed > pushedBefore
mario2.destroy()

print('ALL SM64 PORT CHECKS PASSED')
