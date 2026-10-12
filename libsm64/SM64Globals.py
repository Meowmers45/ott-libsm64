import math
from panda3d.core import Point3, Mat4, BitMask32, ConfigVariableString, ConfigVariableDouble, ConfigVariableInt, \
    ConfigVariableBool

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
# Key that toggles Mario Mode without typing the magic word ('' disables)
TOGGLE_KEY = ConfigVariableString('sm64-toggle-key', 'm').getValue()
# Fixed chase camera behind Mario's head (Panda units)
CAMERA_DISTANCE = ConfigVariableDouble('sm64-camera-distance', 12.0).getValue()
CAMERA_HEIGHT = ConfigVariableDouble('sm64-camera-height', 5.0).getValue()
# How quickly (per second) the chase camera eases in behind Mario's new facing
CAMERA_FOLLOW_RATE = ConfigVariableDouble('sm64-camera-follow-rate', 10.0).getValue()
# SM64 sound effects through libsm64's audio engine
AUDIO_ENABLED = ConfigVariableBool('sm64-audio', True).getValue()
SFX_VOLUME = ConfigVariableDouble('sm64-sfx-volume', 0.7).getValue()
# Collision nodes whose ancestors match one of these (case-insensitive) names become moving surface objects
DYNAMIC_NODE_PATTERNS = [p.lower() for p in ConfigVariableString(
    'sm64-dynamic-node-patterns', 'elevator trolley platform lift goon crate').getValue().split()]
# Scene nodes whose name contains one of these become SM64 water (surface = top of the node's bounds)
WATER_NODE_PATTERNS = [p.lower() for p in ConfigVariableString('sm64-water-node-patterns', 'water pond').getValue().split()]
WATER_EXCLUDE_PATTERNS = [p.lower() for p in ConfigVariableString(
    'sm64-water-exclude-patterns', 'water_can waterfall watering fountain').getValue().split()]
# Synthetic lake bed this far (Panda units) under the water surface so Mario can swim where there is no floor
WATER_DEPTH = ConfigVariableDouble('sm64-water-depth', 15.0).getValue()
NO_WATER_LEVEL = -10000

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
    # SM64 moves along (sin yaw, cos yaw) in (x, z); in panda that is (sin yaw, -cos yaw) == heading 180 + yaw
    return 180.0 + math.degrees(faceAngle)


def headingToFaceAngle(heading):
    return math.radians(heading - 180.0)
