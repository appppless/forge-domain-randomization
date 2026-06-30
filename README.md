# FORGE Domain Randomization Extension

FORGE Domain Randomization is an Isaac Sim / Omniverse extension for producing
deterministic benchmark variants from an existing USD scene. It scans a stage,
samples controlled perturbations, writes non-destructive USD override layers,
and records requested, sampled, achieved, validation, and controllability
artifacts for downstream FORGE execution, oracle, and metrics stages.

The extension is USD-layer based by design: it must not mutate the base scene in
place. A randomized variant is represented as sparse override layers plus a
composition manifest.

## Release Status

Version: `0.1.0`

Release target: **alpha / internal research preview**

This package is ready to publish as an alpha plugin for controlled FORGE
development and collaborator testing. It is not yet a stable public benchmark
plugin because real Isaac smoke-test evidence, compatibility documentation
across Isaac versions, and scene-manifest-backed semantic role validation are
still in progress.

What is currently implemented:

- Omniverse extension lifecycle shell and Tools menu entry.
- Alpha UI panel for selecting targets, factors, output paths, and running DR.
- Reusable Python command API.
- Deterministic sampler with seed replay.
- Sparse text and pxr-backed USDA override layer writers.
- Layer-stack manifest and composed-scene stub generation.
- SceneCraft pipe coupling.
- Strict validator for missing prims, unachieved domains, missing visibility
  pool members, controllability thresholds, and blocking issues.
- Offline unit tests for schemas, sampler, layer writing, composition, UI model
  helpers, SceneCraft coupling, and validator behavior.

Known non-goals for `0.1.0`:

- This extension does not execute robot policies.
- This extension does not synthesize task oracles.
- This extension does not compute benchmark-level metrics.
- This extension does not replace SceneCraft placement evaluation.
- This extension does not make heuristic scan roles benchmark-quality evidence.

## Compatibility

Offline Python:

- Python `>=3.10`
- No Isaac Sim import required when using injected scans and the text writer.

Isaac / Omniverse runtime:

- Requires Isaac Sim / Omniverse modules for live stage scanning, extension UI,
  pxr-backed layer writing, and composed-stage verification.
- Extension dependencies are declared in `config/extension.toml`:
  `omni.usd`, `omni.kit.commands`, `omni.kit.menu.utils`,
  `omni.kit.window.filepicker`, and `isaacsim.gui.components`.

The exact Isaac Sim version matrix is not certified yet. Before publishing
beyond alpha, record the Isaac Sim version, platform, Python version, and smoke
test stage used for validation.

## Package Layout

Important files:

- `config/extension.toml`: Omniverse extension metadata.
- `setup.py`: Python package metadata for offline development.
- `forge_domain_randomization/extension.py`: extension lifecycle shell.
- `forge_domain_randomization/ui_builder.py`: alpha Omniverse UI panel.
- `forge_domain_randomization/ui_models.py`: UI request-building helpers.
- `forge_domain_randomization/commands.py`: reusable command entry points.
- `forge_domain_randomization/schemas.py`: request, scan, manifest, and result schemas.
- `forge_domain_randomization/scanner.py`: USD stage scanning.
- `forge_domain_randomization/sampler.py`: deterministic parameter sampling.
- `forge_domain_randomization/layer_writer.py`: text USDA layer writer.
- `forge_domain_randomization/usd_layer_writer.py`: pxr-backed USDA layer writer.
- `forge_domain_randomization/compose.py`: composed-scene stub generation.
- `forge_domain_randomization/validator.py`: benchmark-facing validation.
- `forge_domain_randomization/scripts/forge_dr_run.py`: standalone headless runner.
- `data/preview.png`: Extension Manager preview image.
- `PACKAGE-LICENSES/forge.domain_randomization-LICENSE.md`: current alpha license notice.
- `tests/`: offline unit tests.

## Install And Enable

For FORGE development, keep this directory under:

```text
extensions/forge.domain_randomization/
```

Inside Isaac Sim, add the repository extension path and enable:

```text
forge.domain_randomization
```

The extension metadata lives at:

```text
extensions/forge.domain_randomization/config/extension.toml
```

When enabled successfully, the UI appears at:

```text
Tools > FORGE > FORGE Domain Randomization
```

For offline Python tests or tooling from the extension directory:

```bash
python -m pip install -e extensions/forge.domain_randomization
```

Do not use ordinary Python to import Isaac-only modules. Use the text writer or
injected scans outside Isaac.

## Quick Start

Minimal Python command use:

```python
from forge_domain_randomization.commands import run_domain_randomization

result = run_domain_randomization(request_dict)
```

Minimal request shape:

