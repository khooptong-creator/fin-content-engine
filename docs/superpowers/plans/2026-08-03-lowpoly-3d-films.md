# Low-Poly Narrative 3D Films Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `three` frame backend that renders low-poly narrative 3D films from a story, driven from the existing Next.js GUI.

**Architecture:** A new per-request frame backend writes `compositions/frames/<slug>.html` exactly like the existing 2D backends, so timing, narration, `index.html` emission and the render command are untouched. A cloud LLM writes one `world.js` per film (the persistent set) and one shot module per frame (camera, lighting, timeline), both composed from a hand-written `primitives.js` DSL. A headless render gate rejects any shot that throws or draws nothing, retries it with the error fed back, then raises rather than substituting a placeholder.

**Tech Stack:** Python 3 / FastAPI (worker), Three.js + GSAP (compositions), Playwright (verification gate), Next 16 / React 19 (GUI), Postgres, HyperFrames + ffmpeg (render).

**Spec:** `docs/superpowers/specs/2026-08-03-lowpoly-3d-films-design.md`

## Global Constraints

- Tests must never touch the network. Patch `_build_frames` (the dispatcher), not a backend — patching a backend lets `FRAME_BACKEND` route around the mock and fire live HTTP.
- Never fabricate content when a model fails. A fallback may supply structure, never substance. A failed shot raises; it never becomes a placeholder that renders and validates cleanly.
- Guards on generated output must be absolute, not proportional. A one-frame film scores 100% on every ratio.
- Ollama is reached at `127.0.0.1:11434`, never `localhost` (Windows resolves ::1 first; Ollama binds IPv4 only). Not used by this backend, but unchanged elsewhere.
- Do not run `pytest` while an end-to-end run is in flight — the DB tests truncate tables and will delete the story mid-render.
- Commit source only. Rendered `mp4`/`mp3`/`wav`, `renders/`, `assets/voice/` are gitignored.
- No characters of any kind in v1.
- Film format is `1920x1080` landscape. Shorts stay `1080x1920`.
- `SHOT_RETRIES` default 2 (three attempts total). `MIN_VERIFIED_FRAMES` default 3.
- Commands are PowerShell. Run tests with `cd worker; ..\.venv\Scripts\python.exe -m pytest tests -q`.

---

## File Structure

| File | Responsibility |
|---|---|
| `worker/app/scene3d/__init__.py` | Package marker; re-exports the public surface |
| `worker/app/scene3d/assets/three.module.js` | Vendored Three.js. Copied into each project dir |
| `worker/app/scene3d/assets/primitives.js` | The DSL. Hand-written, owned by us, never generated |
| `worker/app/scene3d/shell.py` | Builds a 3D frame's HTML from a generated shot module |
| `worker/app/scene3d/author.py` | Cloud calls: world prompt, shot prompt, code extraction |
| `worker/app/scene3d/probes.py` | Pure predicates over probe statistics. No I/O, no browser |
| `worker/app/scene3d/verify.py` | Drives a headless browser, captures stats + screenshots |
| `worker/app/scene3d/backend.py` | Orchestrates world → shots → verify → retry for one board |
| `worker/app/youtube.py` | +`three` branch in `_build_frames`, per-request backend arg |
| `worker/app/storyboard.py` | +`story` pacing profile |
| `worker/app/jobs.py` | Job progress records for the GUI |
| `supabase/migrations/007_jobs.sql` | `jobs` table |
| `worker/app/routes.py` | `mode` on generate, `GET /youtube/jobs/{id}` |
| `gui/src/app/films/page.tsx` | Film generation page |
| `gui/src/components/FilmProgress.tsx` | Live stage progress |
| `gui/src/components/ShotInspector.tsx` | Per-shot probe screenshot + generated JS |

Splitting `probes.py` from `verify.py` is deliberate: the predicates are the part that must be exhaustively tested, and keeping them free of browser I/O means they test in milliseconds with no fixtures.

---

### Task 1: Spike — prove Three.js renders deterministically under paused-timeline seek

This is a throwaway spike, not production code. If it fails, the DSL and the
gate are both worthless and the approach needs rethinking, so it runs first and
alone. Nothing else in this plan may start until this task's verdict is recorded.

**Files:**
- Create: `videos/spike-three/index.html`
- Create: `videos/spike-three/package.json`
- Create: `videos/spike-three/compositions/frames/f01-spike.html`
- Create: `docs/superpowers/plans/2026-08-03-spike-result.md`

**Interfaces:**
- Consumes: nothing
- Produces: a recorded verdict. Later tasks rely on the pattern proven here — a `gsap.timeline({paused:true})` whose `onUpdate` calls `renderer.render()`, with no `requestAnimationFrame` anywhere.

- [ ] **Step 1: Download Three.js into the spike project**

```powershell
New-Item -ItemType Directory -Force "F:\Content Creation Project\videos\spike-three\compositions\frames"
Invoke-WebRequest -Uri "https://unpkg.com/three@0.169.0/build/three.module.js" -OutFile "F:\Content Creation Project\videos\spike-three\three.module.js"
```

- [ ] **Step 2: Write the spike frame**

A cube rotating a full turn over the frame's duration. If seeking works, frame
N of the render shows the cube at angle `2π · N / total`. If it is broken, every
rendered frame shows the same angle.

`videos/spike-three/compositions/frames/f01-spike.html`:

```html
<template>
  <style>
    [id="f01-spike-root"] { width:100%; height:100%; position:relative; overflow:hidden; }
    [id="f01-spike-bg"] { position:absolute; inset:0; background:#0B1220; }
    [id="f01-spike-canvas"] { position:absolute; inset:0; width:100%; height:100%; }
  </style>

  <div id="f01-spike-root" data-composition-id="f01-spike"
       data-width="1920" data-height="1080" data-duration="4">
    <div class="clip" id="f01-spike-bg" data-start="0"
         data-duration="4" data-track-index="0"></div>
    <canvas id="f01-spike-canvas"></canvas>
  </div>

  <script type="module">
    import * as THREE from '../../three.module.js';

    const canvas = document.getElementById('f01-spike-canvas');
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(1920, 1080, false);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, 1920 / 1080, 0.1, 100);
    camera.position.set(0, 2, 6);
    camera.lookAt(0, 0, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.0);
    sun.position.set(3, 5, 2);
    scene.add(sun);

    const cube = new THREE.Mesh(
      new THREE.BoxGeometry(2, 2, 2),
      new THREE.MeshLambertMaterial({ color: 0x38BDF8, flatShading: true })
    );
    scene.add(cube);

    // The whole point of the spike: state is driven by the timeline, and the
    // render happens in onUpdate. No requestAnimationFrame, no Date.now().
    const state = { spin: 0 };
    const tl = gsap.timeline({
      paused: true,
      onUpdate: () => {
        cube.rotation.y = state.spin;
        renderer.render(scene, camera);
      },
    });
    tl.to(state, { spin: Math.PI * 2, duration: 4, ease: 'none' }, 0);

    window.__timelines = window.__timelines || {};
    window.__timelines['f01-spike'] = tl;

    renderer.render(scene, camera);
  </script>
</template>
```

- [ ] **Step 3: Write the parent composition**

`videos/spike-three/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * { margin:0; padding:0; box-sizing:border-box; }
      html, body { width:1920px; height:1080px; overflow:hidden; background:#000; }
      #root { position:relative; width:1920px; height:1080px; overflow:hidden; }
      #stage-fill { position:absolute; inset:0; background:#0B1220; }
      .scene { position:absolute; inset:0; width:100%; height:100%; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0"
         data-duration="4" data-width="1920" data-height="1080">
      <div id="stage-fill" class="clip" data-start="0" data-duration="4" data-track-index="0"></div>
      <div id="el-f01-spike" class="scene"
           data-composition-id="f01-spike"
           data-composition-src="compositions/frames/f01-spike.html"
           data-start="0" data-duration="4" data-track-index="1"></div>
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      window.__timelines["main"] = gsap.timeline({ paused: true });
    </script>
  </body>
</html>
```

`videos/spike-three/package.json`:

```json
{ "name": "spike-three", "private": true, "type": "module" }
```

- [ ] **Step 4: Render the spike**

```powershell
cd "F:\Content Creation Project\videos\spike-three"; npx hyperframes render --output renders/spike.mp4
```

Expected: exits 0, produces `renders/spike.mp4` of about 4 seconds.

- [ ] **Step 5: Extract stills and confirm the cube actually moves**

```powershell
cd "F:\Content Creation Project\videos\spike-three"
ffmpeg -y -v error -i renders/spike.mp4 -vf "select='eq(n\,0)+eq(n\,30)+eq(n\,60)+eq(n\,90)',scale=480:-1" -vsync 0 "renders/probe%02d.png"
```

Then open the four PNGs. **Pass:** the cube is at four visibly different angles.
**Fail:** all four are identical (seek is not driving the scene), or all are
black (WebGL is not compositing into the render).

- [ ] **Step 6: Record the verdict**

Write `docs/superpowers/plans/2026-08-03-spike-result.md` stating PASS or FAIL,
which of the four stills differed, the Three.js version, and the HyperFrames
version from `npx hyperframes --version`.

**If FAIL: stop. Do not start Task 2.** Report the failure mode — identical
stills versus black stills point at different fixes (timeline wiring versus
canvas compositing), and the design may need to change.

- [ ] **Step 7: Commit**

```powershell
git add videos/spike-three docs/superpowers/plans/2026-08-03-spike-result.md
git commit -m "spike: prove Three.js renders under HyperFrames paused-timeline seek"
```

---

### Task 2: Vendor Three.js and build the primitives core

**Files:**
- Create: `worker/app/scene3d/__init__.py`
- Create: `worker/app/scene3d/assets/three.module.js`
- Create: `worker/app/scene3d/assets/primitives.js`
- Create: `worker/tests/test_scene3d_assets.py`

**Interfaces:**
- Consumes: the timeline pattern proven in Task 1
- Produces: `primitives.js` exporting `createStage({width, height, palette})` returning `{scene, camera, renderer, tl, state, render}`; geometry helpers `dome`, `cone`, `box`, `cyl`, `sphere`, `plane`; light helpers `sun`, `ambient`, `pointGlow`; `bloom(strength)`; camera helpers on the returned `cam` object.

- [ ] **Step 1: Vendor Three.js**

```powershell
New-Item -ItemType Directory -Force "F:\Content Creation Project\worker\app\scene3d\assets"
Invoke-WebRequest -Uri "https://unpkg.com/three@0.169.0/build/three.module.js" -OutFile "F:\Content Creation Project\worker\app\scene3d\assets\three.module.js"
```

Vendored rather than CDN-loaded because a render must not depend on the network
mid-run. One file copy per project directory.

- [ ] **Step 2: Write the failing test**

`worker/tests/test_scene3d_assets.py`:

