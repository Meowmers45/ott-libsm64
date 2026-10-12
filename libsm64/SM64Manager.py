import os
import math
import builtins
import ctypes as ct
from direct.directnotify import DirectNotifyGlobal
from direct.task import Task
from direct.task.TaskManagerGlobal import taskMgr
from direct.showbase.ShowBaseGlobal import globalClock
from direct.showbase.DirectObject import DirectObject
from panda3d.core import Point3, Vec3, Mat3, Mat4, Texture, PNMImage, SamplerState, Shader, Filename, \
    CollisionPolygon, UserDataAudio, decomposeMatrix, composeMatrix
from libsm64 import SM64Bindings, SM64Globals

_manager = None

# row-vector basis change panda (x, y, z) -> sm64 (x, z, -y)
_PANDA_TO_SM64 = Mat3(1, 0, 0,
                      0, 0, -1,
                      0, 1, 0)
_SM64_TO_PANDA = Mat3(_PANDA_TO_SM64)
_SM64_TO_PANDA.transposeInPlace()


def sm64EulerFromHpr(hpr):
    """Panda HPR -> libsm64 SM64ObjectTransform.eulerRotation (degrees, ZXY order as used by libsm64)."""
    rot = Mat3()
    composeMatrix(rot, Vec3(1, 1, 1), Vec3(0, 0, 0), hpr)
    r = _SM64_TO_PANDA * rot * _PANDA_TO_SM64
    sx = max(-1.0, min(1.0, -r.getCell(2, 1)))
    x = math.asin(sx)
    if abs(math.cos(x)) > 1e-4:
        y = math.atan2(r.getCell(2, 0), r.getCell(2, 2))
        z = math.atan2(r.getCell(0, 1), r.getCell(1, 1))
    else:
        y = math.atan2(-r.getCell(0, 2), r.getCell(0, 0))
        z = 0.0
    # libsm64 negates the angles it receives (CONVERT_ANGLE)
    return (-math.degrees(x), -math.degrees(y), -math.degrees(z))


def _render():
    return builtins.render


def get():
    global _manager
    if _manager is None:
        _manager = SM64Manager()
    return _manager


class DynamicSurfaceObject:
    """A moving collision node (elevator, trolley...) mirrored as a libsm64 surface object.
    Scale is baked into the vertices; position and rotation are streamed through the object transform."""

    def __init__(self, manager, nodePath):
        self.manager = manager
        self.nodePath = nodePath
        self.objectId = None
        self.surfaces = None
        self.transform = SM64Bindings.SM64ObjectTransform()
        self.baseScale = None
        self.lastPos = None
        self.lastHpr = None
        self.create()

    def __decompose(self, mat):
        scale, shear, hpr = Vec3(), Vec3(), Vec3()
        decomposeMatrix(mat.getUpper3(), scale, shear, hpr)
        return scale, hpr, Point3(mat.getRow3(3))

    def __polygonTriangles(self, scaleMat):
        tris = []
        cnode = self.nodePath.node()
        for i in range(cnode.getNumSolids()):
            solid = cnode.getSolid(i)
            if not isinstance(solid, CollisionPolygon) or not solid.isTangible():
                continue
            pts = [scaleMat.xformPoint(solid.getPoint(j)) for j in range(solid.getNumPoints())]
            for j in range(1, len(pts) - 1):
                tris.append((pts[0], pts[j], pts[j + 1]))
        return tris

    def create(self):
        mat = self.nodePath.getMat(_render())
        scale, hpr, pos = self.__decompose(mat)
        self.baseScale = Vec3(scale)
        tris = self.__polygonTriangles(Mat4.scaleMat(scale))
        if not tris:
            return
        self.surfaces = (SM64Bindings.SM64Surface * len(tris))()
        origin = Point3(0, 0, 0)
        for idx, tri in enumerate(tris):
            s = self.surfaces[idx]
            s.type = SM64Bindings.SURFACE_DEFAULT
            s.terrain = SM64Bindings.TERRAIN_GRASS
            for v in range(3):
                x, y, z = SM64Globals.toSM64(tri[v], origin)
                s.vertices[v][0], s.vertices[v][1], s.vertices[v][2] = int(x), int(y), int(z)
        self.__fillTransform(pos, hpr)
        obj = SM64Bindings.SM64SurfaceObject()
        obj.transform = self.transform
        obj.surfaceCount = len(tris)
        obj.surfaces = ct.cast(self.surfaces, ct.POINTER(SM64Bindings.SM64Surface))
        self.objectId = self.manager.lib.sm64_surface_object_create(ct.byref(obj))

    def __fillTransform(self, pandaPos, hpr):
        x, y, z = self.manager.toSM64(pandaPos)
        self.transform.position[0], self.transform.position[1], self.transform.position[2] = x, y, z
        ex, ey, ez = sm64EulerFromHpr(hpr)
        self.transform.eulerRotation[0], self.transform.eulerRotation[1], self.transform.eulerRotation[2] = ex, ey, ez
        self.lastPos = Point3(pandaPos)
        self.lastHpr = Vec3(hpr)

    def update(self):
        if self.nodePath.isEmpty() or self.nodePath.getTop() != _render():
            self.destroy()
            return False
        mat = self.nodePath.getMat(_render())
        scale, hpr, pos = self.__decompose(mat)
        if self.objectId is None or not scale.almostEqual(self.baseScale, 0.001):
            self.destroy()
            self.create()
            return True
        if not pos.almostEqual(self.lastPos, 1e-4) or not hpr.almostEqual(self.lastHpr, 1e-3):
            self.__fillTransform(pos, hpr)
            self.manager.lib.sm64_surface_object_move(self.objectId, ct.byref(self.transform))
        return True

    def destroy(self):
        if self.objectId is not None:
            self.manager.lib.sm64_surface_object_delete(self.objectId)
            self.objectId = None


