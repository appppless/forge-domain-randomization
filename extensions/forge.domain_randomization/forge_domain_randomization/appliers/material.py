"""Material override edit helpers.

The current DR MVP writes sparse USDA layers instead of mutating the live stage.
These helpers define the low-level USD attributes used by material factors while
keeping pxr imports out of ordinary Python tests.
"""

from __future__ import annotations

from typing import Any


def diffuse_color_edit(
    material_path: str,
    color: list[float] | tuple[float, float, float],
    attribute: str = "inputs:diffuse_color_constant",
) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="asset",
        prim_path=str(material_path),
        attribute=str(attribute),
        value=list(color),
        value_type="color3f",
    )


def roughness_edit(
    material_path: str,
    roughness: float,
    attribute: str = "inputs:reflection_roughness_constant",
) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="asset",
        prim_path=str(material_path),
        attribute=str(attribute),
        value=float(roughness),
        value_type="float",
    )


def texture_asset_edit(
    material_path: str,
    texture_path: str,
    attribute: str = "inputs:diffuse_texture",
) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="asset",
        prim_path=str(material_path),
        attribute=str(attribute),
        value=str(texture_path),
        value_type="asset",
    )


def _layer_edit_type() -> Any:
    from ..sampler import LayerEdit

    return LayerEdit
