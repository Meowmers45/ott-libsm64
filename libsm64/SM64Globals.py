import math
from panda3d.core import Point3, Mat4, BitMask32, ConfigVariableString, ConfigVariableDouble, ConfigVariableInt

# Same values as OTPGlobals.WallBitmask / FloorBitmask (kept here so this package has no otp dependency)
WallBitmask = BitMask32(1)
FloorBitmask = BitMask32(2)
CollisionMask = WallBitmask | FloorBitmask

# 1 Panda unit == SCALE SM64 units (Mario is ~160 SM64 units tall -> ~3.2 Panda units)
SCALE = ConfigVariableDouble('sm64-scale', 50.0).getValue()
TICK_RATE = 1.0 / 30.0
# Only collision polygons within this many Panda units of the SM64 origin are uploaded to libsm64
COLLISION_RADIUS = ConfigVariableDouble('sm64-collision-radius', 400.0).getValue()
# How often (seconds) we look for level geometry changes
SURFACE_CHECK_INTERVAL = ConfigVariableDouble('sm64-surface-check-interval', 2.0).getValue()
LIB_DIR = ConfigVariableString('sm64-lib-dir', 'libsm64').getValue()
ROM_PATH = ConfigVariableString('sm64-rom-path', 'libsm64/sm64.z64').getValue()
# Network state update rate for the local Mario (in 30hz ticks)
NET_SEND_EVERY_TICKS = ConfigVariableInt('sm64-net-send-ticks', 3).getValue()

MarioModeOff = 0
MarioModeOn = 1


def toSM64(point, origin):
    return ((point[0] - origin[0]) * SCALE,
            (point[2] - origin[2]) * SCALE,
            -(point[1] - origin[1]) * SCALE)


def fromSM64(x, y, z, origin):
    return Point3(origin[0] + x / SCALE, origin[1] - z / SCALE, origin[2] + y / SCALE)


def makeConversionMat(origin):
    # row-vector matrix: sm64 (x, y, z) -> panda (x, -z, y), scaled and offset by origin
    conv = Mat4(1, 0, 0, 0,
                0, 0, 1, 0,
                0, -1, 0, 0,
                0, 0, 0, 1)
    return conv * Mat4.scaleMat(1.0 / SCALE) * Mat4.translateMat(origin)


def faceAngleToHeading(faceAngle):
    # SM64 yaw 0 faces +Z (panda -Y); yaw increases toward +X
    return 180.0 - math.degrees(faceAngle)


def headingToFaceAngle(heading):
    return math.radians(180.0 - heading)
