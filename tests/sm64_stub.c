// Minimal stand-in for libsm64 used only to exercise the Python bindings in CI (no ROM needed).
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

struct SM64Surface { int16_t type; int16_t force; uint16_t terrain; int32_t vertices[3][3]; };
struct SM64MarioInputs { float camLookX, camLookZ; float stickX, stickY; uint8_t buttonA, buttonB, buttonZ; };
struct SM64MarioState { float position[3]; float velocity[3]; float faceAngle; float forwardVelocity; int16_t health;
    uint32_t action; int32_t animID; int16_t animFrame; uint32_t flags; uint32_t particleFlags; int16_t invincTimer; };
struct SM64MarioGeometryBuffers { float *position; float *normal; float *color; float *uv; uint16_t numTrianglesUsed; };

typedef void (*DebugFn)(const char *);
static DebugFn g_debug = NULL;
static struct SM64Surface *g_surfaces = NULL;
static uint32_t g_numSurfaces = 0;
static struct SM64MarioState g_marios[8];
static int g_alive[8];
static int g_romSeen = 0;

void sm64_register_debug_print_function(DebugFn fn) { g_debug = fn; }
void sm64_global_init(const uint8_t *rom, uint8_t *outTexture) {
    g_romSeen = rom[0];
    for (int i = 0; i < 4 * 704 * 64; i += 4) { outTexture[i] = 255; outTexture[i+1] = 0; outTexture[i+2] = 0; outTexture[i+3] = (i / 4) % 2 ? 255 : 0; }
    if (g_debug) g_debug("stub init");
}
void sm64_global_terminate(void) {}
void sm64_static_surfaces_load(const struct SM64Surface *arr, uint32_t n) {
    free(g_surfaces); g_surfaces = malloc(sizeof(struct SM64Surface) * (n ? n : 1));
    memcpy(g_surfaces, arr, sizeof(struct SM64Surface) * n); g_numSurfaces = n;
    char buf[64]; snprintf(buf, sizeof buf, "loaded %u surfaces", n); if (g_debug) g_debug(buf);
}
float sm64_surface_find_floor_height(float x, float y, float z) {
    float best = -11000.0f;
    for (uint32_t i = 0; i < g_numSurfaces; ++i) {
        float sy = (float)g_surfaces[i].vertices[0][1];
        if (sy <= y + 78.0f && sy > best) best = sy;
    }
    return best;
}
int32_t sm64_mario_create(float x, float y, float z) {
    if (sm64_surface_find_floor_height(x, y, z) <= -11000.0f) return -1;
    for (int i = 0; i < 8; ++i) if (!g_alive[i]) {
        g_alive[i] = 1; memset(&g_marios[i], 0, sizeof g_marios[i]);
        g_marios[i].position[0] = x; g_marios[i].position[1] = y; g_marios[i].position[2] = z;
        g_marios[i].health = 0x880; g_marios[i].action = 0x0C400201;
        return i;
    }
    return -1;
}
void sm64_mario_tick(int32_t id, const struct SM64MarioInputs *in, struct SM64MarioState *out, struct SM64MarioGeometryBuffers *geo) {
    struct SM64MarioState *m = &g_marios[id];
    m->position[0] += -in->stickX * 10.0f; m->position[2] += -in->stickY * 10.0f;
    if (in->buttonA) m->action = 0x03000880; /* ACT_JUMP */
    m->animFrame++;
    *out = *m;
    geo->numTrianglesUsed = 2;
    float tri[18] = { 0,0,0, 100,0,0, 0,100,0,  0,0,0, 0,100,0, 0,0,100 };
    for (int i = 0; i < 18; i += 3) { geo->position[i] = m->position[0] + tri[i]; geo->position[i+1] = m->position[1] + tri[i+1]; geo->position[i+2] = m->position[2] + tri[i+2];
        geo->normal[i] = 0; geo->normal[i+1] = 1; geo->normal[i+2] = 0; geo->color[i] = 1; geo->color[i+1] = 0; geo->color[i+2] = 0; }
    for (int i = 0; i < 12; ++i) geo->uv[i] = 0.5f;
}
void sm64_mario_delete(int32_t id) { g_alive[id] = 0; }
void sm64_set_mario_action(int32_t id, uint32_t a) { g_marios[id].action = a; }
void sm64_set_mario_animation(int32_t id, int32_t a) { g_marios[id].animID = a; }
void sm64_set_mario_anim_frame(int32_t id, int16_t f) { g_marios[id].animFrame = f; }
void sm64_set_mario_position(int32_t id, float x, float y, float z) { g_marios[id].position[0] = x; g_marios[id].position[1] = y; g_marios[id].position[2] = z; }
void sm64_set_mario_faceangle(int32_t id, float y) { g_marios[id].faceAngle = y; }
void sm64_set_mario_velocity(int32_t id, float x, float y, float z) { g_marios[id].velocity[0] = x; g_marios[id].velocity[1] = y; g_marios[id].velocity[2] = z; }
void sm64_set_mario_forward_velocity(int32_t id, float v) { g_marios[id].forwardVelocity = v; }
void sm64_set_mario_health(int32_t id, uint16_t h) { g_marios[id].health = h; }
void sm64_set_mario_state(int32_t id, uint32_t f) { g_marios[id].flags = f; }
void sm64_mario_interact_cap(int32_t id, uint32_t capFlag, uint16_t capTime, uint8_t playMusic) { g_marios[id].flags = (g_marios[id].flags & ~0x3Fu) | capFlag | 0x10; }

struct SM64ObjectTransform { float position[3]; float eulerRotation[3]; };
struct SM64SurfaceObject { struct SM64ObjectTransform transform; uint32_t surfaceCount; struct SM64Surface *surfaces; };
static struct { int alive; uint32_t count; struct SM64ObjectTransform t; } g_objs[16];
int g_objMoves = 0;
uint32_t sm64_surface_object_create(const struct SM64SurfaceObject *o) {
    for (uint32_t i = 0; i < 16; ++i) if (!g_objs[i].alive) { g_objs[i].alive = 1; g_objs[i].count = o->surfaceCount; g_objs[i].t = o->transform; return i; }
    return 0;
}
void sm64_surface_object_move(uint32_t id, const struct SM64ObjectTransform *t) { g_objs[id].t = *t; g_objMoves++; }
void sm64_surface_object_delete(uint32_t id) { g_objs[id].alive = 0; }
int stub_object_alive_count(void) { int n = 0; for (int i = 0; i < 16; ++i) n += g_objs[i].alive; return n; }
float stub_object_pos_x(uint32_t id) { return g_objs[id].t.position[0]; }
float stub_object_euler_y(uint32_t id) { return g_objs[id].t.eulerRotation[1]; }

static int g_audioInit = 0;
void sm64_audio_init(const uint8_t *rom) { g_audioInit = 1; }
uint32_t sm64_audio_tick(uint32_t queued, uint32_t desired, int16_t *buf) { if (!g_audioInit) return 0; uint32_t n = queued < desired ? 544 : 528; memset(buf, 0, n * 2 * 2 * sizeof(int16_t)); return n; }
void sm64_set_sound_volume(float v) {}
