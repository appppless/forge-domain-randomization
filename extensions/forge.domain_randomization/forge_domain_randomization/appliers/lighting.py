"""Lighting override edit helpers for sparse USDA randomization layers."""

from __future__ import annotations

from typing import Any


def intensity_edit(light_path: str, intensity: float) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="simulator",
        prim_path=str(light_path),
        attribute="inputs:intensity",
        value=float(intensity),
        value_type="float",
    )


def color_edit(light_path: str, color: list[float] | tuple[float, float, float]) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="simulator",
        prim_path=str(light_path),
        attribute="inputs:color",
        value=list(color),
        value_type="color3f",
    )


def _layer_edit_type() -> Any:
    from ..sampler import LayerEdit

    return LayerEdit