```python
"""The DSL is hand-written and copied verbatim into every project.

These tests assert the contract the generated code depends on, so a careless
edit to primitives.js fails here rather than in a render an hour later.
"""
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "app" / "scene3d" / "assets"

REQUIRED_EXPORTS = [
    "createStage", "dome", "cone", "box", "cyl", "sphere", "plane",
    "sun", "ambient", "pointGlow", "bloom",
]


def test_three_is_vendored():
    assert (ASSETS / "three.module.js").exists()


@pytest.mark.parametrize("name", REQUIRED_EXPORTS)
def test_primitives_exports(name):
    source = (ASSETS / "primitives.js").read_text(encoding="utf-8")
    assert f"export function {name}" in source


def test_primitives_never_uses_wall_clock():
    """A render is a seek, not a playback. Wall-clock time desynchronises it."""
    source = (ASSETS / "primitives.js").read_text(encoding="utf-8")
    for banned in ("requestAnimationFrame", "Date.now", "performance.now", "setInterval"):
        assert banned not in source, f"{banned} breaks deterministic seek"


def test_primitives_imports_vendored_three():
    source = (ASSETS / "primitives.js").read_text(encoding="utf-8")
    assert "from './three.module.js'" in source
    assert "unpkg.com" not in source and "cdn.jsdelivr" not in source
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_assets.py -q`
Expected: FAIL — `primitives.js` does not exist.

- [ ] **Step 4: Write primitives.js core**

`worker/app/scene3d/assets/primitives.js`:

```javascript
/**
 * The low-poly DSL. Hand-written and owned by the pipeline; generated shot
 * modules compose these and never import Three.js directly.
 *
 * Art direction is enforced here rather than in the prompt: every primitive
 * builds flat-shaded, untextured material. A model that cannot choose a
 * material cannot drift off-style, and style rules that live in code cannot
 * be prompted away.
 */
import * as THREE from './three.module.js';

const flat = (color) => new THREE.MeshLambertMaterial({ color, flatShading: true });

/** Build the stage every shot renders through. */
export function createStage({ width = 1920, height = 1080, background = '#0B1220' } = {}) {
  const canvas = document.currentScript
    ? document.currentScript.previousElementSibling
    : document.querySelector('canvas');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setSize(width, height, false);
  renderer.setClearColor(new THREE.Color(background), 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 500);
  camera.position.set(0, 3, 10);
  camera.lookAt(0, 0, 0);

  const state = {};
  const render = () => renderer.render(scene, camera);

  // Paused, and rendering only from onUpdate. This is the property Task 1
  // proved; nothing in a shot module may introduce a rAF loop alongside it.
  const tl = gsap.timeline({ paused: true, onUpdate: render });

  const cam = {
    at(x, y, z) { camera.position.set(x, y, z); return cam; },
    lookAt(x, y, z) { camera.lookAt(x, y, z); return cam; },
    dolly(from, to, duration) {
      tl.fromTo(camera.position,
        { x: from[0], y: from[1], z: from[2] },
        { x: to[0], y: to[1], z: to[2], duration, ease: 'power2.inOut' }, 0);
      return cam;
    },
    orbit(radius, height, duration, lookAt = [0, 0, 0]) {
      const o = { a: 0 };
      tl.to(o, {
        a: Math.PI * 2, duration, ease: 'none',
        onUpdate: () => {
          camera.position.set(Math.cos(o.a) * radius, height, Math.sin(o.a) * radius);
          camera.lookAt(lookAt[0], lookAt[1], lookAt[2]);
        },
      }, 0);
      return cam;
    },
  };

  return { THREE, scene, camera, renderer, tl, state, render, cam };
}

export function plane(size, color) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(size, size), flat(color));
  m.rotation.x = -Math.PI / 2;
  return m;
}

export function dome(radius, color, squash = 0.6) {
  const m = new THREE.Mesh(new THREE.SphereGeometry(radius, 12, 8), flat(color));
  m.scale.y = squash;
  return m;
}

export function cone(radius, height, color, segments = 7) {
  return new THREE.Mesh(new THREE.ConeGeometry(radius, height, segments), flat(color));
}

export function box(w, h, d, color) {
  return new THREE.Mesh(new THREE.BoxGeometry(w, h, d), flat(color));
}

export function cyl(radius, height, color, segments = 8) {
  return new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, segments), flat(color));
}

export function sphere(radius, color, detail = 1) {
  return new THREE.Mesh(new THREE.IcosahedronGeometry(radius, detail), flat(color));
}

export function ambient(color = 0xffffff, intensity = 0.45) {
  return new THREE.AmbientLight(color, intensity);
}

export function sun(azimuth, elevation, color = 0xffffff, intensity = 1.0) {
  const light = new THREE.DirectionalLight(color, intensity);
  const r = 30;
  light.position.set(
    Math.cos(azimuth) * Math.cos(elevation) * r,
    Math.sin(elevation) * r,
    Math.sin(azimuth) * Math.cos(elevation) * r,
  );
  return light;
}

export function pointGlow(color, intensity = 2, distance = 20) {
  return new THREE.PointLight(color, intensity, distance);
}

/**
 * Cheap emissive lift. A real UnrealBloomPass needs EffectComposer and a second
 * render target, which doubles render cost for a look this style barely needs;
 * an additive halo sprite reads the same at low poly counts.
 */
export function bloom(mesh, color, strength = 1.4, scale = 1.8) {
  const halo = new THREE.Mesh(
    new THREE.SphereGeometry(scale, 10, 8),
    new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: Math.min(strength * 0.25, 0.6),
      blending: THREE.AdditiveBlending, depthWrite: false,
    }),
  );
  mesh.add(halo);
  return mesh;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_assets.py -q`
Expected: PASS, 15 tests.

- [ ] **Step 6: Commit**

```powershell
git add worker/app/scene3d worker/tests/test_scene3d_assets.py
git commit -m "feat(scene3d): vendor Three.js and add the primitives core"
```

---

### Task 3: Composites, layout and 3D type

**Files:**
- Modify: `worker/app/scene3d/assets/primitives.js`
- Modify: `worker/tests/test_scene3d_assets.py`

**Interfaces:**
- Consumes: `flat`, `box`, `cone`, `cyl`, `sphere`, `dome` from Task 2
- Produces: `tree`, `flower`, `fence`, `path`, `windowPane`, `door`, `building`, `coin`, `vault`, `stack`, `chart3d`, `scatter`, `row`, `place`, `text3d`, `beat`

- [ ] **Step 1: Extend the test's required-export list**

In `worker/tests/test_scene3d_assets.py`, replace `REQUIRED_EXPORTS` with:

```python
REQUIRED_EXPORTS = [
    "createStage", "dome", "cone", "box", "cyl", "sphere", "plane",
    "sun", "ambient", "pointGlow", "bloom",
    "tree", "flower", "fence", "path", "windowPane", "door", "building",
    "coin", "vault", "stack", "chart3d",
    "scatter", "row", "place", "text3d", "beat",
]
```

Add a determinism test — `scatter` must not use `Math.random`, or two renders of
the same film differ:

```python
def test_scatter_is_seeded_not_random():
    source = (ASSETS / "primitives.js").read_text(encoding="utf-8")
    assert "Math.random" not in source, "unseeded randomness breaks reproducible renders"
    assert "export function rand" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_assets.py -q`
Expected: FAIL — missing exports, and `Math.random` absent means `rand` missing.

- [ ] **Step 3: Append the composites to primitives.js**

```javascript
/**
 * Seeded PRNG. Math.random would make two renders of the same film differ,
 * which breaks both the determinism test and any reproducible re-render.
 */
let _seed = 1;
export function seed(n) { _seed = n >>> 0 || 1; }
export function rand() {
  _seed = (_seed * 1664525 + 1013904223) >>> 0;
  return _seed / 4294967296;
}
export function randBetween(lo, hi) { return lo + rand() * (hi - lo); }

export function place(obj, [x, y, z]) { obj.position.set(x, y, z); return obj; }

export function scatter(n, factory, { area = 20, y = 0, parent = null } = {}) {
  const group = parent || new THREE.Group();
  for (let i = 0; i < n; i++) {
    const item = factory(i);
    item.position.set(randBetween(-area, area), y, randBetween(-area, area));
    group.add(item);
  }
  return group;
}

export function row(n, factory, { spacing = 2, axis = 'x' } = {}) {
  const group = new THREE.Group();
  const offset = ((n - 1) * spacing) / 2;
  for (let i = 0; i < n; i++) {
    const item = factory(i);
    const d = i * spacing - offset;
    if (axis === 'x') item.position.x = d;
    else if (axis === 'z') item.position.z = d;
    else item.position.y = d;
    group.add(item);
  }
  return group;
}

export function tree(style = 'conifer', { trunk = '#5A3A22', leaf = '#2E7D32', scale = 1 } = {}) {
  const g = new THREE.Group();
  const t = cyl(0.18 * scale, 1.6 * scale, trunk, 6);
  t.position.y = 0.8 * scale;
  g.add(t);
  if (style === 'conifer') {
    const c = cone(0.9 * scale, 2.4 * scale, leaf, 7);
    c.position.y = 2.4 * scale;
    g.add(c);
  } else {
    for (let i = 0; i < 3; i++) {
      const blob = sphere(randBetween(0.5, 0.8) * scale, leaf, 0);
      blob.position.set(randBetween(-0.4, 0.4) * scale, (1.9 + i * 0.35) * scale, randBetween(-0.4, 0.4) * scale);
      g.add(blob);
    }
  }
  return g;
}

export function flower(color = '#E91E63') {
  const g = new THREE.Group();
  const stem = cyl(0.03, 0.4, '#4CAF50', 5);
  stem.position.y = 0.2;
  const head = sphere(0.12, color, 0);
  head.position.y = 0.45;
  g.add(stem, head);
  return g;
}

export function fence(length = 10, { color = '#6D4C41', posts = 6 } = {}) {
  const g = new THREE.Group();
  const rail1 = box(length, 0.12, 0.08, color); rail1.position.y = 0.9;
  const rail2 = box(length, 0.12, 0.08, color); rail2.position.y = 0.5;
  g.add(rail1, rail2);
  const spacing = length / (posts - 1);
  for (let i = 0; i < posts; i++) {
    const p = box(0.14, 1.3, 0.14, color);
    p.position.set(-length / 2 + i * spacing, 0.65, 0);
    g.add(p);
  }
  return g;
}

export function path(length = 12, width = 1.6, color = '#9E9E9E', steps = 8) {
  const g = new THREE.Group();
  const seg = length / steps;
  for (let i = 0; i < steps; i++) {
    const s = box(width, 0.08, seg * 0.8, color);
    s.position.set(0, 0.04, -length / 2 + i * seg);
    g.add(s);
  }
  return g;
}

export function windowPane(radius = 0.5, { frame = '#BCAAA4', glass = '#FFF3C4' } = {}) {
  const g = new THREE.Group();
  const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, radius * 0.12, 6, 16), flat(frame));
  const pane = new THREE.Mesh(new THREE.CircleGeometry(radius, 16),
    new THREE.MeshBasicMaterial({ color: glass }));
  pane.position.z = -0.02;
  const barH = box(radius * 2, radius * 0.1, 0.06, frame);
  const barV = box(radius * 0.1, radius * 2, 0.06, frame);
  g.add(ring, pane, barH, barV);
  return g;
}

export function door(radius = 1.1, { panel = '#1B5E20', frame = '#BCAAA4' } = {}) {
  const g = new THREE.Group();
  const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, radius * 0.1, 6, 20), flat(frame));
  const face = new THREE.Mesh(new THREE.CircleGeometry(radius, 20), flat(panel));
  face.position.z = -0.02;
  const knob = sphere(radius * 0.07, '#FFD54F', 0);
  knob.position.set(radius * 0.45, 0, 0.06);
  g.add(ring, face, knob);
  return g;
}

export function building(w = 3, h = 5, d = 3, { wall = '#90A4AE', roof = '#455A64' } = {}) {
  const g = new THREE.Group();
  const body = box(w, h, d, wall); body.position.y = h / 2;
  const top = cone(Math.max(w, d) * 0.8, h * 0.4, roof, 4);
  top.position.y = h + h * 0.2; top.rotation.y = Math.PI / 4;
  g.add(body, top);
  return g;
}

export function coin(radius = 0.5, color = '#FFC107') {
  const m = cyl(radius, radius * 0.16, color, 14);
  m.rotation.x = Math.PI / 2;
  return m;
}

export function vault(size = 3, { body = '#546E7A', dial = '#CFD8DC' } = {}) {
  const g = new THREE.Group();
  const shell = box(size, size, size * 0.6, body); shell.position.y = size / 2;
  const wheel = cyl(size * 0.22, 0.18, dial, 12);
  wheel.rotation.x = Math.PI / 2;
  wheel.position.set(0, size / 2, size * 0.32);
  g.add(shell, wheel);
  return g;
}

export function stack(count = 8, factory = () => coin(), { gap = 0.18 } = {}) {
  const g = new THREE.Group();
  for (let i = 0; i < count; i++) {
    const item = factory(i);
    item.position.y = i * gap;
    g.add(item);
  }
  return g;
}

export function chart3d(values, { color = '#38BDF8', spacing = 1.2, maxHeight = 5 } = {}) {
  const g = new THREE.Group();
  const peak = Math.max(...values, 1);
  values.forEach((v, i) => {
    const h = (v / peak) * maxHeight;
    const bar = box(0.8, h, 0.8, color);
    bar.position.set(i * spacing - ((values.length - 1) * spacing) / 2, h / 2, 0);
    g.add(bar);
  });
  return g;
}

/**
 * Extruded-look 3D text without a font loader. TextGeometry needs an async
 * JSON font fetch, which is another network dependency and another failure
 * mode inside a render; layered planes read the same at this poly budget.
 */
export function text3d(str, { color = '#F8FAFC', size = 1, depth = 0.12, layers = 4 } = {}) {
  const g = new THREE.Group();
  const canvas = document.createElement('canvas');
  canvas.width = 1024; canvas.height = 256;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = color;
  ctx.font = `italic 140px Georgia, "Times New Roman", serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(str, 512, 128);
  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  for (let i = 0; i < layers; i++) {
    const mat = new THREE.MeshBasicMaterial({
      map: tex, transparent: true, opacity: i === layers - 1 ? 1 : 0.35, depthWrite: i === layers - 1,
    });
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(size * 4, size), mat);
    plate.position.z = -i * (depth / layers);
    g.add(plate);
  }
  return g;
}

