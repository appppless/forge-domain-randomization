"""Artifact schemas for the FORGE domain randomization extension.

v0.2 — general-purpose Isaac DR tool. No FORGE-specific role/manifest concepts.
Objects/lights/cameras are listed explicitly (whitelist). Each entry carries its
own per-domain randomization parameters.

ObjectSpec.asset payload (open dict, interpreted by the asset composition
pipeline). Supported low-level keys:

    reference_variants / payload_variants:
        List of candidate {"asset_path": str, "prim_path": str?}; one candidate
        is sampled and authored as the current prim's explicit references or
        payloads.
    copy_to:
        Dict or list of dicts with destination prim paths. The new prim is
        authored as a reference/payload to a source prim in the base scene. If
        no explicit ``translation`` is provided, sampler places the copy by
        sampling around the source prim.
    copy_count / copy:
        GUI-like sibling duplicate count. Destination prims are auto-named
        with ``_copy`` suffix and are placed by sampling an XY disk around the
        source prim.
    copy_placement:
        Optional placement policy for copies. ``{"mode": "sample_nearby"}``
        is the default; ``radius_m`` controls the sampled annulus and bbox
        collision checking rejects overlaps with scanned prims and already
        accepted sibling copies. Set ``false`` or ``{"mode": "in_place"}`` to
        keep GUI-style same-transform duplicates.

ObjectSpec.pose payload (open dict, interpreted by the pose pipeline).

Translation / rotation / scale are first-class peers: all three define the
prim's local transform and are processed through the same sampler + applier
path. Supported keys:

    translation_jitter_m: [lo, hi]
        Symmetric scalar range applied per axis in the prim's local frame.
    translation_toward: {"target_prim": str, "distance_m": [lo, hi]}
        Sample a 2D ring position around a target prim, keeping own z.
    rotation_jitter_deg: [lo, hi] | {"x": [lo, hi], "y": [...], "z": [...]}
        Delta Euler rotation in degrees composed on top of the prim's base
        rotation. Shorthand ``[lo, hi]`` is yaw-only (Z axis); the dict form
        selects per-axis ranges, missing axes default to ``[0.0, 0.0]``.
    scale_jitter: [lo, hi] | {"x": [lo, hi], "y": [...], "z": [...]}
        Multiplicative scale delta. Shorthand ``[lo, hi]`` is uniform across
        axes; the dict form selects per-axis factors.

xformOpOrder preservation: the applier never reorders an existing prim's
xformOps. For TRS-layout prims it only rewrites attribute values of ops the
prim already authors; a requested delta on an op type the prim does not
author is skipped with a warning. Matrix-layout prims have no ordering
concern (single transform op).

CameraSpec supports the same layout-aware xform authoring for translation and
rotation. ``yaw_pitch_jitter_deg`` accepts ``[lo, hi]`` to sample both pitch
(Y axis) and yaw (Z axis), or a dict with ``yaw`` / ``pitch`` / ``roll`` aliases
for ``z`` / ``y`` / ``x``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SCHEMA_VERSION = "0.2"

# Canonical Euler order for ``pose.rotation_jitter_deg``. The applier composes
# the sampled delta as Rz * Ry * Rx (extrinsic XYZ) on top of the prim's base
# rotation. Sampler / applier / report all share this convention.
ROTATION_JITTER_EULER_ORDER = "XYZ"


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_dict(value: Any, key: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object or null")
    return dict(value)


def _optional_block(value: Any, key: str) -> dict[str, Any] | None:
    """Per-domain block on an ObjectSpec: missing or empty means 'do nothing'."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object or null")
    if not value:
        return None
    return dict(value)


def _optional_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list or null")
    return list(value)


