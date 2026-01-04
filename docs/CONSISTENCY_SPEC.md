# CONSISTENCY_SPEC.md - 一致性检测与自动重建规范 v1

## 目标

1. **检测**: 自动发现实时计算与回放计算的不一致
2. **诊断**: 定位不一致的根因（数据丢失 vs 逻辑错误）
3. **重建**: 触发自动重建流程修复状态

---

## 1. 不一致性来源分析

### 1.1 可能的不一致来源

| 来源 | 类型 | 示例 | 可自动修复 |
|------|------|------|-----------|
| 网络断连 | 数据丢失 | WebSocket 断开5秒，丢失10条消息 | ✅ |
| 消息乱序 | 顺序错误 | msg_seq=100 在 msg_seq=99 之前处理 | ✅ |
| 进程重启 | 状态丢失 | 内存状态丢失，从 DB 恢复不完整 | ✅ |
| 时钟漂移 | 时间错误 | 服务器时间与 WS 时间差异 > 1s | ⚠️ |
| 代码 Bug | 逻辑错误 | 分类规则实现有误 | ❌ |
| 配置变更 | 参数变更 | 阈值从 0.8 改为 0.7 | ⚠️ |

### 1.2 检测策略

```
不一致 = 实时输出 ≠ 回放输出
```

当检测到不一致时：
1. **记录**: 保存差异详情
2. **分类**: 判断根因类型
3. **决策**: 自动重建 or 人工介入

---

## 2. 一致性检测机制

### 2.1 检测点设计

```python
class ConsistencyCheckpoint:
    """一致性检查点"""

    def __init__(self, window_ms: int = 60000):
        self.window_ms = window_ms
        self.last_check_ts = 0
        self.check_interval_ms = 5 * 60 * 1000  # 5分钟检查一次

        # 滞后检查（等待窗口关闭）
        self.lag_ms = 60000  # 1分钟滞后

    async def maybe_check(self, current_ts: int) -> Optional[ConsistencyReport]:
        """检查是否需要运行一致性检查"""
        if current_ts - self.last_check_ts < self.check_interval_ms:
            return None

        # 检查 [last_check_ts, current_ts - lag_ms] 区间
        check_end = current_ts - self.lag_ms
        check_start = self.last_check_ts if self.last_check_ts > 0 else check_end - self.window_ms

        self.last_check_ts = check_end

        return await self._run_check(check_start, check_end)
```

### 2.2 检查粒度

| 粒度 | 检查内容 | 频率 | 成本 |
|------|----------|------|------|
| Hash | 输出 hash 是否一致 | 5分钟 | 低 |
| Count | 事件数量是否一致 | 5分钟 | 低 |
| Sample | 随机抽样对比 | 30分钟 | 中 |
| Full | 完整输出对比 | 手动/异常时 | 高 |

### 2.3 轻量级检查实现

```python
@dataclass
class QuickConsistencyCheck:
    """轻量级一致性检查"""
    window_start: int
    window_end: int

    # 计数对比
    realtime_counts: Dict[str, int]  # {'shocks': N, 'reactions': M, ...}
    replay_counts: Dict[str, int]

    # Hash 对比
    realtime_hash: str
    replay_hash: str

    @property
    def is_consistent(self) -> bool:
        return self.realtime_hash == self.replay_hash

    @property
    def count_diff(self) -> Dict[str, int]:
        diff = {}
        for key in self.realtime_counts:
            delta = self.realtime_counts[key] - self.replay_counts.get(key, 0)
            if delta != 0:
                diff[key] = delta
        return diff
```

---

## 3. 不一致诊断

### 3.1 诊断流程

```
检测到不一致
    ↓
1. 检查 raw_events 完整性
    ├── 有 gap → 数据丢失
    │      ↓
    │   可重建窗口内？ → 标记需重建
    │
    └── 无 gap → 逻辑问题
           ↓
       2. 对比具体差异
           ├── 事件丢失 → 状态污染
           ├── 事件多余 → 重复处理
           └── 值不同 → 计算错误
```

### 3.2 诊断代码

