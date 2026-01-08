#!/usr/bin/env python3
"""
Belief Reaction System - Replay CLI
Command-line tools for evidence bundle verification and audit.

Usage:
    python -m backend.replay.cli verify --bundle-hash abc123 --token test-token --t0 1704067200000
    python -m backend.replay.cli batch-verify --input bundles.json --output report.txt
    python -m backend.replay.cli audit --token test-token --from-ts 1704000000000 --to-ts 1705000000000

"每一个证据包都可验证、可追溯、可复现"
"""

import argparse
import json
import sys
from datetime import datetime
from typing import Optional

from .engine import ReplayEngine, ReplayStatus
from .verifier import BundleVerifier, VerificationStatus


def cmd_verify(args):
    """Verify a single bundle"""
    print(f"\n{'='*60}")
    print("EVIDENCE BUNDLE VERIFICATION")
    print(f"{'='*60}\n")

    # Load bundle from file or database
    bundle = None

    if args.bundle_file:
        with open(args.bundle_file) as f:
            bundle = json.load(f)
    elif args.bundle_json:
        bundle = json.loads(args.bundle_json)
    else:
        print("ERROR: Must provide --bundle-file or --bundle-json")
        sys.exit(1)

    expected_hash = args.bundle_hash

    # Verify
    verifier = BundleVerifier()
    result = verifier.verify(bundle, expected_hash, check_provenance=not args.skip_provenance)

    # Output
    print(f"Token ID:  {result.token_id}")
    print(f"T0:        {result.t0}")
    print(f"Verified:  {datetime.fromtimestamp(result.verified_at/1000).isoformat()}")
    print()
    print(f"Expected Hash: {result.expected_hash}")
    print(f"Computed Hash: {result.computed_hash}")
    print(f"Hash Match:    {'YES ✓' if result.hash_matches else 'NO ✗'}")
    print()
    print(f"Checks: {result.checks_passed}/{result.checks_total} passed")
    print()

    for check in result.checks:
        status_icon = "✓" if check.status == VerificationStatus.PASS else "✗"
        print(f"  {status_icon} {check.check_name}: {check.message}")

    print()
    print(f"OVERALL: {result.overall_status.value}")

    if args.output:
        with open(args.output, 'w') as f:
            f.write(result.to_json())
        print(f"\nDetailed result saved to: {args.output}")

    # Exit code
    if result.overall_status == VerificationStatus.PASS:
        print("\n✓ Verification PASSED")
        sys.exit(0)
    else:
        print("\n✗ Verification FAILED")
        sys.exit(1)


def cmd_replay(args):
    """Replay raw events and verify"""
    print(f"\n{'='*60}")
    print("REPLAY VERIFICATION")
    print(f"{'='*60}\n")

    # Load raw events
    if not args.events_file:
        print("ERROR: Must provide --events-file")
        sys.exit(1)

    with open(args.events_file) as f:
        raw_events = json.load(f)

    # Replay
    engine = ReplayEngine(checkpoint_interval=args.checkpoint_interval)
    result = engine.replay(
        raw_events=raw_events,
        expected_hash=args.bundle_hash,
        token_id=args.token,
        t0=args.t0,
        window_ms=args.window_ms
    )

    # Output
    print(f"Token ID:     {result.token_id}")
    print(f"T0:           {result.t0}")
    print(f"Events:       {result.events_count}")
    print(f"Duration:     {result.duration_ms}ms")
    print()
    print(f"Expected Hash: {result.expected_hash}")
    print(f"Computed Hash: {result.computed_hash}")
    print(f"Hash Match:    {'YES ✓' if result.hash_matches else 'NO ✗'}")
    print()
    print(f"Reconstructed:")
    print(f"  Shocks:     {result.shocks_detected}")
    print(f"  Reactions:  {result.reactions_classified}")
    print(f"  State Changes: {result.state_changes}")
    print(f"  Checkpoints: {len(result.checkpoints)}")
    print()
    print(f"STATUS: {result.status.value}")

    if result.error:
        print(f"ERROR: {result.error}")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"\nDetailed result saved to: {args.output}")

    # Exit code
    if result.status == ReplayStatus.HASH_MATCH:
        print("\n✓ Replay verification PASSED")
        sys.exit(0)
    else:
        print("\n✗ Replay verification FAILED")
        sys.exit(1)