/** Schedule a callback at an absolute time on the shot's timeline. */
export function beat(tl, t, fn) { tl.call(fn, [], t); return tl; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_assets.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/scene3d/assets/primitives.js worker/tests/test_scene3d_assets.py
git commit -m "feat(scene3d): composites, seeded layout helpers and 3D type"
```

---

### Task 4: The 3D frame shell

**Files:**
- Create: `worker/app/scene3d/shell.py`
- Create: `worker/tests/test_scene3d_shell.py`

**Interfaces:**
- Consumes: nothing from earlier Python tasks
- Produces: `render_3d_frame(slug: str, duration: float, shot_js: str, subtitle: str, width: int = 1920, height: int = 1080) -> str`

- [ ] **Step 1: Write the failing test**

`worker/tests/test_scene3d_shell.py`:

```python
from app.scene3d.shell import render_3d_frame


def test_shell_declares_the_composition_contract():
    html = render_3d_frame("f01-open", 6.5, "// shot", "Hello there")
    assert 'data-composition-id="f01-open"' in html
    assert 'data-duration="6.5"' in html
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html
    assert html.lstrip().startswith("<template>")


def test_shell_embeds_the_shot_module_and_subtitle():
    html = render_3d_frame("f02-turn", 4.0, "stage.tl.to(state, {x: 1});", "A line of narration")
    assert "stage.tl.to(state, {x: 1});" in html
    assert "A line of narration" in html


def test_shell_escapes_subtitle_html():
    html = render_3d_frame("f03", 3.0, "// shot", 'He said "<b>no</b>" & left')
    assert "<b>no</b>" not in html
    assert "&lt;b&gt;no&lt;/b&gt;" in html


def test_shell_registers_exactly_one_timeline_under_the_slug():
    html = render_3d_frame("f04-x", 3.0, "// shot", "x")
    assert html.count('window.__timelines["f04-x"]') == 1


def test_shell_imports_are_relative_to_the_project_root():
    html = render_3d_frame("f05", 3.0, "// shot", "x")
    assert "'../../primitives.js'" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_shell.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scene3d.shell'`.

- [ ] **Step 3: Write shell.py**

```python
"""Wrap a generated shot module in the HyperFrames sub-composition contract.

The 3D analogue of `archetypes._shell`. Everything the renderer requires lives
here so a generated shot cannot get it wrong: the <template> wrapper, the
slug-prefixed root, the canvas, the burned-in subtitle, and exactly one paused
timeline registered under the composition id.

The shot module never imports Three.js directly — it receives a `stage` built
by primitives.js, which is what keeps the art direction and the seek-safety
properties out of the model's reach.
"""

from __future__ import annotations

import html

SUBTITLE_CSS = """
    [id="{slug}-subtitle"] {{
      position: absolute;
      left: 8%;
      right: 8%;
      bottom: 7%;
      text-align: center;
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 30px;
      line-height: 1.4;
      color: #F5F5F5;
      text-shadow: 0 2px 6px rgba(0,0,0,0.85);
      pointer-events: none;
    }}
"""


def render_3d_frame(
    slug: str,
    duration: float,
    shot_js: str,
    subtitle: str,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Build one frame's HTML from a generated shot module."""
    return f"""<template>
  <style>
    [id="{slug}-root"] {{
      width: 100%;
      height: 100%;
      position: relative;
      overflow: hidden;
    }}
    [id="{slug}-canvas"] {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
    }}
{SUBTITLE_CSS.format(slug=slug)}
  </style>

  <div id="{slug}-root" data-composition-id="{slug}"
       data-width="{width}" data-height="{height}" data-duration="{duration}">
    <canvas id="{slug}-canvas" class="clip" data-start="0"
            data-duration="{duration}" data-track-index="0"></canvas>
    <div id="{slug}-subtitle">{html.escape(subtitle, quote=True)}</div>
  </div>

  <script type="module">
    import * as P from '../../primitives.js';

    const canvas = document.getElementById('{slug}-canvas');
    const stage = P.createStage({{ width: {width}, height: {height}, canvas }});
    const {{ scene, camera, tl, state, cam }} = stage;
    P.seed({abs(hash(slug)) % 100000});

    // ---- generated shot module ----
{shot_js}
    // ---- end generated shot module ----

    window.__timelines = window.__timelines || {{}};
    window.__timelines["{slug}"] = tl;
    stage.render();
  </script>
</template>
"""
```

Note: `createStage` must accept an explicit `canvas` option. Update the
signature in `primitives.js` from `createStage({ width, height, background })`
to `createStage({ width, height, background, canvas })` and use the passed
canvas when present, falling back to the existing lookup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_shell.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/scene3d/shell.py worker/app/scene3d/assets/primitives.js worker/tests/test_scene3d_shell.py
git commit -m "feat(scene3d): frame shell wrapping generated shot modules"
```

---

### Task 5: Story pacing profile and landscape format

**Files:**
- Modify: `worker/app/storyboard.py:56-63`
- Modify: `worker/tests/test_storyboard.py`

**Interfaces:**
- Consumes: `Pacing`, `PACING_PROFILES` from `storyboard.py`
- Produces: `PACING_PROFILES["story"]`

- [ ] **Step 1: Write the failing test**

Append to `worker/tests/test_storyboard.py`:

```python
from app.storyboard import PACING_PROFILES, Storyboard, resolve_pacing


def test_story_pacing_profile_exists():
    assert "story" in PACING_PROFILES


def test_story_pacing_breathes_longer_than_news():
    story, news = PACING_PROFILES["story"], PACING_PROFILES["news"]
    assert story.floor > news.floor
    assert story.soft_ceiling > news.soft_ceiling


def test_story_pacing_resolves_from_frontmatter():
    board = Storyboard(meta={"pacing": "story"})
    assert resolve_pacing(None, board) is PACING_PROFILES["story"]


def test_landscape_format_is_read_from_frontmatter():
    board = Storyboard(meta={"format": "1920x1080"})
    assert board.width == 1920
    assert board.height == 1080
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_storyboard.py -q`
Expected: FAIL — `"story"` not in `PACING_PROFILES`.

- [ ] **Step 3: Add the profile**

In `worker/app/storyboard.py`, inside `PACING_PROFILES`, after the `"news"` entry:

```python
    # Narrated story films. The camera is doing the work, so a shot can hold
    # far longer than an explainer card without going dead — and cutting on
    # every clause would destroy the sense of a continuous place.
    "story": Pacing(floor=4.0, soft_ceiling=20.0, lead_in=0.4, tail=0.8),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_storyboard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/storyboard.py worker/tests/test_storyboard.py
git commit -m "feat(storyboard): story pacing profile for narrated films"
```

---

### Task 6: Probe predicates

The part that must be exhaustively tested, kept free of browser I/O so it runs
in milliseconds with no fixtures.

**Files:**
- Create: `worker/app/scene3d/probes.py`
- Create: `worker/tests/test_scene3d_probes.py`

**Interfaces:**
- Consumes: nothing
- Produces: `ProbeStats` dataclass with fields `t: float`, `mean_luma: float`, `variance: float`, `phash: str`; `ShotVerdict` dataclass with `ok: bool` and `reason: str`; `judge_shot(probes: list[ProbeStats]) -> ShotVerdict`; `frames_are_distinct(a: ProbeStats, b: ProbeStats) -> bool`; thresholds `MIN_MEAN_LUMA`, `MIN_VARIANCE`, `MAX_HAMMING_FOR_IDENTICAL`.

- [ ] **Step 1: Write the failing test**

`worker/tests/test_scene3d_probes.py`:

```python
"""The gate's judgement, tested without a browser.

Probe statistics are computed in-page and handed back as plain numbers, so
every predicate here is a pure function over a dataclass. That is the whole
reason this module is separate from verify.py.
"""
import pytest

from app.scene3d.probes import (
    ProbeStats,
    frames_are_distinct,
    judge_shot,
)


def p(t=0.5, mean_luma=0.4, variance=0.05, phash="0" * 16):
    return ProbeStats(t=t, mean_luma=mean_luma, variance=variance, phash=phash)


def test_healthy_shot_passes():
    probes = [
        p(0.1, phash="0000ffff00001111"),
        p(0.5, phash="0000ffff00003333"),
        p(0.9, phash="0000ffff0000cccc"),
    ]
    assert judge_shot(probes).ok


def test_black_frame_is_rejected():
    probes = [p(0.1, mean_luma=0.002), p(0.5), p(0.9)]
    verdict = judge_shot(probes)
    assert not verdict.ok
    assert "black" in verdict.reason


def test_uniform_fill_is_rejected():
    """Camera inside geometry, or staring into empty fog."""
    probes = [p(0.1, variance=0.0001), p(0.5), p(0.9)]
    verdict = judge_shot(probes)
    assert not verdict.ok
    assert "uniform" in verdict.reason


def test_completely_static_shot_is_rejected():
    """All three probes identical means the timeline never drove the render."""
    probes = [p(0.1, phash="abcd" * 4), p(0.5, phash="abcd" * 4), p(0.9, phash="abcd" * 4)]
    verdict = judge_shot(probes)
    assert not verdict.ok
    assert "static" in verdict.reason


def test_too_few_probes_is_rejected():
    assert not judge_shot([p(0.5)]).ok


def test_empty_probes_is_rejected():
    """An absolute check. A shot that produced no probes is not a passing shot."""
    assert not judge_shot([]).ok


def test_distinctness_between_neighbouring_shots():
    a = p(phash="0000000000000000")
    b = p(phash="ffffffffffffffff")
    assert frames_are_distinct(a, b)


def test_neighbouring_shots_that_look_identical_are_not_distinct():
    a = p(phash="0f0f0f0f0f0f0f0f")
    b = p(phash="0f0f0f0f0f0f0f0f")
    assert not frames_are_distinct(a, b)


@pytest.mark.parametrize("bad", ["", "xyz", "0" * 15])
def test_malformed_phash_is_not_distinct(bad):
    """Refuse to call a shot distinct on the basis of a hash we cannot read."""
    assert not frames_are_distinct(p(phash=bad), p(phash="0" * 16))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_probes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scene3d.probes'`.

- [ ] **Step 3: Write probes.py**

```python
"""Predicates over rendered-pixel statistics.

The 2D backends could only ever measure proportions of their output — and a
proportion cannot detect a degraded *input*, which is how a one-frame stub
scored 100% on every ratio and shipped. 3D produces inspectable pixels, so the
checks here are absolute and per-shot: does it draw, does it vary, does it move.

Statistics are computed in-page by the browser and arrive as plain numbers, so
nothing in this module does I/O or needs an image library.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# A frame darker than this is unlit, or the camera is inside geometry.
MIN_MEAN_LUMA = float(os.environ.get("MIN_MEAN_LUMA", "0.02"))
# A frame flatter than this is a single fill: void, fog, or an inside-out mesh.
MIN_VARIANCE = float(os.environ.get("MIN_VARIANCE", "0.0008"))
# Perceptual-hash distance at or below this counts as "the same picture".
MAX_HAMMING_FOR_IDENTICAL = int(os.environ.get("MAX_HAMMING_FOR_IDENTICAL", "4"))

PHASH_LEN = 16


@dataclass(frozen=True)
class ProbeStats:
    """One screenshot's summary, computed in-page."""

    t: float
    mean_luma: float
    variance: float
    phash: str


@dataclass(frozen=True)
class ShotVerdict:
    ok: bool
    reason: str = ""


def _hamming(a: str, b: str) -> int | None:
    if len(a) != PHASH_LEN or len(b) != PHASH_LEN:
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


def frames_are_distinct(a: ProbeStats, b: ProbeStats) -> bool:
    """True when two probes are visibly different pictures.

    An unreadable hash returns False rather than True: refusing to certify
    distinctness we cannot measure is the safe direction, since the caller
    uses this to reject repetition.
    """
    distance = _hamming(a.phash, b.phash)
    if distance is None:
        return False
    return distance > MAX_HAMMING_FOR_IDENTICAL


def judge_shot(probes: list[ProbeStats]) -> ShotVerdict:
    """Decide whether one shot rendered something worth keeping."""
    if len(probes) < 3:
        return ShotVerdict(False, f"expected 3 probes, got {len(probes)}")

    for probe in probes:
        if probe.mean_luma < MIN_MEAN_LUMA:
            return ShotVerdict(False, f"black frame at t={probe.t} (luma {probe.mean_luma:.4f})")
        if probe.variance < MIN_VARIANCE:
            return ShotVerdict(False, f"uniform fill at t={probe.t} (variance {probe.variance:.6f})")

    first, last = probes[0], probes[-1]
    if not frames_are_distinct(first, last):
        return ShotVerdict(False, "static shot: first and last probes are the same picture")

    return ShotVerdict(True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_probes.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/scene3d/probes.py worker/tests/test_scene3d_probes.py
git commit -m "feat(scene3d): absolute per-shot probe predicates"
```

---

### Task 7: The headless verification gate

**Files:**
- Create: `worker/app/scene3d/verify.py`
- Create: `worker/tests/test_scene3d_verify.py`
- Modify: `worker/pyproject.toml`

**Interfaces:**
- Consumes: `ProbeStats`, `ShotVerdict`, `judge_shot` from Task 6
- Produces: `async verify_shot(frame_path: Path, duration: float, out_dir: Path) -> tuple[ShotVerdict, list[ProbeStats], list[str]]` returning the verdict, the probe stats, and captured console errors. Screenshots are written to `out_dir` as `<stem>-p{0,1,2}.png`.

Playwright drives the browser rather than the HyperFrames CLI: the CLI's
snapshot flags are not part of this plan's verified surface, and an explicit
driver keeps the interface swappable if `hyperframes snapshot` turns out to be
sufficient later.

- [ ] **Step 1: Add the dependency**

In `worker/pyproject.toml`, add `"playwright>=1.47"` to the dependency list, then:

```powershell
cd "F:\Content Creation Project\worker"; ..\.venv\Scripts\python.exe -m pip install "playwright>=1.47"; ..\.venv\Scripts\python.exe -m playwright install chromium
```

- [ ] **Step 2: Write the failing test**

`worker/tests/test_scene3d_verify.py`. The browser is patched out — these tests
assert the wiring, not Chromium:

```python
"""Gate wiring. The browser is patched; Chromium is exercised in the e2e run."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.scene3d.probes import ProbeStats
from app.scene3d.verify import PROBE_FRACTIONS, verify_shot


def _stats(phash):
    return {"mean_luma": 0.4, "variance": 0.05, "phash": phash}


@pytest.mark.asyncio
async def test_verify_shot_passes_a_healthy_frame(tmp_path):
    page = AsyncMock()
    page.evaluate = AsyncMock(side_effect=[
        _stats("0000ffff00001111"),
        _stats("0000ffff00003333"),
        _stats("0000ffff0000cccc"),
    ])
    with patch("app.scene3d.verify._open_page", return_value=(page, [])):
        verdict, probes, errors = await verify_shot(tmp_path / "f01.html", 6.0, tmp_path)
    assert verdict.ok
    assert len(probes) == 3
    assert errors == []


@pytest.mark.asyncio
async def test_console_error_fails_the_shot_before_probing(tmp_path):
    """A shot that threw is rejected on the error, not on how it happened to look."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=_stats("0000ffff00001111"))
    with patch("app.scene3d.verify._open_page",
               return_value=(page, ["TypeError: P.hill is not a function"])):
        verdict, probes, errors = await verify_shot(tmp_path / "f01.html", 6.0, tmp_path)
    assert not verdict.ok
    assert "TypeError" in verdict.reason
    assert errors


@pytest.mark.asyncio
async def test_probes_are_taken_at_the_declared_fractions(tmp_path):
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=_stats("0000ffff00001111"))
    with patch("app.scene3d.verify._open_page", return_value=(page, [])):
        await verify_shot(tmp_path / "f01.html", 10.0, tmp_path)
    seeked = [c.args[1] for c in page.evaluate.call_args_list]
    assert seeked == [f * 10.0 for f in PROBE_FRACTIONS]


@pytest.mark.asyncio
async def test_probe_stats_are_returned_as_dataclasses(tmp_path):
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=_stats("0000ffff00001111"))
    with patch("app.scene3d.verify._open_page", return_value=(page, [])):
        _, probes, _ = await verify_shot(tmp_path / "f01.html", 3.0, tmp_path)
    assert all(isinstance(p, ProbeStats) for p in probes)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_verify.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scene3d.verify'`.

- [ ] **Step 4: Write verify.py**

```python
"""Render a generated shot in a real browser and decide whether it drew anything.

This is the mitigation the DSL approach is built on. Letting a model write
JavaScript reopens the malformed-composition failure class that the 2D
archetypes exclude by construction, and this gate is what closes it again: a
shot that throws, draws nothing, or never moves is rejected before it can reach
a render that would look perfectly valid.

Statistics are computed in-page from the canvas so Python needs no image
library; the PNG is written only so the GUI's shot inspector has something to
show a human.
"""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from pathlib import Path

import structlog

from app.scene3d.probes import ProbeStats, ShotVerdict, judge_shot

log = structlog.get_logger()

# Early, middle and late. Enough to catch "never moves" without paying for more.
PROBE_FRACTIONS = (0.1, 0.5, 0.9)

# Computed in-page: mean luminance, variance, and a 64-bit average hash.
_STATS_JS = """
(slug, t) => {
  const tl = window.__timelines && window.__timelines[slug];
  if (tl) { tl.seek(t); }
  const canvas = document.getElementById(slug + '-canvas');
  if (!canvas) { return { mean_luma: 0, variance: 0, phash: '' }; }

  const small = document.createElement('canvas');
  small.width = 8; small.height = 8;
  const ctx = small.getContext('2d');
  ctx.drawImage(canvas, 0, 0, 8, 8);
  const data = ctx.getImageData(0, 0, 8, 8).data;

  const luma = [];
  for (let i = 0; i < data.length; i += 4) {
    luma.push((0.2126 * data[i] + 0.7152 * data[i+1] + 0.0722 * data[i+2]) / 255);
  }
  const mean = luma.reduce((a, b) => a + b, 0) / luma.length;
  const variance = luma.reduce((a, b) => a + (b - mean) ** 2, 0) / luma.length;

  let bits = '';
  for (const l of luma) { bits += (l > mean ? '1' : '0'); }
  let phash = '';
  for (let i = 0; i < 64; i += 4) {
    phash += parseInt(bits.slice(i, i + 4), 2).toString(16);
  }
  return { mean_luma: mean, variance, phash };
}
"""


@asynccontextmanager
async def _browser():
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--use-gl=angle", "--enable-unsafe-swiftshader", "--hide-scrollbars"]
        )
        try:
            yield browser
        finally:
            await browser.close()


async def _open_page(browser, frame_path: Path):
    """Load a frame and collect anything it complained about."""
    page = await browser.new_page(viewport={"width": 1920, "height": 1080})
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(frame_path.resolve().as_uri())
    await page.wait_for_timeout(400)
    return page, errors


async def verify_shot(
    frame_path: Path, duration: float, out_dir: Path
) -> tuple[ShotVerdict, list[ProbeStats], list[str]]:
    """Load one generated frame, probe it three times, and judge it."""
    slug = frame_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    async with _browser() as browser:
        page, errors = await _open_page(browser, frame_path)

        if errors:
            # Reject on the exception, never on how the broken frame happened to
            # look. A shot that threw may still paint a plausible background.
            return ShotVerdict(False, f"runtime error: {errors[0]}"), [], errors

        probes: list[ProbeStats] = []
        for i, fraction in enumerate(PROBE_FRACTIONS):
            t = fraction * duration
            raw = await page.evaluate(_STATS_JS, slug, t)
            probes.append(ProbeStats(t=t, **raw))
            shot = await page.screenshot()
            (out_dir / f"{slug}-p{i}.png").write_bytes(shot)

        await page.close()

    verdict = judge_shot(probes)
    log.info("shot_verified", slug=slug, ok=verdict.ok, reason=verdict.reason)
    return verdict, probes, errors
```

Note: `page.evaluate` in Playwright takes a single argument, so the two-argument
form above needs the call written as `page.evaluate(_STATS_JS, [slug, t])` with
the JS signature `([slug, t]) => {...}`. Use the array form in the
implementation, and update the test's `PROBE_FRACTIONS` assertion to read
`c.args[1][1]`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_verify.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 6: Confirm no network in the suite**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests -q`
Expected: all previously passing tests still pass. No test launches Chromium.

- [ ] **Step 7: Commit**

```powershell
git add worker/app/scene3d/verify.py worker/tests/test_scene3d_verify.py worker/pyproject.toml
git commit -m "feat(scene3d): headless render gate with in-page pixel probes"
```

---

### Task 8: The world call

**Files:**
- Create: `worker/app/scene3d/author.py`
- Create: `worker/tests/test_scene3d_author.py`

**Interfaces:**
- Consumes: `Storyboard` from `app.storyboard`
- Produces: `async author_world(board: Storyboard) -> str`; `extract_js(text: str) -> str`; `WORLD_SYSTEM_PROMPT`; `SceneAuthoringError`

- [ ] **Step 1: Write the failing test**

`worker/tests/test_scene3d_author.py`:

```python
import pytest

from app.scene3d.author import SceneAuthoringError, extract_js


def test_extract_js_unwraps_a_fenced_block():
    assert extract_js("Here you go:\n```javascript\nconst a = 1;\n```\n") == "const a = 1;"


def test_extract_js_accepts_a_bare_js_fence():
    assert extract_js("```js\nconst a = 1;\n```") == "const a = 1;"


def test_extract_js_accepts_unfenced_code():
    assert extract_js("const a = 1;") == "const a = 1;"


def test_extract_js_rejects_empty_output():
    """A failed model must raise, never yield an empty module that renders black."""
    with pytest.raises(SceneAuthoringError):
        extract_js("```javascript\n\n```")


def test_extract_js_rejects_prose_with_no_code():
    with pytest.raises(SceneAuthoringError):
        extract_js("I'm sorry, I can't help with that.")


def test_extract_js_rejects_a_direct_three_import():
    """Bypassing the DSL bypasses the flat-shading rules the style depends on."""
    with pytest.raises(SceneAuthoringError):
        extract_js("```javascript\nimport * as THREE from 'three';\nconst a = 1;\n```")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_author.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scene3d.author'`.

- [ ] **Step 3: Write author.py's world half**

```python
"""Cloud authoring of world and shot modules.

Composing a 3D scene is thousands of tokens of spatial reasoning, well past a
7B, so this stage is cloud-only — the documented exception to the local-first
split. `qwen2.5:7b` keeps the 2D archetype path.

Nothing here ever fabricates a module on failure. A generated film whose scenes
were invented by a fallback renders and validates perfectly, which is exactly
how a total upstream outage once produced a publishable draft.
"""

from __future__ import annotations

import os
import re

import structlog

log = structlog.get_logger()

SCENE_MODEL = os.environ.get("SCENE_MODEL", "gemini-2.0-flash")

_FENCE = re.compile(r"```(?:javascript|js)?\s*\n(.*?)```", re.DOTALL)
_BANNED_IMPORTS = ("from 'three'", 'from "three"', "three.module.js")


class SceneAuthoringError(RuntimeError):
    """The model did not return usable scene code."""


def extract_js(text: str) -> str:
    """Pull a JavaScript module out of a model response, or refuse it."""
    match = _FENCE.search(text or "")
    code = (match.group(1) if match else (text or "")).strip()

    if not code:
        raise SceneAuthoringError("model returned no code")
    if not any(token in code for token in ("=", "(", "{")):
        raise SceneAuthoringError(f"model returned prose, not code: {code[:120]!r}")
    for banned in _BANNED_IMPORTS:
        if banned in code:
            raise SceneAuthoringError(
                "generated code imports Three.js directly; it must use the DSL"
            )
    return code


WORLD_SYSTEM_PROMPT = """You are a technical director building a low-poly 3D world for a narrated short film.

You write ONE JavaScript module that builds the film's persistent set: the
terrain, buildings, standing props and palette that every shot will reuse.

AVAILABLE API — you may use ONLY these, already imported as `P`:
  Stage:    P.createStage, P.seed, P.rand, P.randBetween
  Geometry: P.plane P.dome P.cone P.box P.cyl P.sphere
  Composite:P.tree P.flower P.fence P.path P.windowPane P.door P.building
  Finance:  P.coin P.vault P.stack P.chart3d
  Layout:   P.scatter P.row P.place
  Light:    P.sun P.ambient P.pointGlow P.bloom
  Type:     P.text3d
  Timing:   P.beat

HARD RULES:
- NEVER import Three.js. NEVER construct THREE.* directly. Use only P.*
- NEVER use requestAnimationFrame, Date.now, performance.now or setInterval.
- NEVER use Math.random. Use P.rand() so renders are reproducible.
- NO humanoid characters of any kind.
- Export exactly: `export function buildWorld(P) { ... return { root, palette }; }`
  where `root` is a THREE.Group returned by P helpers and `palette` is an
  object of hex strings the shots will reuse.

STYLE: flat-shaded low-poly. Rolling hills as squashed domes, conifers as cones,
scattered flowers, soft dusk palettes. Think a storybook diorama, not realism.

Return ONLY the JavaScript module in a ```javascript fence."""


async def author_world(board) -> str:
    """Write the film's persistent set. One call per film."""
    prompt = (
        f"FILM TITLE: {board.title}\n"
        f"DIRECTION: {board.direction or 'none given'}\n\n"
        "SCENES THIS WORLD MUST SUPPORT:\n"
        + "\n".join(f"{i}. {f.scene or f.voiceover}" for i, f in enumerate(board.frames, 1))
        + "\n\nBuild one world that every scene above can be filmed inside."
    )
    text = await _call_model(WORLD_SYSTEM_PROMPT, prompt)
    code = extract_js(text)
    log.info("world_authored", title=board.title, chars=len(code))
    return code


async def _call_model(system: str, user: str) -> str:
    """Single cloud call. Retries transient failures, then raises."""
    import asyncio

    from google import genai
    from google.genai import types
    from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

    from app.youtube import _is_retryable

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _once() -> str:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=SCENE_MODEL,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.7),
        )
        return response.text or ""

    return await _once()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_author.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/scene3d/author.py worker/tests/test_scene3d_author.py
