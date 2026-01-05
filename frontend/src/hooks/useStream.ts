/**
 * Belief Reaction System - Real-time Stream Hook
 * v5.9: WebSocket connection for live events
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
  status: 'OPEN' | 'ACKED' | 'RESOLVED';
  summary: string;
  ts?: number;
  acked_at?: number;
  resolved_at?: number;
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
    onShock,
    onReaction,
    onBeliefState,
    onAlert,
    onMessage,
    onConnect,
    onDisconnect,
    onError,
  } = options;

  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [connectionCount, setConnectionCount] = useState(0);
  const [lastMessage, setLastMessage] = useState<StreamMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const message: StreamMessage = JSON.parse(event.data);
      setLastMessage(message);

      // Call general message handler
      onMessage?.(message);

      // Route to specific handlers
      switch (message.type) {
        case 'shock':
          onShock?.(message.payload as ShockPayload);
          break;
        case 'reaction':
          onReaction?.(message.payload as ReactionPayload);
          break;
        case 'belief_state':
          onBeliefState?.(message.payload as BeliefStatePayload);
          break;
        case 'alert.new':
        case 'alert.updated':
        case 'alert.resolved':
          onAlert?.(message.payload as AlertPayload, message.type);
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
  }, [onShock, onReaction, onBeliefState, onAlert, onMessage]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    setConnectionState('connecting');

    const ws = new WebSocket(getStreamUrl());

    ws.onopen = () => {
      setConnectionState('connected');
      reconnectAttemptsRef.current = 0;
      onConnect?.();

      // Send initial subscription if provided
      if (subscription) {
        ws.send(JSON.stringify({
          action: 'subscribe',
          token_ids: subscription.tokenIds,
          event_types: subscription.eventTypes,
          min_severity: subscription.minSeverity,
        }));
      }
    };

    ws.onmessage = handleMessage;

    ws.onclose = () => {
      setConnectionState('disconnected');
      onDisconnect?.();

      // Auto reconnect logic
      if (autoReconnect && reconnectAttemptsRef.current < maxReconnectAttempts) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
        reconnectAttemptsRef.current++;
        setConnectionState('reconnecting');

        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      }
    };

    ws.onerror = (error) => {
      console.error('[STREAM] WebSocket error:', error);
      onError?.(error);
    };

    wsRef.current = ws;
  }, [handleMessage, subscription, autoReconnect, maxReconnectAttempts, onConnect, onDisconnect, onError]);

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

  const subscribe = useCallback((options: SubscriptionOptions) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'subscribe',
        token_ids: options.tokenIds,
        event_types: options.eventTypes,
        min_severity: options.minSeverity,
      }));
    }
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [autoConnect, connect]);

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
  return useStream({
    subscription: {
      tokenIds: [tokenId],
    },
    onShock: handlers.onShock,
    onReaction: handlers.onReaction,
    onBeliefState: handlers.onBeliefState,
    onAlert: handlers.onAlert
      ? (payload, _type) => handlers.onAlert!(payload)
      : undefined,
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
  return useStream({
    subscription: {
      eventTypes: ['alert.new', 'alert.updated', 'alert.resolved'],
      minSeverity: options.minSeverity,
    },
    onAlert: (payload, eventType) => {
      switch (eventType) {
        case 'alert.new':
          options.onNewAlert?.(payload);
          break;
        case 'alert.updated':
          options.onAlertUpdated?.(payload);
          break;
        case 'alert.resolved':
          options.onAlertResolved?.(payload);
          break;
      }
    },
  });
}
