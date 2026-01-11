/**
 * Safe Evidence Fetch Hook
 *
 * Prevents request storms with:
 * - In-flight guard (only one request at a time)
 * - Debounce (wait before fetching on param changes)
 * - 429 backoff (respect Retry-After header)
 * - Stable dependency key (prevents infinite loops)
 * - Global singleton lock (prevents multiple instances from flooding)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { getEvidence, ApiError, type EvidenceResponse } from '@/lib/api';

// =============================================================================
// Module-level singleton guards (shared across all hook instances)
// =============================================================================
let globalInFlightKey: string | null = null;
let globalBackoffUntil = 0;

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

  // Refs for request management
  const inflightRef = useRef(false);
  const backoffUntilRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const retryTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Store params in ref to avoid stale closures
  const paramsRef = useRef({ tokenId, t0, windowBeforeMs, windowAfterMs });
  paramsRef.current = { tokenId, t0, windowBeforeMs, windowAfterMs };

  // Create a stable key for this fetch
  const getFetchKey = useCallback(() => {
    const params = paramsRef.current;
    return `${params.tokenId}|${params.t0}|${params.windowBeforeMs}|${params.windowAfterMs}`;
  }, []);

  // Stable fetch function that reads from ref
  const doFetch = useCallback(async () => {
    const params = paramsRef.current;
    const fetchKey = getFetchKey();
    // DEBUG: trace who is calling doFetch
    console.trace('[DEBUG] useEvidenceFetch.doFetch called', { fetchKey, tokenId: params.tokenId, t0: params.t0 });

    // Check GLOBAL backoff period (shared across all instances)
    const now = Date.now();
    if (now < globalBackoffUntil) {
      const waitTime = globalBackoffUntil - now;
      console.log(`[EvidenceFetch] GLOBAL backoff active, waiting ${waitTime}ms`);
      return;
    }

    // Check GLOBAL in-flight for same key (prevents duplicate fetches across instances)
    if (globalInFlightKey === fetchKey) {
      console.log('[EvidenceFetch] GLOBAL: Already fetching same key, skipping');
      return;
    }

    // Check local in-flight
    if (inflightRef.current) {
      console.log('[EvidenceFetch] Local: Request already in flight, skipping');
      return;
    }

    // Cancel previous request if any
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    // Set both local and global locks
    inflightRef.current = true;
    globalInFlightKey = fetchKey;
    setLoading(true);
    setError(null);

    console.log('[EvidenceFetch] Fetching:', params.tokenId, 't0:', params.t0);

    try {
      const data = await getEvidence(
        {
          token_id: params.tokenId,
          t0: params.t0,
          window_before_ms: params.windowBeforeMs,
          window_after_ms: params.windowAfterMs,
        },
        abortControllerRef.current.signal
      );

      if (mountedRef.current) {
        console.log('[EvidenceFetch] Success');
        setEvidence(data);
        setError(null);
      }
    } catch (err) {
      if (!mountedRef.current) return;

      if (err instanceof ApiError) {
        // Ignore aborted requests
        if (err.status === -1) {
          console.log('[EvidenceFetch] Request aborted');
          return;
        }
        if (err.status === 429 && err.retryAfter) {
          // Set GLOBAL backoff period (shared across all instances)
          globalBackoffUntil = Date.now() + err.retryAfter * 1000;
          console.warn(`[EvidenceFetch] Rate limited, GLOBAL backoff for ${err.retryAfter}s`);
          setError(`Rate limited. Please wait ${err.retryAfter}s`);
        } else {
          console.error('[EvidenceFetch] API error:', err.status, err.message);
          setError(err.message);
        }
      } else {
        console.error('[EvidenceFetch] Unknown error:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
      inflightRef.current = false;
      // Clear global lock only if it's still our key
      if (globalInFlightKey === fetchKey) {
        globalInFlightKey = null;
      }
    }
  }, [getFetchKey]); // Only depends on getFetchKey which is stable

  // Create a stable key for dependency tracking
  const fetchKey = `${tokenId}|${t0}|${windowBeforeMs}|${windowAfterMs}`;

  // Effect that runs on key change (debounced)
  useEffect(() => {
    mountedRef.current = true;

    // Skip if no tokenId
    if (!tokenId) {
      setLoading(false);
      return;
    }

    console.log('[EvidenceFetch] Key changed:', fetchKey);

    // Clear any existing retry timer
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }

    // Cancel any in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Reset state
    inflightRef.current = false;

    // Debounced fetch
    const timeoutId = setTimeout(() => {
      doFetch();
    }, debounceMs);

    return () => {
      clearTimeout(timeoutId);
    };
  }, [fetchKey, debounceMs, doFetch]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
      }
    };
  }, []);

  // Manual refetch
  const refetch = useCallback(() => {
    // Clear backoff on manual refetch
    backoffUntilRef.current = 0;
    // Clear any pending timer
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    doFetch();
  }, [doFetch]);

  return { evidence, loading, error, refetch };
}