class SM64Manager(DirectObject):
    notify = DirectNotifyGlobal.directNotify.newCategory('SM64Manager')
    TaskName = 'sm64-tick'
    SurfaceTaskName = 'sm64-surface-check'

    def __init__(self):
        self.lib = None
        self.rom = None
        self.texture = None
        self.shader = None
        self.initialized = False
        self.origin = Point3(0, 0, 0)
        self.marios = []
        self.surfaceCount = 0
        self.lowestY = SM64Bindings.FLOOR_LOWER_LIMIT
        self.lastCollisionNodeCount = -1
        self.staticMats = {}
        self.dynamicKeys = set()
        self.dynamicObjects = {}
        self.waterRegions = []
        self.tickAccum = 0.0
        self.libPath = os.path.join(SM64Globals.LIB_DIR, SM64Bindings.getLibraryFilename())
        self.romPath = SM64Globals.ROM_PATH
        self._debugPrint = SM64Bindings.DebugPrintFunc(self.__onDebugPrint)
        self.audioEnabled = False
        self.audioStream = None
        self.audioSound = None
        self.audioBuffer = None
        self.audioSamplesPushed = 0
        self.audioStartTime = 0.0

    def __onDebugPrint(self, msg):
        self.notify.info('libsm64: %s' % msg.decode('utf-8', 'replace'))

    def isAvailable(self):
        return os.path.isfile(self.libPath) and os.path.isfile(self.romPath)

    def getMissingMessage(self):
        missing = []
        if not os.path.isfile(self.libPath):
            missing.append('library "%s"' % self.libPath)
        if not os.path.isfile(self.romPath):
            missing.append('ROM "%s"' % self.romPath)
        return 'libsm64 is not set up: missing %s. See libsm64/README.md.' % ' and '.join(missing)

    def ensureInit(self):
        if self.initialized:
            return True
        if not self.isAvailable():
            self.notify.warning(self.getMissingMessage())
            return False
        try:
            self.lib = SM64Bindings.loadLibrary(self.libPath)
            self.lib.sm64_register_debug_print_function(self._debugPrint)
            self.rom = SM64Bindings.loadRom(self.romPath)
            texBuf = (ct.c_uint8 * (4 * SM64Bindings.SM64_TEXTURE_WIDTH * SM64Bindings.SM64_TEXTURE_HEIGHT))()
            self.lib.sm64_global_init(self.rom, texBuf)
        except Exception as e:
            self.notify.warning('Failed to initialize libsm64: %s' % e)
            self.lib = None
            return False
        self.texture = self.__makeTexture(texBuf)
        self.shader = self.__loadShader()
        if self.shader is None:
            self.notify.warning('Mario shader failed to compile; falling back to fixed-function rendering')
        self.initialized = True
        self.__initAudio()
        self.notify.info('libsm64 initialized')
        return True

    def __makeTexture(self, buf):
        w, h = SM64Bindings.SM64_TEXTURE_WIDTH, SM64Bindings.SM64_TEXTURE_HEIGHT
        img = PNMImage(w, h)
        img.addAlpha()
        i = 0
        for y in range(h):
            for x in range(w):
                img.setXelA(x, y, buf[i] / 255.0, buf[i + 1] / 255.0, buf[i + 2] / 255.0, buf[i + 3] / 255.0)
                i += 4
        tex = Texture('MarioTex')
        tex.load(img)
        tex.setMinfilter(SamplerState.FTNearest)
        tex.setMagfilter(SamplerState.FTNearest)
        tex.setAnisotropicDegree(0)
        return tex

    def __loadShader(self):
        shaderDir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shaders')
        vsh = Filename.fromOsSpecific(os.path.join(shaderDir, 'mario.vsh'))
        fsh = Filename.fromOsSpecific(os.path.join(shaderDir, 'mario.fsh'))
        return Shader.load(Shader.SL_GLSL, vertex=vsh, fragment=fsh)

    # Audio: libsm64 renders SM64 sound effects into a PCM stream we feed to Panda
    def __initAudio(self):
        if not SM64Globals.AUDIO_ENABLED:
            return
        base = builtins.base
        if not getattr(base, 'sfxManagerList', None):
            return
        try:
            self.lib.sm64_audio_init(self.rom)
            self.lib.sm64_set_sound_volume(SM64Globals.SFX_VOLUME)
            self.audioStream = UserDataAudio(SM64Bindings.AUDIO_SAMPLE_RATE, 2, True)
            self.audioSound = base.sfxManagerList[0].getSound(self.audioStream)
            self.audioBuffer = (ct.c_int16 * (SM64Bindings.AUDIO_MAX_SAMPLES * 2 * 2))()
            self.audioEnabled = True
        except Exception as e:
            self.notify.warning('SM64 audio unavailable: %s' % e)
            self.audioEnabled = False

    def __startAudio(self):
        if not self.audioEnabled:
            return
        self.audioSamplesPushed = 0
        self.audioStartTime = globalClock.getFrameTime()
        self.audioSound.setLoop(False)
        self.audioSound.setVolume(SM64Globals.SFX_VOLUME)
        self.audioSound.play()

    def __stopAudio(self):
        if self.audioEnabled and self.audioSound is not None:
            self.audioSound.stop()

    def __tickAudio(self):
        if not self.audioEnabled:
            return
        played = int((globalClock.getFrameTime() - self.audioStartTime) * SM64Bindings.AUDIO_SAMPLE_RATE)
        queued = max(0, self.audioSamplesPushed - played)
        numSamples = self.lib.sm64_audio_tick(queued, 1100, self.audioBuffer)
        if numSamples:
            # two stereo int16 batches of numSamples each
            self.audioStream.append(ct.string_at(self.audioBuffer, numSamples * 2 * 4))
            self.audioSamplesPushed += numSamples * 2

    # Coordinate helpers
    def toSM64(self, point):
        return SM64Globals.toSM64(point, self.origin)

    def fromSM64(self, x, y, z):
        return SM64Globals.fromSM64(x, y, z, self.origin)

    def getConversionMat(self):
        return SM64Globals.makeConversionMat(self.origin)

    def findFloorZ(self, point):
        x, y, z = self.toSM64(point)
        height = self.lib.sm64_surface_find_floor_height(x, y + 100.0, z)
        if height <= SM64Bindings.FLOOR_LOWER_LIMIT + 1:
            return None
        return self.fromSM64(x, height, z)[2]

    # Water: named scene nodes (ponds, harbours) become SM64 water with a synthetic lake bed
    def __collectWaterRegions(self):
        regions = []
        render = _render()
        seen = set()
        for pattern in SM64Globals.WATER_NODE_PATTERNS:
            for variant in (pattern, pattern.capitalize(), pattern.upper()):
                for np in render.findAllMatches('**/*%s*' % variant):
                    key = np.getKey()
                    if key in seen:
                        continue
                    seen.add(key)
                    name = np.getName().lower()
                    if any(ex in name for ex in SM64Globals.WATER_EXCLUDE_PATTERNS):
                        continue
                    mn, mx = Point3(), Point3()
                    if not np.calcTightBounds(mn, mx, render):
                        continue
                    if mx.x - mn.x < 2.0 or mx.y - mn.y < 2.0:
                        continue
                    regions.append((mn.x, mn.y, mx.x, mx.y, mx.z))
        return regions

    def getWaterLevelSM64(self, pandaPos):
        x, y = pandaPos[0], pandaPos[1]
        for minX, minY, maxX, maxY, topZ in self.waterRegions:
            if minX <= x <= maxX and minY <= y <= maxY:
                return int((topZ - self.origin[2]) * SM64Globals.SCALE)
        return SM64Globals.NO_WATER_LEVEL

    def isInWater(self, pandaPos):
        return self.getWaterLevelSM64(pandaPos) != SM64Globals.NO_WATER_LEVEL

    def __waterBedTriangles(self):
        tris = []
        cell = 100.0
        radiusSq = SM64Globals.COLLISION_RADIUS * SM64Globals.COLLISION_RADIUS
        for minX, minY, maxX, maxY, topZ in self.waterRegions:
            z = topZ - SM64Globals.WATER_DEPTH
            x0 = minX
            while x0 < maxX:
                x1 = min(x0 + cell, maxX)
                y0 = minY
                while y0 < maxY:
                    y1 = min(y0 + cell, maxY)
                    center = Point3((x0 + x1) * 0.5, (y0 + y1) * 0.5, z)
                    if (center - self.origin).lengthSquared() <= radiusSq:
                        a, b, c, d = Point3(x0, y0, z), Point3(x1, y0, z), Point3(x1, y1, z), Point3(x0, y1, z)
                        tris.append((a, b, c))
                        tris.append((a, c, d))
                    y0 = y1
                x0 = x1
        return tris

    # Level collision
    def __isDynamicNode(self, np):
        if np.getKey() in self.dynamicKeys:
            return True
        for ancestor in np.getAncestors():
            name = ancestor.getName().lower()
            if any(p in name for p in SM64Globals.DYNAMIC_NODE_PATTERNS):
                return True
        return False

    def __collectTriangles(self):
        tris = []
        mask = SM64Globals.CollisionMask
        radiusSq = SM64Globals.COLLISION_RADIUS * SM64Globals.COLLISION_RADIUS
        nodeCount = 0
        render = _render()
        self.staticMats = {}
        for np in render.findAllMatches('**/+CollisionNode'):
            cnode = np.node()
            if (cnode.getIntoCollideMask() & mask).isZero():
                continue
            nodeCount += 1
            if self.__isDynamicNode(np):
                key = np.getKey()
                self.dynamicKeys.add(key)
                if key not in self.dynamicObjects:
                    self.dynamicObjects[key] = DynamicSurfaceObject(self, np)
                continue
            mat = np.getMat(render)
            self.staticMats[np.getKey()] = (np, Mat4(mat))
            for i in range(cnode.getNumSolids()):
                solid = cnode.getSolid(i)
                if not isinstance(solid, CollisionPolygon) or not solid.isTangible():
                    continue
                numPoints = solid.getNumPoints()
                if numPoints < 3:
                    continue
                pts = [mat.xformPoint(solid.getPoint(j)) for j in range(numPoints)]
                if (pts[0] - self.origin).lengthSquared() > radiusSq:
                    continue
                for j in range(1, numPoints - 1):
                    tris.append((pts[0], pts[j], pts[j + 1]))
        return tris, nodeCount

    def loadSurfaces(self):
        if not self.initialized:
            return
        tris, nodeCount = self.__collectTriangles()
        self.lastCollisionNodeCount = nodeCount
        self.waterRegions = self.__collectWaterRegions()
        tris.extend(self.__waterBedTriangles())
        surfaces = (SM64Bindings.SM64Surface * max(len(tris), 1))()
        lowest = 1e9
        for idx, tri in enumerate(tris):
            s = surfaces[idx]
            s.type = SM64Bindings.SURFACE_DEFAULT
            s.force = 0
            s.terrain = SM64Bindings.TERRAIN_GRASS
            for v in range(3):
                x, y, z = self.toSM64(tri[v])
                s.vertices[v][0] = int(x)
                s.vertices[v][1] = int(y)
                s.vertices[v][2] = int(z)
                if y < lowest:
                    lowest = y
        self.surfaceCount = len(tris)
        self.lowestY = lowest if tris else SM64Bindings.FLOOR_LOWER_LIMIT
        self.lib.sm64_static_surfaces_load(surfaces, len(tris))
        self.notify.info('Loaded %d static triangles from %d nodes, %d moving objects, %d water regions (origin %s)' % (
            len(tris), nodeCount, len(self.dynamicObjects), len(self.waterRegions), self.origin))

    def __destroyDynamicObjects(self):
        for obj in self.dynamicObjects.values():
            obj.destroy()
        self.dynamicObjects = {}

    def __updateDynamicObjects(self):
        for key in list(self.dynamicObjects.keys()):
            if not self.dynamicObjects[key].update():
                del self.dynamicObjects[key]

    def recenter(self, point):
        if not self.initialized:
            return
        marioPositions = [(m, m.getPandaPos()) for m in self.marios]
        self.origin = Point3(point)
        self.__destroyDynamicObjects()
        self.loadSurfaces()
        mat = self.getConversionMat()
        for mario, pos in marioPositions:
            mario.setMat(mat)
            mario.warpTo(pos, resetVelocity=False)

    def recenterIfNeeded(self, point):
        if (Point3(point) - self.origin).length() > SM64Globals.COLLISION_RADIUS * 0.5:
            self.recenter(point)
            return True
        return False

    def __surfaceCheckTask(self, task):
        if not self.marios:
            return Task.done
        count = 0
        moved = False
        mask = SM64Globals.CollisionMask
        render = _render()
        for np in render.findAllMatches('**/+CollisionNode'):
            if (np.node().getIntoCollideMask() & mask).isZero():
                continue
            count += 1
            entry = self.staticMats.get(np.getKey())
            if entry is not None and not np.getMat(render).almostEqual(entry[1], 0.001):
                # a "static" node moved: promote it to a moving surface object
                self.dynamicKeys.add(np.getKey())
                moved = True
        if moved or count != self.lastCollisionNodeCount:
            self.loadSurfaces()
        return Task.again

    # Mario bookkeeping
    def registerMario(self, mario):
        if mario not in self.marios:
            self.marios.append(mario)
        if not taskMgr.hasTaskNamed(self.TaskName):
            self.tickAccum = 0.0
            taskMgr.add(self.__tickTask, self.TaskName, sort=30)
            self.__startAudio()
        if not taskMgr.hasTaskNamed(self.SurfaceTaskName):
            taskMgr.doMethodLater(SM64Globals.SURFACE_CHECK_INTERVAL, self.__surfaceCheckTask, self.SurfaceTaskName)

    def unregisterMario(self, mario):
        if mario in self.marios:
            self.marios.remove(mario)
        if not self.marios:
            taskMgr.remove(self.TaskName)
            taskMgr.remove(self.SurfaceTaskName)
            self.__stopAudio()
            self.__destroyDynamicObjects()

    def __tickTask(self, task):
        dt = globalClock.getDt()
        self.tickAccum = min(self.tickAccum + dt, SM64Globals.TICK_RATE * 3)
        while self.tickAccum >= SM64Globals.TICK_RATE:
            self.tickAccum -= SM64Globals.TICK_RATE
            self.__updateDynamicObjects()
            # local Mario first so remote ones see fresh state
            for mario in sorted(self.marios, key=lambda m: not m.isLocal):
                mario.tick()
            self.__tickAudio()
        return Task.cont
