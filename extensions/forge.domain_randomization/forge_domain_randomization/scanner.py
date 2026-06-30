"""Isaac / USD stage scanner for v0.2 domain randomization.

The scanner treats each whitelisted prim as a *semantic unit*: it resolves the
prim by direct path lookup (instead of full-stage traversal) and then walks the
prim's subtree to aggregate the attributes the sampler needs.

This is what lets DR work on referenced assets (e.g. BEHAVIOR-1K / Omniverse
content packs) where the rigid body, mass and material bindings live on
descendants such as <root>/base_link or <root>/base_link/visuals, not on the
root prim that is referenced from the kitchen scene.

All Omniverse imports are kept inside functions. Importing this module from a
normal Python process must not require Isaac Sim.
"""

from __future__ import annotations

import math
from typing import Any

from .registry import build_prim_scan_entry, collect_whitelist_prim_paths
from .schemas import DomainRandomizationRequest, DomainScanReport
from . import xform_layout as _xform_layout


LIGHT_TYPE_NAMES = frozenset({
    "DomeLight", "SphereLight", "RectLight", "DiskLight",
    "DistantLight", "CylinderLight",
})


class IsaacRuntimeUnavailable(RuntimeError):
    """Raised when scanner code is called outside an Isaac / Omniverse runtime."""


def open_stage_and_scan(
    request: DomainRandomizationRequest,
    base_scene_hash: str,
) -> DomainScanReport:
    try:
        import omni.usd
    except Exception as exc:
        raise IsaacRuntimeUnavailable("omni.usd is required to open a stage") from exc

    context = omni.usd.get_context()
    if not context.open_stage(request.base_scene_usd):
        raise RuntimeError(f"failed to open USD stage: {request.base_scene_usd}")
    stage = context.get_stage()
    if stage is None:
        raise RuntimeError("omni.usd returned no active stage")
    return scan_stage(stage, request, base_scene_hash)


