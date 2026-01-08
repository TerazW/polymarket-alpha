"""
Audit module - Fire drill and verification tools.

"如果你不能从原始数据重建出相同的结论，你的系统就不是确定性的。"
"""

from .fire_drill import (
    FireDrillExecutor,
    FireDrillReport,
    FireDrillStatus,
    Discrepancy,
    DiscrepancyType,
    run_fire_drill,
    generate_fire_drill_summary,
)

__all__ = [
    "FireDrillExecutor",
    "FireDrillReport",
    "FireDrillStatus",
    "Discrepancy",
    "DiscrepancyType",
    "run_fire_drill",
    "generate_fire_drill_summary",
]
