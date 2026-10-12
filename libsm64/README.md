# libsm64 for Open Toontown (Mario Mode)

Type `~mario` in the chat box to swap your Toon for Mario, running on real Super Mario 64
physics against the level's collision geometry. Type `~mario` (or `~toon`) again to swap back.
Other players see your Mario too (position + animation state are networked), and your Toon's
nametag stays above Mario's head.

Based on [libsm64](https://github.com/libsm64/libsm64) and the
[libsm64-panda](https://github.com/TheFlowerVixen/libsm64-panda) bindings.

## Setup

Nothing from Nintendo is included. You need two files in this folder:

1. **The libsm64 shared library** – `libsm64.so` (Linux), `libsm64.dylib` (macOS) or `sm64.dll` (Windows).
   * Linux / macOS: run `sh libsm64/build_libsm64.sh` from the repo root.
   * Windows: install [MSYS2](https://www.msys2.org/) (`pacman -S git make mingw-w64-x86_64-gcc python`),
     then in a *MinGW 64-bit* shell run `sh libsm64/build_libsm64.sh`.
     The library must match your Panda3D Python's bitness (x64 for the x64 SDK).
2. **A Super Mario 64 US ROM** (`.z64`, big-endian, sha1 `9bef1128717f958171a4afac3ed78ee2bb4e86ce`),
   saved as `libsm64/sm64.z64`.

Paths can be changed in `etc/Configrc.prc`:

```
sm64-lib-dir libsm64
sm64-rom-path libsm64/sm64.z64
sm64-scale 50                # SM64 units per Panda unit (Mario ~3.2 units tall)
sm64-collision-radius 400    # how far around you level collision is uploaded to libsm64
```

The `etc/toon.dc` file gained two fields (`setMarioMode`, `setMarioState`), so the Astron,
UberDOG, AI and client must all run from this updated source.

## Controls (same as the libsm64-panda example)

| Key            | Action        |
| -------------- | ------------- |
| Arrow keys     | Control stick |
| `Z`            | A (jump)      |
| `X`            | B (punch/dive)|
| `C`            | Z (crouch)    |
| `A` / `D`      | Rotate camera |

The normal Toontown camera follows Mario and slowly swings behind him while he runs.

## How it works

* `SM64Bindings.py` – ctypes bindings for the current libsm64 C API.
* `SM64Manager.py` – loads the library + ROM, builds Mario's texture atlas, extracts every tangible
  `CollisionPolygon` (floor/wall masks) from the scene graph and uploads it to libsm64, and ticks
  all Marios at 30 Hz.
* `SM64Mario.py` – a `NodePath` whose geometry is rebuilt from libsm64's output every tick.
* `LocalMarioController.py` – keyboard input, takes over the Toon's walk controls, keeps the
  (hidden) Toon node on Mario so the camera / nametag / position broadcasts follow him, and sends
  `setMarioState` updates to other clients.
* `toontown/toon/DistributedToon.py` / `LocalToon.py` – `setMarioMode` / `setMarioState` handlers;
  remote clients spawn a libsm64 Mario that follows the Toon's smoothed position and mimics the
  networked action/animation.
* `toontown/spellbook/MagicWordIndex.py` – the `~mario` magic word.

## Known limitations

* Mario can't use doors, tunnels or trolleys (trigger collisions are off while in Mario Mode);
  switch back to your Toon first.
* Moving platforms / elevators are not uploaded as dynamic surfaces.
* SM64 audio is not hooked up yet.
