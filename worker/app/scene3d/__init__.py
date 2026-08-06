"""scene3d — low-poly 3D frame backend.

A new per-request frame backend that writes ``compositions/frames/<slug>.html``
exactly like the existing 2D backends, so timing, narration, ``index.html``
emission and the render command are untouched.

Sub-packages
-----------
assets/   — vendored Three.js r160.1 UMD + hand-written primitives.js DSL
author.py — cloud LLM calls for world + shot code generation (Task 8-9)
backend.py— orchestrates world → shots → verify → retry (Task 10)
shell.py  — builds a 3D frame's HTML from a generated shot module (Task 4)
probes.py — pure predicates over probe stats, no I/O (Task 6)
verify.py — headless browser driver (Task 7)
"""
