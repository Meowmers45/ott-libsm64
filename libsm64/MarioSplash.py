import builtins
from panda3d.core import Point3


class MarioSplashHandler:
    """Plays Toontown's splash ripple + dive sound when a libsm64 Mario enters or leaves water."""
    SoundPath = 'phase_5.5/audio/sfx/AV_jump_in_water.ogg'

    def __init__(self):
        self.sound = builtins.base.loader.loadSfx(self.SoundPath)
        self.splashes = {}

    def __getSplash(self, mario):
        splash = self.splashes.get(id(mario))
        if splash is None:
            from toontown.effects import Splash
            splash = Splash.Splash(builtins.render)
            self.splashes[id(mario)] = splash
        return splash

    def __play(self, mario, surfaceZ, scale, rate, withSound):
        pos = mario.getPandaPos()
        splash = self.__getSplash(mario)
        splash.setPos(Point3(pos[0], pos[1], surfaceZ))
        splash.setScale(scale)
        splash.play(rate)
        if withSound and self.sound is not None:
            builtins.base.playSfx(self.sound, node=splash)

    def onMarioEnteredWater(self, mario, surfaceZ):
        self.__play(mario, surfaceZ, 2.0, 1.0, True)

    def onMarioLeftWater(self, mario, surfaceZ):
        self.__play(mario, surfaceZ, 1.2, 1.5, False)

    def onMarioDestroyed(self, mario):
        splash = self.splashes.pop(id(mario), None)
        if splash is not None:
            splash.destroy()


def install(manager):
    if manager.splashHandler is None:
        manager.splashHandler = MarioSplashHandler()
