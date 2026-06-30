"""XformOp layout inspection and pure-Python 4x4 matrix utilities.

The scanner uses this to classify how a prim authors its local transform so
that DR overrides can be written in the *same* shape. The applier uses the
matrix helpers to convert world-space sampled values back to whatever
attribute the prim already exposes.

Layouts:
    "matrix"  - single xformOp:transform op
    "trs"     - xformOpOrder containing any combination of translate / rotate
                / scale ops (the prim may author one, two, or all three)
    "empty"   - no xformOpOrder yet
    "unknown" - xformOpOrder exists but contains no translate / rotate /
                scale / transform op (custom op names); DR refuses to emit
                pose overrides here.

For "trs" layouts the applier MUST NOT touch xformOpOrder; it only rewrites
the value attribute of ops the prim already authors. A requested delta on an
op type the prim does not author is skipped with a warning. Reordering would
change pose composition semantics and silently break the prim.

The layout descriptor returned by ``extract_layout`` exposes T / R / S as
symmetric sub-dicts. Each component carries ``present`` / ``op_name`` /
``precision`` / ``base_value``; the rotate component also carries ``op_type``
(``rotateXYZ``, ``rotateZYX``, ``orient``, ...). Legacy convenience keys
``translate_op_name`` / ``translate_op_precision`` / ``local_translation``
are kept as mirrors for backward compatibility.

The math helpers are pure Python so this module can be imported and tested
without pxr; the pxr-dependent extractor is gated by a try / except at call
sites.
"""

from __future__ import annotations

from typing import Any


# Canonical rotate-op type tokens. Mirrors the UsdGeom.XformOp.Type* enum
# values we recognise. Sampler / applier branch on these strings; ``orient``
# is handled separately because its value is a quaternion, not Euler vec3.
_ROTATE_TYPE_TOKENS = (
    "rotateXYZ",
    "rotateXZY",
    "rotateYXZ",
    "rotateYZX",
    "rotateZXY",
    "rotateZYX",
    "rotateX",
    "rotateY",
    "rotateZ",
)


def _empty_component() -> dict[str, Any]:
    return {
        "present": False,
        "op_name": None,
        "precision": None,
        "base_value": None,
    }


def empty_layout() -> dict[str, Any]:
    return {
        "layout": "unknown",
        "op_order": [],
        "local_transform_4x4": identity_4x4(),
        "parent_world_transform_4x4": identity_4x4(),
        "translate": _empty_component(),
        "rotate": dict(_empty_component(), op_type=None),
        "scale": _empty_component(),
        # Legacy / convenience mirrors. Existing appliers / tests read these.
        "translate_op_name": None,
        "translate_op_precision": None,
        "local_translation": [0.0, 0.0, 0.0],
    }


def identity_4x4() -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


# --------------------------------------------------------------------------- #
# pxr-backed extractor                                                        #
# --------------------------------------------------------------------------- #