```json
{
  "schema_version": "0.2",
  "request_id": "dr_smoke_001",
  "variant_id": "variant_0001",
  "base_scene_usd": "/abs/path/base_scene.usd",
  "output_dir": "/abs/path/out/dr_smoke",
  "seed": 7,
  "layer_policy": {
    "mode": "single",
    "writer": "pxr"
  },
  "objects": [
    {
      "prim_path": "/World/Table/TargetCup",
      "material": {
        "color_jitter": 0.05,
        "roughness": [0.3, 0.7]
      },
      "pose": {
        "translation_jitter_m": [-0.02, 0.02],
        "rotation_jitter_deg": [-15.0, 15.0]
      }
    }
  ],
  "lights": [
    {
      "prim_path": "/World/KeyLight",
      "intensity_scale": [0.7, 1.3],
      "color_temperature": [3500.0, 6500.0]
    }
  ],
  "cameras": [
    {
      "prim_path": "/World/Camera",
      "pose_jitter_m": [-0.03, 0.03],
      "yaw_pitch_jitter_deg": [-5.0, 5.0],
      "fov_deg": [45.0, 65.0]
    }
  ]
}
```

Use `layer_policy.writer = "pxr"` inside Isaac / Omniverse. Use
`layer_policy.writer = "text"` for offline unit tests and pure Python smoke
checks.

For batch generation, set:

```json
{
  "variants": 8,
  "seed": 100
}
```

Each variant is written under a deterministic seed-specific output directory.

## UI Workflow

Open the panel from:

```text
Tools > FORGE > FORGE Domain Randomization
```

The alpha UI supports:

- Selecting the current base USD stage.
- Selecting an optional `scene_manifest.json`.
- Choosing the output directory.
- Editing request id, variant id, seed, and variant count.
- Selecting writer backend (`pxr` in Isaac, `text` for offline debug).
- Scanning stage candidates.
- Adding object, light, and camera targets.
- Editing conservative material, pose, visibility, physics, lighting, and
  camera ranges.
- Building a request preview.
- Running randomization.
- Composing an existing `layer_stack.json`.
- Reviewing validation summary, controllability score, and artifact paths.

The UI calls `commands.run_domain_randomization()` and
`commands.compose_layer_stack()`. It should not duplicate sampler, writer, or
validator logic.

## Running In Isaac

Standalone headless run:

```bash
isaac-sim --no-window \
  --/app/extensions/enabled/forge.domain_randomization=true \
  --exec extensions/forge.domain_randomization/forge_domain_randomization/scripts/forge_dr_run.py \
  --request /abs/path/domain_randomization_request.json
```

The runner launches Isaac before importing runtime-dependent modules. This keeps
Omniverse imports aligned with Isaac extension conventions.

An Isaac smoke test is considered passing when:

- `base_scene.usd` is not modified in place.
- `domain_scan.json` exists.
- At least one `randomization_layers/*.usda` file exists.
- `layer_stack.json` exists.
- `achieved_domain_report.json` exists.
- `composed_scene.usda` exists when the base scene path is valid.
- The composed stage opens in Isaac / pxr.
- `validation.issues` has no blocking issue.

Do not claim real Isaac validation unless Isaac was actually launched with a
stage-backed request.

Recorded smoke tests:

- `docs/smoke_tests/2026-06-30-demo-environmental-safety.md`

## SceneCraft Pipe Use

SceneCraft coupling is provided through:

- `SceneCraft/domain_randomization_bridge.py`
- `SceneCraft/Tools/domain_randomization_tool.py`
- `SceneCraft/isaac_sim_app.py`

The persistent Isaac host accepts:

```text
domain_randomization_run,{request_json}
```

Python wrapper:

```python
from SceneCraft.Tools.domain_randomization_tool import run_domain_randomization

result = run_domain_randomization(request_dict)
```

The bridge should pass structured JSON payloads and receive JSON-compatible
results.

## Output Artifacts

The command emits:

- `domain_scan.json`
- `randomization_layers/*.usda`
- `layer_stack.json`
- `composed_scene.usda` when composition is possible
- `achieved_domain_report.json`

`domain_scan.json` records what the extension observed in the base stage:

- `schema_version`
- `base_scene_usd`
- `base_scene_hash`
- `stage_units_meters`
- `prims`
- `lights`
- `cameras`
- `warnings`

`layer_stack.json` records how to compose the randomized scene:

- `variant_id`
- `base_scene_usd`
- `sub_layers`
- `composed_scene_usd`
- `composition`

`achieved_domain_report.json` is the benchmark-facing result:

- `variant_id`
- `request_id`
- `seed`
- `base_scene_usd`
- `randomization_layers`
- `composed_scene_usd`
- `layer_stack_path`
- `requested_parameters`
- `sampled_parameters`
- `achieved_parameters`
- `validation`
- `controllability_score`

Downstream systems should consume `achieved_domain_report.json` and
`layer_stack.json`, not infer randomization state from filenames.

## Supported Factors

Object-level factors:

