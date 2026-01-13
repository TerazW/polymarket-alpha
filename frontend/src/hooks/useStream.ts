/**
 * Belief Reaction System - Real-time Stream Hook
 * v5.9: WebSocket connection for live events
 * v5.43: Fixed connection storm caused by unstable dependencies
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { getStreamUrl } from '@/lib/api';

// =============================================================================
// Types
// =============================================================================

export type StreamEventType =
  | 'shock'
  | 'reaction'
  | 'leading_event'
  | 'belief_state'
  | 'alert.new'
  | 'alert.updated'
  | 'alert.resolved'
  | 'tile.ready'
  | 'data.gap'
  | 'hash.mismatch'
  | 'heartbeat'
  | 'subscription.confirmed'
  | 'error';

export interface StreamMessage<T = unknown> {
  type: StreamEventType;
  ts: number;
  token_id?: string;
  payload: T;
}

export interface ShockPayload {
  id: string;
  token_id: string;
  ts: number;
  price: number;
  side: 'BID' | 'ASK';
  trade_vol?: number;
  baseline_size?: number;
  trigger: 'VOLUME' | 'CONSECUTIVE' | 'BOTH';
}

export interface ReactionPayload {
  id: string;
  token_id: string;
  shock_id?: string;
  ts_start: number;
  ts_end: number;
  reaction: string;
  side: 'BID' | 'ASK';
  price: number;
}

export interface BeliefStatePayload {
  token_id: string;
  old_state: string;
  new_state: string;
  ts: number;
}

export interface AlertPayload {
  alert_id: string;
  token_id: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status: 'OPEN' | 'ACKED' | 'RESOLVED' | 'MUTED';
  type?: string;
  summary: string;
  disclaimer?: string;
  ts?: number;
  acked_at?: number;
  resolved_at?: number;
  muted_at?: number;
  muted_until?: number;
}

export interface SubscriptionOptions {
  tokenIds?: string[];
  eventTypes?: StreamEventType[];
  minSeverity?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
}

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

// =============================================================================
// Hook
// =============================================================================

export interface UseStreamOptions {
  /** Auto-connect on mount (default: true) */
  autoConnect?: boolean;
  /** Reconnect on disconnect (default: true) */
  autoReconnect?: boolean;
  /** Max reconnect attempts (default: 5) */
  maxReconnectAttempts?: number;
  /** Initial subscription options */
  subscription?: SubscriptionOptions;
  /** Event handlers */
  onShock?: (payload: ShockPayload) => void;
  onReaction?: (payload: ReactionPayload) => void;
  onBeliefState?: (payload: BeliefStatePayload) => void;
  onAlert?: (payload: AlertPayload, eventType: 'alert.new' | 'alert.updated' | 'alert.resolved') => void;
  onMessage?: (message: StreamMessage) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

export interface UseStreamReturn {
  /** Current connection state */
  connectionState: ConnectionState;
  /** Whether connected */
  isConnected: boolean;
  /** Number of active connections (from heartbeat) */
  connectionCount: number;
  /** Last received message */
  lastMessage: StreamMessage | null;
  /** Connect to stream */
  connect: () => void;
  /** Disconnect from stream */
  disconnect: () => void;
  /** Update subscription */
  subscribe: (options: SubscriptionOptions) => void;
}