```python
class InconsistencyDiagnoser:
    """不一致性诊断器"""

    async def diagnose(self, report: ConsistencyReport) -> DiagnosisResult:
        """诊断不一致的根因"""

        # 1. 检查 raw_events 完整性
        gaps = await self._check_raw_events_gaps(
            report.window_start,
            report.window_end
        )

        if gaps:
            return DiagnosisResult(
                cause=InconsistencyCause.DATA_LOSS,
                gaps=gaps,
                can_rebuild=self._check_rebuild_window(gaps),
                recommendation="REBUILD"
            )

        # 2. 检查序列号连续性
        seq_issues = await self._check_sequence_continuity(
            report.window_start,
            report.window_end
        )

        if seq_issues:
            return DiagnosisResult(
                cause=InconsistencyCause.SEQUENCE_ERROR,
                details=seq_issues,
                can_rebuild=True,
                recommendation="REBUILD"
            )

        # 3. 对比具体差异
        diffs = await self._compare_detailed(report)

        if diffs['missing_events']:
            return DiagnosisResult(
                cause=InconsistencyCause.STATE_CORRUPTION,
                details=diffs,
                can_rebuild=True,
                recommendation="REBUILD"
            )

        if diffs['value_mismatches']:
            return DiagnosisResult(
                cause=InconsistencyCause.LOGIC_ERROR,
                details=diffs,
                can_rebuild=False,
                recommendation="INVESTIGATE"
            )

        return DiagnosisResult(
            cause=InconsistencyCause.UNKNOWN,
            recommendation="MANUAL_REVIEW"
        )

    async def _check_raw_events_gaps(
        self,
        start_ts: int,
        end_ts: int
    ) -> List[TimeGap]:
        """检查 raw_events 是否有时间 gap"""
        query = """
            WITH event_gaps AS (
                SELECT
                    server_ts,
                    LAG(server_ts) OVER (ORDER BY server_ts, seq_num) as prev_ts
                FROM raw_events
                WHERE server_ts >= %s AND server_ts < %s
            )
            SELECT prev_ts as gap_start, server_ts as gap_end
            FROM event_gaps
            WHERE server_ts - prev_ts > 5000  -- 5秒以上 gap
        """
        rows = await self.db.fetch(query, (start_ts, end_ts))
        return [TimeGap(r['gap_start'], r['gap_end']) for r in rows]
```

### 3.3 诊断结果

```python
class InconsistencyCause(Enum):
    DATA_LOSS = "data_loss"           # raw_events 有缺失
    SEQUENCE_ERROR = "sequence_error" # 序列号不连续
    STATE_CORRUPTION = "state_corruption"  # 内存状态污染
    LOGIC_ERROR = "logic_error"       # 代码逻辑错误
    UNKNOWN = "unknown"

@dataclass
class DiagnosisResult:
    cause: InconsistencyCause
    details: Optional[dict] = None
    gaps: Optional[List[TimeGap]] = None
    can_rebuild: bool = False
    recommendation: str = "MANUAL_REVIEW"  # REBUILD | INVESTIGATE | MANUAL_REVIEW
```

---

## 4. 自动重建机制

### 4.1 重建触发条件

```python
class RebuildTrigger:
    """重建触发器"""

    # 自动重建条件
    AUTO_REBUILD_CONDITIONS = [
        InconsistencyCause.DATA_LOSS,
        InconsistencyCause.SEQUENCE_ERROR,
        InconsistencyCause.STATE_CORRUPTION,
    ]

    # 需人工确认
    MANUAL_REBUILD_CONDITIONS = [
        InconsistencyCause.LOGIC_ERROR,
        InconsistencyCause.UNKNOWN,
    ]

    def should_auto_rebuild(self, diagnosis: DiagnosisResult) -> bool:
        """是否应自动重建"""
        return (
            diagnosis.can_rebuild and
            diagnosis.cause in self.AUTO_REBUILD_CONDITIONS
        )
```

### 4.2 重建范围计算

