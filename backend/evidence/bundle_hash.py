"""
Evidence Bundle Hash - Cryptographic verification for evidence bundles

Provides:
1. Compute bundle hash from evidence data
2. Cache bundle hashes for fast verification
3. Verify bundle integrity

Algorithm:
1. Normalize bundle data (sort keys, stable JSON serialization)
2. Compute xxHash64 of normalized data
3. Return hex digest

Usage:
    from backend.evidence.bundle_hash import compute_bundle_hash, verify_bundle

    # Compute hash
    bundle_hash = compute_bundle_hash(evidence_data)

    # Verify
    is_valid = verify_bundle(evidence_data, expected_hash)
"""

import json
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime
from decimal import Decimal


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _normalize_value(value: Any) -> Any:
    """Normalize a value for consistent hashing"""
    if isinstance(value, Decimal):
        # Round to 8 decimal places to avoid floating point issues
        return round(float(value), 8)
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return _normalize_dict(value)
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    return value


def _normalize_dict(d: Dict) -> Dict:
    """Recursively normalize a dictionary for consistent hashing"""
    return {k: _normalize_value(v) for k, v in sorted(d.items())}


def compute_bundle_hash(bundle: Dict[str, Any]) -> str:
    """
    Compute cryptographic hash of an evidence bundle.

    The bundle is normalized (sorted keys, consistent number formatting)
    before hashing to ensure reproducibility.

    Args:
        bundle: Evidence bundle dictionary containing:
            - token_id
            - t0
            - window
            - shocks
            - reactions
            - leading_events
            - belief_states
            - anchors
            - data_health

    Returns:
        64-character hex digest (xxHash64 style, using SHA256 truncated)
    """
    # Extract only the fields that matter for evidence integrity
    evidence_fields = [
        'token_id',
        't0',
        'window',
        'shocks',
        'reactions',
        'leading_events',
        'belief_states',
        'anchors',
    ]

    # Build normalized evidence dict
    normalized = {}
    for field in evidence_fields:
        if field in bundle:
            normalized[field] = _normalize_value(bundle[field])

    # Serialize to JSON with sorted keys
    json_str = json.dumps(normalized, sort_keys=True, cls=DecimalEncoder)

    # Compute hash (using SHA256, take first 16 bytes = 32 hex chars)
    # This mimics xxHash64 output format but uses a standard library
    hash_bytes = hashlib.sha256(json_str.encode('utf-8')).digest()

    # Return first 16 bytes as hex (64-bit equivalent)
    return hash_bytes[:8].hex()


def compute_bundle_hash_xxhash(bundle: Dict[str, Any]) -> str:
    """
    Compute bundle hash using xxhash (if available).
    Falls back to SHA256 if xxhash is not installed.

    Args:
        bundle: Evidence bundle dictionary

    Returns:
        16-character hex digest
    """
    try:
        import xxhash

        evidence_fields = [
            'token_id', 't0', 'window', 'shocks', 'reactions',
            'leading_events', 'belief_states', 'anchors',
        ]

        normalized = {}
        for field in evidence_fields:
            if field in bundle:
                normalized[field] = _normalize_value(bundle[field])

        json_str = json.dumps(normalized, sort_keys=True, cls=DecimalEncoder)
        return xxhash.xxh64(json_str.encode('utf-8')).hexdigest()

    except ImportError:
        # Fall back to SHA256
        return compute_bundle_hash(bundle)


def verify_bundle(bundle: Dict[str, Any], expected_hash: str) -> bool:
    """
    Verify that a bundle matches its expected hash.

    Args:
        bundle: Evidence bundle dictionary
        expected_hash: Expected hash value

    Returns:
        True if hashes match, False otherwise
    """
    computed = compute_bundle_hash(bundle)
    return computed == expected_hash


def create_bundle_id(token_id: str, t0: int) -> str:
    """
    Create a unique bundle ID for caching.

    Args:
        token_id: Token ID
        t0: Evidence window center timestamp (ms)

    Returns:
        Bundle ID string
    """
    return f"{token_id}:{t0}"