- Material color jitter.
- Material roughness range.
- Material texture variants.
- Pose translation jitter.
- Pose translation toward another prim.
- Pose rotation jitter.
- Pose scale jitter.
- Visibility toggles.
- Physics mass, friction, and restitution where supported by scanned prims.
- Asset reference / payload variants.
- Copy-based distractor expansion.

Simulator-level factors:

- Light intensity scale.
- Light color.
- Light color temperature.
- Camera translation jitter.
- Camera yaw / pitch / roll jitter.
- Camera FOV.

Collection factors:

- Visibility pools with `keep_visible`.

Public benchmark-facing factor groups should remain:

- `asset_level`
- `placement_level`
- `simulator_level`

Internal implementation may route these through material, pose, visibility,
lighting, camera, physics, and asset appliers.

## Validation Policy

Validation runs after sampling and layer writing. It does not prevent other
domains from being sampled; it determines whether the produced variant is valid
enough for benchmark use.

Validation is strict by default. A request with enabled factors is
blocking-invalid when:

- A requested object, light, or camera is absent from the scan.
- A requested domain cannot be achieved.
- Enabled factors produce no USD edits.
- Enabled factors produce no achieved parameters.
- A visibility pool references prims absent from the scan.
- `minimum_controllability_score` is configured and not met.

The command-level `success` field follows `validation.success`.

For exploratory UI work or debugging, callers may set:

```json
{
  "validation_policy": {
    "mode": "permissive"
  }
}
```

Permissive validation keeps the same issues in the report but marks them
non-blocking.

Optional controllability threshold:

```json
{
  "validation_policy": {
    "minimum_controllability_score": 0.8
  }
}
```

Validation output includes:

- `success`
- `issues`
- `resample_counts`
- `coverage.enabled_domains`
- `coverage.requested_parameters`
- `coverage.achieved_parameters`
- `coverage.controllability_score`

## Verification

Offline extension tests:

```bash
python -B -m unittest discover -s extensions/forge.domain_randomization/tests
```

Expected current offline result:

```text
Ran 127 tests
OK (skipped=4)
```

FORGE-side planner / runner tests:

```bash
python -B -m unittest discover -s domain_randomization/tests
```

Use `python -B` to avoid leaving `__pycache__` files behind. Remove generated
cache files before publishing.

## Release Checklist

Alpha release checklist:

- Offline extension tests pass in ordinary Python.
- Isaac-only tests are skipped or isolated when Isaac / pxr is unavailable.
- One injected-scan request produces all expected artifacts.
- README documents runtime boundaries, validation behavior, and limitations.
- Extension metadata version matches `setup.py`.
- Extension metadata points to `docs/README.md`, `docs/CHANGELOG.md`, and
  `data/preview.png`.
- License notice is present under `PACKAGE-LICENSES/`.
- No generated `__pycache__`, `.pyc`, or local smoke-test artifacts are included.

Beta release checklist:

- Alpha checklist is satisfied.
- Real Isaac smoke test passes on a recorded Isaac Sim version.
- SceneCraft pipe command works against a live stage.
- UI panel can scan, build, run, compose, and display an achieved report.
- Example request and smoke-test notes are checked into docs or examples.
- Compatibility matrix is documented.
- `data/icon.png` is added if the extension will be distributed through a UI
  catalog that expects package icons.

Stable release checklist:

- Beta checklist is satisfied.
- Deterministic seed replay is verified across multiple scene types.
- Scene-manifest-backed role mapping is supported.
- Validator catches missing prims, missing cameras, invalid layers, failed
  composition, and unachieved requested domains.
- Multiple stage-backed smoke tests are recorded.
- Known limitations are either resolved or explicitly scoped.

## Known Limitations

- `scene_manifest.json` integration is optional and not yet the primary source
  of semantic role truth.
- Heuristic scan results are useful for engineering smoke tests but should not
  be treated as benchmark-quality semantic evidence.
- Real Isaac smoke-test evidence still needs to be recorded for release notes.
- Compatibility across Isaac Sim versions is not yet certified.
- Oracle synthesis and metrics aggregation are outside this extension.
- Real Isaac articulation execution, grasp events, and process-level task
  oracles are not provided by this plugin.

## Troubleshooting

`ModuleNotFoundError: No module named 'pxr'`

: You are running outside Isaac / Omniverse. Use the text writer for unit tests
  or run the request inside Isaac Sim.

`composed_scene.usda` is missing

: The base scene path may not exist, or composition was skipped. Check
  `validation.issues` in `achieved_domain_report.json`.

`success` is false but some layers were written

: This is expected for strict validation. The extension preserves partial
  artifacts for diagnosis but marks the variant invalid when a requested domain
  was not achieved.

No randomized effect is visible

: Confirm the requested prim paths match the open stage, then inspect
  `domain_scan.json`, `sampled_parameters`, `achieved_parameters`, and
  `validation.issues`.

Base scene changed unexpectedly

: Treat this as a release-blocking bug. Domain randomization must write override
  layers or composed stubs, never mutate the base scene in place.