# ── v0.2 spec types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ObjectSpec:
    prim_path: str
    asset: dict[str, Any] | None = None
    material: dict[str, Any] | None = None
    pose: dict[str, Any] | None = None
    visibility: dict[str, Any] | None = None
    physics: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ObjectSpec":
        return cls(
            prim_path=_require_string(payload, "prim_path"),
            asset=_optional_block(payload.get("asset"), "asset"),
            material=_optional_block(payload.get("material"), "material"),
            pose=_optional_block(payload.get("pose"), "pose"),
            visibility=_optional_block(payload.get("visibility"), "visibility"),
            physics=_optional_block(payload.get("physics"), "physics"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"prim_path": self.prim_path}
        for k in ("asset", "material", "pose", "visibility", "physics"):
            v = getattr(self, k)
            if v:
                d[k] = dict(v)
        return d


@dataclass(frozen=True)
class LightSpec:
    prim_path: str
    intensity_scale: list[float] | None = None
    color_temperature: list[float] | None = None
    color: list[float] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LightSpec":
        return cls(
            prim_path=_require_string(payload, "prim_path"),
            intensity_scale=payload.get("intensity_scale"),
            color_temperature=payload.get("color_temperature"),
            color=payload.get("color"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"prim_path": self.prim_path}
        for k in ("intensity_scale", "color_temperature", "color"):
            v = getattr(self, k)
            if v is not None:
                d[k] = list(v)
        return d


@dataclass(frozen=True)
class CameraSpec:
    prim_path: str
    pose_jitter_m: list[float] | None = None
    yaw_pitch_jitter_deg: Any | None = None
    fov_deg: list[float] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CameraSpec":
        return cls(
            prim_path=_require_string(payload, "prim_path"),
            pose_jitter_m=payload.get("pose_jitter_m"),
            yaw_pitch_jitter_deg=payload.get("yaw_pitch_jitter_deg"),
            fov_deg=payload.get("fov_deg"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"prim_path": self.prim_path}
        for k in ("pose_jitter_m", "fov_deg"):
            v = getattr(self, k)
            if v is not None:
                d[k] = list(v)
        if self.yaw_pitch_jitter_deg is not None:
            if isinstance(self.yaw_pitch_jitter_deg, dict):
                d["yaw_pitch_jitter_deg"] = dict(self.yaw_pitch_jitter_deg)
            elif isinstance(self.yaw_pitch_jitter_deg, list):
                d["yaw_pitch_jitter_deg"] = list(self.yaw_pitch_jitter_deg)
            else:
                d["yaw_pitch_jitter_deg"] = self.yaw_pitch_jitter_deg
        return d


@dataclass(frozen=True)
class VisibilityPool:
    id: str
    prims: tuple[str, ...]
    keep_visible: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VisibilityPool":
        raw = payload.get("prims") or []
        if not isinstance(raw, list):
            raise ValueError("visibility_pool.prims must be a list")
        return cls(
            id=str(payload.get("id", "")),
            prims=tuple(str(p) for p in raw),
            keep_visible=int(payload.get("keep_visible", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "prims": list(self.prims), "keep_visible": self.keep_visible}


@dataclass(frozen=True)
class DomainRandomizationRequest:
    """v0.2 request — whitelist-based, no role/manifest concepts."""

    request_id: str
    variant_id: str
    base_scene_usd: str
    output_dir: str
    seed: int
    schema_version: str = SCHEMA_VERSION
    layer_policy: dict[str, Any] = field(default_factory=lambda: {"mode": "single"})
    objects: tuple[ObjectSpec, ...] = field(default_factory=tuple)
    lights: tuple[LightSpec, ...] = field(default_factory=tuple)
    cameras: tuple[CameraSpec, ...] = field(default_factory=tuple)
    visibility_pools: tuple[VisibilityPool, ...] = field(default_factory=tuple)
    # Optional fields kept for backward compat — ignored in v0.2
    scene_manifest: str | None = None
    base_scene_hash: str | None = None
    config_hash: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    realizers: dict[str, Any] = field(default_factory=dict)
    validation_policy: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainRandomizationRequest":
        seed = payload.get("seed")
        if not isinstance(seed, int):
            raise ValueError("seed must be an integer")

        raw_objects: list[dict[str, Any]] = [
            o for o in (payload.get("objects") or []) if isinstance(o, dict)
        ]
        raw_lights: list[dict[str, Any]] = [
            l for l in (payload.get("lights") or []) if isinstance(l, dict)
        ]
        raw_cameras: list[dict[str, Any]] = [
            c for c in (payload.get("cameras") or []) if isinstance(c, dict)
        ]
        raw_pools: list[dict[str, Any]] = [
            p for p in (payload.get("visibility_pools") or []) if isinstance(p, dict)
        ]

        return cls(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            request_id=_require_string(payload, "request_id"),
            variant_id=_require_string(payload, "variant_id"),
            base_scene_usd=_require_string(payload, "base_scene_usd"),
            scene_manifest=payload.get("scene_manifest"),
            output_dir=_require_string(payload, "output_dir"),
            seed=seed,
            base_scene_hash=payload.get("base_scene_hash"),
            config_hash=payload.get("config_hash"),
            layer_policy=_optional_dict(payload.get("layer_policy"), "layer_policy"),
            objects=tuple(ObjectSpec.from_dict(o) for o in raw_objects),
            lights=tuple(LightSpec.from_dict(l) for l in raw_lights),
            cameras=tuple(CameraSpec.from_dict(c) for c in raw_cameras),
            visibility_pools=tuple(VisibilityPool.from_dict(p) for p in raw_pools),
            scope=_optional_dict(payload.get("scope"), "scope"),
            realizers=_optional_dict(payload.get("realizers"), "realizers"),
            validation_policy=_optional_dict(payload.get("validation_policy"), "validation_policy"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "variant_id": self.variant_id,
            "base_scene_usd": self.base_scene_usd,
            "scene_manifest": self.scene_manifest,
            "output_dir": self.output_dir,
            "seed": self.seed,
            "base_scene_hash": self.base_scene_hash,
            "config_hash": self.config_hash,
            "layer_policy": dict(self.layer_policy),
            "objects": [o.to_dict() for o in self.objects],
            "lights": [l.to_dict() for l in self.lights],
            "cameras": [c.to_dict() for c in self.cameras],
            "visibility_pools": [p.to_dict() for p in self.visibility_pools],
            "scope": dict(self.scope),
            "realizers": dict(self.realizers),
            "validation_policy": dict(self.validation_policy),
        }


# ── Scan / result schemas (v0.2 — role fields removed) ─────────────────


@dataclass(frozen=True)
class DomainScanReport:
    base_scene_usd: str
    base_scene_hash: str
    schema_version: str = SCHEMA_VERSION
    stage_units_meters: float | None = None
    prims: list[dict[str, Any]] = field(default_factory=list)
    lights: list[dict[str, Any]] = field(default_factory=list)
    cameras: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainScanReport":
        return cls(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            base_scene_usd=_require_string(payload, "base_scene_usd"),
            base_scene_hash=_require_string(payload, "base_scene_hash"),
            stage_units_meters=payload.get("stage_units_meters"),
            prims=list(payload.get("prims") or []),
            lights=list(payload.get("lights") or []),
            cameras=list(payload.get("cameras") or []),
            warnings=list(payload.get("warnings") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "base_scene_usd": self.base_scene_usd,
            "base_scene_hash": self.base_scene_hash,
            "stage_units_meters": self.stage_units_meters,
            "prims": list(self.prims),
            "lights": list(self.lights),
            "cameras": list(self.cameras),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class LayerStackManifest:
    variant_id: str
    base_scene_usd: str
    sub_layers: list[str]
    schema_version: str = SCHEMA_VERSION
    composed_scene_usd: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "variant_id": self.variant_id,
            "base_scene_usd": self.base_scene_usd,
            "sub_layers": list(self.sub_layers),
            "composed_scene_usd": self.composed_scene_usd,
            "composition": {
                "order": "subLayers_first_is_strongest",
                "base_role": "weakest_sublayer",
                "recommended_strategy": "stub",
                "note": (
                    "The plugin emits only the recipe. Host code (Isaac runtime, "
                    "FORGE planner, or an offline tool) decides whether to compose "
                    "via a stub USDA, a session layer, or flattening. The "
                    "`domain_randomization_compose` command writes a stub on demand."
                ),
            },
        }


@dataclass(frozen=True)
class DomainRandomizationResult:
    variant_id: str
    request_id: str
    seed: int
    base_scene_usd: str
    schema_version: str = SCHEMA_VERSION
    randomization_layers: list[str] = field(default_factory=list)
    composed_scene_usd: str | None = None
    layer_stack_path: str | None = None
    requested_parameters: dict[str, Any] = field(default_factory=dict)
    sampled_parameters: dict[str, Any] = field(default_factory=dict)
    achieved_parameters: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    controllability_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "variant_id": self.variant_id,
            "request_id": self.request_id,
            "seed": self.seed,
            "base_scene_usd": self.base_scene_usd,
            "randomization_layers": list(self.randomization_layers),
            "composed_scene_usd": self.composed_scene_usd,
            "layer_stack_path": self.layer_stack_path,
            "requested_parameters": dict(self.requested_parameters),
            "sampled_parameters": dict(self.sampled_parameters),
            "achieved_parameters": dict(self.achieved_parameters),
            "validation": dict(self.validation),
            "controllability_score": self.controllability_score,
        }