def extract_layout(prim: Any, UsdGeom: Any) -> dict[str, Any]:
    """Build a layout descriptor for a prim. Tolerates missing pxr behaviors."""
    layout = empty_layout()
    try:
        xformable = UsdGeom.Xformable(prim)
    except Exception:
        xformable = None
    if not xformable:
        return layout

    local_matrix = identity_4x4()
    try:
        m = xformable.GetLocalTransformation(0)
        local_matrix = matrix4d_to_list(m)
    except Exception:
        pass

    parent_matrix = identity_4x4()
    try:
        l2w = xformable.ComputeLocalToWorldTransform(0)
        l2w_list = matrix4d_to_list(l2w)
        local_inv = matrix4d_inverse(local_matrix)
        if local_inv is not None:
            parent_matrix = mat_mul(local_inv, l2w_list)
    except Exception:
        pass

    layout["local_transform_4x4"] = local_matrix
    layout["parent_world_transform_4x4"] = parent_matrix
    layout["local_translation"] = [
        float(local_matrix[3]),
        float(local_matrix[7]),
        float(local_matrix[11]),
    ]

    try:
        ordered_ops = list(xformable.GetOrderedXformOps())
    except Exception:
        ordered_ops = []
    layout["op_order"] = [_op_attr_name(op) for op in ordered_ops]

    if not ordered_ops:
        layout["layout"] = "empty"
        return layout

    matrix_op = None
    translate_op = None
    rotate_op = None
    rotate_kind: str | None = None
    scale_op = None
    for op in ordered_ops:
        op_type = _safe_op_type(op, UsdGeom)
        if matrix_op is None and op_type == "transform":
            matrix_op = op
        if translate_op is None and op_type == "translate":
            translate_op = op
        if rotate_op is None and (op_type in _ROTATE_TYPE_TOKENS or op_type == "orient"):
            rotate_op = op
            rotate_kind = op_type
        if scale_op is None and op_type == "scale":
            scale_op = op

    if translate_op is not None or rotate_op is not None or scale_op is not None:
        layout["layout"] = "trs"
        if translate_op is not None:
            _fill_translate(layout, translate_op, UsdGeom)
        if rotate_op is not None:
            _fill_rotate(layout, rotate_op, rotate_kind, UsdGeom)
        if scale_op is not None:
            _fill_scale(layout, scale_op, UsdGeom)
    elif matrix_op is not None:
        layout["layout"] = "matrix"
        # legacy mirror: applier reads `translate_op_name` to find the
        # transform op attribute name in matrix layouts.
        layout["translate_op_name"] = _op_attr_name(matrix_op)
    else:
        layout["layout"] = "unknown"
    return layout


def _fill_translate(layout: dict[str, Any], op: Any, UsdGeom: Any) -> None:
    name = _op_attr_name(op)
    precision = _op_precision_token(op, UsdGeom)
    base = _safe_get_vec3(op)
    layout["translate"] = {
        "present": True,
        "op_name": name,
        "precision": precision,
        "base_value": base,
    }
    layout["translate_op_name"] = name
    layout["translate_op_precision"] = precision
    if base is not None:
        layout["local_translation"] = list(base)


def _fill_rotate(layout: dict[str, Any], op: Any, op_type: str | None, UsdGeom: Any) -> None:
    name = _op_attr_name(op)
    precision = _op_precision_token(op, UsdGeom)
    if op_type == "orient":
        base = _safe_get_quat(op)
    elif op_type in {"rotateX", "rotateY", "rotateZ"}:
        base = _safe_get_scalar(op)
    else:
        base = _safe_get_vec3(op)
    layout["rotate"] = {
        "present": True,
        "op_name": name,
        "precision": precision,
        "op_type": op_type,
        "base_value": base,
    }


def _fill_scale(layout: dict[str, Any], op: Any, UsdGeom: Any) -> None:
    name = _op_attr_name(op)
    precision = _op_precision_token(op, UsdGeom)
    base = _safe_get_vec3(op)
    layout["scale"] = {
        "present": True,
        "op_name": name,
        "precision": precision,
        "base_value": base,
    }


def _safe_get_vec3(op: Any) -> list[float] | None:
    try:
        v = op.Get()
    except Exception:
        return None
    if v is None:
        return None
    try:
        return [float(v[0]), float(v[1]), float(v[2])]
    except Exception:
        return None


def _safe_get_scalar(op: Any) -> float | None:
    try:
        v = op.Get()
    except Exception:
        return None
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _safe_get_quat(op: Any) -> list[float] | None:
    """Return ``[qx, qy, qz, qw]`` for a Gf.Quat-like op value, else None."""
    try:
        q = op.Get()
    except Exception:
        return None
    if q is None:
        return None
    try:
        real = float(q.GetReal())
        im = q.GetImaginary()
        return [float(im[0]), float(im[1]), float(im[2]), real]
    except Exception:
        return None


