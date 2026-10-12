import math
from direct.task import Task
from direct.task.TaskManagerGlobal import taskMgr

DESIGN_ASPECT = 4.0 / 3.0


class HudAspectAdjuster:
    """Keeps Toontown's 4:3-designed HUD anchored to the window edges at any aspect ratio and keeps the
    camera's vertical field of view constant so the horizontal FOV widens with the window."""
    TaskName = 'hud-aspect-adjust'

    def __init__(self, base):
        self.base = base
        self.factor = 1.0
        self.designX = {}
        self.appliedFov = None
        taskMgr.add(self.__task, self.TaskName, sort=-10)

    def destroy(self):
        taskMgr.remove(self.TaskName)

    def getFactor(self):
        aspect = self.base.getAspectRatio()
        if aspect <= 0:
            return 1.0
        return aspect / DESIGN_ASPECT

    def __task(self, task):
        self.__adjustHud()
        self.__adjustFov()
        return Task.cont

    def __adjustHud(self):
        factor = self.getFactor()
        factorChanged = abs(factor - self.factor) > 1e-4
        self.factor = factor
        seen = set()
        for child in self.base.aspect2d.getChildren():
            key = child.getKey()
            seen.add(key)
            x = child.getX()
            entry = self.designX.get(key)
            if entry is None:
                design = x  # freshly created GUI, positioned in 4:3 coordinates
            elif not factorChanged and abs(x - entry[1]) > 1e-5:
                design = x  # moved by game code, again in 4:3 coordinates
            else:
                design = entry[0]
            applied = design * factor
            if abs(applied - x) > 1e-5:
                child.setX(applied)
            self.designX[key] = (design, applied)
        for key in list(self.designX.keys()):
            if key not in seen:
                del self.designX[key]

    def __adjustFov(self):
        lens = self.base.camLens
        fov = lens.getFov()
        if self.appliedFov is not None and abs(fov[1] - self.appliedFov[1]) < 1e-3:
            # only the horizontal FOV changed: that's the lens following a new aspect ratio
            self.appliedFov = (fov[0], fov[1])
            return
        # Game code called setFov(h) meaning a 4:3 horizontal FOV: keep the matching vertical FOV instead
        vDesign = math.degrees(2.0 * math.atan(math.tan(math.radians(fov[0]) * 0.5) / DESIGN_ASPECT))
        lens.setMinFov(vDesign)
        fov = lens.getFov()
        self.appliedFov = (fov[0], fov[1])