git commit -m "feat(scene3d): world authoring with strict code extraction"
```

---

### Task 9: The shot call with error-feedback retry

**Files:**
- Modify: `worker/app/scene3d/author.py`
- Modify: `worker/tests/test_scene3d_author.py`

**Interfaces:**
- Consumes: `extract_js`, `_call_model`, `SceneAuthoringError` from Task 8
- Produces: `async author_shot(board, frame, world_code: str, prior_shots: list[str], last_error: str | None = None) -> str`; `SHOT_SYSTEM_PROMPT`

- [ ] **Step 1: Write the failing test**

Append to `worker/tests/test_scene3d_author.py`:

```python
from unittest.mock import AsyncMock, patch

from app.scene3d.author import author_shot
from app.storyboard import Frame, Storyboard


def _board():
    board = Storyboard(meta={"title": "The Vault"}, direction="dusk, warm")
    board.frames = [
        Frame(index=1, title="Open", voiceover="It began quietly.", scene="wide of the hill"),
        Frame(index=2, title="Turn", voiceover="Then it did not.", scene="push in on the door"),
    ]
    return board


@pytest.mark.asyncio
async def test_shot_prompt_carries_world_and_prior_shots():
    board = _board()
    with patch("app.scene3d.author._call_model",
               new=AsyncMock(return_value="```js\ncam.at(0,2,8);\n```")) as call:
        await author_shot(board, board.frames[1], "export function buildWorld(){}", ["cam.orbit(9,3,6);"])
    user_prompt = call.await_args.args[1]
    assert "buildWorld" in user_prompt
    assert "cam.orbit(9,3,6);" in user_prompt
    assert "push in on the door" in user_prompt


