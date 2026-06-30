"""Camera override edit helpers for sparse USDA randomization layers.

Pose edits are written in the prim's existing xform shape so that the base
camera's xformOpOrder is preserved. See ``pose.transform_edits`` for the
layout contract.
"""

from __future__ import annotations

from typing import Any

from . import pose as _pose


def translation_edits(
    camera_path: str,
    world_translation: list[float] | tuple[float, float, float],
    xform: dict[str, Any] | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    edits, warnings, _ = transform_edits(camera_path, xform, world_translation=world_translation)
    return edits, warnings


def rotation_edits(
    camera_path: str,
    rotation_delta_deg: list[float] | tuple[float, float, float],
    xform: dict[str, Any] | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    edits, warnings, _ = transform_edits(camera_path, xform, rotation_delta_deg=rotation_delta_deg)
    return edits, warnings


def transform_edits(
    camera_path: str,
    xform: dict[str, Any] | None,
    *,
    world_translation: list[float] | tuple[float, float, float] | None = None,
    rotation_delta_deg: list[float] | tuple[float, float, float] | None = None,
) -> tuple[list[Any], list[dict[str, Any]], set[str]]:
    return _pose.transform_edits(
        camera_path,
        xform,
        world_translation=world_translation,
        rotation_delta_deg=rotation_delta_deg,
        domain="simulator",
    )


def focal_length_edit(camera_path: str, focal_length: float) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="simulator",
        prim_path=str(camera_path),
        attribute="focalLength",
        value=float(focal_length),
        value_type="float",
    )


def _layer_edit_type() -> Any:
    from ..sampler import LayerEdit

    return LayerEdit


# Back-compat single-edit helper (assumes trs / double precision).
def translation_edit(camera_path: str, translation: list[float] | tuple[float, float, float]) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="simulator",
        prim_path=str(camera_path),
        attribute="xformOp:translate",
        value=list(translation),
        value_type="double3",
    )
