# Open Toontown x libsm64 — Mario Mode

## Original problem statement
Port libsm64 (via libsm64-panda bindings, https://github.com/TheFlowerVixen/libsm64-panda) into the Open Toontown
source in /app so the player can switch between Mario and their Toon.

## User choices
- Full libsm64 physics; Toontown level collision fed to libsm64; toon hidden while Mario is active
- Toggle via chat magic word `~mario` (aliases `~sm64`, `~mariomode`, `~toon`)
- Networked: other clients render your Mario (new DC fields)
- Files live in /app/libsm64 (user supplies built libsm64 + `sm64.z64` ROM)
- Controls match libsm64-panda example: arrows=stick, Z=A, X=B, C=Z, A/D camera
- Toon's nametag stays above Mario; Toontown camera follows Mario
- Cog battles automatically switch you back to a Toon

## Architecture
- `libsm64/SM64Bindings.py` ctypes bindings for current libsm64.h (int32 surface verts, full MarioState)
- `libsm64/SM64Globals.py` scale (50 SM64 units/Panda unit), Y-up<->Z-up conversions, prc config
- `libsm64/SM64Manager.py` singleton: lib/ROM init, texture atlas, CollisionPolygon extraction (floor/wall masks,
  tangible only, radius-culled, recentering origin), 30Hz fixed-step tick task, periodic surface refresh
- `libsm64/SM64Mario.py` NodePath w/ dynamic Geom fed from libsm64 buffers; local & remote (net-state mimic) modes
- `libsm64/LocalMarioController.py` keys, takes over walk controls (keeps event sphere for cogs/doors/tunnels),
  hidden toon node follows Mario (camera/nametag/pos broadcast), lazy camera follow, net send ~10Hz
- `etc/toon.dc` DistributedToon: `setMarioMode(uint8) broadcast ram ownsend`, `setMarioState(...11 fields) broadcast ownsend`
- `toontown/toon/DistributedToon.py` set/applyMarioMode, remote Mario spawn/retry, hide/show toon geom
- `toontown/toon/LocalToon.py` toggleMarioMode, b_/d_ setters, enable/disableAvatarControls hooks, exitMarioModeForBattle
- `toontown/battle/BattlePlace.py`, `toontown/coghq/CogHQBossBattle.py` call exitMarioModeForBattle on battle entry
- `toontown/spellbook/MagicWordIndex.py` `Mario` magic word (client exec, self only)
- `libsm64/README.md`, `libsm64/build_libsm64.sh`, Configrc.prc keys `sm64-lib-dir`, `sm64-rom-path`, `sm64-scale`, `sm64-collision-radius`

## Verification (June 2026)
- Game cannot run in this container (needs open-toontown Panda3D fork + resources + Astron + ROM)
- `tests/test_sm64_port.py` builds stub libsm64 (`tests/sm64_stub.c`) and runs headless Panda3D checks: PASS
- DC parses; py_compile + ruff F clean on new code; testing agent iteration_1: no issues

## Iteration 2 (June 2026)
- Caps: `~mario wing|metal|vanish|normal` -> sm64_mario_interact_cap / sm64_set_mario_state; flags networked (setMarioState now 12 fields)
- Moving platforms: DynamicSurfaceObject in SM64Manager (name patterns `sm64-dynamic-node-patterns` + motion-promoted static nodes), updated every tick via sm64_surface_object_move
- Sound: sm64_audio_init/tick -> UserDataAudio stream on sfxManagerList[0]; prc `sm64-audio`, `sm64-sfx-volume`
- Hotkey: `sm64-toggle-key` (default `m`) accepted in LocalToon.announceGenerate
- tests/test_sm64_port.py extended; testing agent iteration_2: no issues

## Iteration 3 (June 2026)
- Smooth rotation for moving props: DynamicSurfaceObject bakes scale only and streams position + SM64 ZXY euler
  (sm64EulerFromHpr, verified against libsm64's mtxf_rotate_zxy_and_translate with 50 random HPR/scale cases)

## Backlog
- P1: in-game validation by user (shader colours, nametag height, camera feel, audio latency)
- P2: dynamic surfaces for elevators/moving platforms; Mario attacks interacting with cogs; mesh for toons without libsm64