def cmd_batch_verify(args):
    """Batch verify multiple bundles"""
    print(f"\n{'='*60}")
    print("BATCH VERIFICATION")
    print(f"{'='*60}\n")

    # Load batch input
    with open(args.input) as f:
        batch = json.load(f)

    bundles = batch.get('bundles', [])
    hashes = batch.get('hashes', [])

    if len(bundles) != len(hashes):
        print(f"ERROR: Mismatched bundles ({len(bundles)}) and hashes ({len(hashes)})")
        sys.exit(1)

    print(f"Verifying {len(bundles)} bundles...\n")

    # Verify
    verifier = BundleVerifier()
    results = verifier.batch_verify(bundles, hashes)

    # Generate report
    report = verifier.generate_report(results)
    print(report)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"\nReport saved to: {args.output}")

    # Summary
    passed = sum(1 for r in results if r.overall_status == VerificationStatus.PASS)
    if passed == len(results):
        print(f"\n✓ All {len(results)} bundles PASSED")
        sys.exit(0)
    else:
        print(f"\n✗ {len(results) - passed} bundles FAILED")
        sys.exit(1)


def cmd_audit(args):
    """Run audit on a time range"""
    print(f"\n{'='*60}")
    print("AUDIT RUN")
    print(f"{'='*60}\n")

    print(f"Token: {args.token}")
    print(f"From:  {datetime.fromtimestamp(args.from_ts/1000).isoformat()}")
    print(f"To:    {datetime.fromtimestamp(args.to_ts/1000).isoformat()}")
    print()

    # TODO: Fetch bundles from database and verify
    print("NOTE: Database audit not yet implemented.")
    print("Use --bundle-file for manual verification.")
    print()

    # Placeholder for database integration
    # In production, this would:
    # 1. Query evidence_bundles table for time range
    # 2. For each bundle, verify hash and replay if needed
    # 3. Generate comprehensive audit report

    print("Use the following commands for manual verification:")
    print(f"  python -m backend.replay.cli verify --bundle-file <path> --bundle-hash <hash>")
    print(f"  python -m backend.replay.cli replay --events-file <path> --bundle-hash <hash> --token {args.token} --t0 <timestamp>")


def main():
    parser = argparse.ArgumentParser(
        description="Belief Reaction System - Evidence Replay & Audit CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify a bundle file
  python -m backend.replay.cli verify --bundle-file evidence.json --bundle-hash abc123

  # Replay raw events
  python -m backend.replay.cli replay --events-file events.json --bundle-hash abc123 --token test-token --t0 1704067200000

  # Batch verify
  python -m backend.replay.cli batch-verify --input bundles.json --output report.txt

  # Run audit (requires database)
  python -m backend.replay.cli audit --token test-token --from-ts 1704000000000 --to-ts 1705000000000
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # verify
    verify_parser = subparsers.add_parser('verify', help='Verify a single bundle')
    verify_parser.add_argument('--bundle-file', help='Path to bundle JSON file')
    verify_parser.add_argument('--bundle-json', help='Bundle as JSON string')
    verify_parser.add_argument('--bundle-hash', required=True, help='Expected hash')
    verify_parser.add_argument('--skip-provenance', action='store_true', help='Skip provenance check')
    verify_parser.add_argument('--output', '-o', help='Output file for detailed result')

    # replay
    replay_parser = subparsers.add_parser('replay', help='Replay raw events and verify')
    replay_parser.add_argument('--events-file', required=True, help='Path to raw events JSON')
    replay_parser.add_argument('--bundle-hash', required=True, help='Expected hash')
    replay_parser.add_argument('--token', required=True, help='Token ID')
    replay_parser.add_argument('--t0', required=True, type=int, help='Center timestamp (ms)')
    replay_parser.add_argument('--window-ms', type=int, default=60000, help='Window size (ms)')
    replay_parser.add_argument('--checkpoint-interval', type=int, default=100, help='Checkpoint interval')
    replay_parser.add_argument('--output', '-o', help='Output file for detailed result')

    # batch-verify
    batch_parser = subparsers.add_parser('batch-verify', help='Batch verify multiple bundles')
    batch_parser.add_argument('--input', required=True, help='Input JSON file with bundles and hashes')
    batch_parser.add_argument('--output', '-o', help='Output file for report')

    # audit
    audit_parser = subparsers.add_parser('audit', help='Run audit on time range')
    audit_parser.add_argument('--token', required=True, help='Token ID')
    audit_parser.add_argument('--from-ts', required=True, type=int, help='Start timestamp (ms)')
    audit_parser.add_argument('--to-ts', required=True, type=int, help='End timestamp (ms)')
    audit_parser.add_argument('--output', '-o', help='Output file for report')

    args = parser.parse_args()

    if args.command == 'verify':
        cmd_verify(args)
    elif args.command == 'replay':
        cmd_replay(args)
    elif args.command == 'batch-verify':
        cmd_batch_verify(args)
    elif args.command == 'audit':
        cmd_audit(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