def _op_attr_name(op: Any) -> str:
    try:
        return str(op.GetName())
    except Exception:
        pass
    try:
        return str(op.GetAttr().GetName())
    except Exception:
        return ""


def _safe_op_type(op: Any, UsdGeom: Any) -> str:
    """Classify a UsdGeom.XformOp.

    Returns one of: ``"translate"``, ``"transform"``, ``"scale"``,
    ``"orient"``, ``"rotateXYZ"`` / ``"rotateZYX"`` / ... (specific Euler
    order), or ``"other"``. Name-based fallback collapses all rotates to
    ``"rotateXYZ"`` because the suffix is not standardised.
    """
    try:
        op_type = op.GetOpType()
    except Exception:
        op_type = None
    try:
        T = UsdGeom.XformOp
        if op_type == T.TypeTranslate:
            return "translate"
        if op_type == T.TypeTransform:
            return "transform"
        if op_type == T.TypeScale:
            return "scale"
        if op_type == T.TypeOrient:
            return "orient"
        for tn in (
            "TypeRotateXYZ", "TypeRotateXZY", "TypeRotateYXZ",
            "TypeRotateYZX", "TypeRotateZXY", "TypeRotateZYX",
            "TypeRotateX", "TypeRotateY", "TypeRotateZ",
        ):
            v = getattr(T, tn, None)
            if v is not None and op_type == v:
                # Strip the leading "Type" -> "rotateXYZ" etc.
                return tn[4].lower() + tn[5:]
    except Exception:
        pass
    name = _op_attr_name(op)
    if ":translate" in name:
        return "translate"
    if name == "xformOp:transform" or name.endswith(":transform"):
        return "transform"
    if ":rotateXYZ" in name:
        return "rotateXYZ"
    if ":rotateXZY" in name:
        return "rotateXZY"
    if ":rotateYXZ" in name:
        return "rotateYXZ"
    if ":rotateYZX" in name:
        return "rotateYZX"
    if ":rotateZXY" in name:
        return "rotateZXY"
    if ":rotateZYX" in name:
        return "rotateZYX"
    if ":rotateX" in name:
        return "rotateX"
    if ":rotateY" in name:
        return "rotateY"
    if ":rotateZ" in name:
        return "rotateZ"
    if ":rotate" in name:
        # Generic ``xformOp:rotate`` without a suffix: assume XYZ order.
        return "rotateXYZ"
    if ":scale" in name:
        return "scale"
    if ":orient" in name:
        return "orient"
    return "other"


def _op_precision_token(op: Any, UsdGeom: Any) -> str | None:
    try:
        precision = op.GetPrecision()
    except Exception:
        return None
    try:
        P = UsdGeom.XformOp
        if precision == P.PrecisionDouble:
            return "double"
        if precision == P.PrecisionFloat:
            return "float"
        if precision == P.PrecisionHalf:
            return "half"
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# pure-Python 4x4 matrix helpers (row-major, USD convention)                  #
# --------------------------------------------------------------------------- #

def matrix4d_to_list(matrix: Any) -> list[float]:
    """Convert a pxr Gf.Matrix4d-like object to a row-major 16-float list.

    pxr matrices use `m[i][j]` for row i, column j.
    """
    try:
        out: list[float] = []
        for i in range(4):
            row = matrix[i]
            for j in range(4):
                out.append(float(row[j]))
        if len(out) == 16:
            return out
    except Exception:
        pass
    return identity_4x4()


def mat_mul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for i in range(4):
        for j in range(4):
            s = 0.0
            for k in range(4):
                s += a[i * 4 + k] * b[k * 4 + j]
            out[i * 4 + j] = s
    return out


