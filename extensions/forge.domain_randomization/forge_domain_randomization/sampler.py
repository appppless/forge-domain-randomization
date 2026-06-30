"""Deterministic sampling for v0.2 domain randomization.

Consumes per-prim payload from the request (objects / lights / cameras /
visibility_pools).  No role- or manifest-based dispatch.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from .appliers.asset import copy_prim_reference_edit, payloads_edit, references_edit, relationship_targets_edit
from .appliers.camera import focal_length_edit, transform_edits as camera_transform_edits
from .appliers.lighting import color_edit, intensity_edit
from .appliers.material import diffuse_color_edit, roughness_edit, texture_asset_edit
from .appliers.physics import friction_edit, mass_edit, restitution_edit
from .appliers.pose import transform_edits as pose_transform_edits
from .appliers.visibility import visibility_edit
from . import xform_layout as _xform_layout
from .schemas import (
    CameraSpec,
    DomainRandomizationRequest,
    LightSpec,
    ObjectSpec,
    VisibilityPool,
)


@dataclass(frozen=True)
class LayerEdit:
    domain: str
    prim_path: str
    attribute: str
    value: Any
    value_type: str | None = None


@dataclass(frozen=True)
class RandomizationPlan:
    edits: list[LayerEdit] = field(default_factory=list)
    requested_parameters: dict[str, Any] = field(default_factory=dict)
    sampled_parameters: dict[str, Any] = field(default_factory=dict)
    achieved_parameters: dict[str, Any] = field(default_factory=dict)
    skipped_prims: list[dict[str, str]] = field(default_factory=list)

    def by_domain(self) -> dict[str, list[LayerEdit]]:
        grouped: dict[str, list[LayerEdit]] = {}
        for edit in self.edits:
            grouped.setdefault(edit.domain, []).append(edit)
        return grouped


def sample_randomization(request: DomainRandomizationRequest, scan: dict[str, Any]) -> RandomizationPlan:
    rng = random.Random(_stable_seed(request))
    edits: list[LayerEdit] = []
    requested: dict[str, Any] = {}
    sampled: dict[str, Any] = {}
    achieved: dict[str, Any] = {}
    skipped: list[dict[str, str]] = []

    for obj in request.objects:
        if _lookup_prim(scan, obj.prim_path) is None:
            skipped.append({"prim_path": obj.prim_path, "kind": "object",
                            "reason": "prim not present in scan; no edits emitted"})
            continue
        _sample_object(obj, rng, edits, requested, sampled, achieved, scan, skipped, request)
    for light in request.lights:
        if _lookup_light(scan, light.prim_path) is None:
            skipped.append({"prim_path": light.prim_path, "kind": "light",
                            "reason": "prim not present in scan; no edits emitted"})
            continue
        _sample_light(light, rng, edits, requested, sampled, achieved, scan)
    for cam in request.cameras:
        if _lookup_camera(scan, cam.prim_path) is None:
            skipped.append({"prim_path": cam.prim_path, "kind": "camera",
                            "reason": "prim not present in scan; no edits emitted"})
            continue
        _sample_camera(cam, rng, edits, requested, sampled, achieved, scan, skipped)
    for pool in request.visibility_pools:
        _sample_visibility_pool(pool, rng, edits, requested, sampled, achieved)

    return RandomizationPlan(
        edits=edits,
        requested_parameters=requested,
        sampled_parameters=sampled,
        achieved_parameters=achieved,
        skipped_prims=skipped,
    )


def _stable_seed(request: DomainRandomizationRequest) -> str:
    return "|".join(
        [
            request.base_scene_hash or request.base_scene_usd,
            request.config_hash or request.request_id,
            str(request.seed),
        ]
    )


def _sample_object(
    obj: ObjectSpec,
    rng: random.Random,
    edits: list[LayerEdit],
    requested: dict[str, Any],
    sampled: dict[str, Any],
    achieved: dict[str, Any],
    scan: dict[str, Any],
    skipped: list[dict[str, str]],
    request: DomainRandomizationRequest,
) -> None:
    p = obj.prim_path

    asset_cfg = obj.asset or {}
    if asset_cfg:
        _sample_asset(
            p,
            asset_cfg,
            rng,
            edits,
            requested,
            sampled,
            achieved,
            scan,
            skipped,
            base_scene_usd=scan.get("base_scene_usd") or request.base_scene_usd,
        )

    mat_cfg = obj.material or {}
    if mat_cfg:
        bindings = _lookup_material_bindings(scan, p)
        if not bindings:
            skipped.append({
                "prim_path": p,
                "kind": "object",
                "domain": "material",
                "reason": "material randomization requested but scan found no visual material binding",
            })
        color_jitter = float(mat_cfg.get("color_jitter", 0.0))
        roughness_range = mat_cfg.get("roughness")
        texture_variants = _texture_variants(mat_cfg.get("texture_variants"))
        for item in bindings:
            mat_path = str(item.get("material_path") or "")
            if not mat_path:
                continue
            base_color_attr = _color_attr_for_binding(item)
            base = _color_base_for_binding(item, base_color_attr)
            jittered = tuple(
                _clamp(c + rng.uniform(-color_jitter, color_jitter), 0.0, 1.0) for c in base
            )
            edits.append(diffuse_color_edit(mat_path, jittered, base_color_attr))
            _record(sampled, achieved, f"{p}.material.{mat_path}.base_color", list(jittered))
            _record(sampled, achieved, f"{p}.material.{mat_path}.base_color_attr", base_color_attr)
            if isinstance(roughness_range, list) and len(roughness_range) == 2:
                v = _clamp(rng.uniform(float(roughness_range[0]), float(roughness_range[1])), 0.0, 1.0)
                roughness_attr = str(
                    _material_attr_for_binding(item, "roughness_attr", _default_roughness_attr_for_binding)
                )
                edits.append(roughness_edit(mat_path, v, roughness_attr))
                _record(sampled, achieved, f"{p}.material.{mat_path}.roughness", v)
                _record(sampled, achieved, f"{p}.material.{mat_path}.roughness_attr", roughness_attr)
            if texture_variants:
                texture = rng.choice(texture_variants)
                texture_attr = str(item.get("diffuse_texture_attr") or "inputs:diffuse_texture")
                edits.append(texture_asset_edit(mat_path, texture, texture_attr))
                _record(sampled, achieved, f"{p}.material.{mat_path}.diffuse_texture", texture)
                _record(sampled, achieved, f"{p}.material.{mat_path}.diffuse_texture_attr", texture_attr)
        if "color_jitter" in mat_cfg:
            requested[f"{p}.material.color_jitter"] = mat_cfg.get("color_jitter")
        if "roughness" in mat_cfg:
            requested[f"{p}.material.roughness"] = mat_cfg.get("roughness")
        if "texture_variants" in mat_cfg:
            requested[f"{p}.material.texture_variants"] = mat_cfg.get("texture_variants")

    pose_cfg = obj.pose or {}
    if pose_cfg:
        pose_requested = _pose_requested_parameters(p, pose_cfg)
        requested.update(pose_requested)
        collision_check = bool(pose_cfg.get("collision_check", True))
        max_attempts = max(1, int(pose_cfg.get("collision_max_attempts", 8) or 1))
        padding = max(0.0, float(pose_cfg.get("collision_padding", 0.0) or 0.0))
        last_collision: dict[str, Any] | None = None

        for _attempt in range(max_attempts):
            new_pos, rotation_delta, scale_factors = _sample_pose_components(p, pose_cfg, rng, scan)
            if new_pos is None and rotation_delta is None and scale_factors is None:
                break
            if collision_check:
                candidate_bounds = _candidate_pose_bounds(scan, p, new_pos, rotation_delta, scale_factors)
                if candidate_bounds is not None:
                    last_collision = _first_aabb_collision(scan, p, candidate_bounds, padding)
                    if last_collision is not None:
                        continue

            xform = _prim_xform(scan, p)
            new_edits, warns, applied = pose_transform_edits(
                p,
                xform,
                world_translation=new_pos,
                rotation_delta_deg=rotation_delta,
                scale_factors=scale_factors,
            )
            edits.extend(new_edits)
            _extend_skipped(skipped, warns, kind="object")
            if "translation" in applied and new_pos is not None:
                _record(sampled, achieved, f"{p}.pose.translation", list(new_pos))
            if "rotation" in applied and rotation_delta is not None:
                _record(sampled, achieved, f"{p}.pose.rotation_delta_deg", list(rotation_delta))
            if "scale" in applied and scale_factors is not None:
                _record(sampled, achieved, f"{p}.pose.scale_factors", list(scale_factors))
            last_collision = None
            break
        if last_collision is not None:
            _extend_skipped(skipped, [_bbox_collision_warning(p, last_collision)], kind="object")

    vis_cfg = obj.visibility or {}
    if vis_cfg:
        visible = _sample_visibility(vis_cfg, rng)
        if visible is not None:
            edits.append(visibility_edit(p, visible))
            _record(sampled, achieved, f"{p}.visibility.visible", visible)
            requested[f"{p}.visibility"] = _copy_json_like(vis_cfg)

    phys_cfg = obj.physics or {}
    if phys_cfg:
        scan_prim = _lookup_prim(scan, p)
        phys_scan = (scan_prim or {}).get("physics") or {}
        base_mass = float(phys_scan.get("mass") or 1.0)
        # Carrier prim paths: where the API actually lives on the stage.
        # Fallback to the whitelist root path keeps v0.1-style scans working.
        mass_target = str(phys_scan.get("mass_prim_path") or phys_scan.get("rigid_body_prim_path") or p)
        physics_mat_target = str(phys_scan.get("physics_material_prim_path") or p)

        mass_value = None
        if "mass_scale" in phys_cfg:
            mass_value = max(0.0, base_mass * _scalar_or_uniform(phys_cfg, "mass_scale", rng))
            requested[f"{p}.physics.mass_scale"] = phys_cfg.get("mass_scale")
        elif "mass" in phys_cfg:
            mass_value = max(0.0, _scalar_or_uniform(phys_cfg, "mass", rng))
            requested[f"{p}.physics.mass"] = phys_cfg.get("mass")
        if mass_value is not None:
            edits.append(mass_edit(mass_target, mass_value))
            _record(sampled, achieved, f"{p}.physics.mass", mass_value)
        _sample_physics_attr(phys_cfg, rng, p, physics_mat_target, "friction", friction_edit, edits, sampled, achieved, requested, 0.0, 10.0)
        _sample_physics_attr(phys_cfg, rng, p, physics_mat_target, "restitution", restitution_edit, edits, sampled, achieved, requested, 0.0, 1.0)


def _sample_physics_attr(
    cfg: dict, rng: random.Random, p: str, target: str, key: str, edit_fn: Any,
    edits: list, sampled: dict, achieved: dict, requested: dict,
    lo: float, hi: float,
) -> None:
    rng_range = cfg.get(key)
    if isinstance(rng_range, list) and len(rng_range) == 2:
        val = _clamp(rng.uniform(float(rng_range[0]), float(rng_range[1])), lo, hi)
        edits.append(edit_fn(target, val))
        _record(sampled, achieved, f"{p}.physics.{key}", val)
        requested[f"{p}.physics.{key}"] = rng_range


def _sample_visibility(vis_cfg: dict[str, Any], rng: random.Random) -> bool | None:
    mode = str(vis_cfg.get("mode") or "").strip().lower()
    if vis_cfg.get("visible") is not None and mode not in {"random", "rand", "sample", "sampled"}:
        return bool(vis_cfg["visible"])
    if mode in {"visible", "show", "shown", "keep_visible", "inherited", "on", "true"}:
        return True
    if mode in {"hidden", "hide", "invisible", "off", "false"}:
        return False
    if mode in {"random", "rand", "sample", "sampled"}:
        return bool(rng.getrandbits(1))
    if vis_cfg.get("visible") is not None:
        return bool(vis_cfg["visible"])
    return None


def _pose_requested_parameters(prim_path: str, pose_cfg: dict[str, Any]) -> dict[str, Any]:
    requested: dict[str, Any] = {}
    toward = pose_cfg.get("translation_toward")
    if isinstance(toward, dict):
        target_prim = str(toward.get("target_prim", ""))
        if target_prim:
            requested[f"{prim_path}.pose.translation_toward"] = {
                "target_prim": target_prim,
                "distance_m": list(_range_or_default(toward.get("distance_m"), (0.15, 0.35))),
            }
    if "translation_jitter_m" in pose_cfg:
        requested[f"{prim_path}.pose.translation_jitter_m"] = pose_cfg.get("translation_jitter_m")
    if "rotation_jitter_deg" in pose_cfg:
        requested[f"{prim_path}.pose.rotation_jitter_deg"] = pose_cfg.get("rotation_jitter_deg")
    if "scale_jitter" in pose_cfg:
        requested[f"{prim_path}.pose.scale_jitter"] = pose_cfg.get("scale_jitter")
    return requested


def _sample_pose_components(
    prim_path: str,
    pose_cfg: dict[str, Any],
    rng: random.Random,
    scan: dict[str, Any],
) -> tuple[list[float] | None, list[float] | None, list[float] | None]:
    toward = pose_cfg.get("translation_toward")
    jitter_range = pose_cfg.get("translation_jitter_m")
    new_pos: list[float] | None = None
    rotation_delta: list[float] | None = None
    scale_factors: list[float] | None = None

    if isinstance(toward, dict):
        target_prim = str(toward.get("target_prim", ""))
        dist_range = _range_or_default(toward.get("distance_m"), (0.15, 0.35))
        if target_prim:
            target_pos = _prim_translation(scan, target_prim)
            if target_pos is not None:
                dist = max(0.0, rng.uniform(*dist_range))
                angle = rng.uniform(0.0, math.tau)
                self_pos = _prim_translation(scan, prim_path)
                my_z = self_pos[2] if self_pos is not None else 0.0
                new_pos = [
                    target_pos[0] + math.cos(angle) * dist,
                    target_pos[1] + math.sin(angle) * dist,
                    my_z,
                ]
    elif isinstance(jitter_range, dict):
        pos = _prim_translation(scan, prim_path)
        if pos is not None:
            deltas = [
                rng.uniform(*_range_or_default(jitter_range.get(axis), (0.0, 0.0)))
                for axis in ("x", "y", "z")
            ]
            new_pos = [float(pos[i]) + deltas[i] for i in range(3)]
    elif isinstance(jitter_range, list) and len(jitter_range) == 2:
        pos = _prim_translation(scan, prim_path)
        if pos is not None:
            new_pos = [c + rng.uniform(float(jitter_range[0]), float(jitter_range[1])) for c in pos]

    if "rotation_jitter_deg" in pose_cfg:
        rotation_delta = _sample_rotation_delta(pose_cfg.get("rotation_jitter_deg"), rng)
    if "scale_jitter" in pose_cfg:
        scale_factors = _sample_scale_factors(pose_cfg.get("scale_jitter"), rng)
    return new_pos, rotation_delta, scale_factors


def _sample_asset(
    prim_path: str,
    cfg: dict[str, Any],
    rng: random.Random,
    edits: list[LayerEdit],
    requested: dict[str, Any],
    sampled: dict[str, Any],
    achieved: dict[str, Any],
    scan: dict[str, Any],
    skipped: list[dict[str, str]],
    *,
    base_scene_usd: str,
) -> None:
    reference_variants = _asset_variants(cfg.get("reference_variants") or cfg.get("references"))
    payload_variants = _asset_variants(cfg.get("payload_variants") or cfg.get("payloads"))
    if reference_variants:
        chosen = rng.choice(reference_variants)
        edits.append(references_edit(prim_path, [chosen], op=str(cfg.get("op") or "set")))
        _record(sampled, achieved, f"{prim_path}.asset.references", dict(chosen))
        requested[f"{prim_path}.asset.reference_variants"] = _copy_json_like(cfg.get("reference_variants") or cfg.get("references"))
    if payload_variants:
        chosen = rng.choice(payload_variants)
        edits.append(payloads_edit(prim_path, [chosen], op=str(cfg.get("op") or "set")))
        _record(sampled, achieved, f"{prim_path}.asset.payloads", dict(chosen))
        requested[f"{prim_path}.asset.payload_variants"] = _copy_json_like(cfg.get("payload_variants") or cfg.get("payloads"))

    relationship_specs = _relationship_specs(cfg.get("relationships"))
    for rel_spec in relationship_specs:
        name = str(rel_spec.get("name") or rel_spec.get("relationship") or "")
        targets = rel_spec.get("targets", rel_spec.get("target"))
        target_list = _relationship_targets(targets)
        if not name or not target_list:
            continue
        rel_prim = str(rel_spec.get("prim_path") or prim_path)
        edits.append(relationship_targets_edit(rel_prim, name, target_list))
        _record(sampled, achieved, f"{prim_path}.asset.relationship.{rel_prim}.{name}", list(target_list))
    if relationship_specs:
        requested[f"{prim_path}.asset.relationships"] = _copy_json_like(cfg.get("relationships"))

    copy_items = _copy_specs(cfg.get("copy_to"))
    auto_copy_items = _auto_copy_specs(prim_path, cfg)
    copy_items.extend(auto_copy_items)
    reserved_copy_bounds: list[tuple[str, dict[str, list[float]]]] = []
    for item in copy_items:
        dst = str(item.get("prim_path") or item.get("target_prim_path") or item.get("new_prim_path") or "")
        if not dst:
            continue
        src = str(item.get("source_prim_path") or prim_path)
        asset_path = str(item.get("asset_path") or base_scene_usd)
        use_payload = str(item.get("composition") or item.get("type") or "reference").lower() == "payload"
        translation, candidate_bounds, warning = _copy_translation(
            scan,
            src,
            dst,
            cfg,
            item,
            rng,
            reserved_copy_bounds,
        )
        if warning is not None:
            _extend_skipped(skipped, [warning], kind="object")
            continue
        if use_payload:
            edits.append(payloads_edit(dst, [{"asset_path": asset_path, "prim_path": src}]))
        else:
            edits.append(copy_prim_reference_edit(src, dst, asset_path))
        _record(sampled, achieved, f"{prim_path}.asset.copy.{dst}", {
            "source_prim_path": src,
            "asset_path": asset_path,
            "composition": "payload" if use_payload else "reference",
        })
        if translation is not None:
            edits.append(LayerEdit(
                domain="placement",
                prim_path=dst,
                attribute=str(item.get("translation_attr") or "xformOp:translate"),
                value=[float(v) for v in translation],
                value_type="double3",
            ))
            _record(sampled, achieved, f"{prim_path}.asset.copy.{dst}.translation", list(translation))
            if candidate_bounds is not None:
                reserved_copy_bounds.append((dst, candidate_bounds))
    if copy_items:
        if cfg.get("copy_to") is not None:
            requested[f"{prim_path}.asset.copy_to"] = _copy_json_like(cfg.get("copy_to"))
        if cfg.get("copy_count") is not None:
            requested[f"{prim_path}.asset.copy_count"] = _copy_json_like(cfg.get("copy_count"))
        if cfg.get("copy") is not None:
            requested[f"{prim_path}.asset.copy"] = _copy_json_like(cfg.get("copy"))
        if cfg.get("copy_placement") is not None:
            requested[f"{prim_path}.asset.copy_placement"] = _copy_json_like(cfg.get("copy_placement"))


def _copy_translation(
    scan: dict[str, Any],
    source_prim_path: str,
    destination_prim_path: str,
    asset_cfg: dict[str, Any],
    item: dict[str, Any],
    rng: random.Random,
    reserved_copy_bounds: list[tuple[str, dict[str, list[float]]]],
) -> tuple[list[float] | None, dict[str, list[float]] | None, dict[str, Any] | None]:
    explicit_translation = _coerce_vec3(item.get("translation"), None)
    placement_cfg = _copy_placement_cfg(asset_cfg, item)
    if explicit_translation is not None:
        translation = [float(v) for v in explicit_translation]
        candidate_bounds = _candidate_pose_bounds(scan, source_prim_path, translation, None, None)
        if _copy_collision_check_enabled(placement_cfg):
            collision = _copy_first_collision(
                scan,
                destination_prim_path,
                candidate_bounds,
                reserved_copy_bounds,
                _copy_collision_padding(placement_cfg),
            )
            if collision is not None:
                return None, None, _copy_bbox_collision_warning(destination_prim_path, collision)
        return translation, candidate_bounds, None

    mode = str(placement_cfg.get("mode") or "sample_nearby").lower()
    if mode in {"none", "in_place", "inplace", "disabled", "off"}:
        return None, None, None
    if mode not in {"sample_nearby", "nearby", "disk", "circle", "radial"}:
        return None, None, {
            "type": "copy_placement_unsupported",
            "severity": "warning",
            "prim_path": destination_prim_path,
            "message": f"copy placement mode '{mode}' is unsupported for {destination_prim_path}; copy skipped.",
        }

    source_pos = _copy_source_position(scan, source_prim_path)
    if source_pos is None:
        return None, None, {
            "type": "copy_placement_missing_source_position",
            "severity": "warning",
            "prim_path": destination_prim_path,
            "message": f"source position for {source_prim_path} is unavailable; copy {destination_prim_path} skipped.",
        }
    radius_range = _copy_radius_range(scan, source_prim_path, placement_cfg)
    max_attempts = max(1, int(placement_cfg.get("max_attempts", placement_cfg.get("collision_max_attempts", 16)) or 1))
    padding = _copy_collision_padding(placement_cfg)
    collision_check = _copy_collision_check_enabled(placement_cfg)
    last_collision: dict[str, Any] | None = None
    for _attempt in range(max_attempts):
        radius = _sample_annulus_radius(radius_range, rng)
        angle = rng.uniform(0.0, math.tau)
        translation = [
            source_pos[0] + math.cos(angle) * radius,
            source_pos[1] + math.sin(angle) * radius,
            source_pos[2],
        ]
        candidate_bounds = _candidate_pose_bounds(scan, source_prim_path, translation, None, None)
        if collision_check:
            collision = _copy_first_collision(
                scan,
                destination_prim_path,
                candidate_bounds,
                reserved_copy_bounds,
                padding,
            )
            if collision is not None:
                last_collision = collision
                continue
        return translation, candidate_bounds, None
    return None, None, _copy_bbox_collision_warning(destination_prim_path, last_collision)


def _copy_placement_cfg(asset_cfg: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("copy_placement", item.get("placement", asset_cfg.get("copy_placement")))
    if raw is False:
        return {"mode": "in_place"}
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _copy_collision_check_enabled(placement_cfg: dict[str, Any]) -> bool:
    return bool(placement_cfg.get("collision_check", True))


def _copy_collision_padding(placement_cfg: dict[str, Any]) -> float:
    return max(0.0, float(placement_cfg.get("collision_padding", placement_cfg.get("margin", 0.02)) or 0.0))


def _copy_source_position(scan: dict[str, Any], source_prim_path: str) -> list[float] | None:
    pos = _prim_translation(scan, source_prim_path)
    if pos is not None:
        return [float(v) for v in pos]
    prim = _lookup_prim(scan, source_prim_path)
    bounds = _aabb_from_bounds((prim or {}).get("bounds"))
    if bounds is not None:
        return _aabb_center(bounds)
    return None


def _copy_radius_range(
    scan: dict[str, Any],
    source_prim_path: str,
    placement_cfg: dict[str, Any],
) -> tuple[float, float]:
    explicit = placement_cfg.get("radius_m", placement_cfg.get("radius"))
    if explicit is not None:
        lo, hi = _range_or_default(explicit, (0.0, 0.0))
        return max(0.0, lo), max(0.0, hi)
    prim = _lookup_prim(scan, source_prim_path)
    bounds = _aabb_from_bounds((prim or {}).get("bounds"))
    margin = _copy_collision_padding(placement_cfg)
    if bounds is None:
        return 0.2 + margin, 0.8 + margin
    lo = bounds["aabb_min"]
    hi = bounds["aabb_max"]
    xy_extent = max(hi[0] - lo[0], hi[1] - lo[1], 0.05)
    inner = float(placement_cfg.get("inner_radius_m", xy_extent + margin))
    outer = float(placement_cfg.get("outer_radius_m", max(inner, xy_extent * 3.0 + margin)))
    return max(0.0, inner), max(0.0, outer)


def _sample_annulus_radius(radius_range: tuple[float, float], rng: random.Random) -> float:
    lo, hi = sorted((max(0.0, radius_range[0]), max(0.0, radius_range[1])))
    if hi <= lo:
        return lo
    return math.sqrt(rng.uniform(lo * lo, hi * hi))


def _copy_first_collision(
    scan: dict[str, Any],
    destination_prim_path: str,
    candidate_bounds: dict[str, list[float]] | None,
    reserved_copy_bounds: list[tuple[str, dict[str, list[float]]]],
    padding: float,
) -> dict[str, Any] | None:
    if candidate_bounds is None:
        return None
    collision = _first_aabb_collision(scan, destination_prim_path, candidate_bounds, padding)
    if collision is not None:
        return collision
    for other_path, other_bounds in reserved_copy_bounds:
        if _same_or_related_path(destination_prim_path, other_path):
            continue
        if _aabb_overlap(candidate_bounds, other_bounds, padding):
            return {
                "other_prim_path": other_path,
                "candidate_bounds": candidate_bounds,
                "other_bounds": other_bounds,
                "overlap_volume": _aabb_overlap_volume(candidate_bounds, other_bounds, padding),
            }
    return None


def _copy_bbox_collision_warning(
    destination_prim_path: str,
    collision: dict[str, Any] | None,
) -> dict[str, Any]:
    if collision is None:
        return {
            "type": "copy_bbox_collision_rejected",
            "severity": "warning",
            "prim_path": destination_prim_path,
            "message": (
                f"no collision-free sampled placement found for copy {destination_prim_path}; "
                "copy skipped."
            ),
        }
    other = str(collision.get("other_prim_path") or "")
    volume = float(collision.get("overlap_volume") or 0.0)
    return {
        "type": "copy_bbox_collision_rejected",
        "severity": "warning",
        "prim_path": destination_prim_path,
        "other_prim_path": other,
        "message": (
            f"sampled copy placement for {destination_prim_path} overlaps {other} by AABB broad-phase "
            f"(overlap_volume={volume:.6g}); copy skipped."
        ),
    }


def _sample_light(
    light: LightSpec,
    rng: random.Random,
    edits: list[LayerEdit],
    requested: dict[str, Any],
    sampled: dict[str, Any],
    achieved: dict[str, Any],
    scan: dict[str, Any],
) -> None:
    p = light.prim_path
    if light.intensity_scale:
        base_intensity = _lookup_light_intensity(scan, p, fallback=1.0)
        scale = rng.uniform(*_to_pair(light.intensity_scale))
        intensity = max(0.0, base_intensity * scale)
        edits.append(intensity_edit(p, intensity))
        _record(sampled, achieved, f"{p}.light.intensity", intensity)
        requested[f"{p}.light.intensity_scale"] = list(light.intensity_scale)
    if light.color_temperature:
        temperature = rng.uniform(*_to_pair(light.color_temperature))
        color = _color_temperature_to_rgb(temperature)
        edits.append(color_edit(p, color))
        _record(sampled, achieved, f"{p}.light.color_temperature", temperature)
        _record(sampled, achieved, f"{p}.light.color", list(color))
        requested[f"{p}.light.color_temperature"] = list(light.color_temperature)
    if light.color and not light.color_temperature:
        edits.append(color_edit(p, light.color))
        _record(sampled, achieved, f"{p}.light.color", list(light.color))
        requested[f"{p}.light.color"] = list(light.color)


def _sample_camera(
    cam: CameraSpec,
    rng: random.Random,
    edits: list[LayerEdit],
    requested: dict[str, Any],
    sampled: dict[str, Any],
    achieved: dict[str, Any],
    scan: dict[str, Any],
    skipped: list[dict[str, str]],
) -> None:
    p = cam.prim_path
    new_pos: list[float] | None = None
    rotation_delta: list[float] | None = None

    if cam.pose_jitter_m:
        pos = _prim_translation(scan, p)
        if pos is not None:
            new_pos = [c + rng.uniform(*_to_pair(cam.pose_jitter_m)) for c in pos]
            requested[f"{p}.camera.pose_jitter_m"] = list(cam.pose_jitter_m)
    if cam.yaw_pitch_jitter_deg:
        rotation_delta = _sample_camera_rotation_delta(cam.yaw_pitch_jitter_deg, rng)
        requested[f"{p}.camera.yaw_pitch_jitter_deg"] = _copy_json_like(cam.yaw_pitch_jitter_deg)

    if new_pos is not None or rotation_delta is not None:
        xform = _camera_xform(scan, p)
        new_edits, warns, applied = camera_transform_edits(
            p,
            xform,
            world_translation=new_pos,
            rotation_delta_deg=rotation_delta,
        )
        edits.extend(new_edits)
        _extend_skipped(skipped, warns, kind="camera")
        if "translation" in applied and new_pos is not None:
            _record(sampled, achieved, f"{p}.camera.translation", list(new_pos))
        if "rotation" in applied and rotation_delta is not None:
            _record(sampled, achieved, f"{p}.camera.rotation_delta_deg", list(rotation_delta))

    if cam.fov_deg:
        scan_cam = _lookup_camera(scan, p)
        aperture = float(scan_cam.get("horizontal_aperture") or 20.955) if scan_cam else 20.955
        fov = rng.uniform(*_to_pair(cam.fov_deg))
        focal_length = aperture / (2.0 * math.tan(math.radians(fov) / 2.0))
        edits.append(focal_length_edit(p, focal_length))
        _record(sampled, achieved, f"{p}.camera.fov_deg", fov)
        _record(sampled, achieved, f"{p}.camera.focal_length", focal_length)
        requested[f"{p}.camera.fov_deg"] = list(cam.fov_deg)


def _sample_visibility_pool(
    pool: VisibilityPool,
    rng: random.Random,
    edits: list[LayerEdit],
    requested: dict[str, Any],
    sampled: dict[str, Any],
    achieved: dict[str, Any],
) -> None:
    prims = list(pool.prims)
    rng.shuffle(prims)
    visible_set = set(prims[: max(0, pool.keep_visible)])
    for prim_path in pool.prims:
        visible = prim_path in visible_set
        edits.append(visibility_edit(prim_path, visible))
        _record(sampled, achieved, f"visibility_pool.{pool.id}.{prim_path}.visible", visible)
    requested[f"visibility_pool.{pool.id}.keep_visible"] = pool.keep_visible


def _lookup_prim(scan: dict[str, Any], prim_path: str) -> dict[str, Any] | None:
    for prim in scan.get("prims") or []:
        if str(prim.get("prim_path")) == prim_path:
            return prim
    return None


def _lookup_camera(scan: dict[str, Any], prim_path: str) -> dict[str, Any] | None:
    for cam in scan.get("cameras") or []:
        if str(cam.get("prim_path")) == prim_path:
            return cam
    return None


def _lookup_light(scan: dict[str, Any], prim_path: str) -> dict[str, Any] | None:
    for light in scan.get("lights") or []:
        if str(light.get("prim_path")) == prim_path:
            return light
    return None


def _lookup_material_bindings(scan: dict[str, Any], prim_path: str) -> list[dict[str, Any]]:
    prim = _lookup_prim(scan, prim_path)
    if prim:
        return prim.get("material_bindings") or []
    return []


def _candidate_pose_bounds(
    scan: dict[str, Any],
    prim_path: str,
    world_translation: list[float] | tuple[float, float, float] | None,
    rotation_delta_deg: list[float] | tuple[float, float, float] | None,
    scale_factors: list[float] | tuple[float, float, float] | None,
) -> dict[str, list[float]] | None:
    prim = _lookup_prim(scan, prim_path)
    if prim is None:
        return None
    bounds = _aabb_from_bounds(prim.get("bounds"))
    if bounds is None:
        return None
    pivot = _prim_translation(scan, prim_path)
    if pivot is None:
        pivot = _aabb_center(bounds)
    target_pivot = list(world_translation) if world_translation is not None else list(pivot)
    rotation_matrix = (
        _xform_layout.euler_xyz_to_matrix([float(v) for v in rotation_delta_deg])
        if rotation_delta_deg is not None else None
    )
    scale = [float(v) for v in scale_factors] if scale_factors is not None else [1.0, 1.0, 1.0]
    points: list[list[float]] = []
    for corner in _aabb_corners(bounds):
        relative = [
            (corner[0] - pivot[0]) * scale[0],
            (corner[1] - pivot[1]) * scale[1],
            (corner[2] - pivot[2]) * scale[2],
        ]
        if rotation_matrix is not None:
            relative = _xform_layout.mat_vec_mul_point(rotation_matrix, relative)
        points.append([
            target_pivot[0] + relative[0],
            target_pivot[1] + relative[1],
            target_pivot[2] + relative[2],
        ])
    return _aabb_from_points(points)


def _first_aabb_collision(
    scan: dict[str, Any],
    prim_path: str,
    candidate: dict[str, list[float]],
    padding: float,
) -> dict[str, Any] | None:
    for other in scan.get("prims") or []:
        other_path = str(other.get("prim_path") or "")
        if not other_path or _same_or_related_path(prim_path, other_path):
            continue
        other_bounds = _aabb_from_bounds(other.get("bounds"))
        if other_bounds is None:
            continue
        if _aabb_overlap(candidate, other_bounds, padding):
            return {
                "other_prim_path": other_path,
                "candidate_bounds": candidate,
                "other_bounds": other_bounds,
                "overlap_volume": _aabb_overlap_volume(candidate, other_bounds, padding),
            }
    return None


def _bbox_collision_warning(prim_path: str, collision: dict[str, Any]) -> dict[str, Any]:
    other = str(collision.get("other_prim_path") or "")
    volume = float(collision.get("overlap_volume") or 0.0)
    return {
        "type": "bbox_collision_rejected",
        "severity": "warning",
        "prim_path": prim_path,
        "other_prim_path": other,
        "message": (
            f"sampled pose for {prim_path} overlaps {other} by AABB broad-phase "
            f"(overlap_volume={volume:.6g}); pose override skipped."
        ),
    }


def _aabb_from_bounds(value: Any) -> dict[str, list[float]] | None:
    if not isinstance(value, dict):
        return None
    lo = value.get("aabb_min")
    hi = value.get("aabb_max")
    if not (isinstance(lo, list) and isinstance(hi, list) and len(lo) == 3 and len(hi) == 3):
        return None
    return {"aabb_min": [float(v) for v in lo], "aabb_max": [float(v) for v in hi]}


def _aabb_center(bounds: dict[str, list[float]]) -> list[float]:
    lo = bounds["aabb_min"]
    hi = bounds["aabb_max"]
    return [(lo[i] + hi[i]) * 0.5 for i in range(3)]


def _aabb_corners(bounds: dict[str, list[float]]) -> list[list[float]]:
    lo = bounds["aabb_min"]
    hi = bounds["aabb_max"]
    return [
        [x, y, z]
        for x in (lo[0], hi[0])
        for y in (lo[1], hi[1])
        for z in (lo[2], hi[2])
    ]


def _aabb_from_points(points: list[list[float]]) -> dict[str, list[float]]:
    return {
        "aabb_min": [min(p[i] for p in points) for i in range(3)],
        "aabb_max": [max(p[i] for p in points) for i in range(3)],
    }


def _same_or_related_path(a: str, b: str) -> bool:
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _aabb_overlap(a: dict[str, list[float]], b: dict[str, list[float]], padding: float) -> bool:
    return all(
        (a["aabb_min"][i] - padding) < (b["aabb_max"][i] + padding)
        and (b["aabb_min"][i] - padding) < (a["aabb_max"][i] + padding)
        for i in range(3)
    )


def _aabb_overlap_volume(a: dict[str, list[float]], b: dict[str, list[float]], padding: float) -> float:
    lengths = []
    for i in range(3):
        lo = max(a["aabb_min"][i] - padding, b["aabb_min"][i] - padding)
        hi = min(a["aabb_max"][i] + padding, b["aabb_max"][i] + padding)
        lengths.append(max(0.0, hi - lo))
    return lengths[0] * lengths[1] * lengths[2]


def _texture_variants(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            out.append(item)
        elif isinstance(item, dict):
            candidate = item.get("path") or item.get("asset_path") or item.get("texture")
            if isinstance(candidate, str) and candidate:
                out.append(candidate)
    return out


def _asset_variants(value: Any) -> list[dict[str, str]]:
    raw = value if isinstance(value, list) else []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str) and item:
            out.append({"asset_path": item, "prim_path": ""})
        elif isinstance(item, dict):
            asset_path = item.get("asset_path") or item.get("asset") or item.get("path")
            if not isinstance(asset_path, str) or not asset_path:
                continue
            out.append({
                "asset_path": asset_path,
                "prim_path": str(item.get("prim_path") or item.get("target_prim") or ""),
            })
    return out


def _copy_specs(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _auto_copy_specs(prim_path: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    value = cfg.get("copy_count", cfg.get("copy"))
    if value is None:
        return []
    if isinstance(value, bool):
        count = 1 if value else 0
        options: dict[str, Any] = {}
    elif isinstance(value, int):
        count = value
        options = {}
    elif isinstance(value, dict):
        count = int(value.get("count", 1))
        options = value
    else:
        return []
    count = max(0, count)
    suffix = str(options.get("suffix") or cfg.get("copy_suffix") or "_copy")
    composition = str(options.get("composition") or cfg.get("copy_composition") or "reference")
    specs: list[dict[str, Any]] = []
    for i in range(count):
        specs.append({
            "prim_path": _copy_prim_path(prim_path, suffix, i, count),
            "source_prim_path": prim_path,
            "composition": composition,
        })
    return specs


def _copy_prim_path(prim_path: str, suffix: str, index: int, count: int) -> str:
    head, sep, tail = prim_path.rstrip("/").rpartition("/")
    parent = head if sep else ""
    base = tail or "prim"
    if count == 1:
        name = f"{base}{suffix}"
    else:
        name = f"{base}{suffix}_{index + 1}"
    return f"{parent}/{name}" if parent else f"/{name}"


def _relationship_specs(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _relationship_targets(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _material_attr_for_binding(item: dict[str, Any], key: str, default_fn: Any) -> str:
    model = str(item.get("material_model") or "").lower()
    if model in {"omni_pbr", "sim_pbr", "usd_preview_surface"}:
        return default_fn(item)
    return str(item.get(key) or default_fn(item))


def _color_attr_for_binding(item: dict[str, Any]) -> str:
    model = str(item.get("material_model") or "").lower()
    has_texture = bool(item.get("diffuse_texture") or item.get("diffuse_texture_attr"))
    if model in {"omni_pbr", "sim_pbr"} and has_texture:
        return str(item.get("diffuse_tint_attr") or "inputs:diffuse_tint")
    return str(_material_attr_for_binding(item, "base_color_attr", _default_color_attr_for_binding))


def _color_base_for_binding(item: dict[str, Any], attribute: str) -> tuple[float, float, float]:
    if attribute == "inputs:diffuse_tint":
        return _coerce_color(item.get("diffuse_tint"), (1.0, 1.0, 1.0))
    return _coerce_color(item.get("base_color"), (0.8, 0.8, 0.8))


def _default_color_attr_for_binding(item: dict[str, Any]) -> str:
    model = str(item.get("material_model") or "").lower()
    if model in {"omni_pbr", "sim_pbr"}:
        return "inputs:diffuse_color_constant"
    if model == "usd_preview_surface":
        return "inputs:diffuseColor"
    path = str(item.get("material_path") or "").lower()
    if "omniphbr" in path or "omnipbr" in path or "simpbr" in path:
        return "inputs:diffuse_color_constant"
    return "inputs:diffuseColor"


def _default_roughness_attr_for_binding(item: dict[str, Any]) -> str:
    model = str(item.get("material_model") or "").lower()
    if model in {"omni_pbr", "sim_pbr"}:
        return "inputs:reflection_roughness_constant"
    if model == "usd_preview_surface":
        return "inputs:roughness"
    path = str(item.get("material_path") or "").lower()
    if "omniphbr" in path or "omnipbr" in path or "simpbr" in path:
        return "inputs:reflection_roughness_constant"
    return "inputs:roughness"


def _lookup_light_intensity(scan: dict[str, Any], prim_path: str, fallback: float) -> float:
    for light in scan.get("lights") or []:
        if str(light.get("prim_path")) == prim_path:
            val = light.get("intensity")
            if val is not None:
                return float(val)
    return fallback


def _prim_translation(scan: dict[str, Any], prim_path: str) -> tuple[float, float, float] | None:
    for prim in scan.get("prims") or []:
        if str(prim.get("prim_path")) == prim_path:
            t = (prim.get("world_transform") or {}).get("translation")
            return _coerce_vec3(t, None)
    for cam in scan.get("cameras") or []:
        if str(cam.get("prim_path")) == prim_path:
            t = (cam.get("world_transform") or {}).get("translation")
            return _coerce_vec3(t, None)
    return None


def _prim_xform(scan: dict[str, Any], prim_path: str) -> dict[str, Any] | None:
    prim = _lookup_prim(scan, prim_path)
    if prim is None:
        return None
    return prim.get("xform")


def _camera_xform(scan: dict[str, Any], prim_path: str) -> dict[str, Any] | None:
    cam = _lookup_camera(scan, prim_path)
    if cam is None:
        return None
    return cam.get("xform")


def _extend_skipped(skipped: list[dict[str, str]], warnings: list[dict[str, Any]], *, kind: str) -> None:
    for w in warnings or []:
        skipped.append({
            "prim_path": str(w.get("prim_path", "")),
            "kind": kind,
            "reason": str(w.get("message") or w.get("type") or "skipped"),
        })


def _record(sampled: dict[str, Any], achieved: dict[str, Any], key: str, value: Any) -> None:
    sampled[key] = value
    achieved[key] = value


def _to_pair(value: Any) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    if isinstance(value, (int, float)):
        return float(value), float(value)
    return 0.0, 0.0


def _scalar_or_uniform(cfg: dict[str, Any], key: str, rng: random.Random) -> float:
    v = cfg.get(key)
    if isinstance(v, list) and len(v) == 2:
        return rng.uniform(float(v[0]), float(v[1]))
    return float(v) if v is not None else 1.0


def _range_or_default(value: Any, fallback: tuple[float, float]) -> tuple[float, float]:
    if isinstance(value, list) and len(value) == 2:
        return float(value[0]), float(value[1])
    if isinstance(value, (int, float)):
        s = float(value)
        return s, s
    return fallback


def _sample_rotation_delta(value: Any, rng: random.Random) -> list[float]:
    if isinstance(value, dict):
        return [
            rng.uniform(*_range_or_default(value.get(axis), (0.0, 0.0)))
            for axis in ("x", "y", "z")
        ]
    if isinstance(value, list) and len(value) == 2:
        # Shorthand is yaw-only, matching schemas.py.
        return [0.0, 0.0, rng.uniform(float(value[0]), float(value[1]))]
    if isinstance(value, (int, float)):
        return [0.0, 0.0, float(value)]
    return [0.0, 0.0, 0.0]


def _sample_camera_rotation_delta(value: Any, rng: random.Random) -> list[float]:
    if isinstance(value, dict):
        return [
            rng.uniform(*_range_or_default(value.get("roll", value.get("x")), (0.0, 0.0))),
            rng.uniform(*_range_or_default(value.get("pitch", value.get("y")), (0.0, 0.0))),
            rng.uniform(*_range_or_default(value.get("yaw", value.get("z")), (0.0, 0.0))),
        ]
    if isinstance(value, list) and len(value) == 2:
        return [
            0.0,
            rng.uniform(float(value[0]), float(value[1])),
            rng.uniform(float(value[0]), float(value[1])),
        ]
    if isinstance(value, (int, float)):
        return [0.0, 0.0, float(value)]
    return [0.0, 0.0, 0.0]


def _sample_scale_factors(value: Any, rng: random.Random) -> list[float]:
    if isinstance(value, dict):
        return [
            rng.uniform(*_range_or_default(value.get(axis), (1.0, 1.0)))
            for axis in ("x", "y", "z")
        ]
    if isinstance(value, list) and len(value) == 2:
        factor = rng.uniform(float(value[0]), float(value[1]))
        return [factor, factor, factor]
    if isinstance(value, (int, float)):
        factor = float(value)
        return [factor, factor, factor]
    return [1.0, 1.0, 1.0]


def _coerce_color(value: Any, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    return _coerce_vec3(value, fallback)


def _copy_json_like(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _copy_json_like(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy_json_like(v) for v in value]
    return value


def _coerce_vec3(value: Any, fallback: tuple[float, float, float] | None) -> tuple[float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return float(value[0]), float(value[1]), float(value[2])
    return fallback


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _color_temperature_to_rgb(kelvin: float) -> tuple[float, float, float]:
    temperature = max(1000.0, min(40000.0, kelvin)) / 100.0
    if temperature <= 66.0:
        red = 255.0
        green = 99.4708025861 * math.log(temperature) - 161.1195681661
        blue = 0.0 if temperature <= 19.0 else 138.5177312231 * math.log(temperature - 10.0) - 305.0447927307
    else:
        red = 329.698727446 * ((temperature - 60.0) ** -0.1332047592)
        green = 288.1221695283 * ((temperature - 60.0) ** -0.0755148492)
        blue = 255.0
    return (
        _clamp(red / 255.0, 0.0, 1.0),
        _clamp(green / 255.0, 0.0, 1.0),
        _clamp(blue / 255.0, 0.0, 1.0),
    )