export function useStream(options: UseStreamOptions = {}): UseStreamReturn {
  const {
    autoConnect = true,
    autoReconnect = true,
    maxReconnectAttempts = 5,
    subscription,
  } = options;

  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [connectionCount, setConnectionCount] = useState(0);
  const [lastMessage, setLastMessage] = useState<StreamMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const mountedRef = useRef(true);

  // Store handlers in refs to avoid dependency changes
  const handlersRef = useRef(options);
  handlersRef.current = options;

  // Store subscription in ref for stable access
  const subscriptionRef = useRef(subscription);
  subscriptionRef.current = subscription;

  // Stable message handler that reads from ref
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const message: StreamMessage = JSON.parse(event.data);
      setLastMessage(message);

      const handlers = handlersRef.current;

      // Call general message handler
      handlers.onMessage?.(message);

      // Route to specific handlers
      switch (message.type) {
        case 'shock':
          handlers.onShock?.(message.payload as ShockPayload);
          break;
        case 'reaction':
          handlers.onReaction?.(message.payload as ReactionPayload);
          break;
        case 'belief_state':
          handlers.onBeliefState?.(message.payload as BeliefStatePayload);
          break;
        case 'alert.new':
        case 'alert.updated':
        case 'alert.resolved':
          handlers.onAlert?.(message.payload as AlertPayload, message.type);
          break;
        case 'heartbeat':
          setConnectionCount((message.payload as { connections: number }).connections);
          break;
        case 'subscription.confirmed':
          console.log('[STREAM] Subscription confirmed:', message.payload);
          break;
        case 'error':
          console.error('[STREAM] Error from server:', message.payload);
          break;
      }
    } catch (e) {
      console.error('[STREAM] Failed to parse message:', e);
    }
  }, []); // No deps - reads from handlersRef

  // Stable connect function
  const connect = useCallback(() => {
    // DEBUG: trace who is calling connect
    console.trace('[DEBUG] useStream.connect called', { readyState: wsRef.current?.readyState });
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      console.log('[DEBUG] useStream.connect: already OPEN or CONNECTING, skipping');
      return;
    }

    if (!mountedRef.current) return;

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    setConnectionState('connecting');

    const ws = new WebSocket(getStreamUrl());

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close();
        return;
      }

      setConnectionState('connected');
      reconnectAttemptsRef.current = 0;
      handlersRef.current.onConnect?.();

      // Send initial subscription if provided
      const sub = subscriptionRef.current;
      if (sub) {
        ws.send(JSON.stringify({
          action: 'subscribe',
          token_ids: sub.tokenIds,
          event_types: sub.eventTypes,
          min_severity: sub.minSeverity,
        }));
      }
    };

    ws.onmessage = handleMessage;

    ws.onclose = () => {
      if (!mountedRef.current) return;

      setConnectionState('disconnected');
      handlersRef.current.onDisconnect?.();

      // Auto reconnect logic
      if (autoReconnect && reconnectAttemptsRef.current < maxReconnectAttempts && mountedRef.current) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
        reconnectAttemptsRef.current++;
        setConnectionState('reconnecting');

        reconnectTimeoutRef.current = setTimeout(() => {
          if (mountedRef.current) {
            connect();
          }
        }, delay);
      }
    };

    ws.onerror = (error) => {
      console.error('[STREAM] WebSocket error:', error);
      handlersRef.current.onError?.(error);
    };

    wsRef.current = ws;
  }, [handleMessage, autoReconnect, maxReconnectAttempts]); // Stable deps only

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    reconnectAttemptsRef.current = maxReconnectAttempts; // Prevent auto-reconnect

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setConnectionState('disconnected');
  }, [maxReconnectAttempts]);

  const subscribe = useCallback((newOptions: SubscriptionOptions) => {
    subscriptionRef.current = newOptions;
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'subscribe',
        token_ids: newOptions.tokenIds,
        event_types: newOptions.eventTypes,
        min_severity: newOptions.minSeverity,
      }));
    }
  }, []);

  // Auto-connect on mount - use a stable key instead of connect function
  const autoConnectKey = autoConnect ? 'auto' : 'manual';

  useEffect(() => {
    mountedRef.current = true;

    if (autoConnect) {
      connect();
    }

    return () => {
      mountedRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [autoConnectKey]); // Only depend on the key, not the connect function

  return {
    connectionState,
    isConnected: connectionState === 'connected',
    connectionCount,
    lastMessage,
    connect,
    disconnect,
    subscribe,
  };
}

// =============================================================================
// Simple hook for specific token
// =============================================================================

export function useTokenStream(
  tokenId: string,
  handlers: {
    onShock?: (payload: ShockPayload) => void;
    onReaction?: (payload: ReactionPayload) => void;
    onBeliefState?: (payload: BeliefStatePayload) => void;
    onAlert?: (payload: AlertPayload) => void;
  }
): UseStreamReturn {
  // Store handlers in ref to prevent reconnection on handler change
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  // Create stable handlers that read from ref
  const stableHandlers = useRef({
    onShock: (payload: ShockPayload) => handlersRef.current.onShock?.(payload),
    onReaction: (payload: ReactionPayload) => handlersRef.current.onReaction?.(payload),
    onBeliefState: (payload: BeliefStatePayload) => handlersRef.current.onBeliefState?.(payload),
    onAlert: (payload: AlertPayload) => handlersRef.current.onAlert?.(payload),
  }).current;

  return useStream({
    subscription: {
      tokenIds: tokenId ? [tokenId] : [],
    },
    onShock: stableHandlers.onShock,
    onReaction: stableHandlers.onReaction,
    onBeliefState: stableHandlers.onBeliefState,
    onAlert: (payload) => stableHandlers.onAlert(payload),
    autoConnect: !!tokenId, // Only connect if tokenId is provided
  });
}

// =============================================================================
// Hook for alerts only
// =============================================================================

export function useAlertStream(
  options: {
    minSeverity?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
    onNewAlert?: (payload: AlertPayload) => void;
    onAlertUpdated?: (payload: AlertPayload) => void;
    onAlertResolved?: (payload: AlertPayload) => void;
  }
): UseStreamReturn {
  // Store handlers in ref to prevent reconnection on handler change
  const handlersRef = useRef(options);
  handlersRef.current = options;

  return useStream({
    subscription: {
      eventTypes: ['alert.new', 'alert.updated', 'alert.resolved'],
      minSeverity: options.minSeverity,
    },
    onAlert: (payload, eventType) => {
      const handlers = handlersRef.current;
      switch (eventType) {
        case 'alert.new':
          handlers.onNewAlert?.(payload);
          break;
        case 'alert.updated':
          handlers.onAlertUpdated?.(payload);
          break;
        case 'alert.resolved':
          handlers.onAlertResolved?.(payload);
          break;
      }
    },
  });
}
