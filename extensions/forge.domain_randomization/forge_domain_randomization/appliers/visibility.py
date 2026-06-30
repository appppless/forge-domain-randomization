"""Visibility override edit helpers for sparse USDA randomization layers."""

from __future__ import annotations

from typing import Any


def visibility_edit(prim_path: str, visible: bool) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="placement",
        prim_path=str(prim_path),
        attribute="visibility",
        value="inherited" if visible else "invisible",
        value_type="token",
    )


def _layer_edit_type() -> Any:
    from ..sampler import LayerEdit

    return LayerEdit
