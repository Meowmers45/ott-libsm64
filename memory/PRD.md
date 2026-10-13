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
- Hotkey: `sm64-toggle-key` (default `m`) accepted in LocalToon.announceGenerate (REMOVED in iteration 18)
- tests/test_sm64_port.py extended; testing agent iteration_2: no issues

## Iteration 3 (June 2026)
- Smooth rotation for moving props: DynamicSurfaceObject bakes scale only and streams position + SM64 ZXY euler
  (sm64EulerFromHpr, verified against libsm64's mtxf_rotate_zxy_and_translate with 50 random HPR/scale cases)

## Iteration 4 (June 2026)
- Water swimming: SM64Manager collects water regions from named nodes (`sm64-water-node-patterns`), tight bounds give
  surface + footprint, synthetic lake bed cells added to static surfaces; each Mario tick calls
  sm64_set_mario_water_level with the level at Mario's XY (NO_WATER_LEVEL -10000 otherwise)

## Iteration 5 (June 2026)
- Splash effects: SM64Mario tracks submerged state (100 SM64 units under surface) and notifies SM64Manager
  (onMarioEnteredWater/onMarioLeftWater/onMarioDestroyed); libsm64/MarioSplash.py installs a handler that plays
  toontown.effects.Splash + AV_jump_in_water at the surface (installed from DistributedToon/LocalToon on Mario spawn)

## Iteration 6 (June 2026)
- Camera locked behind Mario: toon heading = Mario facing each frame (A/D camera keys + lazy follow removed)
- Chat no longer opens on keystrokes while Mario is controlled (chatEntry backgroundFocus forced 0, restored on
  release); `T` sends 'enterNormalChat' to open the chat box

## Iteration 7 (June 2026)
- Controls now polled via mouseWatcherNode.isButtonDown: Ctrl=A (jump), Delete=B, C=Z, arrows + WASD stick; Toon
  controlManager forced disabled every frame while Mario is controlled
- Camera: smart camera paused during Mario control; camera pinned at (0,-12,5) relative to toon looking at Mario's
  head (prc sm64-camera-distance / sm64-camera-height); restored on release

## Iteration 8 (June 2026)
- Fixed inverted stick: camLook now cam - mario (SM64 camera->yaw is the Mario->camera direction)
- Shtiker Book / Options blocked while marioMode (PublicWalk handlers) with a system message
- Cog disguise: LocalToon.setCogIndex override ends Mario Mode; toggleMarioMode refuses while isDisguised
- Removed fixed `aspect-ratio 1.333333` from Configrc.prc so Panda derives aspect from the window size

## Iteration 9 (June 2026)
- Sleep: toon.forceGotoSleep() when Mario action is ACT_START_SLEEPING/ACT_SLEEPING; otherwise lastMoved refreshed and wakeUp() if asleep

## Iteration 10 (June 2026)
- Snore bubbles: Toon Sleep state (forced when Mario naps) already shows the "zzz" CFThought bubble on the nametag
  that follows Mario; documented, no extra code
- toontown/toonbase/HudAspectAdjuster.py (started from ToonBase, prc `hud-aspect-adjust`): per-frame task scales x of
  aspect2d children by aspect/(4/3) (tracks design positions, handles new/moved nodes) and converts camLens.setFov(h)
  (4:3 design) into setMinFov(vertical) so the horizontal FOV widens with the window; tests/test_hud_aspect.py

## Iteration 11 (June 2026)
- Crash on Mario->Toon fixed: releaseControls now collisionsOn() before controlManager.enable() (GravityWalker asserts)
- Camera jitter fixed: faceAngleToHeading was mirrored; now heading = 180 + deg(yaw) (verified vs SM64 movement dir)
- Loading screen background scaled uniformly to cover the window (ToontownLoadingScreen.fitBackground)
- testing agent iteration_4: all green

## Iteration 12 (June 2026)
- Widescreen panels: HudAspectAdjuster.widescreenFactor(); ShtikerBook.fitToWindow (image_scale x, tabs/arrows at
  edges, re-fit on 'aspectRatioChanged'); AvatarChooser.fitBackground stretches the Pick-A-Toon backdrop card

## Iteration 13 (June 2026)
- Camera jitter on turning fixed: steering heading latched on key press (SM64Mario.setCameraYaw), view heading eases
  to Mario facing (sm64-camera-follow-rate 10/s); testing agent iteration_5 green
- MinigameRulesPanel.fitToWindow stretches the rules banner for widescreen

## Iteration 14 (June 2026)
- Score panels: already spread by HudAspectAdjuster (aspect2d children x scaled by widescreen factor); covered by
  a new regression in tests/test_hud_aspect.py

## Iteration 15 (June 2026)
- Emotes: DistributedToon.setEmoteState -> SM64Mario.playEmote (ACT_UNINITIALIZED no-op action + anim id map,
  75 ticks or until input; Sleepy -> ACT_START_SLEEPING); remote Marios mirror via net state/emote hook
- Laff bridge: LocalMarioController shows Mario health/0x880 * maxHp on laffMeter (adjustFace quietly), restored on release

## Iteration 16 (June 2026)
- Suspend/resume: Place.exitWalk -> LocalToon.suspendMarioMode() (marioMode off, marioSuspended=True); Place.enterWalk ->
  resumeMarioMode() (re-enables only if suspended, not disguised, controls enabled). Covers Shtiker Book/Options,
  every zone change (teleport/tunnel/door/elevator/died), NPC dialogs and Cog battles (exitMarioModeForBattle now
  suspends). Explicit `~mario` toggle clears the pending resume; toggle refuses while controls are disabled.
  PublicWalk no longer blocks the Book in Mario mode.
- Continuous turning: LocalMarioController.steeringReference - left/right (and forward+side) measured against Mario's
  live facing; only "back" latches the view heading (anti flip-flop). Regression in tests/test_sm64_port.py
- Water off by default: prc `sm64-water 0` (SM64Globals.WATER_ENABLED); __collectWaterRegions returns [] so no water
  level / lake bed / splash. Set `sm64-water 1` to re-enable swimming.
- testing agent iteration_6 green

## Iteration 17 (June 2026)
- Mario attacks Cogs: DistributedSuit.__handleToonCollision ignores bumps while Mario is active unless
  SM64Mario.isAttacking() (ACT_FLAG_ATTACKING bit 23: punch/kick/dive/slide kick/ground pound) -> battle starts
- Return whisper: resumeMarioMode whispers TTLocalizer.SM64MarioBack ("It's-a me! Mario's back.") after restore
- Startup gate: ToonBase.checkSM64Available (prc `sm64-required 1`) shows TTGlobalDialog with the missing lib/ROM
  (SM64Manager.getMissingParts) and exits on OK instead of connecting; replaces the remote-Mario placeholder idea
- testing agent iteration_7 green
- Mario/Toon switch button (LocalToon.createMarioButton, quit_button gui, pos (-0.98,0,-0.92) next to the laff meter;
  red "Mario" / blue "Toon", shown by PublicWalk enter, hidden on exit/disguise; requestMarioToggle);
  hover tooltip DirectLabel "Switch to Mario" / "Back to Toon" bound to DGG.ENTER/EXIT (iteration 19)

## Iteration 18 (June 2026)
- Removed the `M` toggle hotkey (`sm64-toggle-key`, SM64Globals.TOGGLE_KEY, LocalToon.acceptMarioHotkey); Mario is
  entered via the on-screen button or `~mario` only

## Iteration 20 (June 2026)
- SM64 sounds: SM64Bindings.sm64_play_sound_global + SOUND_MENU_CLICK_FILE_SELECT / SOUND_ACTION_BONK; SM64Manager.playSound
  (starts tick+audio if needed; audio lingers `sm64-audio-linger` 1.5s via TickStopTaskName after the last Mario leaves)
- Button click (LocalToon.requestMarioToggle) and Cog hit effect (DistributedSuit.__playMarioHitEffect: DustCloud + bonk)
- Street segments: LocalMarioController drives toon.ccTravOnFloor (ccRay2 + camFloorCollisionBroadcaster) every frame
  while controlling, so Street.enterZone ('on-floor') keeps firing with the smart camera paused
- Nametag: DistributedToon.getMarioDisplayName appends "\n\1red\1(Playing As Mario)\2" (TTLocalizer.SM64PlayingAsMario)
  through setDisplayName; refreshed in hideToonForMario/showToonAfterMario

## Backlog
- P1: in-game validation by user (shader colours, nametag height, camera feel, turning feel, audio latency)
- P2: dynamic surfaces for elevators/moving platforms; Mario attacks interacting with cogs; mesh for toons without libsm64