```python
class RebuildWindowCalculator:
    """重建窗口计算器"""

    # 最大回溯时间
    MAX_REBUILD_WINDOW_MS = 30 * 60 * 1000  # 30分钟

    # 安全边界（确保状态完整）
    SAFETY_MARGIN_MS = 60 * 1000  # 1分钟

    def calculate_rebuild_window(
        self,
        inconsistency_start: int,
        current_ts: int
    ) -> Optional[Tuple[int, int]]:
        """计算需要重建的时间窗口"""

        # 检查是否在可重建范围内
        if current_ts - inconsistency_start > self.MAX_REBUILD_WINDOW_MS:
            return None  # 超出重建窗口

        # 添加安全边界
        rebuild_start = inconsistency_start - self.SAFETY_MARGIN_MS
        rebuild_end = current_ts

        return (rebuild_start, rebuild_end)
```

### 4.3 重建执行流程

```python
class StateRebuilder:
    """状态重建器"""

    def __init__(self, db, engine: ReactionEngine):
        self.db = db
        self.engine = engine

    async def rebuild(
        self,
        start_ts: int,
        end_ts: int,
        token_ids: Optional[List[str]] = None
    ) -> RebuildResult:
        """执行状态重建"""

        logger.info(f"Starting rebuild: {start_ts} -> {end_ts}")

        # 1. 暂停实时处理（可选，取决于架构）
        # await self.engine.pause()

        # 2. 清理目标时间范围内的状态
        await self._clear_state(start_ts, end_ts, token_ids)

        # 3. 从 raw_events 重新计算
        replay_engine = ReplayEngine(self.db, start_ts, end_ts)
        outputs = await replay_engine.run()

        # 4. 写入重建的结果
        await self._persist_outputs(outputs)

        # 5. 恢复实时处理
        # await self.engine.resume()

        # 6. 验证重建结果
        verification = await self._verify_rebuild(start_ts, end_ts)

        return RebuildResult(
            start_ts=start_ts,
            end_ts=end_ts,
            events_processed=len(outputs['shocks']) + len(outputs['reactions']),
            verification=verification,
            success=verification.is_consistent
        )

    async def _clear_state(
        self,
        start_ts: int,
        end_ts: int,
        token_ids: Optional[List[str]]
    ):
        """清理目标范围内的状态"""
        tables = ['shocks', 'reactions', 'leading_events', 'state_changes']

        for table in tables:
            if token_ids:
                query = f"""
                    DELETE FROM {table}
                    WHERE timestamp >= %s AND timestamp < %s
                    AND token_id = ANY(%s)
                """
                await self.db.execute(query, (start_ts, end_ts, token_ids))
            else:
                query = f"""
                    DELETE FROM {table}
                    WHERE timestamp >= %s AND timestamp < %s
                """
                await self.db.execute(query, (start_ts, end_ts))

        # 清理内存状态
        self.engine.clear_state(start_ts, end_ts, token_ids)
```

---

## 5. 告警与通知

### 5.1 告警级别

```python
class ConsistencyAlertLevel(Enum):
    INFO = "info"           # 轻微不一致，已自动修复
    WARNING = "warning"     # 需要重建，自动执行中
    ERROR = "error"         # 重建失败，需人工介入
    CRITICAL = "critical"   # 逻辑错误，可能影响所有计算
```

### 5.2 告警内容

```python
@dataclass
class ConsistencyAlert:
    level: ConsistencyAlertLevel
    timestamp: int
    window_start: int
    window_end: int

    # 诊断信息
    cause: InconsistencyCause
    difference_summary: str

    # 采取的行动
    action_taken: str  # "AUTO_REBUILD" | "PENDING_MANUAL" | "NONE"
    rebuild_result: Optional[RebuildResult] = None

    def to_message(self) -> str:
        """生成告警消息"""
        return f"""
[{self.level.value.upper()}] Consistency Alert

Time Window: {self.window_start} - {self.window_end}
Cause: {self.cause.value}
Difference: {self.difference_summary}

Action: {self.action_taken}
{"Rebuild Result: " + str(self.rebuild_result) if self.rebuild_result else ""}
"""
```

---

## 6. 配置参数