def mat_vec_mul_point(matrix: list[float], point: list[float]) -> list[float]:
    """Multiply a 3-vector treated as (x, y, z, 1) by a row-major 4x4 matrix.

    USD's Gf.Matrix4d * Gf.Vec3 convention treats vectors as row vectors and
    multiplies on the right (v_out = v_in * M).  We replicate that here.
    """
    x, y, z = float(point[0]), float(point[1]), float(point[2])
    m = matrix
    rx = x * m[0] + y * m[4] + z * m[8] + m[12]
    ry = x * m[1] + y * m[5] + z * m[9] + m[13]
    rz = x * m[2] + y * m[6] + z * m[10] + m[14]
    return [rx, ry, rz]


def matrix4d_inverse(matrix: list[float]) -> list[float] | None:
    """Generic 4x4 inverse via cofactor expansion. Returns None if singular."""
    m = matrix
    inv = [0.0] * 16
    inv[0] = (m[5] * m[10] * m[15] - m[5] * m[11] * m[14]
              - m[9] * m[6] * m[15] + m[9] * m[7] * m[14]
              + m[13] * m[6] * m[11] - m[13] * m[7] * m[10])
    inv[4] = (-m[4] * m[10] * m[15] + m[4] * m[11] * m[14]
              + m[8] * m[6] * m[15] - m[8] * m[7] * m[14]
              - m[12] * m[6] * m[11] + m[12] * m[7] * m[10])
    inv[8] = (m[4] * m[9] * m[15] - m[4] * m[11] * m[13]
              - m[8] * m[5] * m[15] + m[8] * m[7] * m[13]
              + m[12] * m[5] * m[11] - m[12] * m[7] * m[9])
    inv[12] = (-m[4] * m[9] * m[14] + m[4] * m[10] * m[13]
               + m[8] * m[5] * m[14] - m[8] * m[6] * m[13]
               - m[12] * m[5] * m[10] + m[12] * m[6] * m[9])
    inv[1] = (-m[1] * m[10] * m[15] + m[1] * m[11] * m[14]
              + m[9] * m[2] * m[15] - m[9] * m[3] * m[14]
              - m[13] * m[2] * m[11] + m[13] * m[3] * m[10])
    inv[5] = (m[0] * m[10] * m[15] - m[0] * m[11] * m[14]
              - m[8] * m[2] * m[15] + m[8] * m[3] * m[14]
              + m[12] * m[2] * m[11] - m[12] * m[3] * m[10])
    inv[9] = (-m[0] * m[9] * m[15] + m[0] * m[11] * m[13]
              + m[8] * m[1] * m[15] - m[8] * m[3] * m[13]
              - m[12] * m[1] * m[11] + m[12] * m[3] * m[9])
    inv[13] = (m[0] * m[9] * m[14] - m[0] * m[10] * m[13]
               - m[8] * m[1] * m[14] + m[8] * m[2] * m[13]
               + m[12] * m[1] * m[10] - m[12] * m[2] * m[9])
    inv[2] = (m[1] * m[6] * m[15] - m[1] * m[7] * m[14]
              - m[5] * m[2] * m[15] + m[5] * m[3] * m[14]
              + m[13] * m[2] * m[7] - m[13] * m[3] * m[6])
    inv[6] = (-m[0] * m[6] * m[15] + m[0] * m[7] * m[14]
              + m[4] * m[2] * m[15] - m[4] * m[3] * m[14]
              - m[12] * m[2] * m[7] + m[12] * m[3] * m[6])
    inv[10] = (m[0] * m[5] * m[15] - m[0] * m[7] * m[13]
               - m[4] * m[1] * m[15] + m[4] * m[3] * m[13]
               + m[12] * m[1] * m[7] - m[12] * m[3] * m[5])
    inv[14] = (-m[0] * m[5] * m[14] + m[0] * m[6] * m[13]
               + m[4] * m[1] * m[14] - m[4] * m[2] * m[13]
               - m[12] * m[1] * m[6] + m[12] * m[2] * m[5])
    inv[3] = (-m[1] * m[6] * m[11] + m[1] * m[7] * m[10]
              + m[5] * m[2] * m[11] - m[5] * m[3] * m[10]
              - m[9] * m[2] * m[7] + m[9] * m[3] * m[6])
    inv[7] = (m[0] * m[6] * m[11] - m[0] * m[7] * m[10]
              - m[4] * m[2] * m[11] + m[4] * m[3] * m[10]
              + m[8] * m[2] * m[7] - m[8] * m[3] * m[6])
    inv[11] = (-m[0] * m[5] * m[11] + m[0] * m[7] * m[9]
               + m[4] * m[1] * m[11] - m[4] * m[3] * m[9]
               - m[8] * m[1] * m[7] + m[8] * m[3] * m[5])
    inv[15] = (m[0] * m[5] * m[10] - m[0] * m[6] * m[9]
               - m[4] * m[1] * m[10] + m[4] * m[2] * m[9]
               + m[8] * m[1] * m[6] - m[8] * m[2] * m[5])
    det = m[0] * inv[0] + m[1] * inv[4] + m[2] * inv[8] + m[3] * inv[12]
    if det == 0.0:
        return None
    inv_det = 1.0 / det
    return [v * inv_det for v in inv]