def scan_stage(
    stage: Any,
    request: DomainRandomizationRequest,
    base_scene_hash: str,
) -> DomainScanReport:
    try:
        from pxr import Gf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade
    except Exception as exc:
        raise IsaacRuntimeUnavailable("pxr modules are required to scan a stage") from exc

    whitelist = sorted(collect_whitelist_prim_paths(request))
    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_],
        useExtentsHint=True,
    )

    prims: list[dict[str, Any]] = []
    scanned_lights: list[dict[str, Any]] = []
    scanned_cameras: list[dict[str, Any]] = []
    warnings: list[str] = []

    for whitelist_path in whitelist:
        try:
            prim = stage.GetPrimAtPath(whitelist_path)
        except Exception as exc:
            warnings.append(f"resolve failed for {whitelist_path}: {exc}")
            continue
        if not prim or not prim.IsValid():
            warnings.append(f"whitelist prim not found on stage: {whitelist_path}")
            continue
        if not prim.IsActive():
            warnings.append(f"whitelist prim is inactive: {whitelist_path}")
            continue

        try:
            kind = _classify_prim(prim, UsdGeom, UsdLux)
        except Exception as exc:
            warnings.append(f"classify failed for {whitelist_path}: {exc}")
            continue

        try:
            if kind == "camera":
                scanned_cameras.append(_scan_camera(prim, UsdGeom, Gf))
            elif kind == "light":
                scanned_lights.append(_scan_light(prim))
            else:
                prims.append(_scan_subtree(
                    whitelist_path=whitelist_path,
                    prim=prim,
                    bbox_cache=bbox_cache,
                    Gf=Gf, Usd=Usd, UsdGeom=UsdGeom,
                    UsdPhysics=UsdPhysics, UsdShade=UsdShade,
                ))
        except Exception as exc:
            warnings.append(f"scan failed for {whitelist_path}: {exc}")

    return DomainScanReport(
        base_scene_usd=request.base_scene_usd,
        base_scene_hash=base_scene_hash,
        stage_units_meters=_stage_units(stage),
        prims=prims,
        lights=scanned_lights,
        cameras=scanned_cameras,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# classification                                                              #
# --------------------------------------------------------------------------- #

def _classify_prim(prim: Any, UsdGeom: Any, UsdLux: Any) -> str:
    type_name = str(prim.GetTypeName())
    if type_name == "Camera":
        return "camera"
    if type_name in LIGHT_TYPE_NAMES:
        return "light"
    try:
        if hasattr(UsdLux, "Light") and prim.IsA(UsdLux.Light):
            return "light"
    except Exception:
        pass
    try:
        if hasattr(UsdLux, "LightAPI") and prim.HasAPI(UsdLux.LightAPI):
            return "light"
    except Exception:
        pass
    try:
        if prim.IsA(UsdGeom.Camera):
            return "camera"
    except Exception:
        pass
    return "generic"


# --------------------------------------------------------------------------- #
# generic prim subtree scan                                                   #
# --------------------------------------------------------------------------- #

def _scan_subtree(
    *,
    whitelist_path: str,
    prim: Any,
    bbox_cache: Any,
    Gf: Any, Usd: Any, UsdGeom: Any,
    UsdPhysics: Any, UsdShade: Any,
) -> dict[str, Any]:
    descendants = _iter_descendants(prim, Usd, UsdGeom)
    transform = _safe_call(
        _extract_transform, prim, UsdGeom, Gf,
        default={
            "translation": [0.0, 0.0, 0.0],
            "rotation_euler_deg": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        },
    )
    xform_layout = _safe_call(
        _xform_layout.extract_layout, prim, UsdGeom,
        default=_xform_layout.empty_layout(),
    )
    bounds = _safe_call(_extract_bounds, prim, bbox_cache, default=None)
    physics = _safe_call(
        _extract_physics, descendants, UsdPhysics, UsdShade,
        default=_empty_physics(),
    )
    material_bindings = _safe_call(
        _extract_material_bindings, descendants, UsdShade,
        default=[],
    )

    return build_prim_scan_entry(
        prim_path=whitelist_path,
        type_name=str(prim.GetTypeName()) or "Xform",
        transform=transform,
        xform=xform_layout,
        bounds=bounds,
        physics=physics,
        material_bindings=material_bindings,
        source_confidence="whitelist",
    )


def _empty_xform_layout() -> dict[str, Any]:
    return _xform_layout.empty_layout()


def _identity_4x4() -> list[float]:
    return _xform_layout.identity_4x4()


def _empty_physics() -> dict[str, Any]:
    return {
        "has_rigid_body": False,
        "rigid_body_prim_path": None,
        "has_collision": False,
        "collision_prim_paths": [],
        "mass": None,
        "mass_prim_path": None,
        "friction": None,
        "restitution": None,
        "physics_material_prim_path": None,
    }


def _safe_call(fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return default


# --------------------------------------------------------------------------- #
# subtree traversal                                                           #
# --------------------------------------------------------------------------- #

def _iter_descendants(root: Any, Usd: Any, UsdGeom: Any) -> list[Any]:
    """Return root and every active descendant.

    Skips instance proxies (they cannot be edited in override layers anyway)
    and non-default purposes (proxy / render / guide).
    """
    try:
        default_purpose = UsdGeom.Tokens.default_
    except Exception:
        default_purpose = None

    try:
        iterator = iter(Usd.PrimRange(root))
    except Exception:
        return _manual_descendants(root)

    out: list[Any] = []
    for prim in iterator:
        if not prim or not prim.IsValid() or not prim.IsActive():
            continue
        try:
            if prim.IsInstanceProxy():
                continue
        except Exception:
            pass
        if default_purpose is not None:
            try:
                if prim.IsA(UsdGeom.Imageable):
                    purpose = UsdGeom.Imageable(prim).GetPurposeAttr().Get()
                    if purpose is not None and purpose != default_purpose:
                        continue
            except Exception:
                pass
        out.append(prim)
    return out


def _manual_descendants(root: Any) -> list[Any]:
    out: list[Any] = []

    def _walk(p: Any) -> None:
        if not p or not p.IsValid() or not p.IsActive():
            return
        out.append(p)
        try:
            children = list(p.GetChildren())
        except Exception:
            children = []
        for child in children:
            _walk(child)

    _walk(root)
    return out


# --------------------------------------------------------------------------- #
# transform / bounds                                                          #
# --------------------------------------------------------------------------- #

def _extract_transform(prim: Any, UsdGeom: Any, Gf: Any) -> dict[str, list[float]]:
    default = {
        "translation": [0.0, 0.0, 0.0],
        "rotation_euler_deg": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }
    try:
        xformable = UsdGeom.Xformable(prim)
    except Exception:
        xformable = None
    if not xformable:
        return default
    try:
        matrix = xformable.ComputeLocalToWorldTransform(0)
    except Exception:
        matrix = None
    if matrix is None:
        return default

    translation = [0.0, 0.0, 0.0]
    rotation_euler_deg = [0.0, 0.0, 0.0]
    scale = [1.0, 1.0, 1.0]

    try:
        t = matrix.ExtractTranslation()
        translation = [float(t[0]), float(t[1]), float(t[2])]
    except Exception:
        pass

    try:
        xform = Gf.Transform(matrix)
        s = xform.GetScale()
        scale = [float(s[0]), float(s[1]), float(s[2])]
        rot = xform.GetRotation()
        quat = rot.GetQuat() if hasattr(rot, "GetQuat") else rot.GetQuaternion()
        rotation_euler_deg = _quat_to_euler_xyz_deg(quat)
    except Exception:
        pass

    return {
        "translation": translation,
        "rotation_euler_deg": rotation_euler_deg,
        "scale": scale,
    }


def _quat_to_euler_xyz_deg(quat: Any) -> list[float]:
    """Convert a quaternion to intrinsic XYZ Euler angles (degrees).

    Tolerates pxr quaternion types whose real / imaginary components are
    exposed via GetReal/GetImaginary.
    """
    try:
        w = float(quat.GetReal())
        imag = quat.GetImaginary()
        x = float(imag[0]); y = float(imag[1]); z = float(imag[2])
    except Exception:
        try:
            w = float(quat.real)
            x = float(quat.imaginary[0]); y = float(quat.imaginary[1]); z = float(quat.imaginary[2])
        except Exception:
            return [0.0, 0.0, 0.0]

    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0.0:
        return [0.0, 0.0, 0.0]
    w /= norm; x /= norm; y /= norm; z /= norm

    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    pitch = math.asin(sinp)

    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return [math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]


def _extract_bounds(prim: Any, bbox_cache: Any) -> dict[str, list[float]] | None:
    try:
        bbox = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        lower = bbox.GetMin()
        upper = bbox.GetMax()
        if not math.isfinite(float(lower[0])) or not math.isfinite(float(upper[0])):
            return None
        return {
            "aabb_min": [float(lower[0]), float(lower[1]), float(lower[2])],
            "aabb_max": [float(upper[0]), float(upper[1]), float(upper[2])],
        }
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# physics                                                                     #
# --------------------------------------------------------------------------- #

def _extract_physics(
    descendants: list[Any],
    UsdPhysics: Any,
    UsdShade: Any,
) -> dict[str, Any]:
    """Walk descendants and aggregate physics APIs onto a single record.

    Policy (strategy A): record the *first* descendant carrying RigidBodyAPI
    as the rigid body carrier. Collect every descendant carrying CollisionAPI.
    Mass is read from the first descendant with MassAPI (root preferred).
    Friction / restitution come from the physics MaterialAPI bound on the
    rigid body carrier (or any descendant with a physics binding).
    """
    out = _empty_physics()

    rigid_body_carrier: Any = None
    mass_carrier: Any = None
    collision_paths: list[str] = []

    for prim in descendants:
        try:
            if rigid_body_carrier is None and _has_api(prim, UsdPhysics, "RigidBodyAPI"):
                rigid_body_carrier = prim
        except Exception:
            pass
        try:
            if _has_api(prim, UsdPhysics, "CollisionAPI"):
                collision_paths.append(str(prim.GetPath()))
        except Exception:
            pass
        try:
            if mass_carrier is None and _has_api(prim, UsdPhysics, "MassAPI"):
                mass_carrier = prim
        except Exception:
            pass

    if rigid_body_carrier is not None:
        out["has_rigid_body"] = True
        out["rigid_body_prim_path"] = str(rigid_body_carrier.GetPath())

    if collision_paths:
        out["has_collision"] = True
        out["collision_prim_paths"] = collision_paths

    if mass_carrier is not None:
        try:
            mass_attr = UsdPhysics.MassAPI(mass_carrier).GetMassAttr()
            value = mass_attr.Get() if mass_attr else None
            if value is not None:
                out["mass"] = float(value)
                out["mass_prim_path"] = str(mass_carrier.GetPath())
        except Exception:
            pass

    # Physics material: prefer rigid body carrier binding, otherwise scan
    # descendants for any prim with a "physics" purpose material binding.
    physics_material_prim = None
    candidates = []
    if rigid_body_carrier is not None:
        candidates.append(rigid_body_carrier)
    candidates.extend(descendants)
    seen_paths: set[str] = set()
    for prim in candidates:
        try:
            path = str(prim.GetPath())
        except Exception:
            continue
        if path in seen_paths:
            continue
        seen_paths.add(path)
        try:
            binding_api = UsdShade.MaterialBindingAPI(prim)
        except Exception:
            continue
        material = _compute_bound_material(binding_api, "physics")
        if material:
            physics_material_prim = material.GetPrim()
            break

    if physics_material_prim is not None:
        out["physics_material_prim_path"] = str(physics_material_prim.GetPath())
        try:
            phys_api = UsdPhysics.MaterialAPI(physics_material_prim)
            friction_attr = getattr(phys_api, "GetDynamicFrictionAttr", lambda: None)()
            if friction_attr:
                fv = friction_attr.Get()
                if fv is not None:
                    out["friction"] = float(fv)
            restitution_attr = getattr(phys_api, "GetRestitutionAttr", lambda: None)()
            if restitution_attr:
                rv = restitution_attr.Get()
                if rv is not None:
                    out["restitution"] = float(rv)
        except Exception:
            pass

    return out


def _has_api(prim: Any, UsdPhysics: Any, api_name: str) -> bool:
    api_cls = getattr(UsdPhysics, api_name, None)
    if api_cls is None:
        return False
    try:
        return bool(prim.HasAPI(api_cls))
    except Exception:
        try:
            return bool(api_cls(prim))
        except Exception:
            return False


def _compute_bound_material(binding_api: Any, purpose: str | None) -> Any:
    """Return the bound UsdShade.Material or None.

    Tolerates the two pxr signatures (positional purpose vs token).
    """
    if binding_api is None:
        return None
    try:
        if purpose:
            result = binding_api.ComputeBoundMaterial(purpose)
        else:
            result = binding_api.ComputeBoundMaterial()
    except Exception:
        try:
            result = binding_api.ComputeBoundMaterial()
        except Exception:
            return None
    if isinstance(result, tuple):
        material = result[0] if result else None
    else:
        material = result
    if material is None:
        return None
    try:
        if not material.GetPrim().IsValid():
            return None
    except Exception:
        return None
    return material


# --------------------------------------------------------------------------- #
# material bindings                                                           #
# --------------------------------------------------------------------------- #

def _extract_material_bindings(
    descendants: list[Any],
    UsdShade: Any,
) -> list[dict[str, Any]]:
    """For every descendant carrying MaterialBindingAPI, record the bound
    visual material along with shader-level base_color / roughness reads.
    """
    bindings: list[dict[str, Any]] = []
    seen_material_paths: set[str] = set()

    for prim in descendants:
        try:
            if not _has_material_binding(prim, UsdShade):
                continue
        except Exception:
            continue
        try:
            binding_api = UsdShade.MaterialBindingAPI(prim)
        except Exception:
            continue
        # default (allPurpose) binding == visual material
        material = _compute_bound_material(binding_api, None)
        if material is None:
            continue
        material_prim = material.GetPrim()
        target_prim = _resolve_shader_prim(material_prim, UsdShade) or material_prim
        target_path = str(target_prim.GetPath())
        binding_prim_path = str(prim.GetPath())
        key = f"{binding_prim_path}::{target_path}"
        if key in seen_material_paths:
            continue
        seen_material_paths.add(key)
        shader_inputs = _enumerate_shader_inputs(target_prim, UsdShade)
        shader_info = _shader_info(target_prim)
        material_model = _classify_material_model(target_prim, shader_info, shader_inputs)
        slots = _select_material_slots(material_model, shader_inputs)
        bindings.append({
            "binding_prim_path": binding_prim_path,
            "material_path": target_path,
            "material_model": material_model,
            "shader_id": shader_info.get("id"),
            "shader_source_asset": shader_info.get("source_asset"),
            "shader_inputs": sorted(shader_inputs),
            "base_color": _coerce_vec3_value(slots.get("base_color")),
            "base_color_attr": slots.get("base_color_attr"),
            "diffuse_tint": _coerce_vec3_value(slots.get("diffuse_tint")),
            "diffuse_tint_attr": slots.get("diffuse_tint_attr"),
            "roughness": _coerce_scalar_value(slots.get("roughness")),
            "roughness_attr": slots.get("roughness_attr"),
            "diffuse_texture": _coerce_asset_value(slots.get("diffuse_texture")),
            "diffuse_texture_attr": slots.get("diffuse_texture_attr"),
        })
    return bindings


def _has_material_binding(prim: Any, UsdShade: Any) -> bool:
    api_cls = getattr(UsdShade, "MaterialBindingAPI", None)
    if api_cls is None:
        return False
    try:
        if prim.HasAPI(api_cls):
            return True
    except Exception:
        pass
    # Fallback: explicit relationship presence.
    try:
        rel = prim.GetRelationship("material:binding")
        if rel and rel.GetTargets():
            return True
    except Exception:
        pass
    return False


def _resolve_shader_prim(material_prim: Any, UsdShade: Any) -> Any:
    try:
        material = UsdShade.Material(material_prim)
        result = material.ComputeSurfaceSource()
        if isinstance(result, tuple) and result:
            shader = result[0]
        else:
            shader = result
        if shader:
            try:
                prim = shader.GetPrim()
                if prim and prim.IsValid():
                    return prim
            except Exception:
                pass
    except Exception:
        pass

    try:
        for child in material_prim.GetChildren():
            if str(child.GetTypeName()) == "Shader":
                return child
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------- #
# lights / cameras                                                            #
# --------------------------------------------------------------------------- #

def _scan_light(prim: Any) -> dict[str, Any]:
    intensity = None
    color = None
    try:
        intensity_attr = prim.GetAttribute("inputs:intensity")
        if intensity_attr:
            v = intensity_attr.Get()
            intensity = float(v) if v is not None else None
    except Exception:
        intensity = None
    try:
        color_attr = prim.GetAttribute("inputs:color")
        if color_attr:
            v = color_attr.Get()
            if v is not None:
                color = [float(v[0]), float(v[1]), float(v[2])]
    except Exception:
        color = None
    return {
        "prim_path": str(prim.GetPath()),
        "name": prim.GetName(),
        "type_name": str(prim.GetTypeName()),
        "intensity": intensity,
        "color": color,
    }


def _scan_camera(prim: Any, UsdGeom: Any, Gf: Any) -> dict[str, Any]:
    transform = _safe_call(
        _extract_transform, prim, UsdGeom, Gf,
        default={
            "translation": [0.0, 0.0, 0.0],
            "rotation_euler_deg": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        },
    )
    xform = _safe_call(
        _xform_layout.extract_layout, prim, UsdGeom,
        default=_xform_layout.empty_layout(),
    )
    focal_length = None
    horizontal_aperture = None
    try:
        camera = UsdGeom.Camera(prim)
        fa = camera.GetFocalLengthAttr().Get()
        focal_length = float(fa) if fa is not None else None
        ha = camera.GetHorizontalApertureAttr().Get()
        horizontal_aperture = float(ha) if ha is not None else None
    except Exception:
        pass
    return {
        "prim_path": str(prim.GetPath()),
        "name": prim.GetName(),
        "type_name": str(prim.GetTypeName()),
        "world_transform": transform,
        "xform": xform,
        "focal_length": focal_length,
        "horizontal_aperture": horizontal_aperture,
    }


# --------------------------------------------------------------------------- #
# attribute reads (shader)                                                    #
# --------------------------------------------------------------------------- #

def _enumerate_shader_inputs(shader_prim: Any, UsdShade: Any) -> dict[str, Any]:
    """Return authored shader inputs keyed by full attr name.

    Uses UsdShade.Shader.GetInputs when available. Falls back to raw prim
    attributes in tests or unusual pxr bindings. Values are raw USD values;
    semantic coercion happens after material-model slot selection.
    """
    out: dict[str, Any] = {}
    try:
        shader = UsdShade.Shader(shader_prim)
        for shader_input in shader.GetInputs():
            attr_name = _shader_input_attr_name(shader_input)
            if not attr_name:
                continue
            value = _shader_input_value(shader_input)
            out[attr_name] = value
    except Exception:
        pass

    if out:
        return out

    try:
        names = list(getattr(shader_prim, "_attrs", {}).keys())
    except Exception:
        names = []
    for name in names:
        if not str(name).startswith("inputs:"):
            continue
        try:
            attr = shader_prim.GetAttribute(name)
            value = attr.Get() if attr else None
            if value is not None:
                out[str(name)] = value
        except Exception:
            continue
    return out


def _shader_input_attr_name(shader_input: Any) -> str | None:
    try:
        attr = shader_input.GetAttr()
        if attr:
            return str(attr.GetName())
    except Exception:
        pass
    try:
        full_name = shader_input.GetFullName()
        if full_name:
            return str(full_name)
    except Exception:
        pass
    try:
        base_name = shader_input.GetBaseName()
        if base_name:
            return f"inputs:{base_name}"
    except Exception:
        pass
    return None


def _shader_input_value(shader_input: Any) -> Any:
    try:
        attr = shader_input.GetAttr()
        value = attr.Get() if attr else None
        if value is not None:
            return value
    except Exception:
        pass
    try:
        return shader_input.Get()
    except Exception:
        return None


def _shader_info(shader_prim: Any) -> dict[str, str | None]:
    shader_id = _read_string_attr(shader_prim, ("info:id", "info:mdl:sourceAsset:subIdentifier"))
    source_asset = _read_asset_attr_with_name(shader_prim, (
        "info:mdl:sourceAsset",
        "info:sourceAsset",
    ))[1]
    implementation_source = _read_string_attr(shader_prim, ("info:implementationSource",))
    return {
        "id": shader_id,
        "source_asset": source_asset,
        "implementation_source": implementation_source,
    }


def _classify_material_model(
    shader_prim: Any,
    shader_info: dict[str, str | None],
    shader_inputs: dict[str, Any],
) -> str:
    shader_identity = " ".join(
        str(x or "")
        for x in (
            shader_info.get("id"),
            shader_info.get("source_asset"),
            shader_info.get("implementation_source"),
            str(shader_prim.GetPath()) if hasattr(shader_prim, "GetPath") else "",
        )
    ).lower()
    input_names = " ".join(shader_inputs).lower()
    if "simpbr" in shader_identity:
        return "sim_pbr"
    if "omnipbr" in shader_identity:
        return "omni_pbr"
    if "usdpreviewsurface" in shader_identity:
        return "usd_preview_surface"
    if "diffuse_color_constant" in input_names or "reflection_roughness_constant" in input_names:
        return "omni_pbr"
    if "diffusecolor" in input_names or "inputs:roughness" in input_names:
        return "usd_preview_surface"
    return "unknown"


def _select_material_slots(material_model: str, shader_inputs: dict[str, Any]) -> dict[str, Any]:
    if material_model == "usd_preview_surface":
        base_color_names = ("inputs:diffuseColor",)
        tint_names = ()
        roughness_names = ("inputs:roughness",)
        texture_names = ("inputs:diffuseTexture", "inputs:file")
    elif material_model in {"omni_pbr", "sim_pbr"}:
        base_color_names = ("inputs:diffuse_color_constant",)
        tint_names = ("inputs:diffuse_tint",)
        roughness_names = ("inputs:reflection_roughness_constant",)
        texture_names = ("inputs:diffuse_texture",)
    else:
        base_color_names = (
            "inputs:diffuseColor",
            "inputs:diffuse_color",
            "inputs:diffuse_color_constant",
            "inputs:base_color",
            "inputs:baseColor",
            "inputs:albedo",
        )
        tint_names = ("inputs:diffuse_tint",)
        roughness_names = (
            "inputs:roughness",
            "inputs:reflection_roughness_constant",
        )
        texture_names = (
            "inputs:diffuse_texture",
            "inputs:diffuseTexture",
            "inputs:base_color_texture",
            "inputs:file",
        )

    base_color_attr, base_color = _first_input_value(shader_inputs, base_color_names)
    diffuse_tint_attr, diffuse_tint = _first_input_value(shader_inputs, tint_names)
    roughness_attr, roughness = _first_input_value(shader_inputs, roughness_names)
    texture_attr, texture = _first_input_value(shader_inputs, texture_names)
    return {
        "base_color_attr": base_color_attr,
        "base_color": base_color,
        "diffuse_tint_attr": diffuse_tint_attr,
        "diffuse_tint": diffuse_tint,
        "roughness_attr": roughness_attr,
        "roughness": roughness,
        "diffuse_texture_attr": texture_attr,
        "diffuse_texture": texture,
    }


def _first_input_value(
    shader_inputs: dict[str, Any],
    names: tuple[str, ...],
) -> tuple[str | None, Any]:
    for name in names:
        if name in shader_inputs:
            return name, shader_inputs[name]
    return None, None


def _coerce_scalar_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_vec3_value(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except Exception:
        return None


def _coerce_asset_value(value: Any) -> str | None:
    if value is None:
        return None
    path = getattr(value, "path", None)
    if path is not None:
        return str(path)
    resolved_path = getattr(value, "resolvedPath", None)
    if resolved_path is not None:
        return str(resolved_path)
    return str(value)


def _read_string_attr(prim: Any, names: tuple[str, ...]) -> str | None:
    for name in names:
        try:
            attr = prim.GetAttribute(name)
            value = attr.Get() if attr else None
            if value is not None:
                return str(value)
        except Exception:
            continue
    return None

def _read_scalar_attr_with_name(prim: Any, names: tuple[str, ...]) -> tuple[str | None, float | None]:
    for name in names:
        try:
            attr = prim.GetAttribute(name)
            value = attr.Get() if attr else None
            if value is not None:
                return name, float(value)
        except Exception:
            continue
    return None, None


def _read_vec3_attr_with_name(prim: Any, names: tuple[str, ...]) -> tuple[str | None, list[float] | None]:
    for name in names:
        try:
            attr = prim.GetAttribute(name)
            value = attr.Get() if attr else None
            if value is not None:
                return name, [float(value[0]), float(value[1]), float(value[2])]
        except Exception:
            continue
    return None, None


def _read_asset_attr_with_name(prim: Any, names: tuple[str, ...]) -> tuple[str | None, str | None]:
    for name in names:
        try:
            attr = prim.GetAttribute(name)
            value = attr.Get() if attr else None
            if value is None:
                continue
            path = getattr(value, "path", None)
            if path is not None:
                return name, str(path)
            resolved_path = getattr(value, "resolvedPath", None)
            if resolved_path is not None:
                return name, str(resolved_path)
            return name, str(value)
        except Exception:
            continue
    return None, None


def _read_scalar_attr(prim: Any, names: tuple[str, ...]) -> float | None:
    return _read_scalar_attr_with_name(prim, names)[1]


def _read_vec3_attr(prim: Any, names: tuple[str, ...]) -> list[float] | None:
    return _read_vec3_attr_with_name(prim, names)[1]


# --------------------------------------------------------------------------- #
# stage units                                                                 #
# --------------------------------------------------------------------------- #

def _stage_units(stage: Any) -> float | None:
    try:
        from pxr import UsdGeom

        return float(UsdGeom.GetStageMetersPerUnit(stage))
    except Exception:
        return None
