"""Headless test for toontown/toonbase/HudAspectAdjuster.py (no Toontown assets needed)."""
import os
import sys
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from panda3d.core import loadPrcFileData
loadPrcFileData('', 'window-type none')
loadPrcFileData('', 'audio-library-name null')
from direct.showbase.ShowBase import ShowBase
base = ShowBase()
from panda3d.core import PerspectiveLens
base.camLens = PerspectiveLens()  # window-type none has no camera

from toontown.toonbase.HudAspectAdjuster import HudAspectAdjuster, DESIGN_ASPECT

# fake the window aspect ratio
aspect = [DESIGN_ASPECT]
base.getAspectRatio = lambda ignoreWin=False: aspect[0]
base.camLens.setAspectRatio(aspect[0])
base.camLens.setFov(52)

adj = HudAspectAdjuster(base)
laff = base.aspect2d.attachNewNode('laffMeter')
laff.setPos(-1.18, 0, -0.87)
dialog = base.aspect2d.attachNewNode('dialog')
dialog.setPos(0, 0, 0.2)

run = adj._HudAspectAdjuster__task
run(None)
assert abs(laff.getX() + 1.18) < 1e-5  # unchanged at 4:3
fov = base.camLens.getFov()
assert abs(fov[0] - 52) < 1e-3, fov
vDesign = fov[1]
assert abs(vDesign - math.degrees(2 * math.atan(math.tan(math.radians(26)) / DESIGN_ASPECT))) < 1e-3

# widen to 16:9: HUD corners follow the edges, vertical FOV stays, horizontal FOV widens
aspect[0] = 16.0 / 9.0
base.camLens.setAspectRatio(aspect[0])
run(None)
assert abs(laff.getX() + 1.18 * (16.0 / 9.0) / DESIGN_ASPECT) < 1e-5, laff.getX()
assert abs(dialog.getX()) < 1e-6
fov = base.camLens.getFov()
assert abs(fov[1] - vDesign) < 1e-3 and fov[0] > 52, fov

# game code repositions in 4:3 coords while widescreen -> rescaled
laff.setX(-1.0)
run(None)
assert abs(laff.getX() + 1.0 * (16.0 / 9.0) / DESIGN_ASPECT) < 1e-5, laff.getX()
# a new HUD node created while widescreen is rescaled immediately
book = base.aspect2d.attachNewNode('book')
book.setX(1.2)
run(None)
assert abs(book.getX() - 1.2 * (16.0 / 9.0) / DESIGN_ASPECT) < 1e-5

# minigame changes FOV (4:3 design value) while widescreen -> vertical recomputed from it
base.camLens.setFov(80)
run(None)
fov = base.camLens.getFov()
expectedV = math.degrees(2 * math.atan(math.tan(math.radians(40)) / DESIGN_ASPECT))
assert abs(fov[1] - expectedV) < 1e-3 and fov[0] > 80, fov

# back to 4:3: everything returns to design values
aspect[0] = DESIGN_ASPECT
base.camLens.setAspectRatio(aspect[0])
run(None)
assert abs(laff.getX() + 1.0) < 1e-5 and abs(book.getX() - 1.2) < 1e-5
assert abs(base.camLens.getFov()[0] - 80) < 1e-2, base.camLens.getFov()
print('HUD ASPECT CHECKS PASSED')
