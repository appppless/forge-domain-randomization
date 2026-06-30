"""UI-side request helpers for the FORGE domain randomization extension.

This module is intentionally ordinary Python. The Omniverse UI can import it,
and offline tests can validate request construction without Isaac Sim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any


@dataclass
class UIPrimRandomization:
    prim_path: str
    prim_kind: str
    enabled: bool = False
    material: bool = False
    pose: bool = False
    visibility: bool = False
    asset: bool = False
    physics: bool = False
    light: bool = False
    camera_pose: bool = False
    camera_fov: bool = False
    available_material: bool = True
    available_pose: bool = True
    available_visibility: bool = True
    available_asset: bool = True
    available_physics: bool = True
    available_light: bool = True
    available_camera_pose: bool = True
    available_camera_fov: bool = True
    current_values: dict[str, Any] = field(default_factory=dict)
    material_color_jitter: float = 0.05
    roughness_min: float = 0.35
    roughness_max: float = 0.8
    translation_min_m: float = -0.02
    translation_max_m: float = 0.02
    translation_x_min_m: float = -0.02
    translation_x_max_m: float = 0.02
    translation_y_min_m: float = -0.02
    translation_y_max_m: float = 0.02
    translation_z_min_m: float = -0.02
    translation_z_max_m: float = 0.02
    rotation_min_deg: float = -15.0
    rotation_max_deg: float = 15.0
    rotation_x_min_deg: float = 0.0
    rotation_x_max_deg: float = 0.0
    rotation_y_min_deg: float = 0.0
    rotation_y_max_deg: float = 0.0
    rotation_z_min_deg: float = -15.0
    rotation_z_max_deg: float = 15.0
    scale_x_min: float = 1.0
    scale_x_max: float = 1.0
    scale_y_min: float = 1.0
    scale_y_max: float = 1.0
    scale_z_min: float = 1.0
    scale_z_max: float = 1.0
    visibility_mode: str = "random"
    copy_count: int = 1
    copy_radius_min_m: float = 0.15
    copy_radius_max_m: float = 0.45
    copy_max_attempts: int = 16
    copy_collision_check: bool = True
    copy_suffix: str = "_copy"
    mass_scale_min: float = 0.9
    mass_scale_max: float = 1.1
    intensity_min: float = 0.8
    intensity_max: float = 1.2
    color_temperature_min: float = 3000.0
    color_temperature_max: float = 6500.0
    camera_pose_min_m: float = -0.03
    camera_pose_max_m: float = 0.03
    camera_yaw_pitch_min_deg: float = -5.0
    camera_yaw_pitch_max_deg: float = 5.0
    camera_fov_min_deg: float = 45.0
    camera_fov_max_deg: float = 65.0

    def __post_init__(self) -> None:
        if (
            (self.translation_min_m, self.translation_max_m) != (-0.02, 0.02)
            and (self.translation_x_min_m, self.translation_x_max_m) == (-0.02, 0.02)
            and (self.translation_y_min_m, self.translation_y_max_m) == (-0.02, 0.02)
            and (self.translation_z_min_m, self.translation_z_max_m) == (-0.02, 0.02)
        ):
            self.translation_x_min_m = self.translation_min_m
            self.translation_x_max_m = self.translation_max_m
            self.translation_y_min_m = self.translation_min_m
            self.translation_y_max_m = self.translation_max_m
            self.translation_z_min_m = self.translation_min_m
            self.translation_z_max_m = self.translation_max_m
        if (
            (self.rotation_min_deg, self.rotation_max_deg) != (-15.0, 15.0)
            and (self.rotation_z_min_deg, self.rotation_z_max_deg) == (-15.0, 15.0)
        ):
            self.rotation_z_min_deg = self.rotation_min_deg
            self.rotation_z_max_deg = self.rotation_max_deg


@dataclass
class UITargetSelection:
    objects: list[str] = field(default_factory=list)
    lights: list[str] = field(default_factory=list)
    cameras: list[str] = field(default_factory=list)
    prims: list[UIPrimRandomization] = field(default_factory=list)
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class UIFactorSelection:
    object_material: bool = True
    object_pose: bool = True
    light: bool = True
    camera: bool = True


@dataclass
class UIRunSettings:
    base_scene_usd: str
    output_dir: str
    request_id: str
    variant_id: str
    seed: int = 1
    variants: int = 1
    writer: str = "pxr"
    scene_manifest: str = ""


def default_output_dir(base_scene_usd: str) -> str:
    if base_scene_usd:
        parent = Path(base_scene_usd).expanduser().resolve().parent
        return str(parent / "forge_dr")
    return str(Path.cwd() / "forge_dr")


def build_request_payload(
    settings: UIRunSettings,
    targets: UITargetSelection,
    factors: UIFactorSelection,
) -> dict[str, Any]:
    """Build a v0.2 DR request from UI state."""
    objects, lights, cameras = _build_specs(targets, factors)
    payload: dict[str, Any] = {
        "schema_version": "0.2",
        "request_id": settings.request_id,
        "variant_id": settings.variant_id,
        "base_scene_usd": settings.base_scene_usd,
        "output_dir": settings.output_dir,
        "seed": int(settings.seed),
        "layer_policy": {
            "mode": "single",
            "writer": settings.writer,
        },
        "objects": objects,
        "lights": lights,
        "cameras": cameras,
    }
    if settings.scene_manifest:
        payload["scene_manifest"] = settings.scene_manifest
    if int(settings.variants) > 1:
        payload["variants"] = int(settings.variants)
    return payload


def summarize_targets(targets: UITargetSelection, *, limit: int = 8) -> str:
    enabled = [p for p in targets.prims if p.enabled]
    lines = [
        f"Objects: {len(targets.objects)}",
        f"Lights: {len(targets.lights)}",
        f"Cameras: {len(targets.cameras)}",
    ]
    if targets.prims:
        lines.append(f"Enabled prims: {len(enabled)}")
    preview = targets.objects[:limit] + targets.lights[:limit] + targets.cameras[:limit]
    if preview:
        lines.append("")
        lines.extend(preview[:limit])
        remaining = len(targets.objects) + len(targets.lights) + len(targets.cameras) - min(len(preview), limit)
        if remaining > 0:
            lines.append(f"... {remaining} more")
    return "\n".join(lines)


def summarize_result(result: dict[str, Any]) -> str:
    if not result:
        return "No run yet."
    lines = [
        f"Success: {bool(result.get('success'))}",
        f"Variant: {result.get('variant_id', '')}",
    ]
    if result.get("message"):
        lines.append(f"Message: {result['message']}")
    for key in ("result_path", "scan_path", "layer_stack_path", "composed_scene_usd"):
        value = result.get(key)
        if value:
            lines.append(f"{key}: {value}")
    if "variants" in result:
        lines.append(f"Variants: {len(result.get('variants') or [])}")
    return "\n".join(lines)


def is_object_candidate_path(path: str) -> bool:
    return _is_selectable_object_path(path)


def object_candidate_score(evidence: dict[str, Any]) -> int:
    """Compatibility helper for tests and older UI code.

    The UI scan now treats object discovery as a top-level candidate selection
    problem instead of a confidence-scoring problem. Positive means the path can
    appear in the object selector; negative means it is an obvious structural or
    implementation node.
    """
    path = str(evidence.get("path") or "")
    return 1 if _is_selectable_object_path(path) else -1


def prune_nested_candidates(paths: list[str] | list[dict[str, Any]]) -> list[str]:
    """Keep only the highest selectable candidate for each nested subtree."""
    candidates: list[str] = []
    for item in paths:
        if isinstance(item, dict):
            path = str(item.get("path") or "")
        else:
            path = str(item)
        if not path or not _is_selectable_object_path(path):
            continue
        if path not in candidates:
            candidates.append(path)

    pruned: list[str] = []
    for path in sorted(candidates, key=lambda value: (value.count("/"), value)):
        if any(_is_descendant(path, kept) for kept in pruned):
            continue
        pruned.append(path)
    return pruned


def prim_config_from_metadata(
    prim_path: str,
    prim_kind: str,
    factors: UIFactorSelection,
    metadata: dict[str, Any] | None = None,
) -> UIPrimRandomization:
    metadata = metadata or {}
    current_values = current_values_from_metadata(prim_kind, metadata)
    if prim_kind == "object":
        material_available = bool(metadata.get("material_bindings")) if metadata else True
        pose_available = _has_xform(metadata) if metadata else True
        physics = metadata.get("physics") or {}
        physics_available = bool(
            not metadata
            or physics.get("has_rigid_body")
            or physics.get("mass_prim_path")
            or physics.get("mass") is not None
        )
        roughness = current_values.get("roughness")
        return UIPrimRandomization(
            prim_path=prim_path,
            prim_kind="object",
            enabled=True,
            material=factors.object_material and material_available,
            pose=factors.object_pose and pose_available,
            available_material=material_available,
            available_pose=pose_available,
            available_visibility=True,
            available_asset=True,
            available_physics=physics_available,
            current_values=current_values,
            roughness_min=float(roughness) if roughness is not None else 0.35,
            roughness_max=float(roughness) if roughness is not None else 0.8,
        )
    if prim_kind == "light":
        return UIPrimRandomization(
            prim_path=prim_path,
            prim_kind="light",
            enabled=True,
            light=factors.light,
            available_light=True,
            current_values=current_values,
        )
    fov = current_values.get("fov_deg")
    return UIPrimRandomization(
        prim_path=prim_path,
        prim_kind="camera",
        enabled=True,
        camera_pose=factors.camera,
        camera_fov=factors.camera,
        available_camera_pose=_has_xform(metadata) if metadata else True,
        available_camera_fov=fov is not None if metadata else True,
        current_values=current_values,
        camera_fov_min_deg=float(fov) if fov is not None else 45.0,
        camera_fov_max_deg=float(fov) if fov is not None else 65.0,
    )


def current_values_from_metadata(prim_kind: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if prim_kind == "object":
        out: dict[str, Any] = {}
        material = _first_material_binding(metadata)
        if material:
            out["material_path"] = material.get("material_path")
            color = material.get("base_color")
            if color is None:
                color = material.get("diffuse_tint")
            if color is not None:
                out["base_color"] = color
            roughness = material.get("roughness")
            if roughness is not None:
                out["roughness"] = roughness
        transform = metadata.get("world_transform") or {}
        if transform:
            out["translation"] = transform.get("translation")
            out["rotation_euler_deg"] = transform.get("rotation_euler_deg")
            out["scale"] = transform.get("scale")
        physics = metadata.get("physics") or {}
        if physics:
            out["mass"] = physics.get("mass")
            out["rigid_body_prim_path"] = physics.get("rigid_body_prim_path")
            out["has_collision"] = physics.get("has_collision")
        return {k: v for k, v in out.items() if v is not None}
    if prim_kind == "light":
        return {
            k: v for k, v in {
                "intensity": metadata.get("intensity"),
                "color": metadata.get("color"),
            }.items()
            if v is not None
        }
    if prim_kind == "camera":
        out = {}
        transform = metadata.get("world_transform") or {}
        if transform:
            out["translation"] = transform.get("translation")
            out["rotation_euler_deg"] = transform.get("rotation_euler_deg")
        out["focal_length"] = metadata.get("focal_length")
        out["horizontal_aperture"] = metadata.get("horizontal_aperture")
        out["fov_deg"] = _camera_fov(metadata)
        return {k: v for k, v in out.items() if v is not None}
    return {}


def format_current_values(values: dict[str, Any]) -> str:
    if not values:
        return "Current: unavailable from scan."
    lines = []
    for key in sorted(values):
        lines.append(f"{key}: {_format_value(values[key])}")
    return "\n".join(lines)


def _is_selectable_object_path(path: str) -> bool:
    parts = [p.lower() for p in path.split("/") if p]
    if not parts:
        return False
    internal_names = {"looks", "materials", "visuals", "collisions", "collision", "base_link"}
    structural_leaf_names = {
        "world", "room", "rooms", "floor", "floors", "ceiling", "ceilings", "walls",
    }
    structural_leaf_prefixes = ("room_", "wall", "floor", "ceiling")
    if any(part in internal_names for part in parts):
        return False
    leaf = parts[-1]
    if leaf in structural_leaf_names:
        return False
    return not leaf.startswith(structural_leaf_prefixes)


def _is_descendant(path: str, ancestor: str) -> bool:
    prefix = ancestor.rstrip("/") + "/"
    return path.startswith(prefix)


def _first_material_binding(metadata: dict[str, Any]) -> dict[str, Any]:
    bindings = metadata.get("material_bindings") or []
    return bindings[0] if bindings and isinstance(bindings[0], dict) else {}


def _has_xform(metadata: dict[str, Any]) -> bool:
    if not metadata:
        return False
    xform = metadata.get("xform") or {}
    transform = metadata.get("world_transform") or {}
    return bool(transform or xform.get("layout") not in {None, "none", "unsupported"})


def _camera_fov(metadata: dict[str, Any]) -> float | None:
    focal = metadata.get("focal_length")
    aperture = metadata.get("horizontal_aperture")
    if focal is None or aperture is None:
        return None
    try:
        focal_f = float(focal)
        aperture_f = float(aperture)
    except (TypeError, ValueError):
        return None
    if focal_f <= 0.0:
        return None
    return math.degrees(2.0 * math.atan(aperture_f / (2.0 * focal_f)))


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        return "[" + ", ".join(_format_value(v) for v in value) + "]"
    return str(value)


def _build_specs(
    targets: UITargetSelection,
    factors: UIFactorSelection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if targets.prims:
        objects: list[dict[str, Any]] = []
        lights: list[dict[str, Any]] = []
        cameras: list[dict[str, Any]] = []
        for prim in targets.prims:
            if not prim.enabled:
                continue
            if prim.prim_kind == "object":
                spec = _object_spec_from_prim(prim)
                if spec is not None:
                    objects.append(spec)
            elif prim.prim_kind == "light" and prim.light:
                lights.append(_light_spec_from_prim(prim))
            elif prim.prim_kind == "camera":
                spec = _camera_spec_from_prim(prim)
                if spec is not None:
                    cameras.append(spec)
        return objects, lights, cameras

    objects = [
        spec for path in targets.objects
        if (spec := _object_spec(path, factors, targets.metadata.get(path))) is not None
    ]
    lights = [_light_spec(path) for path in targets.lights if factors.light]
    cameras = [_camera_spec(path) for path in targets.cameras if factors.camera]
    return objects, lights, cameras


def _object_spec(
    path: str,
    factors: UIFactorSelection,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    spec: dict[str, Any] = {"prim_path": path}
    material_available = bool(metadata.get("material_bindings")) if metadata is not None else True
    pose_available = _has_xform(metadata) if metadata is not None else True
    if factors.object_material and material_available:
        spec["material"] = {
            "color_jitter": 0.05,
            "roughness": [0.35, 0.8],
        }
    if factors.object_pose and pose_available:
        spec["pose"] = {
            "translation_jitter_m": [-0.02, 0.02],
            "rotation_jitter_deg": [-15.0, 15.0],
        }
    return spec if len(spec) > 1 else None


def _object_spec_from_prim(prim: UIPrimRandomization) -> dict[str, Any] | None:
    spec: dict[str, Any] = {"prim_path": prim.prim_path}
    if prim.material and prim.available_material:
        spec["material"] = {
            "color_jitter": prim.material_color_jitter,
            "roughness": [prim.roughness_min, prim.roughness_max],
        }
    if prim.pose and prim.available_pose:
        spec["pose"] = {
            "translation_jitter_m": _axis_ranges(
                prim.translation_x_min_m,
                prim.translation_x_max_m,
                prim.translation_y_min_m,
                prim.translation_y_max_m,
                prim.translation_z_min_m,
                prim.translation_z_max_m,
            ),
            "rotation_jitter_deg": _axis_ranges(
                prim.rotation_x_min_deg,
                prim.rotation_x_max_deg,
                prim.rotation_y_min_deg,
                prim.rotation_y_max_deg,
                prim.rotation_z_min_deg,
                prim.rotation_z_max_deg,
            ),
            "scale_jitter": _axis_ranges(
                prim.scale_x_min,
                prim.scale_x_max,
                prim.scale_y_min,
                prim.scale_y_max,
                prim.scale_z_min,
                prim.scale_z_max,
            ),
        }
    if prim.visibility and prim.available_visibility:
        visibility = _visibility_spec(prim.visibility_mode)
        if visibility:
            spec["visibility"] = visibility
    if prim.asset and prim.available_asset:
        asset = _asset_copy_spec(prim)
        if asset:
            spec["asset"] = asset
    if prim.physics and prim.available_physics:
        spec["physics"] = {"mass_scale": [prim.mass_scale_min, prim.mass_scale_max]}
    return spec if len(spec) > 1 else None


def _light_spec(path: str) -> dict[str, Any]:
    return {
        "prim_path": path,
        "intensity_scale": [0.8, 1.2],
        "color_temperature": [3000.0, 6500.0],
    }


def _light_spec_from_prim(prim: UIPrimRandomization) -> dict[str, Any]:
    return {
        "prim_path": prim.prim_path,
        "intensity_scale": [prim.intensity_min, prim.intensity_max],
        "color_temperature": [prim.color_temperature_min, prim.color_temperature_max],
    }


def _camera_spec(path: str) -> dict[str, Any]:
    return {
        "prim_path": path,
        "pose_jitter_m": [-0.03, 0.03],
        "yaw_pitch_jitter_deg": [-5.0, 5.0],
        "fov_deg": [45.0, 65.0],
    }


def _camera_spec_from_prim(prim: UIPrimRandomization) -> dict[str, Any] | None:
    spec: dict[str, Any] = {"prim_path": prim.prim_path}
    if prim.camera_pose and prim.available_camera_pose:
        spec["pose_jitter_m"] = [prim.camera_pose_min_m, prim.camera_pose_max_m]
        spec["yaw_pitch_jitter_deg"] = [prim.camera_yaw_pitch_min_deg, prim.camera_yaw_pitch_max_deg]
    if prim.camera_fov and prim.available_camera_fov:
        spec["fov_deg"] = [prim.camera_fov_min_deg, prim.camera_fov_max_deg]
    return spec if len(spec) > 1 else None


def _visibility_spec(mode: str) -> dict[str, Any] | None:
    normalized = str(mode or "random").strip().lower()
    if normalized in {"visible", "show", "shown", "keep_visible", "inherited", "on", "true"}:
        return {"mode": "visible", "visible": True}
    if normalized in {"hidden", "hide", "invisible", "off", "false"}:
        return {"mode": "hidden", "visible": False}
    if normalized in {"random", "rand", "sample", "sampled"}:
        return {"mode": "random"}
    return {"mode": "random"}


def _asset_copy_spec(prim: UIPrimRandomization) -> dict[str, Any] | None:
    count = max(0, int(prim.copy_count))
    if count <= 0:
        return None
    return {
        "copy_count": {
            "count": count,
            "suffix": prim.copy_suffix or "_copy",
            "composition": "reference",
        },
        "copy_placement": {
            "mode": "sample_nearby",
            "radius_m": [float(prim.copy_radius_min_m), float(prim.copy_radius_max_m)],
            "max_attempts": max(1, int(prim.copy_max_attempts)),
            "collision_check": bool(prim.copy_collision_check),
        },
    }


def _axis_ranges(
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    z_min: float,
    z_max: float,
) -> dict[str, list[float]]:
    return {
        "x": [float(x_min), float(x_max)],
        "y": [float(y_min), float(y_max)],
        "z": [float(z_min), float(z_max)],
    }