# --------------------------------------------------------------------------- #
# world / local helpers used by appliers                                      #
# --------------------------------------------------------------------------- #

def world_translation_from_local_matrix(
    local_matrix: list[float], parent_world: list[float]
) -> list[float]:
    """Compose: world = local * parent_world; extract translation row."""
    composed = mat_mul(local_matrix, parent_world)
    return [composed[12], composed[13], composed[14]]


def world_to_local_translation(
    world_translation: list[float],
    parent_world: list[float],
) -> list[float] | None:
    """Convert a world-space target translation to local-space by inverting
    the parent's world transform.

    Returns None if the parent is singular.  Rotation / scale in the local
    transform are preserved by the caller (we only override the translate op).
    """
    parent_inv = matrix4d_inverse(parent_world)
    if parent_inv is None:
        return None
    return mat_vec_mul_point(parent_inv, world_translation)


def replace_translation(matrix: list[float], translation: list[float]) -> list[float]:
    """Return a copy of `matrix` with row 3 (translation row) replaced.

    USD's row-major Matrix4d stores translation in row 3 (indices 12..14).
    """
    out = list(matrix)
    out[12] = float(translation[0])
    out[13] = float(translation[1])
    out[14] = float(translation[2])
    out[15] = 1.0
    return out


# --------------------------------------------------------------------------- #
# TRS composition / decomposition (pure Python, USD row-vector convention)    #
#                                                                             #
# USD applies xformOps in the order listed in xformOpOrder.  With row-vector  #
# convention the local matrix is the product of per-op matrices read left to  #
# right: for op_order = [translate, rotateXYZ, scale],                        #
#     local = T * Rx * Ry * Rz * S                                            #
# Sampler / applier use these helpers to build deltas and to recompose a      #
# single matrix4d for matrix-layout prims.                                    #
# --------------------------------------------------------------------------- #

def translation_matrix(t: list[float]) -> list[float]:
    """Return a 4x4 row-major matrix with translation row = t."""
    out = identity_4x4()
    out[12], out[13], out[14] = float(t[0]), float(t[1]), float(t[2])
    return out


def scale_matrix(s: list[float]) -> list[float]:
    """Return a 4x4 diagonal scale matrix."""
    out = identity_4x4()
    out[0], out[5], out[10] = float(s[0]), float(s[1]), float(s[2])
    return out


def _rot_x(angle_rad: float) -> list[float]:
    import math
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    m = identity_4x4()
    m[5], m[6] = c, s
    m[9], m[10] = -s, c
    return m


def _rot_y(angle_rad: float) -> list[float]:
    import math
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    m = identity_4x4()
    m[0], m[2] = c, -s
    m[8], m[10] = s, c
    return m


