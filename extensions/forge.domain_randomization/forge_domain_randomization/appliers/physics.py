"""Physics override edit helpers for sparse USDA randomization layers."""

from __future__ import annotations

from typing import Any


def mass_edit(prim_path: str, mass: float) -> Any:
    return _physics_edit(prim_path, "physics:mass", mass)


def friction_edit(prim_path: str, friction: float) -> Any:
    return _physics_edit(prim_path, "physics:dynamicFriction", friction)


def restitution_edit(prim_path: str, restitution: float) -> Any:
    return _physics_edit(prim_path, "physics:restitution", restitution)


def _physics_edit(prim_path: str, attribute: str, value: float) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="simulator",
        prim_path=str(prim_path),
        attribute=attribute,
        value=float(value),
        value_type="float",
    )


def _layer_edit_type() -> Any:
    from ..sampler import LayerEdit

    return LayerEdit
