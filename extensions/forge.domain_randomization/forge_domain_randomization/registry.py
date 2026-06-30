"""Whitelist-based prim path helpers for v0.2 domain randomization.

No role inference, no scope filtering, no manifest concepts.
The request explicitly lists every prim that may be touched.
"""

from __future__ import annotations

from typing import Any

from .schemas import DomainRandomizationRequest


def collect_whitelist_prim_paths(request: DomainRandomizationRequest) -> set[str]:
    """Return every USD prim path referenced by the request (objects, lights,
    cameras, visibility_pools, and translation_toward targets)."""
    paths: set[str] = set()
    for obj in request.objects:
        paths.add(obj.prim_path)
        if obj.asset:
            for item in _copy_specs(obj.asset.get("copy_to")):
                source = item.get("source_prim_path")
                if isinstance(source, str) and source:
                    paths.add(source)
        if obj.pose and isinstance(obj.pose.get("translation_toward"), dict):
            target = obj.pose["translation_toward"].get("target_prim")
            if isinstance(target, str):
                paths.add(target)
    for light in request.lights:
        paths.add(light.prim_path)
    for cam in request.cameras:
        paths.add(cam.prim_path)
    for pool in request.visibility_pools:
        paths.update(pool.prims)
    return paths


def _copy_specs(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def build_prim_scan_entry(
    prim_path: str,
    type_name: str,
    transform: dict[str, list[float]],
    bounds: dict[str, list[float]] | None,
    physics: dict[str, Any],
    material_bindings: list[dict[str, Any]],
    source_confidence: str,
    xform: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "prim_path": prim_path,
        "type_name": type_name,
        "world_transform": transform,
        "xform": xform,
        "bounds": bounds,
        "physics": physics,
        "material_bindings": material_bindings,
        "source_confidence": source_confidence,
    }
