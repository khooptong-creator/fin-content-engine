/**
 * The low-poly DSL. Hand-written and owned by the pipeline; generated shot
 * modules compose these and never import Three.js directly.
 *
 * THIS IS A CLASSIC SCRIPT — no import, no export. HyperFrames does not
 * preserve ``type="module"`` on injected sub-compositions, so ESM dies
 * silently at parse time. Load Three.js r160.1 UMD first (it sets
 * ``window.THREE``), then this file, then the generated shot module.
 *
 * Art direction is enforced here rather than in the prompt: every primitive
 * builds flat-shaded, untextured material. A model that cannot choose a
 * material cannot drift off-style, and style rules that live in code cannot
 * be prompted away.
 *
 * Exposed on ``window.Prim``.
 */
(function (global) {
  var THREE = global.THREE;

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  /** Flat-shaded Lambert — the only material the model can reach. */
  function flat(color) {
    return new THREE.MeshLambertMaterial({ color: color, flatShading: true });
  }

  /**
   * Seeded PRNG. ``Math.random`` would make two renders of the same film
   * produce different scatter positions, breaking both reproducibility and
   * the determinism test.
   */
  var _seed = 1;
  function seed(n) { _seed = (n >>> 0) || 1; }
  function rand() {
    _seed = (_seed * 1664525 + 1013904223) >>> 0;
    return _seed / 4294967296;
  }
  function randBetween(lo, hi) { return lo + rand() * (hi - lo); }

  // -----------------------------------------------------------------------
  // Stage
  // -----------------------------------------------------------------------

  /**
   * Build the stage every shot renders through.
   *
   * Returns the objects a generated shot module works with. The timeline is
   * paused and rendering only from ``onUpdate`` — this is the property the
   * spike proved. Nothing in a shot module may introduce a rAF loop.
   */
  function createStage(opts) {
    opts = opts || {};
    var width = opts.width || 1920;
    var height = opts.height || 1080;
    var background = opts.background || '#0B1220';

    var canvas = opts.canvas || document.querySelector('canvas');
    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
    renderer.setSize(width, height, false);
    renderer.setClearColor(new THREE.Color(background), 1);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 500);
    camera.position.set(0, 3, 10);
    camera.lookAt(0, 0, 0);

    var state = {};
    var _render = function () { renderer.render(scene, camera); };

    var tl = gsap.timeline({ paused: true, onUpdate: _render });

    var cam = {
      at: function (x, y, z) { camera.position.set(x, y, z); return cam; },
      lookAt: function (x, y, z) { camera.lookAt(x, y, z); return cam; },
      dolly: function (from, to, duration) {
        tl.fromTo(camera.position,
          { x: from[0], y: from[1], z: from[2] },
          { x: to[0], y: to[1], z: to[2], duration: duration, ease: 'power2.inOut' }, 0);
        return cam;
      },
      orbit: function (radius, height, duration, lookAt) {
        lookAt = lookAt || [0, 0, 0];
        var o = { a: 0 };
        tl.to(o, {
          a: Math.PI * 2, duration: duration, ease: 'none',
          onUpdate: function () {
            camera.position.set(
              Math.cos(o.a) * radius, height, Math.sin(o.a) * radius
            );
            camera.lookAt(lookAt[0], lookAt[1], lookAt[2]);
          },
        }, 0);
        return cam;
      },
    };

    return {
      THREE: THREE, scene: scene, camera: camera, renderer: renderer,
      tl: tl, state: state, render: _render, cam: cam,
    };
  }

  // -----------------------------------------------------------------------
  // Geometry primitives
  // -----------------------------------------------------------------------

  function plane(size, color) {
    var m = new THREE.Mesh(new THREE.PlaneGeometry(size, size), flat(color));
    m.rotation.x = -Math.PI / 2;
    return m;
  }

  function dome(radius, color, squash) {
    if (squash === undefined) squash = 0.6;
    var m = new THREE.Mesh(
      new THREE.SphereGeometry(radius, 12, 8), flat(color)
    );
    m.scale.y = squash;
    return m;
  }

  function cone(radius, height, color, segments) {
    if (segments === undefined) segments = 7;
    return new THREE.Mesh(
      new THREE.ConeGeometry(radius, height, segments), flat(color)
    );
  }

  function box(w, h, d, color) {
    return new THREE.Mesh(new THREE.BoxGeometry(w, h, d), flat(color));
  }

  function cyl(radius, height, color, segments) {
    if (segments === undefined) segments = 8;
    return new THREE.Mesh(
      new THREE.CylinderGeometry(radius, radius, height, segments), flat(color)
    );
  }

  function sphere(radius, color, detail) {
    if (detail === undefined) detail = 1;
    return new THREE.Mesh(
      new THREE.IcosahedronGeometry(radius, detail), flat(color)
    );
  }

  // -----------------------------------------------------------------------
  // Lights
  // -----------------------------------------------------------------------

  function ambient(color, intensity) {
    if (color === undefined) color = 0xffffff;
    if (intensity === undefined) intensity = 0.45;
    return new THREE.AmbientLight(color, intensity);
  }

  function sun(azimuth, elevation, color, intensity) {
    if (color === undefined) color = 0xffffff;
    if (intensity === undefined) intensity = 1.0;
    var light = new THREE.DirectionalLight(color, intensity);
    var r = 30;
    light.position.set(
      Math.cos(azimuth) * Math.cos(elevation) * r,
      Math.sin(elevation) * r,
      Math.sin(azimuth) * Math.cos(elevation) * r
    );
    return light;
  }

  function pointGlow(color, intensity, distance) {
    if (intensity === undefined) intensity = 2;
    if (distance === undefined) distance = 20;
    return new THREE.PointLight(color, intensity, distance);
  }

  // -----------------------------------------------------------------------
  // Effects
  // -----------------------------------------------------------------------

  /**
   * Cheap emissive lift. A real UnrealBloomPass needs EffectComposer and a
   * second render target; an additive halo sprite reads the same at low poly
   * counts.
   */
  function bloom(mesh, color, strength, scale) {
    if (strength === undefined) strength = 1.4;
    if (scale === undefined) scale = 1.8;
    var halo = new THREE.Mesh(
      new THREE.SphereGeometry(scale, 10, 8),
      new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: Math.min(strength * 0.25, 0.6),
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    mesh.add(halo);
    return mesh;
  }

  // -----------------------------------------------------------------------
  // Layout helpers
  // -----------------------------------------------------------------------

  function place(obj, pos) {
    obj.position.set(pos[0], pos[1], pos[2]);
    return obj;
  }

  function scatter(n, factory, opts) {
    opts = opts || {};
    var area = opts.area || 20;
    var y = opts.y || 0;
    var parent = opts.parent || null;
    var group = parent || new THREE.Group();
    for (var i = 0; i < n; i++) {
      var item = factory(i);
      item.position.set(randBetween(-area, area), y, randBetween(-area, area));
      group.add(item);
    }
    return group;
  }

  function row(n, factory, opts) {
    opts = opts || {};
    var spacing = opts.spacing || 2;
    var axis = opts.axis || 'x';
    var group = new THREE.Group();
    var offset = ((n - 1) * spacing) / 2;
    for (var i = 0; i < n; i++) {
      var item = factory(i);
      var d = i * spacing - offset;
      if (axis === 'x') item.position.x = d;
      else if (axis === 'z') item.position.z = d;
      else item.position.y = d;
      group.add(item);
    }
    return group;
  }

  // -----------------------------------------------------------------------
  // Composites
  // -----------------------------------------------------------------------

  function tree(style, opts) {
    if (style === undefined) style = 'conifer';
    opts = opts || {};
    var trunk = opts.trunk || '#5A3A22';
    var leaf = opts.leaf || '#2E7D32';
    var scl = opts.scale || 1;
    var g = new THREE.Group();
    var t = cyl(0.18 * scl, 1.6 * scl, trunk, 6);
    t.position.y = 0.8 * scl;
    g.add(t);
    if (style === 'conifer') {
      var c = cone(0.9 * scl, 2.4 * scl, leaf, 7);
      c.position.y = 2.4 * scl;
      g.add(c);
    } else {
      for (var i = 0; i < 3; i++) {
        var blob = sphere(randBetween(0.5, 0.8) * scl, leaf, 0);
        blob.position.set(
          randBetween(-0.4, 0.4) * scl,
          (1.9 + i * 0.35) * scl,
          randBetween(-0.4, 0.4) * scl
        );
        g.add(blob);
      }
    }
    return g;
  }

  function flower(color) {
    if (color === undefined) color = '#E91E63';
    var g = new THREE.Group();
    var stem = cyl(0.03, 0.4, '#4CAF50', 5);
    stem.position.y = 0.2;
    var head = sphere(0.12, color, 0);
    head.position.y = 0.45;
    g.add(stem, head);
    return g;
  }

  function fence(length, opts) {
    if (length === undefined) length = 10;
    opts = opts || {};
    var color = opts.color || '#6D4C41';
    var posts = opts.posts || 6;
    var g = new THREE.Group();
    var rail1 = box(length, 0.12, 0.08, color); rail1.position.y = 0.9;
    var rail2 = box(length, 0.12, 0.08, color); rail2.position.y = 0.5;
    g.add(rail1, rail2);
    var spacing = length / (posts - 1);
    for (var i = 0; i < posts; i++) {
      var p = box(0.14, 1.3, 0.14, color);
      p.position.set(-length / 2 + i * spacing, 0.65, 0);
      g.add(p);
    }
    return g;
  }

  function path(length, width, color, steps) {
    if (length === undefined) length = 12;
    if (width === undefined) width = 1.6;
    if (color === undefined) color = '#9E9E9E';
    if (steps === undefined) steps = 8;
    var g = new THREE.Group();
    var seg = length / steps;
    for (var i = 0; i < steps; i++) {
      var s = box(width, 0.08, seg * 0.8, color);
      s.position.set(0, 0.04, -length / 2 + i * seg);
      g.add(s);
    }
    return g;
  }

  function windowPane(radius, opts) {
    if (radius === undefined) radius = 0.5;
    opts = opts || {};
    var frameColor = opts.frame || '#BCAAA4';
    var glass = opts.glass || '#FFF3C4';
    var g = new THREE.Group();
    var ring = new THREE.Mesh(
      new THREE.TorusGeometry(radius, radius * 0.12, 6, 16), flat(frameColor)
    );
    var pane = new THREE.Mesh(
      new THREE.CircleGeometry(radius, 16),
      new THREE.MeshBasicMaterial({ color: glass })
    );
    pane.position.z = -0.02;
    var barH = box(radius * 2, radius * 0.1, 0.06, frameColor);
    var barV = box(radius * 0.1, radius * 2, 0.06, frameColor);
    g.add(ring, pane, barH, barV);
    return g;
  }

  function door(radius, opts) {
    if (radius === undefined) radius = 1.1;
    opts = opts || {};
    var panel = opts.panel || '#1B5E20';
    var frameColor = opts.frame || '#BCAAA4';
    var g = new THREE.Group();
    var ring = new THREE.Mesh(
      new THREE.TorusGeometry(radius, radius * 0.1, 6, 20), flat(frameColor)
    );
    var face = new THREE.Mesh(new THREE.CircleGeometry(radius, 20), flat(panel));
    face.position.z = -0.02;
    var knob = sphere(radius * 0.07, '#FFD54F', 0);
    knob.position.set(radius * 0.45, 0, 0.06);
    g.add(ring, face, knob);
    return g;
  }

  function building(w, h, d, opts) {
    if (w === undefined) w = 3;
    if (h === undefined) h = 5;
    if (d === undefined) d = 3;
    opts = opts || {};
    var wall = opts.wall || '#90A4AE';
    var roof = opts.roof || '#455A64';
    var g = new THREE.Group();
    var body = box(w, h, d, wall); body.position.y = h / 2;
    var top = cone(Math.max(w, d) * 0.8, h * 0.4, roof, 4);
    top.position.y = h + h * 0.2; top.rotation.y = Math.PI / 4;
    g.add(body, top);
    return g;
  }

  // -----------------------------------------------------------------------
  // Finance / data-vis primitives
  // -----------------------------------------------------------------------

  function coin(radius, color) {
    if (radius === undefined) radius = 0.5;
    if (color === undefined) color = '#FFC107';
    var m = cyl(radius, radius * 0.16, color, 14);
    m.rotation.x = Math.PI / 2;
    return m;
  }

  function vault(size, opts) {
    if (size === undefined) size = 3;
    opts = opts || {};
    var bodyColor = opts.body || '#546E7A';
    var dial = opts.dial || '#CFD8DC';
    var g = new THREE.Group();
    var shell = box(size, size, size * 0.6, bodyColor);
    shell.position.y = size / 2;
    var wheel = cyl(size * 0.22, 0.18, dial, 12);
    wheel.rotation.x = Math.PI / 2;
    wheel.position.set(0, size / 2, size * 0.32);
    g.add(shell, wheel);
    return g;
  }

  function stack(count, factory, opts) {
    if (count === undefined) count = 8;
    if (factory === undefined) factory = function () { return coin(); };
    opts = opts || {};
    var gap = opts.gap || 0.18;
    var g = new THREE.Group();
    for (var i = 0; i < count; i++) {
      var item = factory(i);
      item.position.y = i * gap;
      g.add(item);
    }
    return g;
  }

  function chart3d(values, opts) {
    opts = opts || {};
    var color = opts.color || '#38BDF8';
    var spacing = opts.spacing || 1.2;
    var maxHeight = opts.maxHeight || 5;
    var g = new THREE.Group();
    var peak = Math.max.apply(null, values.concat([1]));
    values.forEach(function (v, i) {
      var h = (v / peak) * maxHeight;
      var bar = box(0.8, h, 0.8, color);
      bar.position.set(
        i * spacing - ((values.length - 1) * spacing) / 2, h / 2, 0
      );
      g.add(bar);
    });
    return g;
  }

  /**
   * Extruded-look 3D text without a font loader. TextGeometry needs an async
   * JSON font fetch, which is another network dependency and failure mode
   * inside a render; layered planes read the same at this poly budget.
   */
  function text3d(str, opts) {
    opts = opts || {};
    var color = opts.color || '#F8FAFC';
    var size = opts.size || 1;
    var depth = opts.depth || 0.12;
    var layers = opts.layers !== undefined ? opts.layers : 4;
    var g = new THREE.Group();
    var charWidth = size * 0.6;
    var totalWidth = str.length * charWidth;
    for (var l = 0; l < layers; l++) {
      for (var i = 0; i < str.length; i++) {
        var tile = new THREE.Mesh(
          new THREE.BoxGeometry(charWidth * 0.8, size, depth),
          flat(color)
        );
        tile.position.set(
          i * charWidth - totalWidth / 2 + charWidth / 2,
          0,
          (l - (layers - 1) / 2) * depth * 2
        );
        g.add(tile);
      }
    }
    return g;
  }

  /**
   * Beat-sync pulse target. Call ``beat.pulse()`` from a GSAP timeline
   * callback to animate the attached mesh on the beat.
   */
  function beat(mesh, opts) {
    opts = opts || {};
    var scale = opts.scale || 1.15;
    var duration = opts.duration || 0.15;
    return {
      pulse: function () {
        if (!mesh) return;
        gsap.to(mesh.scale, {
          x: scale, y: scale, z: scale,
          duration: duration, yoyo: true, repeat: 1, ease: 'power2.out',
        });
      },
    };
  }

  // -----------------------------------------------------------------------
  // Namespace
  // -----------------------------------------------------------------------

  var Prim = {
    // Stage
    createStage: createStage,

    // Geometry
    dome: dome,
    cone: cone,
    box: box,
    cyl: cyl,
    sphere: sphere,
    plane: plane,

    // Lights
    sun: sun,
    ambient: ambient,
    pointGlow: pointGlow,

    // Effects
    bloom: bloom,

    // Seeded PRNG
    seed: seed,
    rand: rand,
    randBetween: randBetween,

    // Layout
    place: place,
    scatter: scatter,
    row: row,

    // Composites
    tree: tree,
    flower: flower,
    fence: fence,
    path: path,
    windowPane: windowPane,
    door: door,
    building: building,

    // Finance / data-vis
    coin: coin,
    vault: vault,
    stack: stack,
    chart3d: chart3d,

    // Type
    text3d: text3d,
    beat: beat,
  };

  global.Prim = Prim;
})(window);
