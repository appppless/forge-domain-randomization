"""Command entry point for v0.2 domain randomization.

Supports optional batch over `variants` (default 1).  Each variant gets its own
output_dir/<variant_seed>/ subdirectory; a single-variant request writes
directly to output_dir.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .layer_writer import write_layer_stack_manifest, write_randomization_layers
from .reports import hash_file, stable_json_hash, write_json
from .sampler import sample_randomization
from .scanner import open_stage_and_scan, scan_stage
from .schemas import DomainRandomizationRequest, DomainRandomizationResult
from .validator import controllability_score, validate_randomization
from .compose import compose_stage_from_manifest, compose_stage


def run_domain_randomization(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one or more domain randomization variants.

    Supports two private keys for testing / pipe execution:
    - `_injected_scan` (dict): use as scan instead of touching Isaac.
    - `_stage` (Usd.Stage): scan this live stage instead of opening base_scene_usd.
    """
    # Extract non-copyable keys before deepcopy.
    stage = payload.pop("_stage", None)
    injected_scan = payload.pop("_injected_scan", None)

    variants = int(payload.get("variants", 1) or 1)
    if variants < 1:
        variants = 1

    base_seed = int(payload.get("seed", 0))
    root_output_dir = payload["output_dir"]

    results: list[dict[str, Any]] = []
    for i in range(variants):
        sub_payload = deepcopy(payload)
        sub_seed = base_seed + i
        sub_payload["seed"] = sub_seed
        if variants > 1:
            sub_payload["output_dir"] = str(Path(root_output_dir) / f"variant_{sub_seed:04d}")
            sub_payload["variant_id"] = f"{payload.get('variant_id', payload.get('request_id', 'variant'))}_{sub_seed:04d}"
            sub_payload["request_id"] = sub_payload["variant_id"]
        if stage is not None:
            sub_payload["_stage"] = stage
        if injected_scan is not None:
            sub_payload["_injected_scan"] = injected_scan
        results.append(_run_single(sub_payload))

    if variants == 1:
        return results[0]
    return {
        "success": all(r.get("success") for r in results),
        "variants": results,
    }


