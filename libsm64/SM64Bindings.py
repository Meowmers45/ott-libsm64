import ctypes as ct
import os
import sys

SM64_TEXTURE_WIDTH = 64 * 11
SM64_TEXTURE_HEIGHT = 64
SM64_GEO_MAX_TRIANGLES = 1024

SURFACE_DEFAULT = 0x0000
TERRAIN_GRASS = 0x0000

ACT_IDLE = 0x0C400201
ACT_UNINITIALIZED = 0x00000000
ACT_START_SLEEPING = 0x0C400202
ACT_SLEEPING = 0x0C000203
ACT_FREEFALL = 0x0100088C
ACT_SPAWN_SPIN_AIRBORNE = 0x00001924

MARIO_NORMAL_CAP = 0x00000001
MARIO_VANISH_CAP = 0x00000002
MARIO_METAL_CAP = 0x00000004
MARIO_WING_CAP = 0x00000008
MARIO_CAP_ON_HEAD = 0x00000010
MARIO_CAP_IN_HAND = 0x00000020
MARIO_SPECIAL_CAPS = MARIO_VANISH_CAP | MARIO_METAL_CAP | MARIO_WING_CAP
CAP_FLAGS = {'wing': MARIO_WING_CAP, 'metal': MARIO_METAL_CAP, 'vanish': MARIO_VANISH_CAP}

AUDIO_SAMPLE_RATE = 32000
AUDIO_MAX_SAMPLES = 544

FLOOR_LOWER_LIMIT = -11000.0


class SM64Surface(ct.Structure):
    _fields_ = [
        ('type', ct.c_int16),
        ('force', ct.c_int16),
        ('terrain', ct.c_uint16),
        ('vertices', (ct.c_int32 * 3) * 3),
    ]


class SM64ObjectTransform(ct.Structure):
    _fields_ = [
        ('position', ct.c_float * 3),
        ('eulerRotation', ct.c_float * 3),
    ]


class SM64SurfaceObject(ct.Structure):
    _fields_ = [
        ('transform', SM64ObjectTransform),
        ('surfaceCount', ct.c_uint32),
        ('surfaces', ct.POINTER(SM64Surface)),
    ]


class SM64MarioInputs(ct.Structure):
    _fields_ = [
        ('camLookX', ct.c_float), ('camLookZ', ct.c_float),
        ('stickX', ct.c_float), ('stickY', ct.c_float),
        ('buttonA', ct.c_uint8), ('buttonB', ct.c_uint8), ('buttonZ', ct.c_uint8),
    ]


class SM64MarioState(ct.Structure):
    _fields_ = [
        ('position', ct.c_float * 3),
        ('velocity', ct.c_float * 3),
        ('faceAngle', ct.c_float),
        ('forwardVelocity', ct.c_float),
        ('health', ct.c_int16),
        ('action', ct.c_uint32),
        ('animID', ct.c_int32),
        ('animFrame', ct.c_int16),
        ('flags', ct.c_uint32),
        ('particleFlags', ct.c_uint32),
        ('invincTimer', ct.c_int16),
    ]


class SM64MarioGeometryBuffers(ct.Structure):
    _fields_ = [
        ('position', ct.POINTER(ct.c_float)),
        ('normal', ct.POINTER(ct.c_float)),
        ('color', ct.POINTER(ct.c_float)),
        ('uv', ct.POINTER(ct.c_float)),
        ('numTrianglesUsed', ct.c_uint16),
    ]

    def __init__(self):
        ct.Structure.__init__(self)
        vec3Count = SM64_GEO_MAX_TRIANGLES * 3 * 3
        self.positionData = (ct.c_float * vec3Count)()
        self.normalData = (ct.c_float * vec3Count)()
        self.colorData = (ct.c_float * vec3Count)()
        self.uvData = (ct.c_float * (SM64_GEO_MAX_TRIANGLES * 3 * 2))()
        self.position = ct.cast(self.positionData, ct.POINTER(ct.c_float))
        self.normal = ct.cast(self.normalData, ct.POINTER(ct.c_float))
        self.color = ct.cast(self.colorData, ct.POINTER(ct.c_float))
        self.uv = ct.cast(self.uvData, ct.POINTER(ct.c_float))
        self.numTrianglesUsed = 0