def _rot_z(angle_rad: float) -> list[float]:
    import math
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    m = identity_4x4()
    m[0], m[1] = c, s
    m[4], m[5] = -s, c
    return m


def euler_xyz_to_matrix(euler_deg: list[float]) -> list[float]:
    """Build a 4x4 rotation matrix for ``xformOp:rotateXYZ`` semantics.

    USD's rotateXYZ applies rotateX first, then rotateY, then rotateZ. Under
    row-vector convention that composes as ``R = Rx * Ry * Rz`` (left to
    right). Inputs are degrees.
    """
    import math
    rx = math.radians(float(euler_deg[0]))
    ry = math.radians(float(euler_deg[1]))
    rz = math.radians(float(euler_deg[2]))
    return mat_mul(mat_mul(_rot_x(rx), _rot_y(ry)), _rot_z(rz))


def matrix_to_euler_xyz(matrix: list[float]) -> list[float]:
    """Inverse of ``euler_xyz_to_matrix``: return ``[rx, ry, rz]`` in degrees.

    Assumes the input is a pure rotation (no scale, no shear). Call
    ``decompose_trs`` first if scale may be present. Falls back to a gimbal-
    lock branch when |ry| ~= 90 deg.
    """
    import math
    m = matrix
    sin_ry = -float(m[2])
    if sin_ry > 1.0:
        sin_ry = 1.0
    elif sin_ry < -1.0:
        sin_ry = -1.0
    ry = math.asin(sin_ry)
    cos_ry = math.cos(ry)
    EPS = 0.000001
    if abs(cos_ry) > EPS:
        rx = math.atan2(float(m[6]), float(m[10]))
        rz = math.atan2(float(m[1]), float(m[0]))
    else:
        rx = math.atan2(-float(m[9]), float(m[5]))
        rz = 0.0
    return [math.degrees(rx), math.degrees(ry), math.degrees(rz)]


def decompose_trs(matrix: list[float]) -> tuple[list[float], list[float], list[float]]:
    """Decompose a row-major local matrix into translation, XYZ euler (deg), and scale.

    Assumes ``matrix = T * Rx*Ry*Rz * S`` with no shear. Under the row-vector
    convention, scale is recovered from column norms; rotation is what remains
    after normalising those columns. Degenerate (zero-norm) columns leave the
    corresponding rotation column as identity and scale axis as 0.
    """
    import math
    m = matrix
    t = [float(m[12]), float(m[13]), float(m[14])]
    sx = math.sqrt(m[0] * m[0] + m[4] * m[4] + m[8] * m[8])
    sy = math.sqrt(m[1] * m[1] + m[5] * m[5] + m[9] * m[9])
    sz = math.sqrt(m[2] * m[2] + m[6] * m[6] + m[10] * m[10])
    rot = identity_4x4()
    EPS = 0.000000001
    norms = (sx, sy, sz)
    for col_idx, s in enumerate(norms):
        if s > EPS:
            rot[0 * 4 + col_idx] = m[0 * 4 + col_idx] / s
            rot[1 * 4 + col_idx] = m[1 * 4 + col_idx] / s
            rot[2 * 4 + col_idx] = m[2 * 4 + col_idx] / s
    euler = matrix_to_euler_xyz(rot)
    return t, euler, [sx, sy, sz]


def compose_trs(
    translation: list[float],
    euler_xyz_deg: list[float],
    scale: list[float],
) -> list[float]:
    """Compose a row-major local matrix for op_order = [translate, rotate, scale].

    Under USD row-vector convention a point composes as
    ``p_out = p_in * T * R * S``, so the composed matrix is ``T * R * S``.
    """
    T = translation_matrix(translation)
    R = euler_xyz_to_matrix(euler_xyz_deg)
    S = scale_matrix(scale)
    return mat_mul(mat_mul(T, R), S)