```python
# =============================================================================
# CONSISTENCY CHECK PARAMETERS
# =============================================================================

# 检查频率
CONSISTENCY_CHECK_INTERVAL_MS = 5 * 60 * 1000   # 5分钟检查一次
CONSISTENCY_CHECK_LAG_MS = 60 * 1000            # 滞后1分钟（确保窗口关闭）
CONSISTENCY_CHECK_WINDOW_MS = 60 * 1000         # 每次检查1分钟窗口

# Gap 检测阈值
RAW_EVENTS_GAP_THRESHOLD_MS = 5000              # 5秒以上认为是 gap

# 重建参数
MAX_REBUILD_WINDOW_MS = 30 * 60 * 1000          # 最大重建30分钟
REBUILD_SAFETY_MARGIN_MS = 60 * 1000            # 重建安全边界1分钟
AUTO_REBUILD_MAX_RETRIES = 3                    # 自动重建最多重试3次

# 告警阈值
ALERT_DIFFERENCE_THRESHOLD = 5                  # 差异 >= 5 个事件触发告警
```

---

## 7. 状态流转图

```
                    ┌─────────────┐
                    │   NORMAL    │
                    │  (正常运行)  │
                    └──────┬──────┘
                           │
                    一致性检查失败
                           │
                           ▼
                    ┌─────────────┐
                    │ DIAGNOSING  │
                    │  (诊断中)    │
                    └──────┬──────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
    可自动重建       需人工确认      逻辑错误
            │              │              │
            ▼              ▼              ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │ REBUILDING  │ │   WAITING   │ │   BROKEN    │
    │  (重建中)    │ │ (等待确认)   │ │  (需修复)    │
    └──────┬──────┘ └─────────────┘ └─────────────┘
           │
    重建成功 │ 重建失败
           │     │
           ▼     ▼
    ┌─────────────┐
    │   NORMAL    │  ←─ 人工确认/修复后
    └─────────────┘
```

---

## 8. API 接口

### 8.1 手动触发一致性检查

```
POST /api/consistency/check
Content-Type: application/json

{
    "start_ts": 1704326400000,
    "end_ts": 1704330000000,
    "token_ids": ["0x..."],  // 可选
    "check_level": "full"    // "quick" | "full"
}

Response:
{
    "is_consistent": false,
    "diagnosis": {
        "cause": "data_loss",
        "gaps": [
            {"start": 1704327000000, "end": 1704327005000}
        ],
        "can_rebuild": true,
        "recommendation": "REBUILD"
    }
}
```

### 8.2 手动触发重建

```
POST /api/consistency/rebuild
Content-Type: application/json

{
    "start_ts": 1704326400000,
    "end_ts": 1704330000000,
    "token_ids": ["0x..."],  // 可选
    "dry_run": false         // true = 只预览，不实际执行
}

Response:
{
    "rebuild_id": "uuid",
    "status": "completed",
    "events_processed": 1234,
    "verification": {
        "is_consistent": true,
        "new_hash": "abc123..."
    }
}
```

### 8.3 查看一致性状态

```
GET /api/consistency/status

Response:
{
    "current_state": "NORMAL",
    "last_check": {
        "timestamp": 1704330000000,
        "window": [1704329940000, 1704330000000],
        "is_consistent": true
    },
    "recent_issues": [],
    "pending_rebuilds": []
}
```

---

## 9. 监控指标

```python
# Prometheus 指标
consistency_checks_total = Counter(
    'consistency_checks_total',
    'Total number of consistency checks',
    ['result']  # 'passed' | 'failed'
)

consistency_check_duration_seconds = Histogram(
    'consistency_check_duration_seconds',
    'Duration of consistency checks'
)

rebuilds_total = Counter(
    'rebuilds_total',
    'Total number of state rebuilds',
    ['trigger', 'result']  # trigger: 'auto' | 'manual', result: 'success' | 'failure'
)

inconsistency_gap_seconds = Histogram(
    'inconsistency_gap_seconds',
    'Duration of detected gaps in raw_events'
)
```

---

## 10. Changelog

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-01-04 | 初始规范 |
