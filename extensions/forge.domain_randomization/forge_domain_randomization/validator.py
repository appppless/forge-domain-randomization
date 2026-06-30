"""Validation helpers for v0.2 domain randomization.

No role or manifest checks. Independently validates each whitelisted prim and
turns request/achievement gaps into benchmark-facing issues.
"""

from __future__ import annotations

from typing import Any

from .sampler import RandomizationPlan
from .schemas import DomainRandomizationRequest


def validate_randomization(
    request: DomainRandomizationRequest,
    scan: dict[str, Any],
    plan: RandomizationPlan,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    requested_domains = _requested_domains(request)
    strict = _strict_validation_enabled(request)

    for w in scan.get("warnings") or []:
        issues.append({"type": "scan_warning", "severity": "warning", "message": w, "blocking": False})

    for skipped in getattr(plan, "skipped_prims", None) or []:
        reason = skipped.get("reason") or "no edits emitted"
        domain = skipped.get("domain")
        prim_path = str(skipped.get("prim_path") or "")
        issue_type = "unsupported_domain" if domain else "prim_not_on_stage"
        blocking = strict and _skip_blocks_request(skipped, requested_domains)
        severity = "error" if blocking else "warning"
        message = (
            f"{skipped.get('kind', 'prim')} '{skipped.get('prim_path')}' "
            f"{domain + ' ' if domain else ''}skipped: {reason}"
        )
        issues.append({
            "type": issue_type,
            "severity": severity,
            "message": message,
            "prim_path": prim_path,
            "domain": domain,
            "reason": reason,
            "blocking": blocking,
        })

    enabled_count = _enabled_domain_count(request)
    if not plan.edits and enabled_count > 0:
        issues.append({
            "type": "empty_randomization_plan",
            "severity": "error" if strict else "warning",
            "message": "No USD edits were generated.",
            "blocking": strict,
        })

    achieved_count = len(plan.achieved_parameters)
    if enabled_count > 0 and achieved_count == 0:
        issues.append({
            "type": "no_parameters_achieved",
            "severity": "error" if strict else "warning",
            "message": "Enabled domains produced no achieved parameters (stage may lack matching prims).",
            "blocking": strict,
        })

    issues.extend(_missing_visibility_pool_prims(request, scan, strict=strict))
    issues.extend(_unachieved_requested_domains(request, plan, strict=strict))

    minimum_score = _minimum_controllability_score(request)
    score = controllability_score(request, plan)
    if minimum_score is not None and score < minimum_score:
        issues.append({
            "type": "controllability_below_threshold",
            "severity": "error" if strict else "warning",
            "message": (
                f"Controllability score {score:.3f} is below requested minimum "
                f"{minimum_score:.3f}."
            ),
            "controllability_score": score,
            "minimum_controllability_score": minimum_score,
            "blocking": strict,
        })

    blocking = [i for i in issues if i.get("blocking")]
    return {
        "success": not blocking,
        "issues": issues,
        "resample_counts": {},
        "coverage": {
            "enabled_domains": enabled_count,
            "requested_parameters": len(plan.requested_parameters),
            "achieved_parameters": achieved_count,
            "controllability_score": score,
        },
    }


def controllability_score(request: DomainRandomizationRequest, plan: RandomizationPlan) -> float:
    enabled = _enabled_domain_count(request)
    if enabled == 0:
        return 1.0
    achieved = len(plan.achieved_parameters)
    return min(1.0, achieved / enabled)


def _strict_validation_enabled(request: DomainRandomizationRequest) -> bool:
    policy = request.validation_policy or {}
    if "strict" in policy:
        return bool(policy["strict"])
    mode = str(policy.get("mode") or "").strip().lower()
    if mode in {"permissive", "warn", "warning", "non_blocking", "non-blocking"}:
        return False
    return True


def _minimum_controllability_score(request: DomainRandomizationRequest) -> float | None:
    policy = request.validation_policy or {}
    raw = policy.get("minimum_controllability_score", policy.get("min_controllability_score"))
    if raw is None:
        return None
    return max(0.0, min(1.0, float(raw)))


def _enabled_domain_count(request: DomainRandomizationRequest) -> int:
    enabled = sum(
        1
        for obj in request.objects
        for domain in ("asset", "material", "pose", "visibility", "physics")
        if getattr(obj, domain)
    )
    enabled += sum(
        1
        for light in request.lights
        for attr in ("intensity_scale", "color_temperature", "color")
        if getattr(light, attr)
    )
    enabled += sum(
        1
        for cam in request.cameras
        for attr in ("pose_jitter_m", "fov_deg", "yaw_pitch_jitter_deg")
        if getattr(cam, attr)
    )
    enabled += len(request.visibility_pools)
    return enabled


def _requested_domains(request: DomainRandomizationRequest) -> set[tuple[str, str]]:
    domains: set[tuple[str, str]] = set()
    for obj in request.objects:
        for domain in ("asset", "material", "pose", "visibility", "physics"):
            if getattr(obj, domain):
                domains.add((obj.prim_path, domain))
        if any(getattr(obj, domain) for domain in ("asset", "material", "pose", "visibility", "physics")):
            domains.add((obj.prim_path, "*"))
    for light in request.lights:
        if any(getattr(light, attr) for attr in ("intensity_scale", "color_temperature", "color")):
            domains.add((light.prim_path, "*"))
            domains.add((light.prim_path, "light"))
    for cam in request.cameras:
        if any(getattr(cam, attr) for attr in ("pose_jitter_m", "fov_deg", "yaw_pitch_jitter_deg")):
            domains.add((cam.prim_path, "*"))
            domains.add((cam.prim_path, "camera"))
    return domains


def _skip_blocks_request(skipped: dict[str, Any], requested_domains: set[tuple[str, str]]) -> bool:
    prim_path = str(skipped.get("prim_path") or "")
    domain = skipped.get("domain")
    if not prim_path:
        return False
    if domain:
        return (prim_path, str(domain)) in requested_domains
    return (prim_path, "*") in requested_domains


def _missing_visibility_pool_prims(
    request: DomainRandomizationRequest,
    scan: dict[str, Any],
    *,
    strict: bool,
) -> list[dict[str, Any]]:
    known = {
        str(item.get("prim_path"))
        for section in ("prims", "lights", "cameras")
        for item in (scan.get(section) or [])
        if item.get("prim_path")
    }
    issues: list[dict[str, Any]] = []
    for pool in request.visibility_pools:
        missing = [p for p in pool.prims if p not in known]
        if not missing:
            continue
        issues.append({
            "type": "visibility_pool_missing_prims",
            "severity": "error" if strict else "warning",
            "message": f"Visibility pool '{pool.id}' references prims not present in scan.",
            "pool_id": pool.id,
            "missing_prims": missing,
            "blocking": strict,
        })
    return issues


def _unachieved_requested_domains(
    request: DomainRandomizationRequest,
    plan: RandomizationPlan,
    *,
    strict: bool,
) -> list[dict[str, Any]]:
    achieved_keys = set(plan.achieved_parameters)
    issues: list[dict[str, Any]] = []

    for obj in request.objects:
        for domain in ("asset", "material", "pose", "visibility", "physics"):
            if not getattr(obj, domain):
                continue
            prefix = f"{obj.prim_path}.{domain}."
            if not any(k.startswith(prefix) for k in achieved_keys):
                issues.append(_unachieved_issue(obj.prim_path, domain, strict))

    for light in request.lights:
        if light.intensity_scale and not _has_achieved(achieved_keys, light.prim_path, "light.intensity"):
            issues.append(_unachieved_issue(light.prim_path, "light.intensity", strict))
        if light.color_temperature and not _has_achieved(achieved_keys, light.prim_path, "light.color_temperature"):
            issues.append(_unachieved_issue(light.prim_path, "light.color_temperature", strict))
        if light.color and not _has_achieved(achieved_keys, light.prim_path, "light.color"):
            issues.append(_unachieved_issue(light.prim_path, "light.color", strict))

    for cam in request.cameras:
        if cam.pose_jitter_m and not _has_achieved(achieved_keys, cam.prim_path, "camera.translation"):
            issues.append(_unachieved_issue(cam.prim_path, "camera.translation", strict))
        if cam.yaw_pitch_jitter_deg and not _has_achieved(achieved_keys, cam.prim_path, "camera.rotation_delta_deg"):
            issues.append(_unachieved_issue(cam.prim_path, "camera.rotation_delta_deg", strict))
        if cam.fov_deg and not _has_achieved(achieved_keys, cam.prim_path, "camera.fov_deg"):
            issues.append(_unachieved_issue(cam.prim_path, "camera.fov_deg", strict))

    for pool in request.visibility_pools:
        prefix = f"visibility_pool.{pool.id}."
        if not any(k.startswith(prefix) for k in achieved_keys):
            issues.append(_unachieved_issue(f"visibility_pool.{pool.id}", "visibility_pool", strict))

    return issues


def _has_achieved(achieved_keys: set[str], prim_path: str, suffix: str) -> bool:
    return f"{prim_path}.{suffix}" in achieved_keys


def _unachieved_issue(prim_path: str, domain: str, strict: bool) -> dict[str, Any]:
    return {
        "type": "requested_domain_unachieved",
        "severity": "error" if strict else "warning",
        "message": f"Requested domain '{domain}' for '{prim_path}' produced no achieved parameter.",
        "prim_path": prim_path,
        "domain": domain,
        "blocking": strict,
    }
