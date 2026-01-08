'use client';

/**
 * v5.36: Evidence Disclaimer Watermark
 *
 * CRITICAL: This component enforces the paradigm principle that
 * this system shows EVIDENCE, not PREDICTIONS.
 *
 * Must be displayed on all data visualization components.
 *
 * "看存在没意义，看反应才有意义" - but we show reaction evidence, not predictions
 */

interface EvidenceDisclaimerProps {
  /** Position on the visualization */
  position?: 'top-right' | 'bottom-left' | 'bottom-right' | 'center';
  /** Compact mode for smaller visualizations */
  compact?: boolean;
  /** Additional CSS classes */
  className?: string;
}

export function EvidenceDisclaimer({
  position = 'bottom-right',
  compact = false,
  className = '',
}: EvidenceDisclaimerProps) {
  const positionClasses: Record<string, string> = {
    'top-right': 'top-2 right-2',
    'bottom-left': 'bottom-2 left-2',
    'bottom-right': 'bottom-2 right-2',
    'center': 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2',
  };

  if (compact) {
    return (
      <div
        className={`absolute ${positionClasses[position]} px-2 py-0.5
          bg-gray-900/70 border border-gray-700 rounded text-[10px]
          text-gray-400 pointer-events-none select-none ${className}`}
      >
        Evidence only · Not prediction
      </div>
    );
  }

  return (
    <div
      className={`absolute ${positionClasses[position]} px-3 py-1.5
        bg-gray-900/80 border border-gray-600 rounded-lg
        pointer-events-none select-none ${className}`}
    >
      <div className="text-xs text-gray-300 font-medium">
        📊 Evidence, not prediction
      </div>
      <div className="text-[10px] text-gray-500 mt-0.5">
        Past reactions shown · Future not implied
      </div>
    </div>
  );
}

/**
 * Watermark overlay for canvas-based visualizations
 * Can be drawn directly on canvas
 */
export function drawEvidenceWatermark(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  options: { compact?: boolean; position?: 'bottom-right' | 'bottom-left' } = {}
) {
  const { compact = false, position = 'bottom-right' } = options;

  ctx.save();

  const text = compact
    ? 'Evidence only · Not prediction'
    : 'Evidence, not prediction';

  ctx.font = compact ? '9px sans-serif' : '11px sans-serif';
  const textWidth = ctx.measureText(text).width;
  const padding = 8;
  const boxWidth = textWidth + padding * 2;
  const boxHeight = compact ? 18 : 24;

  let x: number;
  const y = height - boxHeight - 8;

  if (position === 'bottom-left') {
    x = 8;
  } else {
    x = width - boxWidth - 8;
  }

  // Background
  ctx.fillStyle = 'rgba(17, 24, 39, 0.8)';
  ctx.strokeStyle = 'rgba(75, 85, 99, 0.8)';
  ctx.lineWidth = 1;

  // Rounded rect
  const radius = 4;
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + boxWidth - radius, y);
  ctx.quadraticCurveTo(x + boxWidth, y, x + boxWidth, y + radius);
  ctx.lineTo(x + boxWidth, y + boxHeight - radius);
  ctx.quadraticCurveTo(x + boxWidth, y + boxHeight, x + boxWidth - radius, y + boxHeight);
  ctx.lineTo(x + radius, y + boxHeight);
  ctx.quadraticCurveTo(x, y + boxHeight, x, y + boxHeight - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();

  ctx.fill();
  ctx.stroke();

  // Text
  ctx.fillStyle = 'rgba(156, 163, 175, 0.9)';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x + boxWidth / 2, y + boxHeight / 2);

  ctx.restore();
}

export default EvidenceDisclaimer;
