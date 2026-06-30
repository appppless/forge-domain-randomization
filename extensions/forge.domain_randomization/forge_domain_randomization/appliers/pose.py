"""Pose override edit helpers for sparse USDA randomization layers.

The override is written in the *same* xform shape the prim already uses so
that xformOpOrder survives untouched. TRS-layout prims get value overrides for
their existing translate / rotate / scale ops; matrix-layout prims get one
combined matrix override.
"""

from __future__ import annotations

import math
from typing import Any

from .. import xform_layout as _xform_layout


def translation_edits(
    prim_path: str,
    world_translation: list[float] | tuple[float, float, float],
    xform: dict[str, Any] | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Return ``(edits, warnings)``.

    `xform` is the scan's xform layout dict (see scanner). Behaviour:
      * ``None`` -> legacy v0.1 fallback: write ``xformOp:translate`` directly
        with the supplied translation. Used when the scan predates the layout
        extractor; appropriate when world == local (typical for fixtures /
        SceneCraft scenes anchored at world root).
      * ``layout == "trs"`` -> write only the existing translate op attribute.
      * ``layout == "matrix"`` -> rewrite the single transform op matrix with
        the same rotation / scale but the new translation row.
      * ``layout == "empty"`` -> author a new ``xformOp:translate`` and declare
        ``xformOpOrder`` so it actually takes effect.
      * ``layout == "unknown"`` -> refuse; emit a warning instead.
    """
    edits, warnings, _ = transform_edits(
        prim_path,
        xform,
        world_translation=world_translation,
        domain="placement",
    )
    return edits, warnings


def rotation_edits(
    prim_path: str,
    euler_delta_deg: list[float] | tuple[float, float, float],
    xform: dict[str, Any] | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    edits, warnings, _ = transform_edits(
        prim_path,
        xform,
        rotation_delta_deg=euler_delta_deg,
        domain="placement",
    )
    return edits, warnings


def scale_edits(
    prim_path: str,
    scale_factors: list[float] | tuple[float, float, float],
    xform: dict[str, Any] | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    edits, warnings, _ = transform_edits(
        prim_path,
        xform,
        scale_factors=scale_factors,
        domain="placement",
    )
    return edits, warnings


def transform_edits(
    prim_path: str,
    xform: dict[str, Any] | None,
    *,
    world_translation: list[float] | tuple[float, float, float] | None = None,
    rotation_delta_deg: list[float] | tuple[float, float, float] | None = None,
    scale_factors: list[float] | tuple[float, float, float] | None = None,
    domain: str = "placement",
) -> tuple[list[Any], list[dict[str, Any]], set[str]]:
    """Return ``(edits, warnings, applied_components)`` for a combined pose edit.

    `applied_components` contains any of ``translation`` / ``rotation`` /
    ``scale`` whose override was actually emitted. Matrix-layout prims need
    this combined path so rotation and scale do not emit competing
    xformOp:transform values.
    """
    if xform is None:
        return _legacy_transform_edits(
            prim_path,
            world_translation=world_translation,
            rotation_delta_deg=rotation_delta_deg,
            scale_factors=scale_factors,
            domain=domain,
        )
    return _emit_transform(
        prim_path,
        xform,
        world_translation=world_translation,
        rotation_delta_deg=rotation_delta_deg,
        scale_factors=scale_factors,
        domain=domain,
    )


def _legacy_edits(prim_path: str, world_translation, *, domain: str) -> list[Any]:
    LayerEdit = _layer_edit_type()
    return [LayerEdit(
        domain=domain,
        prim_path=str(prim_path),
        attribute="xformOp:translate",
        value=[float(world_translation[0]), float(world_translation[1]), float(world_translation[2])],
        value_type="double3",
    )]


def _legacy_transform_edits(
    prim_path: str,
    *,
    world_translation: list[float] | tuple[float, float, float] | None,
    rotation_delta_deg: list[float] | tuple[float, float, float] | None,
    scale_factors: list[float] | tuple[float, float, float] | None,
    domain: str,
) -> tuple[list[Any], list[dict[str, Any]], set[str]]:
    LayerEdit = _layer_edit_type()
    edits: list[Any] = []
    applied: set[str] = set()
    if world_translation is not None:
        edits.extend(_legacy_edits(prim_path, world_translation, domain=domain))
        applied.add("translation")
    if rotation_delta_deg is not None:
        edits.append(LayerEdit(
            domain=domain,
            prim_path=str(prim_path),
            attribute="xformOp:rotateXYZ",
            value=[float(rotation_delta_deg[0]), float(rotation_delta_deg[1]), float(rotation_delta_deg[2])],
            value_type="double3",
        ))
        applied.add("rotation")
    if scale_factors is not None:
        edits.append(LayerEdit(
            domain=domain,
            prim_path=str(prim_path),
            attribute="xformOp:scale",
            value=[float(scale_factors[0]), float(scale_factors[1]), float(scale_factors[2])],
            value_type="double3",
        ))
        applied.add("scale")
    return edits, [], applied


def _emit(
    prim_path: str,
    world_translation: list[float] | tuple[float, float, float],
    xform: dict[str, Any],
    *,
    domain: str,
) -> tuple[list[Any], list[dict[str, Any]]]:
    edits, warnings, _ = _emit_transform(
        prim_path,
        xform,
        world_translation=world_translation,
        rotation_delta_deg=None,
        scale_factors=None,
        domain=domain,
    )
    return edits, warnings


def _emit_transform(
    prim_path: str,
    xform: dict[str, Any],
    *,
    world_translation: list[float] | tuple[float, float, float] | None,
    rotation_delta_deg: list[float] | tuple[float, float, float] | None,
    scale_factors: list[float] | tuple[float, float, float] | None,
    domain: str,
) -> tuple[list[Any], list[dict[str, Any]], set[str]]:
    LayerEdit = _layer_edit_type()
    edits: list[Any] = []
    warnings: list[dict[str, Any]] = []
    applied: set[str] = set()

    layout = str(xform.get("layout") or "unknown")
    parent_world = list(xform.get("parent_world_transform_4x4") or _xform_layout.identity_4x4())
    local_matrix = list(xform.get("local_transform_4x4") or _xform_layout.identity_4x4())
    local_t = None
    if world_translation is not None:
        world_t = [float(world_translation[0]), float(world_translation[1]), float(world_translation[2])]
        local_t = _xform_layout.world_to_local_translation(world_t, parent_world)
        if local_t is None:
            warnings.append({
                "type": "parent_transform_singular",
                "severity": "warning",
                "prim_path": prim_path,
                "message": (
                    "parent world transform is singular; translation override "
                    "skipped to avoid producing an invalid xform."
                ),
            })
            if rotation_delta_deg is None and scale_factors is None:
                return edits, warnings, applied

    if layout == "trs":
        if world_translation is not None and local_t is not None:
            translate = xform.get("translate") or {}
            if translate.get("present") or xform.get("translate_op_name"):
                attr_name = str(translate.get("op_name") or xform.get("translate_op_name") or "xformOp:translate")
                precision = str(translate.get("precision") or xform.get("translate_op_precision") or "double")
                edits.append(LayerEdit(
                    domain=domain,
                    prim_path=prim_path,
                    attribute=attr_name,
                    value=list(local_t),
                    value_type=_vec3_type_for_precision(precision),
                ))
                applied.add("translation")
            else:
                warnings.append(_missing_op_warning(prim_path, "translate", "translation"))

        if rotation_delta_deg is not None:
            edit = _trs_rotation_edit(prim_path, xform, rotation_delta_deg, domain)
            if edit is None:
                warnings.append(_missing_op_warning(prim_path, "rotate", "rotation"))
            elif isinstance(edit, dict):
                warnings.append(edit)
            else:
                edits.append(edit)
                applied.add("rotation")

        if scale_factors is not None:
            edit = _trs_scale_edit(prim_path, xform, scale_factors, domain)
            if edit is None:
                warnings.append(_missing_op_warning(prim_path, "scale", "scale"))
            else:
                edits.append(edit)
                applied.add("scale")
        return edits, warnings, applied

    if layout == "matrix":
        attr_name = str(xform.get("translate_op_name") or "xformOp:transform")
        if local_t is not None and rotation_delta_deg is None and scale_factors is None:
            new_matrix = _xform_layout.replace_translation(local_matrix, local_t)
            edits.append(LayerEdit(
                domain=domain,
                prim_path=prim_path,
                attribute=attr_name,
                value=list(new_matrix),
                value_type="matrix4d",
            ))
            applied.add("translation")
            return edits, warnings, applied
        translation, euler, scale = _xform_layout.decompose_trs(local_matrix)
        if local_t is not None:
            translation = list(local_t)
            applied.add("translation")
        if rotation_delta_deg is not None:
            euler = [
                euler[0] + float(rotation_delta_deg[0]),
                euler[1] + float(rotation_delta_deg[1]),
                euler[2] + float(rotation_delta_deg[2]),
            ]
            applied.add("rotation")
        if scale_factors is not None:
            scale = [
                scale[0] * float(scale_factors[0]),
                scale[1] * float(scale_factors[1]),
                scale[2] * float(scale_factors[2]),
            ]
            applied.add("scale")
        new_matrix = _xform_layout.compose_trs([0.0, 0.0, 0.0], euler, scale)
        new_matrix = _xform_layout.replace_translation(new_matrix, translation)
        edits.append(LayerEdit(
            domain=domain,
            prim_path=prim_path,
            attribute=attr_name,
            value=list(new_matrix),
            value_type="matrix4d",
        ))
        return edits, warnings, applied

    if layout == "empty":
        op_order: list[str] = []
        if local_t is not None:
            edits.append(LayerEdit(
                domain=domain,
                prim_path=prim_path,
                attribute="xformOp:translate",
                value=list(local_t),
                value_type="double3",
            ))
            op_order.append("xformOp:translate")
            applied.add("translation")
        if rotation_delta_deg is not None:
            edits.append(LayerEdit(
                domain=domain,
                prim_path=prim_path,
                attribute="xformOp:rotateXYZ",
                value=[float(rotation_delta_deg[0]), float(rotation_delta_deg[1]), float(rotation_delta_deg[2])],
                value_type="double3",
            ))
            op_order.append("xformOp:rotateXYZ")
            applied.add("rotation")
        if scale_factors is not None:
            edits.append(LayerEdit(
                domain=domain,
                prim_path=prim_path,
                attribute="xformOp:scale",
                value=[float(scale_factors[0]), float(scale_factors[1]), float(scale_factors[2])],
                value_type="double3",
            ))
            op_order.append("xformOp:scale")
            applied.add("scale")
        if op_order:
            edits.append(LayerEdit(
                domain=domain,
                prim_path=prim_path,
                attribute="xformOpOrder",
                value=op_order,
                value_type="token[]",
            ))
        return edits, warnings, applied

    # unknown layout: refuse, keep base intact.
    warnings.append({
        "type": "unknown_xform_layout",
        "severity": "warning",
        "prim_path": prim_path,
        "message": (
            "prim's xformOpOrder has no translate or transform op; "
            "translation override skipped to preserve base authoring."
        ),
        "op_order": list(xform.get("op_order") or []),
    })
    return edits, warnings, applied


def _trs_rotation_edit(
    prim_path: str,
    xform: dict[str, Any],
    delta: list[float] | tuple[float, float, float],
    domain: str,
) -> Any | dict[str, Any] | None:
    rotate = xform.get("rotate") or {}
    if not rotate.get("present"):
        return None
    op_type = str(rotate.get("op_type") or "rotateXYZ")
    attr_name = str(rotate.get("op_name") or f"xformOp:{op_type}")
    precision = str(rotate.get("precision") or "double")
    base = rotate.get("base_value")
    LayerEdit = _layer_edit_type()

    if op_type == "orient":
        base_quat = _coerce_quat_xyzw(base, (0.0, 0.0, 0.0, 1.0))
        delta_quat = _euler_xyz_delta_to_quat_xyzw(delta)
        new_quat = _quat_normalize(_quat_multiply_xyzw(base_quat, delta_quat))
        return LayerEdit(
            domain=domain,
            prim_path=prim_path,
            attribute=attr_name,
            value=list(new_quat),
            value_type=_quat_type_for_precision(precision),
        )

    if op_type in {"rotateX", "rotateY", "rotateZ"}:
        axis = {"rotateX": 0, "rotateY": 1, "rotateZ": 2}[op_type]
        base_value = _coerce_scalar(base, 0.0)
        return LayerEdit(
            domain=domain,
            prim_path=prim_path,
            attribute=attr_name,
            value=base_value + float(delta[axis]),
            value_type=_scalar_type_for_precision(precision),
        )

    base_vec = _coerce_vec3(base, (0.0, 0.0, 0.0))
    return LayerEdit(
        domain=domain,
        prim_path=prim_path,
        attribute=attr_name,
        value=[
            base_vec[0] + float(delta[0]),
            base_vec[1] + float(delta[1]),
            base_vec[2] + float(delta[2]),
        ],
        value_type=_vec3_type_for_precision(precision),
    )


def _trs_scale_edit(
    prim_path: str,
    xform: dict[str, Any],
    factors: list[float] | tuple[float, float, float],
    domain: str,
) -> Any | None:
    scale = xform.get("scale") or {}
    if not scale.get("present"):
        return None
    attr_name = str(scale.get("op_name") or "xformOp:scale")
    precision = str(scale.get("precision") or "double")
    base = _coerce_vec3(scale.get("base_value"), (1.0, 1.0, 1.0))
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain=domain,
        prim_path=prim_path,
        attribute=attr_name,
        value=[
            base[0] * float(factors[0]),
            base[1] * float(factors[1]),
            base[2] * float(factors[2]),
        ],
        value_type=_vec3_type_for_precision(precision),
    )


def _missing_op_warning(prim_path: str, op_name: str, component: str) -> dict[str, Any]:
    return {
        "type": f"missing_{op_name}_op",
        "severity": "warning",
        "prim_path": prim_path,
        "message": (
            f"prim has no authored {op_name} op; {component} override skipped "
            "to preserve base xformOpOrder."
        ),
    }


def _vec3_type_for_precision(precision: str | None) -> str:
    p = (precision or "double").lower()
    if p == "float":
        return "float3"
    if p == "half":
        return "half3"
    return "double3"


def _scalar_type_for_precision(precision: str | None) -> str:
    p = (precision or "double").lower()
    if p == "float":
        return "float"
    if p == "half":
        return "half"
    return "double"


def _quat_type_for_precision(precision: str | None) -> str:
    p = (precision or "double").lower()
    if p == "float":
        return "quatf"
    if p == "half":
        return "quath"
    return "quatd"


def _coerce_vec3(value: Any, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return float(value[0]), float(value[1]), float(value[2])
    return fallback


def _coerce_quat_xyzw(
    value: Any,
    fallback: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return float(value[0]), float(value[1]), float(value[2]), float(value[3])
    return fallback


def _coerce_scalar(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


def _axis_angle_quat_xyzw(axis: str, angle_deg: float) -> tuple[float, float, float, float]:
    half = math.radians(float(angle_deg)) * 0.5
    s = math.sin(half)
    c = math.cos(half)
    if axis == "x":
        return s, 0.0, 0.0, c
    if axis == "y":
        return 0.0, s, 0.0, c
    return 0.0, 0.0, s, c


def _euler_xyz_delta_to_quat_xyzw(
    delta: list[float] | tuple[float, float, float],
) -> tuple[float, float, float, float]:
    qx = _axis_angle_quat_xyzw("x", float(delta[0]))
    qy = _axis_angle_quat_xyzw("y", float(delta[1]))
    qz = _axis_angle_quat_xyzw("z", float(delta[2]))
    return _quat_normalize(_quat_multiply_xyzw(_quat_multiply_xyzw(qx, qy), qz))


def _quat_multiply_xyzw(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _quat_normalize(
    q: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x, y, z, w = q
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 0.0:
        return 0.0, 0.0, 0.0, 1.0
    return x / norm, y / norm, z / norm, w / norm


def _layer_edit_type() -> Any:
    from ..sampler import LayerEdit
    return LayerEdit


# Back-compat: tests / external callers may still import translation_edit.
# Behaves as a single-edit shortcut that assumes layout="trs" with default
# attr name / precision; emits a list-compatible single LayerEdit.
def translation_edit(prim_path: str, translation, attribute: str = "xformOp:translate",
                     precision: str = "double") -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="placement",
        prim_path=str(prim_path),
        attribute=attribute,
        value=list(translation),
        value_type=_vec3_type_for_precision(precision),
    )
