/**
 * Safe Evidence Fetch Hook
 *
 * Prevents request storms with:
 * - In-flight guard (only one request at a time)
 * - Debounce (wait before fetching on param changes)
 * - 429 backoff (respect Retry-After header)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { getEvidence, ApiError, type EvidenceResponse } from '@/lib/api';

interface UseEvidenceFetchParams {
  tokenId: string;
  t0: number;
  windowBeforeMs?: number;
  windowAfterMs?: number;
  debounceMs?: number;
}

interface UseEvidenceFetchResult {
  evidence: EvidenceResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useEvidenceFetch({
  tokenId,
  t0,
  windowBeforeMs = 60000,
  windowAfterMs = 30000,
  debounceMs = 300,
}: UseEvidenceFetchParams): UseEvidenceFetchResult {
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // In-flight guard
  const inflightRef = useRef(false);
  // Backoff timer (for 429)
  const backoffUntilRef = useRef(0);
  // Abort controller for cancellation
  const abortControllerRef = useRef<AbortController | null>(null);
  // Track if component is mounted
  const mountedRef = useRef(true);

  const fetchEvidence = useCallback(async () => {
    // Check backoff period
    const now = Date.now();
    if (now < backoffUntilRef.current) {
      console.log(`[EvidenceFetch] Backing off until ${new Date(backoffUntilRef.current).toISOString()}`);
      return;
    }

    // Check in-flight
    if (inflightRef.current) {
      console.log('[EvidenceFetch] Request already in flight, skipping');
      return;
    }

    // Cancel previous request if any
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    inflightRef.current = true;
    setLoading(true);
    setError(null);

    try {
      const data = await getEvidence({
        token_id: tokenId,
        t0,
        window_before_ms: windowBeforeMs,
        window_after_ms: windowAfterMs,
      });

      if (mountedRef.current) {
        setEvidence(data);
        setError(null);
      }
    } catch (err) {
      if (!mountedRef.current) return;

      if (err instanceof ApiError) {
        if (err.status === 429 && err.retryAfter) {
          // Set backoff period
          backoffUntilRef.current = Date.now() + err.retryAfter * 1000;
          console.warn(`[EvidenceFetch] Rate limited, backing off for ${err.retryAfter}s`);
          setError(`Rate limited. Please wait ${err.retryAfter}s`);
        } else {
          setError(err.message);
        }
      } else {
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
      inflightRef.current = false;
    }
  }, [tokenId, t0, windowBeforeMs, windowAfterMs]);

  // Debounced fetch on param changes
  useEffect(() => {
    mountedRef.current = true;

    // Skip if no tokenId
    if (!tokenId) return;

    const timeoutId = setTimeout(() => {
      fetchEvidence();
    }, debounceMs);

    return () => {
      clearTimeout(timeoutId);
      // Don't set mounted to false on every cleanup - only on unmount
    };
  }, [tokenId, t0, windowBeforeMs, windowAfterMs, debounceMs, fetchEvidence]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const refetch = useCallback(() => {
    // Clear backoff on manual refetch
    backoffUntilRef.current = 0;
    fetchEvidence();
  }, [fetchEvidence]);

  return { evidence, loading, error, refetch };
}
