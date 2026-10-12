import os
import builtins
import ctypes as ct
from direct.directnotify import DirectNotifyGlobal
from direct.task import Task
from direct.task.TaskManagerGlobal import taskMgr
from direct.showbase.ShowBaseGlobal import globalClock
from direct.showbase.DirectObject import DirectObject
from panda3d.core import Point3, Texture, PNMImage, SamplerState, Shader, Filename, CollisionPolygon
from libsm64 import SM64Bindings, SM64Globals

_manager = None


def _render():
    return builtins.render


def get():
    global _manager
    if _manager is None:
        _manager = SM64Manager()
    return _manager


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
        self.tickAccum = 0.0
        self.libPath = os.path.join(SM64Globals.LIB_DIR, SM64Bindings.getLibraryFilename())
        self.romPath = SM64Globals.ROM_PATH
        self._debugPrint = SM64Bindings.DebugPrintFunc(self.__onDebugPrint)

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

    # Level collision
    def __collectTriangles(self):
        tris = []
        mask = SM64Globals.CollisionMask
        radiusSq = SM64Globals.COLLISION_RADIUS * SM64Globals.COLLISION_RADIUS
        nodeCount = 0
        render = _render()
        for np in render.findAllMatches('**/+CollisionNode'):
            cnode = np.node()
            if (cnode.getIntoCollideMask() & mask).isZero():
                continue
            nodeCount += 1
            mat = np.getMat(render)
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
        self.notify.info('Loaded %d collision triangles from %d nodes (origin %s)' % (len(tris), nodeCount, self.origin))

    def recenter(self, point):
        if not self.initialized:
            return
        marioPositions = [(m, m.getPandaPos()) for m in self.marios]
        self.origin = Point3(point)
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
        mask = SM64Globals.CollisionMask
        for np in _render().findAllMatches('**/+CollisionNode'):
            if not (np.node().getIntoCollideMask() & mask).isZero():
                count += 1
        if count != self.lastCollisionNodeCount:
            self.loadSurfaces()
        return Task.again

    # Mario bookkeeping
    def registerMario(self, mario):
        if mario not in self.marios:
            self.marios.append(mario)
        if not taskMgr.hasTaskNamed(self.TaskName):
            self.tickAccum = 0.0
            taskMgr.add(self.__tickTask, self.TaskName, sort=30)
        if not taskMgr.hasTaskNamed(self.SurfaceTaskName):
            taskMgr.doMethodLater(SM64Globals.SURFACE_CHECK_INTERVAL, self.__surfaceCheckTask, self.SurfaceTaskName)

    def unregisterMario(self, mario):
        if mario in self.marios:
            self.marios.remove(mario)
        if not self.marios:
            taskMgr.remove(self.TaskName)
            taskMgr.remove(self.SurfaceTaskName)

    def __tickTask(self, task):
        dt = globalClock.getDt()
        self.tickAccum = min(self.tickAccum + dt, SM64Globals.TICK_RATE * 3)
        while self.tickAccum >= SM64Globals.TICK_RATE:
            self.tickAccum -= SM64Globals.TICK_RATE
            # local Mario first so remote ones see fresh state
            for mario in sorted(self.marios, key=lambda m: not m.isLocal):
                mario.tick()
        return Task.cont
