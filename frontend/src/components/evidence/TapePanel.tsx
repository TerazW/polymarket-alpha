'use client';

import { useState } from 'react';
import type {
  ShockEvent,
  ReactionEvent,
  LeadingEvent,
  StateChange,
  ReactionType,
} from '@/types/api';
import { REACTION_COLORS, STATE_COLORS } from '@/types/api';

interface TapePanelProps {
  shocks: ShockEvent[];
  reactions: ReactionEvent[];
  leadingEvents: LeadingEvent[];
  stateChanges: StateChange[];
  selectedEventId: string | null;
  onEventClick: (eventId: string, timestamp: number) => void;
}

type EventFilter = 'all' | 'shocks' | 'reactions' | 'leading' | 'states';

export function TapePanel({
  shocks,
  reactions,
  leadingEvents,
  stateChanges,
  selectedEventId,
  onEventClick,
}: TapePanelProps) {
  const [filter, setFilter] = useState<EventFilter>('all');
  const [expandedProof, setExpandedProof] = useState<string | null>(null);

  // Combine and sort all events
  const allEvents = [
    ...shocks.map((e) => ({ ...e, eventType: 'shock' as const })),
    ...reactions.map((e) => ({ ...e, eventType: 'reaction' as const })),
    ...leadingEvents.map((e) => ({ ...e, eventType: 'leading' as const })),
    ...stateChanges.map((e) => ({ ...e, eventType: 'state' as const })),
  ].sort((a, b) => b.timestamp - a.timestamp); // Most recent first

  // Filter events
  const filteredEvents = allEvents.filter((e) => {
    if (filter === 'all') return true;
    if (filter === 'shocks') return e.eventType === 'shock';
    if (filter === 'reactions') return e.eventType === 'reaction';
    if (filter === 'leading') return e.eventType === 'leading';
    if (filter === 'states') return e.eventType === 'state';
    return true;
  });

  return (
    <div className="flex flex-col h-full">
      {/* Header with filter */}
      <div className="p-3 border-b border-gray-800">
        <h3 className="font-semibold mb-2">Event Tape</h3>
        <div className="flex gap-1 flex-wrap">
          {(['all', 'shocks', 'reactions', 'leading', 'states'] as EventFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-1 text-xs rounded ${
                filter === f ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Event list */}
      <div className="flex-1 overflow-y-auto">
        {filteredEvents.length === 0 ? (
          <div className="p-4 text-center text-gray-500">No events</div>
        ) : (
          <div className="divide-y divide-gray-800">
            {filteredEvents.map((event) => {
              if (event.eventType === 'shock') {
                return (
                  <ShockCard
                    key={event.id}
                    shock={event}
                    isSelected={event.id === selectedEventId}
                    onClick={() => onEventClick(event.id, event.timestamp)}
                  />
                );
              }
              if (event.eventType === 'reaction') {
                return (
                  <ReactionCard
                    key={event.id}
                    reaction={event}
                    isSelected={event.id === selectedEventId}
                    isExpanded={expandedProof === event.id}
                    onToggleProof={() =>
                      setExpandedProof(expandedProof === event.id ? null : event.id)
                    }
                    onClick={() => onEventClick(event.id, event.timestamp)}
                  />
                );
              }
              if (event.eventType === 'leading') {
                return (
                  <LeadingEventCard
                    key={event.id}
                    event={event}
                    isSelected={event.id === selectedEventId}
                    onClick={() => onEventClick(event.id, event.timestamp)}
                  />
                );
              }
              if (event.eventType === 'state') {
                return (
                  <StateChangeCard
                    key={event.id}
                    change={event}
                    isSelected={event.id === selectedEventId}
                    onClick={() => onEventClick(event.id, event.timestamp)}
                  />
                );
              }
              return null;
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// Event card components

function ShockCard({
  shock,
  isSelected,
  onClick,
}: {
  shock: ShockEvent;
  isSelected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full p-3 text-left hover:bg-gray-800/50 transition-colors ${
        isSelected ? 'bg-yellow-500/10 border-l-2 border-yellow-500' : ''
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-yellow-500">⚡</span>
        <span className="font-medium text-yellow-400">Shock</span>
        <span className="text-xs text-gray-500 ml-auto">{formatTime(shock.timestamp)}</span>
      </div>
      <div className="text-sm text-gray-400">
        @ {(parseFloat(shock.price) * 100).toFixed(0)}% ({shock.side})
      </div>
      <div className="text-xs text-gray-500 mt-1">
        Vol: {shock.trade_volume.toLocaleString()} | Trigger: {shock.trigger_type}
      </div>
    </button>
  );
}

function ReactionCard({
  reaction,
  isSelected,
  isExpanded,
  onToggleProof,
  onClick,
}: {
  reaction: ReactionEvent;
  isSelected: boolean;
  isExpanded: boolean;
  onToggleProof: () => void;
  onClick: () => void;
}) {
  const color = REACTION_COLORS[reaction.reaction_type];

  return (
    <div
      className={`p-3 hover:bg-gray-800/50 transition-colors ${
        isSelected ? 'bg-blue-500/10 border-l-2 border-blue-500' : ''
      }`}
    >
      <button onClick={onClick} className="w-full text-left">
        <div className="flex items-center gap-2 mb-1">
          <span
            className="w-3 h-3 rounded-sm"
            style={{ backgroundColor: color }}
          />
          <span className="font-medium" style={{ color }}>
            {reaction.reaction_type}
          </span>
          <span className="text-xs text-gray-500 ml-auto">{formatTime(reaction.timestamp)}</span>
        </div>
        <div className="text-sm text-gray-400">
          @ {(parseFloat(reaction.price) * 100).toFixed(0)}% ({reaction.side})
        </div>
        <div className="flex gap-3 text-xs text-gray-500 mt-1">
          <span>Drop: {(reaction.drop_ratio * 100).toFixed(0)}%</span>
          <span>Refill: {(reaction.refill_ratio * 100).toFixed(0)}%</span>
          {reaction.price_shift_ticks > 0 && <span>Shift: {reaction.price_shift_ticks} ticks</span>}
        </div>
      </button>

      {/* Proof toggle */}
      <button
        onClick={onToggleProof}
        className="mt-2 text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
      >
        <span>{isExpanded ? '▼' : '▶'}</span>
        <span>Proof</span>
      </button>

      {/* Expanded proof panel */}
      {isExpanded && (
        <div className="mt-2 p-2 bg-gray-900 rounded text-xs">
          <div className="font-mono text-gray-300 mb-2">{reaction.proof.rule_triggered}</div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-gray-500 mb-1">Thresholds</div>
              {Object.entries(reaction.proof.thresholds).map(([key, val]) => (
                <div key={key} className="flex justify-between">
                  <span className="text-gray-400">{key}:</span>
                  <span>{typeof val === 'number' ? val.toFixed(2) : val}</span>
                </div>
              ))}
            </div>
            <div>
              <div className="text-gray-500 mb-1">Actual</div>
              {Object.entries(reaction.proof.actual_values).map(([key, val]) => (
                <div key={key} className="flex justify-between">
                  <span className="text-gray-400">{key}:</span>
                  <span
                    className={
                      meetsThreshold(key, val, reaction.proof.thresholds)
                        ? 'text-green-400'
                        : 'text-red-400'
                    }
                  >
                    {typeof val === 'number' ? val.toFixed(2) : val}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-2 text-gray-500">
            Window: {reaction.proof.window_type}
          </div>
        </div>
      )}
    </div>
  );
}

function LeadingEventCard({
  event,
  isSelected,
  onClick,
}: {
  event: LeadingEvent;
  isSelected: boolean;
  onClick: () => void;
}) {
  const colors: Record<string, string> = {
    PRE_SHOCK_PULL: '#a855f7',
    DEPTH_COLLAPSE: '#ef4444',
    GRADUAL_THINNING: '#f97316',
  };
  const color = colors[event.event_type] || '#6b7280';

  return (
    <button
      onClick={onClick}
      className={`w-full p-3 text-left hover:bg-gray-800/50 transition-colors ${
        isSelected ? 'bg-purple-500/10 border-l-2 border-purple-500' : ''
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg">▲</span>
        <span className="font-medium" style={{ color }}>
          {event.event_type.replace(/_/g, ' ')}
        </span>
        <span className="text-xs text-gray-500 ml-auto">{formatTime(event.timestamp)}</span>
      </div>
      <div className="text-sm text-gray-400">
        @ {(parseFloat(event.price) * 100).toFixed(0)}% ({event.side})
      </div>
      <div className="flex gap-3 text-xs text-gray-500 mt-1">
        <span>Drop: {(event.drop_ratio * 100).toFixed(0)}%</span>
        <span>Trade nearby: {event.trade_volume_nearby}</span>
        {event.levels_affected && <span>Levels: {event.levels_affected}</span>}
      </div>
    </button>
  );
}

function StateChangeCard({
  change,
  isSelected,
  onClick,
}: {
  change: StateChange;
  isSelected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full p-3 text-left hover:bg-gray-800/50 transition-colors ${
        isSelected ? 'bg-gray-700 border-l-2 border-white' : ''
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span style={{ color: STATE_COLORS[change.old_state] }}>●</span>
        <span className="text-gray-500">→</span>
        <span style={{ color: STATE_COLORS[change.new_state] }}>●</span>
        <span className="font-medium" style={{ color: STATE_COLORS[change.new_state] }}>
          {change.new_state}
        </span>
        <span className="text-xs text-gray-500 ml-auto">{formatTime(change.timestamp)}</span>
      </div>
      <div className="text-xs text-gray-500 mt-1">
        {change.evidence.slice(0, 2).map((e, i) => (
          <div key={i}>• {e}</div>
        ))}
        {change.evidence.length > 2 && (
          <div className="text-gray-600">+{change.evidence.length - 2} more</div>
        )}
      </div>
    </button>
  );
}

// Helper functions

function formatTime(ts: number): string {
  const date = new Date(ts);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function meetsThreshold(key: string, actual: number, thresholds: Record<string, number>): boolean {
  const threshold = thresholds[key];
  if (threshold === undefined) return true;

  // Simple heuristic: if key contains 'max', actual should be <= threshold
  // if key contains 'min', actual should be >= threshold
  if (key.includes('max')) return actual <= threshold;
  if (key.includes('min')) return actual >= threshold;
  return true;
}