class BundleHashCache:
    """
    Cache for bundle hashes to avoid recomputation.

    Usage:
        cache = BundleHashCache(db_conn)

        # Get or compute hash
        hash_value = cache.get_or_compute(bundle)

        # Verify
        is_valid = cache.verify(bundle, expected_hash)
    """

    def __init__(self, db_conn=None):
        """
        Initialize cache.

        Args:
            db_conn: Optional database connection for persistent caching
        """
        self.db_conn = db_conn
        self._memory_cache: Dict[str, str] = {}

    def _get_from_db(self, bundle_id: str) -> Optional[str]:
        """Get cached hash from database"""
        if not self.db_conn:
            return None

        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT bundle_hash FROM evidence_bundles WHERE bundle_id = %s",
                    (bundle_id,)
                )
                row = cur.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def _save_to_db(self, bundle_id: str, token_id: str, t0: int,
                    window_from: int, window_to: int, bundle_hash: str,
                    shock_count: int = 0, reaction_count: int = 0,
                    leading_count: int = 0, state_count: int = 0):
        """Save hash to database cache"""
        if not self.db_conn:
            return

        try:
            with self.db_conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO evidence_bundles (
                        bundle_id, token_id, t0, window_from, window_to,
                        bundle_hash, shock_count, reaction_count,
                        leading_count, state_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (bundle_id) DO UPDATE SET
                        bundle_hash = EXCLUDED.bundle_hash,
                        shock_count = EXCLUDED.shock_count,
                        reaction_count = EXCLUDED.reaction_count,
                        leading_count = EXCLUDED.leading_count,
                        state_count = EXCLUDED.state_count
                """, (
                    bundle_id, token_id, t0, window_from, window_to,
                    bundle_hash, shock_count, reaction_count,
                    leading_count, state_count
                ))
                self.db_conn.commit()
        except Exception as e:
            print(f"[BUNDLE CACHE] Failed to save: {e}")

    def get_or_compute(self, bundle: Dict[str, Any]) -> str:
        """
        Get cached hash or compute and cache it.

        Args:
            bundle: Evidence bundle

        Returns:
            Bundle hash
        """
        token_id = bundle.get('token_id', '')
        t0 = bundle.get('t0', 0)
        bundle_id = create_bundle_id(token_id, t0)

        # Check memory cache
        if bundle_id in self._memory_cache:
            return self._memory_cache[bundle_id]

        # Check database cache
        cached = self._get_from_db(bundle_id)
        if cached:
            self._memory_cache[bundle_id] = cached
            return cached

        # Compute hash
        bundle_hash = compute_bundle_hash(bundle)

        # Cache it
        self._memory_cache[bundle_id] = bundle_hash

        # Save to database
        window = bundle.get('window', {})
        self._save_to_db(
            bundle_id=bundle_id,
            token_id=token_id,
            t0=t0,
            window_from=window.get('from_ts', 0),
            window_to=window.get('to_ts', 0),
            bundle_hash=bundle_hash,
            shock_count=len(bundle.get('shocks', [])),
            reaction_count=len(bundle.get('reactions', [])),
            leading_count=len(bundle.get('leading_events', [])),
            state_count=len(bundle.get('belief_states', []))
        )

        return bundle_hash

    def verify(self, bundle: Dict[str, Any], expected_hash: str) -> bool:
        """
        Verify bundle integrity against expected hash.

        Args:
            bundle: Evidence bundle
            expected_hash: Expected hash value

        Returns:
            True if valid, False otherwise
        """
        return verify_bundle(bundle, expected_hash)

    def clear_cache(self, token_id: str = None):
        """Clear memory cache"""
        if token_id:
            to_remove = [k for k in self._memory_cache if k.startswith(token_id)]
            for k in to_remove:
                del self._memory_cache[k]
        else:
            self._memory_cache.clear()


# Convenience functions
def get_bundle_hash(bundle: Dict[str, Any]) -> str:
    """Convenience function to get bundle hash"""
    return compute_bundle_hash(bundle)


def create_evidence_bundle_response(
    token_id: str,
    t0: int,
    window: Dict[str, int],
    market: Dict[str, Any],
    anchors: List[Dict],
    shocks: List[Dict],
    reactions: List[Dict],
    leading_events: List[Dict],
    belief_states: List[Dict],
    data_health: Dict[str, Any],
    tiles_manifest: Optional[Dict] = None,
    include_hash: bool = True
) -> Dict[str, Any]:
    """
    Create a complete evidence bundle response with hash.

    Args:
        token_id: Token ID
        t0: Evidence window center
        window: Time window {from_ts, to_ts}
        market: Market info
        anchors: Anchor levels
        shocks: Shock events
        reactions: Reaction events
        leading_events: Leading events
        belief_states: Belief state changes
        data_health: Data health metrics
        tiles_manifest: Optional tiles manifest
        include_hash: Whether to compute and include bundle hash

    Returns:
        Complete evidence bundle response
    """
    bundle = {
        'token_id': token_id,
        't0': t0,
        'window': window,
        'market': market,
        'anchors': anchors,
        'shocks': shocks,
        'reactions': reactions,
        'leading_events': leading_events,
        'belief_states': belief_states,
        'data_health': data_health,
    }

    if tiles_manifest:
        bundle['tiles_manifest'] = tiles_manifest

    if include_hash:
        bundle['bundle_hash'] = compute_bundle_hash(bundle)

    return bundle
