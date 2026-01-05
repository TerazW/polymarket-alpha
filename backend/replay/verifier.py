"""
Belief Reaction System - Bundle Verifier v1
Verifies evidence bundle integrity and provides audit reports.

"每一个证据包都可验证、可追溯、可复现"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
import json
import time

from backend.evidence.bundle_hash import compute_bundle_hash, verify_bundle


class VerificationStatus(Enum):
    """Verification result status"""
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class VerificationCheck:
    """Individual verification check result"""
    check_name: str
    status: VerificationStatus
    expected: Any = None
    actual: Any = None
    message: str = ""


@dataclass
class VerificationResult:
    """Complete verification result"""
    bundle_id: str = ""
    token_id: str = ""
    t0: int = 0
    verified_at: int = 0

    # Overall status
    overall_status: VerificationStatus = VerificationStatus.PASS
    checks_passed: int = 0
    checks_failed: int = 0
    checks_total: int = 0

    # Hash verification
    expected_hash: str = ""
    computed_hash: str = ""
    hash_matches: bool = False

    # Individual checks
    checks: List[VerificationCheck] = field(default_factory=list)

    # Errors
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bundle_id": self.bundle_id,
            "token_id": self.token_id,
            "t0": self.t0,
            "verified_at": self.verified_at,
            "verified_at_iso": datetime.fromtimestamp(self.verified_at / 1000).isoformat() if self.verified_at else None,
            "overall_status": self.overall_status.value,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "checks_total": self.checks_total,
            "expected_hash": self.expected_hash,
            "computed_hash": self.computed_hash,
            "hash_matches": self.hash_matches,
            "checks": [
                {
                    "name": c.check_name,
                    "status": c.status.value,
                    "expected": c.expected,
                    "actual": c.actual,
                    "message": c.message,
                }
                for c in self.checks
            ],
            "errors": self.errors,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class BundleVerifier:
    """
    Verifies evidence bundle integrity with multiple checks.

    Checks performed:
    1. Hash integrity (stored vs computed)
    2. Timestamp consistency (events within window)
    3. Sequence continuity (no gaps in event sequence)
    4. Schema completeness (required fields present)
    5. Provenance validity (engine version, config hash)

    Usage:
        verifier = BundleVerifier()
        result = verifier.verify(bundle, expected_hash)

        if result.overall_status == VerificationStatus.PASS:
            print("Verification passed!")
        else:
            for check in result.checks:
                if check.status == VerificationStatus.FAIL:
                    print(f"Failed: {check.check_name}: {check.message}")
    """

    def __init__(self):
        self.required_fields = [
            'token_id',
            't0',
            'window',
        ]

    def verify(
        self,
        bundle: Dict[str, Any],
        expected_hash: str,
        check_provenance: bool = True
    ) -> VerificationResult:
        """
        Verify a bundle against expected hash and run integrity checks.

        Args:
            bundle: Evidence bundle to verify
            expected_hash: Expected hash from storage
            check_provenance: Whether to check engine version/config

        Returns:
            VerificationResult with detailed check results
        """
        now = int(time.time() * 1000)

        result = VerificationResult(
            bundle_id=f"{bundle.get('token_id', 'unknown')}_{bundle.get('t0', 0)}",
            token_id=bundle.get('token_id', ''),
            t0=bundle.get('t0', 0),
            verified_at=now,
            expected_hash=expected_hash,
        )

        try:
            # 1. Hash integrity check
            self._check_hash(bundle, expected_hash, result)

            # 2. Schema completeness
            self._check_schema(bundle, result)

            # 3. Timestamp consistency
            self._check_timestamps(bundle, result)

            # 4. Sequence continuity
            self._check_sequence(bundle, result)

            # 5. Provenance (optional)
            if check_provenance:
                self._check_provenance(bundle, result)

        except Exception as e:
            result.errors.append(f"Verification error: {str(e)}")
            result.overall_status = VerificationStatus.ERROR

        # Calculate totals
        result.checks_total = len(result.checks)
        result.checks_passed = sum(1 for c in result.checks if c.status == VerificationStatus.PASS)
        result.checks_failed = sum(1 for c in result.checks if c.status == VerificationStatus.FAIL)

        # Determine overall status
        if result.errors:
            result.overall_status = VerificationStatus.ERROR
        elif result.checks_failed > 0 or not result.hash_matches:
            result.overall_status = VerificationStatus.FAIL
        else:
            result.overall_status = VerificationStatus.PASS

        return result

    def _check_hash(self, bundle: Dict, expected: str, result: VerificationResult):
        """Check hash integrity"""
        computed = compute_bundle_hash(bundle)
        result.computed_hash = computed
        result.hash_matches = (computed == expected)

        check = VerificationCheck(
            check_name="hash_integrity",
            status=VerificationStatus.PASS if result.hash_matches else VerificationStatus.FAIL,
            expected=expected,
            actual=computed,
            message="Hash matches" if result.hash_matches else "Hash mismatch - bundle may be tampered"
        )
        result.checks.append(check)

    def _check_schema(self, bundle: Dict, result: VerificationResult):
        """Check schema completeness"""
        missing = []
        for field in self.required_fields:
            if field not in bundle:
                missing.append(field)

        check = VerificationCheck(
            check_name="schema_completeness",
            status=VerificationStatus.PASS if not missing else VerificationStatus.FAIL,
            expected=self.required_fields,
            actual=list(bundle.keys()),
            message="All required fields present" if not missing else f"Missing fields: {missing}"
        )
        result.checks.append(check)

    def _check_timestamps(self, bundle: Dict, result: VerificationResult):
        """Check timestamp consistency"""
        window = bundle.get('window', {})
        from_ts = window.get('from_ts', 0)
        to_ts = window.get('to_ts', 0)

        # Check trades are within window
        trades = bundle.get('trades', [])
        out_of_bounds = []

        for i, trade in enumerate(trades):
            ts = trade.get('ts', 0)
            if ts < from_ts or ts > to_ts:
                out_of_bounds.append(i)

        check = VerificationCheck(
            check_name="timestamp_consistency",
            status=VerificationStatus.PASS if not out_of_bounds else VerificationStatus.FAIL,
            expected=f"All events within [{from_ts}, {to_ts}]",
            actual=f"{len(out_of_bounds)} events out of bounds",
            message="All events within window" if not out_of_bounds else f"Events out of window: {out_of_bounds[:5]}..."
        )
        result.checks.append(check)

    def _check_sequence(self, bundle: Dict, result: VerificationResult):
        """Check sequence continuity"""
        trades = bundle.get('trades', [])

        # Check timestamps are monotonically increasing
        out_of_order = []
        prev_ts = 0

        for i, trade in enumerate(trades):
            ts = trade.get('ts', 0)
            if ts < prev_ts:
                out_of_order.append((i, prev_ts, ts))
            prev_ts = ts

        check = VerificationCheck(
            check_name="sequence_continuity",
            status=VerificationStatus.PASS if not out_of_order else VerificationStatus.FAIL,
            expected="Monotonically increasing timestamps",
            actual=f"{len(out_of_order)} out of order" if out_of_order else "All in order",
            message="Sequence is continuous" if not out_of_order else f"Out of order at: {out_of_order[:3]}"
        )
        result.checks.append(check)

    def _check_provenance(self, bundle: Dict, result: VerificationResult):
        """Check provenance information"""
        provenance = bundle.get('provenance', {})

        has_engine_version = 'engine_version' in provenance
        has_config_hash = 'config_hash' in provenance

        if not provenance:
            # Provenance might be at top level for older bundles
            has_engine_version = 'engine_version' in bundle
            has_config_hash = 'config_hash' in bundle

        check = VerificationCheck(
            check_name="provenance_validity",
            status=VerificationStatus.PASS if (has_engine_version and has_config_hash) else VerificationStatus.FAIL,
            expected="engine_version and config_hash present",
            actual={
                'has_engine_version': has_engine_version,
                'has_config_hash': has_config_hash,
            },
            message="Provenance complete" if (has_engine_version and has_config_hash) else "Missing provenance fields"
        )
        result.checks.append(check)

    def batch_verify(
        self,
        bundles: List[Dict[str, Any]],
        expected_hashes: List[str]
    ) -> List[VerificationResult]:
        """
        Batch verify multiple bundles.

        Args:
            bundles: List of evidence bundles
            expected_hashes: Corresponding expected hashes

        Returns:
            List of VerificationResult
        """
        results = []
        for bundle, expected in zip(bundles, expected_hashes):
            result = self.verify(bundle, expected)
            results.append(result)
        return results

    def generate_report(self, results: List[VerificationResult]) -> str:
        """Generate human-readable audit report"""
        lines = [
            "=" * 60,
            "EVIDENCE BUNDLE VERIFICATION REPORT",
            f"Generated: {datetime.now().isoformat()}",
            "=" * 60,
            "",
        ]

        passed = sum(1 for r in results if r.overall_status == VerificationStatus.PASS)
        failed = sum(1 for r in results if r.overall_status == VerificationStatus.FAIL)
        errors = sum(1 for r in results if r.overall_status == VerificationStatus.ERROR)

        lines.append(f"Summary: {passed} passed, {failed} failed, {errors} errors")
        lines.append("")

        for i, result in enumerate(results, 1):
            status_icon = "✓" if result.overall_status == VerificationStatus.PASS else "✗"
            lines.append(f"{status_icon} Bundle {i}: {result.bundle_id}")
            lines.append(f"   Token: {result.token_id}")
            lines.append(f"   T0: {result.t0}")
            lines.append(f"   Hash: {result.computed_hash[:16]}...")
            lines.append(f"   Status: {result.overall_status.value}")

            if result.overall_status != VerificationStatus.PASS:
                for check in result.checks:
                    if check.status == VerificationStatus.FAIL:
                        lines.append(f"   - FAIL: {check.check_name}: {check.message}")

            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)
