"""
Evidence Grade Validation - ADR-004 Compliance

Enforces the evidence grade → alert severity binding from ADR-004:
- Grade A/B: All severities allowed (CRITICAL, HIGH, MEDIUM, LOW)
- Grade C: Only MEDIUM/LOW, requires manual escalation
- Grade D: Only LOW, requires manual review

"不可逾越的证据等级屏障"
"""

import logging
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class EvidenceGrade(str, Enum):
    """Evidence quality grade per ADR-004."""
    A = "A"  # Full integrity - all data complete, hashes verified
    B = "B"  # Minor issues - small gaps but replayable
    C = "C"  # Degraded - significant gaps, use with caution
    D = "D"  # Tainted - integrity compromised


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ADR-004 Policy: Evidence Grade → Allowed Severities
GRADE_SEVERITY_POLICY = {
    EvidenceGrade.A: [AlertSeverity.LOW, AlertSeverity.MEDIUM, AlertSeverity.HIGH, AlertSeverity.CRITICAL],
    EvidenceGrade.B: [AlertSeverity.LOW, AlertSeverity.MEDIUM, AlertSeverity.HIGH, AlertSeverity.CRITICAL],
    EvidenceGrade.C: [AlertSeverity.LOW, AlertSeverity.MEDIUM],  # No CRITICAL/HIGH
    EvidenceGrade.D: [AlertSeverity.LOW],  # Only LOW
}


@dataclass
class GradeValidationResult:
    """Result of evidence grade validation."""
    allowed: bool
    original_severity: AlertSeverity
    final_severity: AlertSeverity
    grade: EvidenceGrade
    downgraded: bool
    reason: str


def validate_alert_severity(
    evidence_grade: EvidenceGrade,
    requested_severity: AlertSeverity,
    auto_downgrade: bool = True
) -> GradeValidationResult:
    """
    Validate if a severity level is allowed for the given evidence grade.

    Args:
        evidence_grade: The evidence quality grade (A/B/C/D)
        requested_severity: The severity the system wants to assign
        auto_downgrade: If True, automatically downgrade to max allowed; if False, reject

    Returns:
        GradeValidationResult with validation outcome

    Per ADR-004:
    - CRITICAL/HIGH alerts ONLY allowed for Grade A/B evidence
    - Grade C: max MEDIUM
    - Grade D: max LOW
    """
    allowed_severities = GRADE_SEVERITY_POLICY.get(evidence_grade, [AlertSeverity.LOW])

    if requested_severity in allowed_severities:
        return GradeValidationResult(
            allowed=True,
            original_severity=requested_severity,
            final_severity=requested_severity,
            grade=evidence_grade,
            downgraded=False,
            reason=f"Severity {requested_severity.value} allowed for grade {evidence_grade.value}"
        )

    # Severity not allowed for this grade
    if auto_downgrade:
        # Downgrade to max allowed severity
        severity_order = [AlertSeverity.LOW, AlertSeverity.MEDIUM, AlertSeverity.HIGH, AlertSeverity.CRITICAL]
        max_allowed = max(allowed_severities, key=lambda s: severity_order.index(s))

        logger.warning(
            f"[GRADE] Downgrading severity from {requested_severity.value} to {max_allowed.value} "
            f"(evidence grade {evidence_grade.value})"
        )

        return GradeValidationResult(
            allowed=True,
            original_severity=requested_severity,
            final_severity=max_allowed,
            grade=evidence_grade,
            downgraded=True,
            reason=f"Downgraded from {requested_severity.value} to {max_allowed.value} due to grade {evidence_grade.value}"
        )
    else:
        return GradeValidationResult(
            allowed=False,
            original_severity=requested_severity,
            final_severity=requested_severity,
            grade=evidence_grade,
            downgraded=False,
            reason=f"Severity {requested_severity.value} not allowed for grade {evidence_grade.value}. Allowed: {[s.value for s in allowed_severities]}"
        )


def compute_evidence_grade(
    has_gaps: bool = False,
    hash_verified: bool = True,
    tainted_windows: int = 0,
    coverage_ratio: float = 1.0
) -> EvidenceGrade:
    """
    Compute evidence grade from data quality metrics.

    Args:
        has_gaps: Whether there are data gaps in the time range
        hash_verified: Whether bundle hash verification passed
        tainted_windows: Number of tainted windows in the data
        coverage_ratio: Ratio of expected vs actual data points (0.0 - 1.0)

    Returns:
        EvidenceGrade (A, B, C, or D)
    """
    # Grade D: Tainted/compromised
    if not hash_verified or tainted_windows > 3:
        return EvidenceGrade.D

    # Grade C: Degraded
    if has_gaps or coverage_ratio < 0.7 or tainted_windows > 0:
        return EvidenceGrade.C

    # Grade B: Minor issues
    if coverage_ratio < 0.95:
        return EvidenceGrade.B

    # Grade A: Full integrity
    return EvidenceGrade.A


def get_max_severity_for_grade(grade: EvidenceGrade) -> AlertSeverity:
    """Get the maximum allowed severity for a given evidence grade."""
    allowed = GRADE_SEVERITY_POLICY.get(grade, [AlertSeverity.LOW])
    severity_order = [AlertSeverity.LOW, AlertSeverity.MEDIUM, AlertSeverity.HIGH, AlertSeverity.CRITICAL]
    return max(allowed, key=lambda s: severity_order.index(s))


def requires_manual_escalation(grade: EvidenceGrade, severity: AlertSeverity) -> bool:
    """
    Check if manual escalation is required for this grade/severity combination.

    Per ADR-004:
    - Grade C with MEDIUM: requires manual escalation for HIGH/CRITICAL
    - Grade D: always requires manual review
    """
    if grade == EvidenceGrade.D:
        return True

    if grade == EvidenceGrade.C and severity in [AlertSeverity.MEDIUM]:
        return True  # User wanted HIGH/CRITICAL but got MEDIUM

    return False


# =============================================================================
# Integration with AlertPayload
# =============================================================================

def apply_grade_policy(
    severity: str,
    evidence_grade: str,
    auto_downgrade: bool = True
) -> Tuple[str, bool, str]:
    """
    Apply evidence grade policy to alert severity.

    Convenience function for integration with existing alert code.

    Args:
        severity: Severity string (LOW, MEDIUM, HIGH, CRITICAL)
        evidence_grade: Grade string (A, B, C, D)
        auto_downgrade: Whether to auto-downgrade or reject

    Returns:
        (final_severity, was_downgraded, reason)
    """
    try:
        grade = EvidenceGrade(evidence_grade)
        sev = AlertSeverity(severity)
    except ValueError as e:
        logger.warning(f"[GRADE] Invalid grade or severity: {e}")
        return severity, False, "Invalid grade or severity value"

    result = validate_alert_severity(grade, sev, auto_downgrade=auto_downgrade)
    return result.final_severity.value, result.downgraded, result.reason
