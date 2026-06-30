"""Asset-level USD composition edit helpers."""

from __future__ import annotations

from typing import Any


def references_edit(
    prim_path: str,
    references: Any,
    *,
    op: str = "set",
) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="asset",
        prim_path=str(prim_path),
        attribute="references",
        value={"op": str(op or "set"), "items": _items(references)},
        value_type="references",
    )


def payloads_edit(
    prim_path: str,
    payloads: Any,
    *,
    op: str = "set",
) -> Any:
    LayerEdit = _layer_edit_type()
    return LayerEdit(
        domain="asset",
        prim_path=str(prim_path),
        attribute="payloads",
        value={"op": str(op or "set"), "items": _items(payloads)},
        value_type="payloads",
    )


def copy_prim_reference_edit(
    source_prim_path: str,
    destination_prim_path: str,
    base_scene_usd: str,
) -> Any:
    return references_edit(
        destination_prim_path,
        [{"asset_path": str(base_scene_usd), "prim_path": str(source_prim_path)}],
    )


def relationship_targets_edit(
    prim_path: str,
    relationship_name: str,
    targets: list[str] | tuple[str, ...] | str,
) -> Any:
    LayerEdit = _layer_edit_type()
    if isinstance(targets, str):
        target_list = [targets]
    else:
        target_list = [str(t) for t in targets]
    return LayerEdit(
        domain="asset",
        prim_path=str(prim_path),
        attribute=str(relationship_name),
        value=target_list,
        value_type="relationship",
    )


def material_binding_edit(prim_path: str, material_path: str) -> Any:
    return relationship_targets_edit(prim_path, "material:binding", str(material_path))


def _items(value: Any) -> list[dict[str, str]]:
    raw = value if isinstance(value, list) else [value]
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            out.append({"asset_path": item})
        elif isinstance(item, dict):
            asset_path = item.get("asset_path") or item.get("asset") or item.get("path") or ""
            prim_path = item.get("prim_path") or item.get("target_prim") or ""
            out.append({
                "asset_path": str(asset_path),
                "prim_path": str(prim_path),
            })
    return out


def _layer_edit_type() -> Any:
    from ..sampler import LayerEdit

    return LayerEdit
