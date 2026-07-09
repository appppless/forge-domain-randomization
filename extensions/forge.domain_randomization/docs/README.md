# FORGE Domain Randomization Extension

## Introduction

The FORGE Domain Randomization extension adds USD-layer based domain
randomization to assets and environments in Isaac Sim / Omniverse. It scans the current stage, lets user
choose scene targets, samples deterministic variations, and writes
non-destructive USD override layers for benchmark and simulation workflows.

With this extension, users can randomize scene properties such as object
materials, poses, visibility, asset variants, lights, cameras, and selected
physics parameters without modifying the original USD scene. Each run records
the request, sampled values, generated layers, validation result, and composed
scene metadata so the same variant can be inspected or replayed later.

FORGE Domain Randomization lets you apply anything from subtle perturbations to
large scene changes on top of a base USD scene, creating diverse 3D variants for
training robot policies and evaluating model robustness.

## Installation

To install the extension in Isaac Sim or another Omniverse Kit app:

1. Clone this repository.
2. Open Isaac Sim.
3. Go to `Window > Extensions`.
4. Click the settings gear in the Extensions window.
5. Add the Kit maintained extension registry address to make third-party extensions discoverable. Via the Extensions window (Window > Extensions >
options button > Settings > Extension Registries):
- Name: kit/community
- URL: https://dw290v42wisod.cloudfront.net/exts/kit/community.
6. Search for `FORGE Domain Randomization`.
7. Enable the `forge.domain_randomization` extension.


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
- `PACKAGE-LICENSES/forge.domain_randomization-LICENSE.md`: MIT license notice.
- `tests/`: offline unit tests.

## Basic Usage

To create randomized variants from an open USD stage:

1. Open a scene in Isaac Sim.
2. Open `Tools > FORGE > FORGE Domain Randomization`.
3. Select the output directory for generated artifacts.
4. Set a request id, variant id, seed, and variant count.
5. Choose the writer backend:
   - `pxr` for Isaac Sim / Omniverse usage.
   - `text` for offline debug and tests.
6. Click the scan action to inspect available objects, lights, and cameras.
7. Add targets and choose the randomization ranges to apply.
8. Run the randomization.

The extension writes USD override layers and metadata into the selected output
directory. The base scene remains unchanged.

## Python API

The extension can also be driven from Python through the command API:

```python
from forge_domain_randomization.commands import run_domain_randomization

result = run_domain_randomization(request_dict)
```

A minimal request looks like this:

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

For batch generation, include a variant count:

```json
{
  "variants": 8,
  "seed": 100
}
```

Each variant uses a deterministic seed and is written to its own output
directory.

## Output Artifacts

A randomization run can produce:

- USDA override layers for the sampled variant.
- `layer_stack.json` describing the generated layer stack.
- `achieved_domain_report.json` describing requested and achieved changes.
- `domain_scan.json` when a stage scan is recorded.
- A composed scene stub for reopening or downstream validation.

These artifacts are intended for FORGE benchmark pipelines, replayable
simulation experiments, and inspection of generated domain variation.

## Offline Development

For local Python development:

```bash
python -m pip install -e extensions/forge.domain_randomization
python -B -m unittest discover -s extensions/forge.domain_randomization/tests
```

Offline code paths do not require Isaac Sim when using injected scans and the
`text` writer. Live stage scanning, UI usage, and pxr-backed layer writing
require Isaac Sim / Omniverse modules.

## Notes

- The extension writes override layers and does not edit the base USD scene in
  place.
- The same seed and request produce deterministic sampled values.
- The extension focuses on domain randomization. It does not execute robot
  policies, synthesize task oracles, or compute benchmark-level metrics.
- Isaac Sim / Omniverse dependencies are declared in
  `extensions/forge.domain_randomization/config/extension.toml`.
