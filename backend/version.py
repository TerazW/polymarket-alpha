"""
Belief Reaction System - Version and Config Management

Provides:
1. ENGINE_VERSION - Semantic version of the collector engine
2. CONFIG_HASH - MD5 hash of poc/config.py for reproducibility
3. Config snapshot management for auditability

Usage:
    from backend.version import ENGINE_VERSION, CONFIG_HASH, get_version_info

    # Get version info
    info = get_version_info()
    print(info['engine_version'])  # "v4.1.0"
    print(info['config_hash'])     # "a1b2c3d4e5f6..."
"""

import os
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime

# =============================================================================
# Engine Version
# =============================================================================
# Semantic versioning: MAJOR.MINOR.PATCH
# - MAJOR: Breaking changes to detection logic
# - MINOR: New features (e.g., new reaction types, leading events)
# - PATCH: Bug fixes, performance improvements

ENGINE_VERSION = "v4.1.0"

# Version history:
# v4.1.0 - Evidence auditability (engine_version, config_hash, raw_event_seq)
# v4.0.0 - 250ms time bucket sampling, server timestamp, raw_events table
# v3.0.0 - Dual window (FAST/SLOW), 7 reaction types, 3 leading events
# v2.0.0 - baseline_size median, absolute thresholds
# v1.0.0 - Initial shock detection and reaction classification


# =============================================================================
# Config Hash Calculation
# =============================================================================

def _get_config_path() -> str:
    """Get the path to poc/config.py"""
    # Go up from backend/version.py to project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "poc", "config.py")


def _calculate_config_hash() -> str:
    """Calculate MD5 hash of poc/config.py"""
    config_path = _get_config_path()

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    except FileNotFoundError:
        return "config_not_found"
    except Exception as e:
        return f"error_{str(e)[:20]}"


def _get_config_content() -> Optional[str]:
    """Get the content of poc/config.py"""
    config_path = _get_config_path()

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


# Calculate config hash at import time (cached)
CONFIG_HASH = _calculate_config_hash()


# =============================================================================
# Version Info Functions
# =============================================================================

def get_version_info() -> Dict[str, Any]:
    """
    Get complete version information.

    Returns:
        dict with engine_version, config_hash, and metadata
    """
    return {
        'engine_version': ENGINE_VERSION,
        'config_hash': CONFIG_HASH,
        'config_path': _get_config_path(),
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    }


def save_config_snapshot(db_conn) -> bool:
    """
    Save current config to config_snapshots table if not already exists.

    Args:
        db_conn: Database connection

    Returns:
        True if saved (new config), False if already exists
    """
    content = _get_config_content()
    if content is None:
        return False

    try:
        with db_conn.cursor() as cur:
            # Check if this config_hash already exists
            cur.execute(
                "SELECT 1 FROM config_snapshots WHERE config_hash = %s",
                (CONFIG_HASH,)
            )
            if cur.fetchone():
                return False

            # Insert new config snapshot
            cur.execute("""
                INSERT INTO config_snapshots (config_hash, engine_version, config_content)
                VALUES (%s, %s, %s)
                ON CONFLICT (config_hash) DO NOTHING
            """, (CONFIG_HASH, ENGINE_VERSION, content))
            db_conn.commit()
            return True

    except Exception as e:
        print(f"[VERSION] Failed to save config snapshot: {e}")
        return False


def validate_config_hash(db_conn, expected_hash: str) -> bool:
    """
    Validate that a config_hash exists in config_snapshots.

    Args:
        db_conn: Database connection
        expected_hash: The config hash to validate

    Returns:
        True if found, False otherwise
    """
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM config_snapshots WHERE config_hash = %s",
                (expected_hash,)
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def get_config_for_hash(db_conn, config_hash: str) -> Optional[str]:
    """
    Retrieve config content for a given hash.

    Args:
        db_conn: Database connection
        config_hash: The config hash to look up

    Returns:
        Config content if found, None otherwise
    """
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT config_content FROM config_snapshots WHERE config_hash = %s",
                (config_hash,)
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception:
        return None


# =============================================================================
# Provenance Tracking
# =============================================================================

class RawEventSequenceTracker:
    """
    Tracks raw_event sequence numbers for provenance.

    Usage:
        tracker = RawEventSequenceTracker()

        # When saving raw_event, get its seq
        seq = tracker.record_seq(seq_from_db)

        # When generating shock event
        shock.raw_event_seq_start = tracker.get_range_start(token_id)
        shock.raw_event_seq_end = tracker.get_range_end(token_id)
    """

    def __init__(self):
        # {token_id: [seq_numbers]}
        self._sequences: Dict[str, list] = {}
        # Rolling window size (keep last N sequences)
        self._window_size = 1000

    def record_seq(self, token_id: str, seq: int):
        """Record a sequence number for a token"""
        if token_id not in self._sequences:
            self._sequences[token_id] = []

        self._sequences[token_id].append(seq)

        # Trim to window size
        if len(self._sequences[token_id]) > self._window_size:
            self._sequences[token_id] = self._sequences[token_id][-self._window_size:]

    def get_range_for_window(self, token_id: str, from_ts_ms: int, to_ts_ms: int,
                             ts_to_seq: Dict[int, int]) -> tuple:
        """
        Get sequence range for a time window.

        Args:
            token_id: Token ID
            from_ts_ms: Window start (ms)
            to_ts_ms: Window end (ms)
            ts_to_seq: Mapping from timestamp to sequence

        Returns:
            (seq_start, seq_end) tuple
        """
        if token_id not in self._sequences or not self._sequences[token_id]:
            return (None, None)

        seqs = self._sequences[token_id]
        return (seqs[0], seqs[-1]) if seqs else (None, None)

    def get_last_n(self, token_id: str, n: int = 10) -> list:
        """Get last N sequence numbers"""
        if token_id not in self._sequences:
            return []
        return self._sequences[token_id][-n:]

    def clear(self, token_id: str = None):
        """Clear sequences for a token or all tokens"""
        if token_id:
            self._sequences.pop(token_id, None)
        else:
            self._sequences.clear()


# Global sequence tracker
raw_event_tracker = RawEventSequenceTracker()