DebugPrintFunc = ct.CFUNCTYPE(None, ct.c_char_p)


def getLibraryFilename():
    if sys.platform.startswith('darwin'):
        return 'libsm64.dylib'
    if sys.platform in ('win32', 'cygwin'):
        return 'sm64.dll'
    return 'libsm64.so'


def loadLibrary(path):
    lib = ct.cdll.LoadLibrary(os.path.abspath(path))
    lib.sm64_register_debug_print_function.argtypes = [DebugPrintFunc]
    lib.sm64_global_init.argtypes = [ct.POINTER(ct.c_uint8), ct.POINTER(ct.c_uint8)]
    lib.sm64_global_terminate.argtypes = []
    lib.sm64_static_surfaces_load.argtypes = [ct.POINTER(SM64Surface), ct.c_uint32]
    lib.sm64_mario_create.argtypes = [ct.c_float, ct.c_float, ct.c_float]
    lib.sm64_mario_create.restype = ct.c_int32
    lib.sm64_mario_tick.argtypes = [ct.c_int32, ct.POINTER(SM64MarioInputs), ct.POINTER(SM64MarioState),
                                    ct.POINTER(SM64MarioGeometryBuffers)]
    lib.sm64_mario_delete.argtypes = [ct.c_int32]
    lib.sm64_set_mario_action.argtypes = [ct.c_int32, ct.c_uint32]
    lib.sm64_set_mario_animation.argtypes = [ct.c_int32, ct.c_int32]
    lib.sm64_set_mario_anim_frame.argtypes = [ct.c_int32, ct.c_int16]
    lib.sm64_set_mario_position.argtypes = [ct.c_int32, ct.c_float, ct.c_float, ct.c_float]
    lib.sm64_set_mario_faceangle.argtypes = [ct.c_int32, ct.c_float]
    lib.sm64_set_mario_velocity.argtypes = [ct.c_int32, ct.c_float, ct.c_float, ct.c_float]
    lib.sm64_set_mario_forward_velocity.argtypes = [ct.c_int32, ct.c_float]
    lib.sm64_set_mario_health.argtypes = [ct.c_int32, ct.c_uint16]
    lib.sm64_set_mario_water_level.argtypes = [ct.c_int32, ct.c_int]
    lib.sm64_set_mario_state.argtypes = [ct.c_int32, ct.c_uint32]
    lib.sm64_mario_interact_cap.argtypes = [ct.c_int32, ct.c_uint32, ct.c_uint16, ct.c_uint8]
    lib.sm64_surface_find_floor_height.argtypes = [ct.c_float, ct.c_float, ct.c_float]
    lib.sm64_surface_find_floor_height.restype = ct.c_float
    lib.sm64_surface_object_create.argtypes = [ct.POINTER(SM64SurfaceObject)]
    lib.sm64_surface_object_create.restype = ct.c_uint32
    lib.sm64_surface_object_move.argtypes = [ct.c_uint32, ct.POINTER(SM64ObjectTransform)]
    lib.sm64_surface_object_delete.argtypes = [ct.c_uint32]
    lib.sm64_audio_init.argtypes = [ct.POINTER(ct.c_uint8)]
    lib.sm64_audio_tick.argtypes = [ct.c_uint32, ct.c_uint32, ct.POINTER(ct.c_int16)]
    lib.sm64_audio_tick.restype = ct.c_uint32
    lib.sm64_set_sound_volume.argtypes = [ct.c_float]
    return lib


def loadRom(path):
    with open(path, 'rb') as f:
        data = f.read()
    return (ct.c_uint8 * len(data)).from_buffer_copy(data)
