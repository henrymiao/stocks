from __future__ import annotations

from .method_models import EvidenceValue


def _materially_different(left: object, right: object, tolerance: float) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left != right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        scale = max(abs(float(left)), abs(float(right)), 1e-12)
        return abs(float(left) - float(right)) / scale > tolerance
    return left != right


def resolve_evidence(
    key: str,
    opend: EvidenceValue | None,
    supplemental: EvidenceValue | None,
    *,
    relative_tolerance: float = 0.05,
) -> tuple[EvidenceValue | None, str | None]:
    if opend is None:
        return supplemental, None
    if supplemental is None:
        return opend, None
    conflict = None
    if _materially_different(opend.value, supplemental.value, relative_tolerance):
        conflict = f"{key}:{opend.source}!={supplemental.source}"
    return opend, conflict