@pytest.mark.asyncio
async def test_shot_prompt_feeds_the_previous_error_back():
    """The retry has to know what broke, or it reruns the same mistake."""
    board = _board()
    with patch("app.scene3d.author._call_model",
               new=AsyncMock(return_value="```js\ncam.at(0,2,8);\n```")) as call:
        await author_shot(board, board.frames[0], "world", [], last_error="TypeError: P.hill is not a function")
    assert "P.hill is not a function" in call.await_args.args[1]


@pytest.mark.asyncio
async def test_shot_raises_rather_than_returning_a_stub():
    board = _board()
    with patch("app.scene3d.author._call_model", new=AsyncMock(return_value="Sorry, I cannot.")):
        with pytest.raises(SceneAuthoringError):
            await author_shot(board, board.frames[0], "world", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_author.py -q`
Expected: FAIL — `author_shot` does not exist.

- [ ] **Step 3: Add the shot half to author.py**

```python
SHOT_SYSTEM_PROMPT = """You are a cinematographer framing ONE shot inside an existing low-poly 3D world.

The world module is given to you. You do not rebuild it — you place the camera,
set the light for the time of day, add any props specific to this moment, and
animate the shot on the timeline.

IN SCOPE for your code: `scene`, `camera`, `cam`, `tl`, `state`, and `P.*`.
The world's root group is already added to the scene as `world`.

AVAILABLE API — ONLY these, on `P`:
  Geometry: P.plane P.dome P.cone P.box P.cyl P.sphere
  Composite:P.tree P.flower P.fence P.path P.windowPane P.door P.building
  Finance:  P.coin P.vault P.stack P.chart3d
  Layout:   P.scatter P.row P.place
  Light:    P.sun P.ambient P.pointGlow P.bloom
  Type:     P.text3d
  Timing:   P.beat
  Camera:   cam.at(x,y,z) cam.lookAt(x,y,z) cam.dolly(from,to,dur) cam.orbit(r,h,dur,lookAt)

HARD RULES:
- NEVER import Three.js. NEVER construct THREE.* directly.
- NEVER use requestAnimationFrame, Date.now, performance.now or setInterval.
  The renderer SEEKS a paused timeline; wall-clock animation renders frozen.
- NEVER use Math.random. Use P.rand().
- ALL animation must be on `tl` (the paused timeline), spanning the shot duration.
- The camera must MOVE or something in frame must move. A completely static
  shot is rejected automatically.
- The camera must be OUTSIDE all geometry and something must be lit and visible.
  A black or uniform frame is rejected automatically.
- NO humanoid characters.

Write statements only — no function wrapper, no imports, no exports.
Return ONLY JavaScript in a ```javascript fence."""


async def author_shot(
    board,
    frame,
    world_code: str,
    prior_shots: list[str],
    last_error: str | None = None,
) -> str:
    """Frame one scene inside the film's world.

    `prior_shots` is passed for the same reason the 2D path passes used
    archetypes: each shot is authored in isolation, and without the history the
    model reaches for the same camera every time and the film reads as one
    angle repeated.
    """
    recent = "\n\n".join(prior_shots[-3:]) or "none yet — this is the first shot"
    parts = [
        f"FILM: {board.title}",
        f"DIRECTION: {board.direction or 'none given'}",
        f"SHOT DURATION: {frame.duration:.1f} seconds",
        "",
        "WORLD MODULE (already built and added to the scene as `world`):",
        "```javascript",
        world_code,
        "```",
        "",
        f"THIS SHOT — scene: {frame.scene or frame.title}",
        f"NARRATION OVER IT: {frame.voiceover}",
        "",
        "PREVIOUS SHOTS (do not repeat these camera angles):",
        "```javascript",
        recent,
        "```",
    ]
    if last_error:
        parts += [
            "",
            "YOUR PREVIOUS ATTEMPT WAS REJECTED. Fix this specific problem:",
            f"  {last_error}",
        ]
    text = await _call_model(SHOT_SYSTEM_PROMPT, "\n".join(parts))
    code = extract_js(text)
    log.info("shot_authored", slug=frame.slug, chars=len(code), retry=bool(last_error))
    return code
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_author.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/scene3d/author.py worker/tests/test_scene3d_author.py
git commit -m "feat(scene3d): shot authoring with error-feedback retry"
```

---

### Task 10: The backend orchestrator

**Files:**
- Create: `worker/app/scene3d/backend.py`
- Create: `worker/tests/test_scene3d_backend.py`

**Interfaces:**
- Consumes: `author_world`, `author_shot`, `SceneAuthoringError` (Task 8/9), `render_3d_frame` (Task 4), `verify_shot` (Task 7), `frames_are_distinct` (Task 6)
- Produces: `async build_3d_frames(board: Storyboard, video_dir: Path) -> list[str]` returning the slugs that failed every attempt; `SHOT_RETRIES`; `MIN_VERIFIED_FRAMES`; `ShotReport` dataclass with `slug`, `attempts`, `ok`, `reason`, `js`, `probe_pngs`

- [ ] **Step 1: Write the failing test**

`worker/tests/test_scene3d_backend.py`:

```python
"""Orchestration: retry on rejection, raise rather than substitute."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.scene3d.probes import ProbeStats, ShotVerdict
from app.storyboard import Frame, Storyboard


def _board(n=3):
    board = Storyboard(meta={"title": "T"})
    board.frames = [
        Frame(index=i, title=f"S{i}", voiceover=f"line {i}", scene=f"scene {i}", duration=5.0)
        for i in range(1, n + 1)
    ]
    return board


def _probes(phash):
    return [ProbeStats(t=t, mean_luma=0.4, variance=0.05, phash=phash) for t in (0.5, 2.5, 4.5)]


@pytest.mark.asyncio
async def test_all_shots_pass_on_first_attempt(tmp_path):
    from app.scene3d.backend import build_3d_frames

    hashes = iter(["0000000000000001", "00000000000000ff", "000000000000ff00"])
    with (
        patch("app.scene3d.backend.author_world", new=AsyncMock(return_value="world")),
        patch("app.scene3d.backend.author_shot", new=AsyncMock(return_value="cam.at(0,1,5);")),
        patch("app.scene3d.backend.verify_shot",
              new=AsyncMock(side_effect=lambda *a, **k: (ShotVerdict(True), _probes(next(hashes)), []))),
    ):
        failed = await build_3d_frames(_board(), tmp_path)
    assert failed == []


@pytest.mark.asyncio
async def test_a_rejected_shot_is_retried_with_the_reason(tmp_path):
    from app.scene3d.backend import build_3d_frames

    verdicts = [
        (ShotVerdict(False, "black frame at t=0.5"), [], []),
        (ShotVerdict(True), _probes("0000000000000001"), []),
        (ShotVerdict(True), _probes("00000000000000ff"), []),
        (ShotVerdict(True), _probes("000000000000ff00"), []),
    ]
    shot = AsyncMock(return_value="cam.at(0,1,5);")
    with (
        patch("app.scene3d.backend.author_world", new=AsyncMock(return_value="world")),
        patch("app.scene3d.backend.author_shot", new=shot),
        patch("app.scene3d.backend.verify_shot", new=AsyncMock(side_effect=verdicts)),
    ):
        failed = await build_3d_frames(_board(), tmp_path)
    assert failed == []
    assert shot.await_args_list[1].kwargs["last_error"] == "black frame at t=0.5"


@pytest.mark.asyncio
async def test_a_shot_failing_every_attempt_is_reported_not_substituted(tmp_path):
    from app.scene3d.backend import build_3d_frames

    with (
        patch("app.scene3d.backend.author_world", new=AsyncMock(return_value="world")),
        patch("app.scene3d.backend.author_shot", new=AsyncMock(return_value="cam.at(0,1,5);")),
        patch("app.scene3d.backend.verify_shot",
              new=AsyncMock(return_value=(ShotVerdict(False, "uniform fill"), [], []))),
    ):
        failed = await build_3d_frames(_board(1), tmp_path)
    assert failed == ["f01-s1"]
    # Nothing was written in place of the failed shot.
    assert not list((tmp_path / "compositions" / "frames").glob("*.html"))


@pytest.mark.asyncio
async def test_a_repeated_camera_angle_is_rejected(tmp_path):
    """Same failure shape as the 2D archetype-repeat bug, in 3D."""
    from app.scene3d.backend import build_3d_frames

    same = "0f0f0f0f0f0f0f0f"
    with (
        patch("app.scene3d.backend.author_world", new=AsyncMock(return_value="world")),
        patch("app.scene3d.backend.author_shot", new=AsyncMock(return_value="cam.at(0,1,5);")),
        patch("app.scene3d.backend.verify_shot",
              new=AsyncMock(return_value=(ShotVerdict(True), _probes(same), []))),
    ):
        failed = await build_3d_frames(_board(2), tmp_path)
    assert "f02-s2" in failed


@pytest.mark.asyncio
async def test_world_authoring_failure_raises(tmp_path):
    """No world means no film. Never proceed with an invented one."""
    from app.scene3d.author import SceneAuthoringError
    from app.scene3d.backend import build_3d_frames

    with patch("app.scene3d.backend.author_world",
               new=AsyncMock(side_effect=SceneAuthoringError("model returned no code"))):
        with pytest.raises(SceneAuthoringError):
            await build_3d_frames(_board(), tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_backend.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scene3d.backend'`.

- [ ] **Step 3: Write backend.py**

```python
"""Orchestrate one film's 3D frames: world, then shot-verify-retry per frame.

The retry loop is the point. A model writing free-form JavaScript will
occasionally put the camera inside a hill or forget a light, and the gate
catches that — but only if the failure feeds back into the next attempt.
Exhausting the retries reports the slug; it never writes a substitute, because
a substituted shot renders and validates exactly like a real one.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from app.scene3d.author import author_shot, author_world
from app.scene3d.probes import ProbeStats, frames_are_distinct
from app.scene3d.shell import render_3d_frame
from app.scene3d.verify import verify_shot

log = structlog.get_logger()

SHOT_RETRIES = int(os.environ.get("SHOT_RETRIES", "2"))
MIN_VERIFIED_FRAMES = int(os.environ.get("MIN_VERIFIED_FRAMES", "3"))

ASSETS = Path(__file__).resolve().parent / "assets"


@dataclass
class ShotReport:
    slug: str
    attempts: int = 0
    ok: bool = False
    reason: str = ""
    js: str = ""
    probe_pngs: list[str] = field(default_factory=list)


def _install_assets(video_dir: Path) -> None:
    """Copy the DSL and Three.js into the project so a render needs no network."""
    video_dir.mkdir(parents=True, exist_ok=True)
    for name in ("three.module.js", "primitives.js"):
        shutil.copyfile(ASSETS / name, video_dir / name)


async def build_3d_frames(board, video_dir: Path) -> list[str]:
    """Build every frame as a verified 3D shot. Returns slugs that never passed."""
    _install_assets(video_dir)
    frames_dir = video_dir / "compositions" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = video_dir / "renders" / "probes"

    world_code = await author_world(board)
    (video_dir / "compositions" / "world.js").write_text(world_code, encoding="utf-8")

    failed: list[str] = []
    reports: list[ShotReport] = []
    prior_shots: list[str] = []
    accepted_probes: list[ProbeStats] = []

    for frame in board.frames:
        report = ShotReport(slug=frame.slug)
        last_error: str | None = None
        frame_path = frames_dir / f"{frame.slug}.html"

        for attempt in range(SHOT_RETRIES + 1):
            report.attempts = attempt + 1
            shot_js = await author_shot(
                board, frame, world_code, prior_shots, last_error=last_error
            )
            frame_path.write_text(
                render_3d_frame(
                    frame.slug, frame.duration, shot_js, frame.voiceover,
                    width=board.width, height=board.height,
                ),
                encoding="utf-8",
            )
            verdict, probes, _errors = await verify_shot(frame_path, frame.duration, probe_dir)

            if verdict.ok and accepted_probes and not frames_are_distinct(
                accepted_probes[-1], probes[len(probes) // 2]
            ):
                verdict = type(verdict)(False, "shot looks identical to the previous one")

            if verdict.ok:
                report.ok = True
                report.js = shot_js
                report.probe_pngs = [f"{frame.slug}-p{i}.png" for i in range(3)]
                prior_shots.append(shot_js)
                accepted_probes.append(probes[len(probes) // 2])
                break

            last_error = verdict.reason
            report.reason = verdict.reason
            log.warning("shot_rejected", slug=frame.slug, attempt=attempt + 1, reason=verdict.reason)

        if not report.ok:
            # Deliberately leave nothing behind. A substituted shot would render
            # and validate exactly like a real one, and ship.
            frame_path.unlink(missing_ok=True)
            failed.append(frame.slug)
        reports.append(report)

    board.meta["shot_reports"] = reports
    log.info("3d_frames_built", frames=len(board.frames), failed=len(failed))
    return failed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_scene3d_backend.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/scene3d/backend.py worker/tests/test_scene3d_backend.py
git commit -m "feat(scene3d): orchestrator with verify-retry and no substitution"
```

---

### Task 11: Wire the backend into the pipeline

**Files:**
- Modify: `worker/app/youtube.py:75` (signature), `:150` (guard block), `:549-556` (dispatcher)
- Modify: `worker/tests/test_youtube.py`

**Interfaces:**
- Consumes: `build_3d_frames`, `MIN_VERIFIED_FRAMES` from Task 10
- Produces: `generate_youtube_video(story_id, channel_id, upload_preference="manual", backend: str | None = None)`; `_build_frames(board, video_dir, backend: str | None = None)`

- [ ] **Step 1: Write the failing test**

Append to `worker/tests/test_youtube.py`:

```python
@pytest.mark.asyncio
async def test_build_frames_routes_to_three(tmp_path):
    """Per-request backend beats the env default, so both formats run from one worker."""
    from app.storyboard import Storyboard
    from app import youtube

    with patch("app.youtube.build_3d_frames", new=AsyncMock(return_value=[])) as three:
        await youtube._build_frames(Storyboard(), tmp_path, backend="three")
    three.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_generation_aborts_below_min_verified_frames(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    """An absolute floor. Ratios read a two-frame film with one good shot as 50% fine."""
    mock_fetch.return_value = {"id": "s1", "title": "T", "summary": "S"}
    mock_script.return_value = (
        "---\ntitle: T\nformat: 1920x1080\npacing: story\n---\n"
        "# Scene 1\nVoiceover: a\n# Scene 2\nVoiceover: b\n"
        "# Scene 3\nVoiceover: c\n# Scene 4\nVoiceover: d\n"
    )
    mock_audio.return_value = []
    # Two of four shots never passed the gate: only two verified remain.
    mock_frames.return_value = ["f01-frame", "f02-frame"]
    mock_run.return_value = MagicMock(returncode=0)

    with patch("app.youtube.VIDEOS_DIR", tmp_path):
        result = await youtube.generate_youtube_video(uuid.uuid4(), "ch1", backend="three")

    assert result is None
    mock_record.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_youtube.py -q`
Expected: FAIL — `_build_frames` takes no `backend` argument.

- [ ] **Step 3: Update the dispatcher**

In `worker/app/youtube.py`, replace `_build_frames` (around line 552):

```python
async def _build_frames(board: Storyboard, video_dir: Path, backend: str | None = None) -> list[str]:
    """Dispatch frame generation to the requested backend.

    Backend is per request so a single running worker can produce both a
    portrait 2D Short and a landscape 3D film without an env change or restart;
    FRAME_BACKEND only supplies the default.
    """
    chosen = (backend or FRAME_BACKEND).lower()
    if chosen == "three":
        from app.scene3d.backend import build_3d_frames

        return await build_3d_frames(board, video_dir)
    if chosen == "gemini":
        return await _generate_frame_compositions(board, video_dir)
    return await _generate_frame_compositions_local(board, video_dir)
```

Add the import near the top of `youtube.py` so the test can patch
`app.youtube.build_3d_frames`:

```python
from app.scene3d.backend import MIN_VERIFIED_FRAMES, build_3d_frames
```

and change the local import inside `_build_frames` to use the module-level name.

- [ ] **Step 4: Thread the backend through the entrypoint**

Change the signature at line 75:

```python
async def generate_youtube_video(
    story_id: uuid.UUID,
    channel_id: str,
    upload_preference: str = "manual",
    backend: str | None = None,
) -> uuid.UUID | None:
```

Change the `_build_frames` call at line 150:

```python
    placeholders = await _build_frames(board, video_dir, backend=backend)
```

Immediately after the existing placeholder-ratio block (after line 165), add the
absolute floor:

```python
    verified = len(board.frames) - len(placeholders)
    if verified < MIN_VERIFIED_FRAMES:
        # Absolute, not proportional. Every ratio above reads a two-frame film
        # with one good shot as a healthy 50%, and a one-frame film as flawless.
        log.error(
            "youtube_generation_aborted",
            reason="too_few_verified_frames",
            story_id=str(story_id),
            verified=verified,
            minimum=MIN_VERIFIED_FRAMES,
        )
        return None
```

- [ ] **Step 5: Run the whole suite**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests -q`
Expected: all pass, including the 93 that passed before.

- [ ] **Step 6: Commit**

```powershell
git add worker/app/youtube.py worker/tests/test_youtube.py
git commit -m "feat(youtube): per-request three backend and MIN_VERIFIED_FRAMES floor"
```

---

### Task 12: Job progress records

**Files:**
- Create: `supabase/migrations/007_jobs.sql`
- Create: `worker/app/jobs.py`
- Create: `worker/tests/test_jobs.py`

**Interfaces:**
- Consumes: the DB pool accessor already used by `app/db.py`
- Produces: `async create_job(kind: str, story_id) -> uuid.UUID`; `async set_stage(job_id, stage: str, done: int = 0, total: int = 0)`; `async fail_job(job_id, error: str)`; `async finish_job(job_id, draft_id)`; `async get_job(job_id) -> dict | None`; `STAGES`

- [ ] **Step 1: Write the migration**

`supabase/migrations/007_jobs.sql`:

```sql
-- Progress for long-running generation runs, so the GUI can show a stage
-- rather than a spinner. Rows are cheap and worth keeping: a failed film's
-- stage and error are the first thing anyone asks for.
CREATE TABLE IF NOT EXISTS jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind        text NOT NULL,
    story_id    uuid REFERENCES stories(id) ON DELETE CASCADE,
    stage       text NOT NULL DEFAULT 'queued',
    done        int  NOT NULL DEFAULT 0,
    total       int  NOT NULL DEFAULT 0,
    error       text,
    draft_id    uuid,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_created_idx ON jobs (created_at DESC);
```

- [ ] **Step 2: Write the failing test**

`worker/tests/test_jobs.py`:

```python
from app.jobs import STAGES


def test_stages_are_ordered_and_complete():
    assert STAGES == ["queued", "script", "narration", "world", "shots", "render", "done"]


def test_stage_index_is_monotonic():
    """The GUI renders a progress bar from this ordering."""
    assert all(STAGES.index(a) < STAGES.index(b) for a, b in zip(STAGES, STAGES[1:]))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_jobs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.jobs'`.

- [ ] **Step 4: Write jobs.py**

```python
"""Coarse progress for a generation run.

Deliberately coarse: one row updated at stage boundaries, polled by the GUI.
A finer-grained channel (websockets, per-frame events) would be more
infrastructure than a five-stage pipeline needs.
"""

from __future__ import annotations

import uuid

import structlog

from app.db import get_pool

log = structlog.get_logger()

STAGES = ["queued", "script", "narration", "world", "shots", "render", "done"]


async def create_job(kind: str, story_id: uuid.UUID) -> uuid.UUID:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO jobs (kind, story_id, stage) VALUES ($1, $2, 'queued') RETURNING id",
            kind, story_id,
        )


async def set_stage(job_id: uuid.UUID, stage: str, done: int = 0, total: int = 0) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET stage=$2, done=$3, total=$4, updated_at=now() WHERE id=$1",
            job_id, stage, done, total,
        )


async def fail_job(job_id: uuid.UUID, error: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET error=$2, updated_at=now() WHERE id=$1", job_id, error
        )


async def finish_job(job_id: uuid.UUID, draft_id: uuid.UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET stage='done', draft_id=$2, updated_at=now() WHERE id=$1",
            job_id, draft_id,
        )


async def get_job(job_id: uuid.UUID) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id=$1", job_id)
        return dict(row) if row else None
```

Check `app/db.py` for the actual pool accessor name and use it; if it differs
from `get_pool`, use the existing one rather than adding a second accessor.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_jobs.py -q`
Expected: PASS.

- [ ] **Step 6: Apply the migration**

```powershell
cd "F:\Content Creation Project"; Get-Content supabase/migrations/007_jobs.sql | psql $env:DATABASE_URL
```

- [ ] **Step 7: Commit**

```powershell
git add supabase/migrations/007_jobs.sql worker/app/jobs.py worker/tests/test_jobs.py
git commit -m "feat(jobs): coarse stage progress for generation runs"
```

---

### Task 13: API — mode on generate, job polling endpoint

**Files:**
- Modify: `worker/app/routes.py:75-100`
- Modify: `worker/tests/test_youtube.py`

**Interfaces:**
- Consumes: `create_job`, `get_job` (Task 12), `generate_youtube_video(backend=...)` (Task 11)
- Produces: `POST /youtube/generate` accepting `mode: "short" | "film"` and returning `{"job_id": ...}`; `GET /youtube/jobs/{job_id}`

- [ ] **Step 1: Write the failing test**

```python
def test_mode_maps_to_backend():
    from app.routes import backend_for_mode

    assert backend_for_mode("film") == "three"
    assert backend_for_mode("short") is None      # falls through to FRAME_BACKEND
    assert backend_for_mode(None) is None


def test_unknown_mode_is_rejected():
    """Silently defaulting an unknown mode ships the wrong format under a real headline."""
    import pytest
    from app.routes import backend_for_mode

    with pytest.raises(ValueError):
        backend_for_mode("cinema")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests/test_youtube.py -q`
Expected: FAIL — `backend_for_mode` does not exist.

- [ ] **Step 3: Update routes.py**

Add near the other helpers:

```python
MODE_BACKENDS = {"short": None, "film": "three"}


def backend_for_mode(mode: str | None) -> str | None:
    """Map the GUI's format toggle to a frame backend.

    `None` means "use the FRAME_BACKEND default", which is what a Short wants.
    An unrecognised mode raises rather than defaulting, so a typo cannot
    quietly publish a portrait 2D video under a film's headline.
    """
    if mode is None:
        return None
    if mode not in MODE_BACKENDS:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODE_BACKENDS)}")
    return MODE_BACKENDS[mode]
```

Extend `YouTubeGenerateRequest` with `mode: str | None = None`, and in
`youtube_generate` resolve the backend, create a job, and run the generation as
a background task returning the job id:

```python
@router.post("/youtube/generate")
async def youtube_generate(req: YouTubeGenerateRequest) -> dict:
    try:
        backend = backend_for_mode(req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = await create_job(kind=req.mode or "short", story_id=req.story_id)

    async def run() -> None:
        try:
            draft_id = await generate_youtube_video(
                req.story_id, req.channel_id, req.upload_preference, backend=backend
            )
            if draft_id:
                await finish_job(job_id, draft_id)
            else:
                await fail_job(job_id, "generation aborted; see worker logs")
        except Exception as exc:
            await fail_job(job_id, str(exc))

    asyncio.create_task(run())
    return {"job_id": str(job_id)}


@router.get("/youtube/jobs/{job_id}")
async def youtube_job(job_id: uuid.UUID) -> dict:
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in job.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd worker; ..\.venv\Scripts\python.exe -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/routes.py worker/tests/test_youtube.py
git commit -m "feat(api): film mode on generate and a job polling endpoint"
```

---

### Task 14: GUI — the films page

**Files:**
- Create: `gui/src/app/films/page.tsx`
- Create: `gui/src/components/FilmProgress.tsx`
- Modify: `gui/src/components/Sidebar.tsx`

**Interfaces:**
- Consumes: `POST /youtube/generate` with `mode`, `GET /youtube/jobs/{id}` (Task 13), `GET /stories`
- Produces: a `/films` route; `FilmProgress` taking `{ jobId: string }`

- [ ] **Step 1: Write FilmProgress**

`gui/src/components/FilmProgress.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";

const STAGES = ["queued", "script", "narration", "world", "shots", "render", "done"];

type Job = {
  stage: string;
  done: number;
  total: number;
  error: string | null;
  draft_id: string | null;
};

export default function FilmProgress({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    const tick = async () => {
      const res = await fetch(`/api/youtube/jobs/${jobId}`);
      if (!res.ok || cancelled) return;
      const next: Job = await res.json();
      setJob(next);
      // Stop polling once the run has settled, either way.
      if (next.stage === "done" || next.error) clearInterval(timer);
    };

    const timer = setInterval(tick, 2000);
    tick();
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId]);

  if (!job) return <p className="text-sm text-neutral-400">Starting…</p>;

  const current = STAGES.indexOf(job.stage);

  return (
    <div className="space-y-3">
      <ol className="flex flex-wrap gap-2">
        {STAGES.map((stage, i) => (
          <li
            key={stage}
            className={`rounded px-2 py-1 text-xs ${
              i < current
                ? "bg-emerald-900/40 text-emerald-300"
                : i === current
                  ? "bg-sky-900/50 text-sky-200"
                  : "bg-neutral-800 text-neutral-500"
            }`}
          >
            {stage}
            {i === current && job.total > 0 ? ` ${job.done}/${job.total}` : ""}
          </li>
        ))}
      </ol>
      {job.error && (
        <p className="rounded bg-red-950/50 p-3 text-sm text-red-300">{job.error}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write the films page**

`gui/src/app/films/page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";

import FilmProgress from "@/components/FilmProgress";

type Story = { id: string; title: string };

export default function FilmsPage() {
  const [stories, setStories] = useState<Story[]>([]);
  const [storyId, setStoryId] = useState("");
  const [mode, setMode] = useState<"short" | "film">("film");
  const [jobId, setJobId] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/stories")
      .then((r) => r.json())
      .then(setStories)
      .catch(() => setStories([]));
  }, []);

  const generate = async () => {
    setBusy(true);
    try {
      const res = await fetch("/api/youtube/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ story_id: storyId, channel_id: "default", mode }),
      });
      const data = await res.json();
      setJobId(data.job_id ?? "");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <h1 className="text-2xl font-semibold">Generate a video</h1>

      <select
        className="w-full rounded border border-neutral-700 bg-neutral-900 p-2"
        value={storyId}
        onChange={(e) => setStoryId(e.target.value)}
      >
        <option value="">Select a story…</option>
        {stories.map((s) => (
          <option key={s.id} value={s.id}>
            {s.title}
          </option>
        ))}
      </select>

      <div className="flex gap-2">
        {(["short", "film"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`rounded px-4 py-2 text-sm ${
              mode === m ? "bg-sky-600 text-white" : "bg-neutral-800 text-neutral-300"
            }`}
          >
            {m === "short" ? "Short (2D, portrait)" : "Story Film (3D, landscape)"}
          </button>
        ))}
      </div>

      <button
        onClick={generate}
        disabled={!storyId || busy}
        className="rounded bg-emerald-600 px-4 py-2 text-white disabled:opacity-40"
      >
        {busy ? "Starting…" : "Generate"}
      </button>

      {jobId && <FilmProgress jobId={jobId} />}
    </main>
  );
}
```

- [ ] **Step 3: Add the sidebar link**

In `gui/src/components/Sidebar.tsx`, add a `Films` entry pointing at `/films`,
matching the existing link markup.

- [ ] **Step 4: Verify it builds and renders**

```powershell
cd "F:\Content Creation Project\gui"; npm run build
```

Expected: build succeeds. Then `npm run dev` and open `http://localhost:3000/films`
— the story dropdown populates and the mode toggle switches.

- [ ] **Step 5: Commit**

```powershell
git add gui/src/app/films gui/src/components/FilmProgress.tsx gui/src/components/Sidebar.tsx
git commit -m "feat(gui): films page with format toggle and live stage progress"
```

---

### Task 15: GUI — the shot inspector

The highest-value screen in the build. Without it a failed film is a wall of
logs, and knowing *which* shot broke and why is the entire point of the gate.

**Files:**
- Create: `gui/src/components/ShotInspector.tsx`
- Modify: `gui/src/app/films/page.tsx`
- Modify: `worker/app/routes.py`

**Interfaces:**
- Consumes: `ShotReport` from Task 10
- Produces: `GET /youtube/jobs/{job_id}/shots` returning `[{slug, ok, attempts, reason, js, probe_pngs}]`; `ShotInspector` taking `{ jobId: string }`

- [ ] **Step 1: Persist the reports**

In `worker/app/scene3d/backend.py`, after the loop, write the reports next to
the video so the API can serve them without a DB round trip:

```python
    import json
    (video_dir / "renders" / "shots.json").write_text(
        json.dumps([report.__dict__ for report in reports], indent=2), encoding="utf-8"
    )
```

- [ ] **Step 2: Serve them**

In `worker/app/routes.py`:

```python
@router.get("/youtube/jobs/{job_id}/shots")
async def youtube_job_shots(job_id: uuid.UUID) -> list[dict]:
    """Per-shot verification reports, for the GUI's inspector."""
    import json

    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    path = VIDEOS_DIR / f"story-{job['story_id']}" / "renders" / "shots.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 3: Write the inspector**

`gui/src/components/ShotInspector.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";

type Shot = {
  slug: string;
  ok: boolean;
  attempts: number;
  reason: string;
  js: string;
  probe_pngs: string[];
};

export default function ShotInspector({ jobId }: { jobId: string }) {
  const [shots, setShots] = useState<Shot[]>([]);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/youtube/jobs/${jobId}/shots`)
      .then((r) => r.json())
      .then(setShots)
      .catch(() => setShots([]));
  }, [jobId]);

  if (!shots.length) return null;

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">Shots</h2>
      {shots.map((shot) => (
        <div key={shot.slug} className="rounded border border-neutral-800">
          <button
            onClick={() => setOpen(open === shot.slug ? null : shot.slug)}
            className="flex w-full items-center gap-3 p-3 text-left"
          >
            <span className={shot.ok ? "text-emerald-400" : "text-red-400"}>
              {shot.ok ? "✓" : "✗"}
            </span>
            <span className="font-mono text-sm">{shot.slug}</span>
            {shot.attempts > 1 && (
              <span className="text-xs text-amber-400">{shot.attempts} attempts</span>
            )}
            {!shot.ok && <span className="text-xs text-red-300">{shot.reason}</span>}
          </button>

          {open === shot.slug && (
            <div className="space-y-3 border-t border-neutral-800 p-3">
              <div className="flex gap-2 overflow-x-auto">
                {shot.probe_pngs.map((png) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={png} src={`/api/probes/${png}`} alt={png} className="h-32 rounded" />
                ))}
              </div>
              <pre className="overflow-x-auto rounded bg-neutral-950 p-3 text-xs">
                <code>{shot.js || "// no code retained for a failed shot"}</code>
              </pre>
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
```

- [ ] **Step 4: Mount it**

In `gui/src/app/films/page.tsx`, import `ShotInspector` and render
`{jobId && <ShotInspector jobId={jobId} />}` below `FilmProgress`.

- [ ] **Step 5: Verify**

```powershell
cd "F:\Content Creation Project\gui"; npm run build
```

Expected: build succeeds.

- [ ] **Step 6: Commit**

```powershell
git add gui/src/components/ShotInspector.tsx gui/src/app/films/page.tsx worker/app/routes.py worker/app/scene3d/backend.py
git commit -m "feat(gui): per-shot inspector with probe stills and generated code"
```

---

### Task 16: End-to-end run and documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/youtube/YT-HANDOFF.md`
- Modify: `worker/.env.example` (create if absent)

**Interfaces:**
- Consumes: everything above
- Produces: a rendered film, and the amended local/cloud policy

- [ ] **Step 1: Confirm no e2e run is in flight, then run the suite**

```powershell
cd "F:\Content Creation Project\worker"; ..\.venv\Scripts\python.exe -m pytest tests -q
```

Expected: all pass. DB tests error without local Postgres — expected.

- [ ] **Step 2: Generate a film end to end**

Seed or pick a story, then from the GUI's `/films` page select it, choose
**Story Film (3D, landscape)**, and Generate. Watch the stages advance.

- [ ] **Step 3: Inspect the result**

Confirm: `videos/story-<id>/renders/video.mp4` exists, is 1920×1080, and its
shots show a recognisable persistent set from varied camera angles. Extract a
contact sheet to check quickly:

```powershell
cd "F:\Content Creation Project\videos\story-<id>"
ffmpeg -y -v error -i renders/video.mp4 -vf "fps=1/7,scale=480:-1,tile=4x3" -frames:v 1 renders/sheet.png
```

- [ ] **Step 4: Amend the local/cloud table in CLAUDE.md**

Add a row and a qualifier to the existing table:

```markdown
| Frame design (2D archetypes) | **Local** — Ollama `qwen2.5:7b` on the RTX 3070 | Free, no rate limit. Model picks an archetype + fills slots (~dozens of tokens), never writes HTML |
| Frame design (3D films) | **Cloud** — Gemini/Claude | Composing a 3D scene is thousands of tokens of spatial reasoning, well past a 7B. Render stays local |
```

And extend the Rules section:

```markdown
- The 3D backend lets a model write JavaScript, which reopens the malformed-
  composition failure class the archetypes exclude by construction. The
  headless render gate in `scene3d/verify.py` is the entire mitigation — a
  weakened gate ships broken videos. `MIN_VERIFIED_FRAMES` is absolute, not a
  ratio, for the same reason `MIN_SCRIPT_FRAMES` is.
```

- [ ] **Step 5: Document the new environment variables**

`worker/.env.example`:

```
SCENE_MODEL=gemini-2.0-flash
SHOT_RETRIES=2
MIN_VERIFIED_FRAMES=3
MIN_MEAN_LUMA=0.02
MIN_VARIANCE=0.0008
MAX_HAMMING_FOR_IDENTICAL=4
```

- [ ] **Step 6: Append a handoff section**

Add a `## Session Handoff — <date>` section to `docs/youtube/YT-HANDOFF.md`
recording: the rendered film's path and properties, how many shots needed a
retry and why, the observed cloud token cost per film, and any primitive the
model kept reaching for that does not exist yet (the best signal for what to
add to the DSL next).

- [ ] **Step 7: Commit**

```powershell
git add CLAUDE.md docs/youtube/YT-HANDOFF.md worker/.env.example
git commit -m "docs: 3D film backend, amended local/cloud split, gate rationale"
git push
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 architecture, `three` backend, per-request selection | 11 |
| §1 world/shot split | 8, 9, 10 |
| §1 module layout | 2, 4, 6, 7, 8, 10 |
| §1 determinism constraint | 1 (spike), 2 (test bans wall-clock), 9 (prompt rule) |
| §2 DSL and primitive list | 2, 3 |
| §2 material policy enforced in code | 2 (`flat` helper) |
| §3 guard 1, static check | Folded into guard 2 — a syntax error surfaces as a page error in the browser, so a separate `node --check` step would add a Node dependency to catch what Chromium already catches. Deviation from spec, noted here deliberately |
| §3 guard 2, sandbox execution | 7 |
| §3 guard 3, pixel probes | 6, 7 |
| §3 guard 4, cross-frame distinctness | 6, 10 |
| §3 guard 5, `MIN_VERIFIED_FRAMES` | 11 |
| §3 guard 6, retry then raise | 10 |
| §4 `/films` page, toggle, progress | 12, 13, 14 |
| §4 shot inspector | 15 |
| §4 API changes | 13 |
| §5 testing | Every task |
| Risks: spike first | 1 |

**Placeholder scan:** none. Every step carries the code or the exact command.

**Type consistency:** `ProbeStats(t, mean_luma, variance, phash)` and
`ShotVerdict(ok, reason)` are defined in Task 6 and used unchanged in 7 and 10.
`verify_shot` returns a 3-tuple in 7 and is consumed as a 3-tuple in 10.
`build_3d_frames(board, video_dir) -> list[str]` matches `_build_frames`'s
existing contract, so the guards in `youtube.py` need no reshaping.

**Known deviation:** the spec's guard 1 (a separate `node --check` pass) is
folded into guard 2. A malformed module throws on load and is captured by the
page-error listener, so the separate pass would add a Node subprocess per shot
to catch a strict subset of what the browser already reports.