def _run_single(payload: dict[str, Any]) -> dict[str, Any]:
    request = DomainRandomizationRequest.from_dict(payload)
    output_dir = Path(request.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_hash = request.base_scene_hash
    if base_hash is None and Path(request.base_scene_usd).exists():
        base_hash = hash_file(request.base_scene_usd)
        request = DomainRandomizationRequest.from_dict({**request.to_dict(), "base_scene_hash": base_hash})
    if request.config_hash is None:
        cfg_for_hash = {
            "objects": [o.to_dict() for o in request.objects],
            "lights": [l.to_dict() for l in request.lights],
            "cameras": [c.to_dict() for c in request.cameras],
            "visibility_pools": [p.to_dict() for p in request.visibility_pools],
        }
        request = DomainRandomizationRequest.from_dict({**request.to_dict(), "config_hash": stable_json_hash(cfg_for_hash)})

    injected_scan = payload.get("_injected_scan")
    active_stage = payload.get("_stage")
    if injected_scan is not None:
        scan = dict(injected_scan)
        scan.setdefault("schema_version", request.schema_version)
        scan.setdefault("base_scene_usd", request.base_scene_usd)
        scan.setdefault("base_scene_hash", request.base_scene_hash or "sha256:unknown")
    elif active_stage is not None:
        scan = scan_stage(active_stage, request, base_scene_hash=request.base_scene_hash or "sha256:unknown").to_dict()
    else:
        scan = open_stage_and_scan(request, base_scene_hash=request.base_scene_hash or "sha256:unknown").to_dict()

    scan_path = write_json(output_dir / "domain_scan.json", scan)
    plan = sample_randomization(request, scan)
    layer_paths = _write_randomization_layers(request, plan)

    # Always compose: write a stub USDA that subLayers DR overrides on top of
    # the base scene. The DR extension owns both the sublayer artifacts and
    # this composition entry point so downstream code can open one file and
    # get a stage with all randomization applied. Composition issues are
    # surfaced through `validation.issues`, not raised.
    composed_path = output_dir / "composed_scene.usda"
    base_for_compose = request.base_scene_usd
    if Path(base_for_compose).exists():
        compose_result = compose_stage(
            base_scene_usd=base_for_compose,
            sub_layers=layer_paths,
            output_path=composed_path,
            variant_id=request.variant_id,
            verify=True,
        )
        composed_scene_usd = compose_result.composed_scene_usd
        compose_issues = compose_result.issues
    else:
        composed_scene_usd = None
        compose_issues = [{
            "type": "compose_skipped",
            "severity": "warning",
            "message": (
                f"base_scene_usd does not exist on disk ({base_for_compose}); "
                "skipped writing composed_scene.usda."
            ),
        }]

    layer_stack_path = write_layer_stack_manifest(
        request, layer_paths, composed_scene_usd=composed_scene_usd,
    )

    validation = validate_randomization(request, scan, plan)
    for issue in compose_issues:
        validation.setdefault("issues", []).append({
            "blocking": False,
            **issue,
        })
    score = controllability_score(request, plan)

    result = DomainRandomizationResult(
        variant_id=request.variant_id,
        request_id=request.request_id,
        seed=request.seed,
        base_scene_usd=request.base_scene_usd,
        randomization_layers=layer_paths,
        composed_scene_usd=composed_scene_usd,
        layer_stack_path=layer_stack_path,
        requested_parameters=plan.requested_parameters,
        sampled_parameters=plan.sampled_parameters,
        achieved_parameters=plan.achieved_parameters,
        validation=validation,
        controllability_score=score,
    )
    result_path = write_json(output_dir / "achieved_domain_report.json", result.to_dict())

    return {
        "success": bool(validation.get("success", True)),
        "variant_id": request.variant_id,
        "result_path": result_path,
        "scan_path": scan_path,
        "layer_stack_path": layer_stack_path,
        "composed_scene_usd": composed_scene_usd,
    }


def _write_randomization_layers(request: DomainRandomizationRequest, plan: Any) -> list[str]:
    writer = str(request.layer_policy.get("writer") or request.layer_policy.get("backend") or "pxr")
    if writer in {"pxr", "usd", "online"}:
        from .usd_layer_writer import write_randomization_layers_pxr

        return write_randomization_layers_pxr(request, plan)
    return write_randomization_layers(request, plan)

def compose_layer_stack(payload: dict[str, Any]) -> dict[str, Any]:
    """Stub-compose a randomization layer stack into a single .usda entry point.

    Accepts one of two payload shapes:

    1) `{"layer_stack_path": ".../layer_stack.json", "output_path": "..."}`
       Reads the manifest and stubs subLayers = [<dr layers...>, base_scene_usd].

    2) `{"base_scene_usd": "...", "sub_layers": [...], "output_path": "..."}`
       Same composition, bypassing the manifest file.

    `verify` (default true) checks sublayer existence and, if pxr is available,
    tries opening the composed stage. Issues never raise — they are returned in
    the response under `issues`.

    This is intentionally separate from `run_domain_randomization`. Composing
    the stage is a *host* policy decision (session-layer vs. stub file vs.
    flatten); the DR plugin only emits the recipe.
    """
    verify = bool(payload.get("verify", True))
    try:
        if "layer_stack_path" in payload:
            result = compose_stage_from_manifest(
                layer_stack_path=str(payload["layer_stack_path"]),
                output_path=payload.get("output_path"),
                verify=verify,
            )
        else:
            base = payload.get("base_scene_usd")
            sub_layers = payload.get("sub_layers") or []
            output_path = payload.get("output_path")
            if not base or output_path is None:
                raise ValueError(
                    "compose_layer_stack requires either 'layer_stack_path' or "
                    "('base_scene_usd', 'sub_layers', 'output_path')"
                )
            result = compose_stage(
                base_scene_usd=str(base),
                sub_layers=list(sub_layers),
                output_path=str(output_path),
                variant_id=str(payload.get("variant_id") or ""),
                verify=verify,
            )
    except Exception as exc:
        return {
            "success": False,
            "message": f"{type(exc).__name__}: {exc}",
            "composed_scene_usd": None,
        }

    has_error = any(i.get("severity") == "error" for i in result.issues)
    return {
        "success": not has_error,
        "composed_scene_usd": result.composed_scene_usd,
        "sub_layers": result.sub_layers,
        "base_scene_usd": result.base_scene_usd,
        "issues": result.issues,
    }
