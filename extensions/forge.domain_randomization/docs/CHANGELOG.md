# Changelog

## 0.1.0 - 2026-06-30

- Add isolated Isaac / Omniverse extension package.
- Add extension lifecycle shell and Tools > FORGE menu entry.
- Add alpha UI panel for stage scanning, target selection, request preview,
  randomization runs, composition, and result summaries.
- Add reusable command entry points for single-variant and batch DR runs.
- Add deterministic sampler for object material, pose, visibility, asset copy /
  reference / payload, lighting, camera, physics, and visibility-pool factors.
- Add sparse text USDA and pxr-backed layer writers.
- Add layer-stack manifest generation and composed-scene stub composition.
- Add standalone headless Isaac runner skeleton.
- Add SceneCraft pipe coupling for `domain_randomization_run`.
- Add strict validation for missing requested prims, unsupported or unachieved
  domains, missing visibility-pool prims, empty plans, controllability
  thresholds, and command-level success propagation.
- Add offline tests for schemas, sampling, command behavior, composition,
  scanner extractors, SceneCraft coupling, UI helpers, USD layer writing,
  validation, and transform layout behavior.
- Add artifact-backed Isaac smoke-test record for the demo environmental safety
  scene.

Known release limits:

- Isaac version, launch command, and composed-stage reopen evidence should be
  recorded in future smoke-test notes before beta.
- `scene_manifest.json` is optional and not yet the source of benchmark-quality
  semantic role truth.
- Oracle synthesis, robot execution, and metrics aggregation are outside this
  extension.
