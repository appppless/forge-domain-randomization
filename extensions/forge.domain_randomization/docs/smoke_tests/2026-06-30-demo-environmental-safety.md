# Isaac Smoke Test: Demo Environmental Safety

Result: **PASS for artifact-contract smoke check**

Evidence level: **artifact-backed, not full runtime certification**

Date: 2026-06-30

This record includes a committed snapshot of the real smoke-test output
artifacts. It is valid evidence that the extension produced the expected
domain-randomization artifact contract for one stage-backed run. It is not, by
itself, final beta/stable evidence because the exact Isaac Sim version, launch
command, application log, and an explicit post-run composed-stage reopen log
were not captured.

## Source Artifacts

Output directory:

```text
/home/znr/collected_scene/demo_environmental_safety/forge_dr
```

Committed artifact snapshot:

```text
extensions/forge.domain_randomization/docs/smoke_tests/2026-06-30-demo-environmental-safety/artifacts
```

Snapshot contents:

```text
artifacts/
  SHA256SUMS
  achieved_domain_report.json
  composed_scene.usda
  domain_scan.json
  layer_stack.json
  randomization_layers/
    dr_seed_0001.usda
```

Base scene:

```text
/home/znr/collected_scene/demo_environmental_safety/kitchen_new.usda
```

Base scene hash from `domain_scan.json`:

```text
sha256:4fab109157d14e1ad88ff273a8930e29150c9c8448392c558598d3b057b8d294
```

## Runtime Metadata

| Field | Value |
| --- | --- |
| Isaac Sim version | Not recorded |
| Platform | Local Linux workstation |
| Invocation | UI run, exact command not recorded |
| Writer backend | `pxr` |
| Request id | `forge_dr_ui_request` |
| Variant id | `forge_dr_ui_variant` |
| Seed | `1` |
| Schema version | `0.2` |

## Acceptance Criteria

| Gate | Required Evidence | Observed Evidence | Result |
| --- | --- | --- | --- |
| Base scene was scanned | `domain_scan.json` exists and names the base scene | Present; base scene path and hash recorded | PASS |
| Randomization layer was written | At least one `randomization_layers/*.usda` exists | `randomization_layers/dr_seed_0001.usda` present | PASS |
| Layer stack was emitted | `layer_stack.json` exists and references DR layer | Present; one sublayer listed | PASS |
| Composed scene entry point was emitted | `composed_scene.usda` exists | Present | PASS |
| Achieved report was emitted | `achieved_domain_report.json` exists | Present | PASS |
| Validator accepted the run | `validation.success == true` and no blocking issues | `success: true`, `issues: []` | PASS |
| Controllability was complete | `controllability_score >= 1.0` for this request | `1.0` | PASS |
| Base scene was not copied as full variant | DR output uses sparse override layer plus composition stub | `dr_seed_0001.usda` contains sparse `over` opinions; composition stub sublayers DR layer and base scene | PASS |
| Composed stage was reopened in Isaac after run | Isaac or pxr log showing `Usd.Stage.Open(composed_scene.usda)` success | Not captured | NOT RECORDED |

Overall smoke-test status is PASS for the artifact contract because every
required output artifact is present in the committed snapshot and the achieved
report validates successfully. The missing reopen log is tracked as a
documentation gap for beta readiness, not as a failure of this artifact-contract
check.

## Artifact Inventory

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `artifacts/domain_scan.json` | 8044 bytes | `1bfc2c4f2e502aa0d0a8828abe4af483bbcd6280857cabd8ad2d2cedb19f6666` |
| `artifacts/randomization_layers/dr_seed_0001.usda` | 2433 bytes | `e1d0ac08cc81ddefcb11b751be23730cd8b184901946f2885d8295863b9e29c3` |
| `artifacts/layer_stack.json` | 793 bytes | `a52009a06ceeedfef1384ded49db39b5f109f04b371e4ceebdd912b2d3f1c1ba` |
| `artifacts/composed_scene.usda` | 490 bytes | `1da830cdd7d1e95cbc8a9c55b893e817b7396db3638291feb3bd0cfb74b1f1aa` |
| `artifacts/achieved_domain_report.json` | 8675 bytes | `d025b9d5aadbb9c7f133e819a25a04d7d68cecdc2791af2539766aa0a4bac8ce` |

The same hashes are recorded in `artifacts/SHA256SUMS`.

## Scan Summary

Observed in `domain_scan.json`:

- Stage units meters: `1.0`
- Scanned prims: `2`
- Scanned lights: `0`
- Scanned cameras: `0`
- Scan warnings: `0`

Scanned target coverage matched the selected UI request targets for this run.

## Randomized Targets

Primary randomized prims:

- `/World/rooms/kitchen/BoxOfCereal_01`
- `/World/rooms/kitchen/CarvingKnife_01`

Generated copy:

- `/World/rooms/kitchen/BoxOfCereal_01_copy`

Achieved factor coverage included:

- cereal asset copy and sampled nearby placement
- cereal material color tint and roughness
- cereal mass scale
- cereal pose translation, rotation, and scale
- cereal visibility
- knife material color tint and roughness
- knife pose translation, rotation, and scale

## Validation Evidence

Observed in `achieved_domain_report.json`:

```json
{
  "success": true,
  "issues": [],
  "coverage": {
    "enabled_domains": 7,
    "requested_parameters": 14,
    "achieved_parameters": 18,
    "controllability_score": 1.0
  }
}
```

Top-level `controllability_score`:

```text
1.0
```

Blocking issues:

```text
None
```

Known warnings:

```text
None recorded
```

## Composition Evidence

Observed in `composed_scene.usda`:

```text
subLayers = [
    randomization_layers/dr_seed_0001.usda,
    kitchen_new.usda
]
```

Observed in `layer_stack.json`:

- `composition.order`: `subLayers_first_is_strongest`
- `composition.base_role`: `weakest_sublayer`
- `sub_layers`: one DR layer
- `composed_scene_usd`: `/home/znr/collected_scene/demo_environmental_safety/forge_dr/composed_scene.usda`

This confirms the extension emitted a sparse randomization layer plus a
composition entry point. The artifact set does not include an application log
proving a second explicit `Usd.Stage.Open` of the composed scene after the run.

## Limitations Of This Record

This smoke-test note is intentionally narrower than a beta release certificate.
Missing evidence:

- Exact Isaac Sim version.
- Exact launch command or complete UI action log.
- Extension git commit or package build id.
- Isaac application log.
- Explicit post-run composed-stage reopen result.
- Screenshot or rendered visual confirmation of the randomized scene.

## Next Smoke-Test Upgrade

For the next run, capture:

```text
isaac-sim --version
exact launch command
extension git commit
domain_randomization_request.json
isaac_run.log
Usd.Stage.Open(composed_scene.usda) result
optional screenshot of composed_scene.usda
```

Those additions would make the record strong enough to use as beta-readiness
evidence instead of only alpha artifact-contract evidence.
