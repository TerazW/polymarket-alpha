# REPLAY_SPEC.md - 确定性回放规范 v1

## 目标

确保系统可以：
1. 从 `raw_events` 表重建任意时间段的所有状态
2. 两次回放产生完全相同的输出（Deterministic）
3. 验证系统一致性（Consistency Check）

---

## 1. raw_events Schema

```sql
CREATE TABLE raw_events (
    -- 主键
    event_id        UUID            DEFAULT gen_random_uuid(),

    -- 排序键（用于确定性回放）
    server_ts       TIMESTAMPTZ     NOT NULL,   -- 服务器收到消息的时间
    seq_num         BIGINT          NOT NULL,   -- 单调递增序列号

    -- 消息内容
    token_id        TEXT            NOT NULL,   -- 市场 ID
    msg_type        TEXT            NOT NULL,   -- 'book', 'trade', 'price_change'
    raw_payload     JSONB           NOT NULL,   -- 原始 WebSocket 消息

    -- 处理元数据
    client_ts       TIMESTAMPTZ,                -- 客户端本地时间（参考）
    ws_ts           TIMESTAMPTZ,                -- WebSocket 消息中的时间戳

    PRIMARY KEY (server_ts, seq_num)
);

-- TimescaleDB hypertable
SELECT create_hypertable('raw_events', 'server_ts',
    chunk_time_interval => INTERVAL '1 day');

-- 索引
CREATE INDEX idx_raw_events_token ON raw_events (token_id, server_ts);
CREATE INDEX idx_raw_events_type ON raw_events (msg_type, server_ts);

-- 保留策略 (7天)
SELECT add_retention_policy('raw_events', INTERVAL '7 days');
```

---

## 2. 排序键 (sort_key)

### 2.1 定义

```
sort_key = (server_ts, seq_num)
```

- **server_ts**: 服务器收到 WebSocket 消息的时间戳（毫秒精度）
- **seq_num**: 进程内单调递增的序列号

### 2.2 seq_num 生成规则

```python
class SeqNumGenerator:
    """进程内单调递增序列号生成器"""

    def __init__(self):
        self._counter = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def reset(self):
        """仅在回放模式下使用"""
        with self._lock:
            self._counter = 0

# 全局实例
_seq_gen = SeqNumGenerator()

def get_next_seq() -> int:
    return _seq_gen.next()
```

### 2.3 为什么需要 seq_num

同一毫秒内可能收到多条消息，仅靠 `server_ts` 无法保证顺序。`seq_num` 提供了：
1. **全局唯一性**: `(server_ts, seq_num)` 保证唯一
2. **因果序**: 先收到的消息 seq_num 更小
3. **可重建性**: 回放时按 `(server_ts, seq_num)` 排序即可还原原始顺序

---

## 3. 同 Timestamp 处理优先级

当 `server_ts` 相同时，按 `seq_num` 升序处理。

### 3.1 消息类型处理优先级

如果需要在**同一时间桶内**对不同类型消息排序，使用以下优先级：

| 优先级 | msg_type | 原因 |
|--------|----------|------|
| 1 | `book` | Order book 更新是状态基础 |
| 2 | `trade` | 成交依赖于 order book 状态 |
| 3 | `price_change` | 价格变化是结果，非原因 |

### 3.2 实现

```python
MSG_TYPE_PRIORITY = {
    'book': 1,
    'trade': 2,
    'price_change': 3,
}

def replay_sort_key(event: dict) -> tuple:
    """
    生成回放排序键

    Returns:
        (server_ts_ms, msg_type_priority, seq_num)
    """
    return (
        event['server_ts'],  # 毫秒时间戳
        MSG_TYPE_PRIORITY.get(event['msg_type'], 99),
        event['seq_num']
    )
```

---

## 4. 回放流程

### 4.1 回放模式入口

```python
class ReplayEngine:
    """确定性回放引擎"""

    def __init__(self, db_conn, start_ts: int, end_ts: int):
        self.db = db_conn
        self.start_ts = start_ts
        self.end_ts = end_ts

        # 初始化干净的状态
        self.state_store = InMemoryStateStore()
        self.shock_detector = ShockDetector()
        self.reaction_classifier = ReactionClassifier()
        self.belief_state_machine = BeliefStateMachine()
        self.alert_system = AlertSystem()

        # 输出收集
        self.replay_outputs = {
            'shocks': [],
            'reactions': [],
            'leading_events': [],
            'state_changes': [],
            'alerts': []
        }

    def run(self) -> dict:
        """执行回放"""
        events = self._load_events()

        for event in events:
            self._process_event(event)

        return self.replay_outputs

    def _load_events(self) -> list:
        """按排序键加载事件"""
        query = """
            SELECT event_id, server_ts, seq_num, token_id,
                   msg_type, raw_payload, ws_ts
            FROM raw_events
            WHERE server_ts >= %s AND server_ts < %s
            ORDER BY server_ts, seq_num
        """
        rows = self.db.execute(query, (self.start_ts, self.end_ts))
        return [self._row_to_event(r) for r in rows]

    def _process_event(self, event: dict):
        """处理单个事件（与实时处理逻辑相同）"""
        msg_type = event['msg_type']
        payload = event['raw_payload']

        if msg_type == 'book':
            self._handle_book_update(event)
        elif msg_type == 'trade':
            self._handle_trade(event)
        elif msg_type == 'price_change':
            self._handle_price_change(event)
```

### 4.2 时间模拟

回放时使用事件中的 `server_ts` 作为当前时间：

```python
class ReplayTimeClock:
    """回放时间模拟器"""

    def __init__(self):
        self._current_ts = 0

    def set_time(self, ts: int):
        """设置当前回放时间"""
        self._current_ts = ts

    def now(self) -> int:
        """获取当前时间（毫秒）"""
        return self._current_ts

# 替换 time.time() 调用
_replay_clock = ReplayTimeClock()

def get_current_time_ms() -> int:
    if REPLAY_MODE:
        return _replay_clock.now()
    return int(time.time() * 1000)
```

---

## 5. 输出对比报告格式

### 5.1 输出 Hash 计算

```python
import hashlib
import json

def compute_output_hash(outputs: dict) -> str:
    """计算输出的确定性 hash"""

    # 规范化输出格式
    normalized = {
        'shocks': [_normalize_shock(s) for s in outputs['shocks']],
        'reactions': [_normalize_reaction(r) for r in outputs['reactions']],
        'leading_events': [_normalize_leading(e) for e in outputs['leading_events']],
        'state_changes': [_normalize_state_change(c) for c in outputs['state_changes']],
    }

    # 排序确保确定性
    for key in normalized:
        normalized[key].sort(key=lambda x: (x['timestamp'], x['id']))

    # 计算 hash
    json_str = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()

def _normalize_shock(shock: ShockEvent) -> dict:
    return {
        'id': shock.shock_id,
        'timestamp': shock.ts_start,
        'token_id': shock.token_id,
        'price': str(shock.price),
        'side': shock.side,
        'trigger_type': shock.trigger_type,
        'baseline_size': round(shock.baseline_size, 2),
    }

def _normalize_reaction(reaction: ReactionEvent) -> dict:
    return {
        'id': reaction.reaction_id,
        'timestamp': reaction.timestamp,
        'token_id': reaction.token_id,
        'price': str(reaction.price),
        'side': reaction.side,
        'reaction_type': reaction.reaction_type.value,
        'refill_ratio': round(reaction.refill_ratio, 4),
        'drop_ratio': round(reaction.drop_ratio, 4),
    }

# ... 类似的 normalize 函数
```

### 5.2 对比报告

```python
@dataclass
class ReplayComparisonReport:
    """回放对比报告"""

    # 时间范围
    start_ts: int
    end_ts: int

    # 原始运行
    original_hash: str
    original_counts: dict  # {'shocks': N, 'reactions': M, ...}

    # 回放运行
    replay_hash: str
    replay_counts: dict

    # 对比结果
    is_consistent: bool
    differences: List[dict]  # 差异详情

    def to_json(self) -> str:
        return json.dumps({
            'start_ts': self.start_ts,
            'end_ts': self.end_ts,
            'original_hash': self.original_hash,
            'original_counts': self.original_counts,
            'replay_hash': self.replay_hash,
            'replay_counts': self.replay_counts,
            'is_consistent': self.is_consistent,
            'difference_count': len(self.differences),
            'differences': self.differences[:10],  # 只显示前10个差异
        }, indent=2)
```

### 5.3 差异类型

```python
class DifferenceType(Enum):
    MISSING_IN_REPLAY = "missing_in_replay"   # 原始有，回放没有
    EXTRA_IN_REPLAY = "extra_in_replay"       # 原始没有，回放有
    VALUE_MISMATCH = "value_mismatch"         # 都有但值不同
    ORDER_MISMATCH = "order_mismatch"         # 顺序不同

@dataclass
class Difference:
    diff_type: DifferenceType
    event_type: str  # 'shock', 'reaction', etc.
    event_id: str
    field: Optional[str]  # 哪个字段不同
    original_value: Optional[str]
    replay_value: Optional[str]
```

---

## 6. 一致性检查流程

### 6.1 自动检查触发

```python
CONSISTENCY_CHECK_INTERVAL_MS = 5 * 60 * 1000  # 每5分钟检查一次
CONSISTENCY_CHECK_WINDOW_MS = 60 * 1000        # 检查最近1分钟

async def scheduled_consistency_check():
    """定时一致性检查"""
    while True:
        await asyncio.sleep(CONSISTENCY_CHECK_INTERVAL_MS / 1000)

        end_ts = int(time.time() * 1000) - 60000  # 1分钟前（确保窗口关闭）
        start_ts = end_ts - CONSISTENCY_CHECK_WINDOW_MS

        report = await run_consistency_check(start_ts, end_ts)

        if not report.is_consistent:
            logger.error(f"Consistency check FAILED: {report.to_json()}")
            # 触发告警
            await trigger_inconsistency_alert(report)
```

### 6.2 手动检查接口

```python
async def run_consistency_check(
    start_ts: int,
    end_ts: int
) -> ReplayComparisonReport:
    """运行一致性检查"""

    # 1. 加载原始输出
    original_outputs = await load_original_outputs(start_ts, end_ts)
    original_hash = compute_output_hash(original_outputs)

    # 2. 执行回放
    replay_engine = ReplayEngine(db, start_ts, end_ts)
    replay_outputs = replay_engine.run()
    replay_hash = compute_output_hash(replay_outputs)

    # 3. 对比
    differences = compare_outputs(original_outputs, replay_outputs)

    return ReplayComparisonReport(
        start_ts=start_ts,
        end_ts=end_ts,
        original_hash=original_hash,
        original_counts=count_outputs(original_outputs),
        replay_hash=replay_hash,
        replay_counts=count_outputs(replay_outputs),
        is_consistent=(original_hash == replay_hash),
        differences=differences
    )
```

---

## 7. API 接口

### 7.1 回放接口

```
POST /api/replay
Content-Type: application/json

{
    "start_ts": 1704326400000,
    "end_ts": 1704330000000,
    "token_ids": ["0x...", "0x..."],  // 可选，不传则全部
    "output_format": "full"  // "full" | "summary" | "hash_only"
}

Response:
{
    "replay_id": "uuid",
    "duration_ms": 1234,
    "output_hash": "abc123...",
    "counts": {
        "shocks": 45,
        "reactions": 42,
        "leading_events": 8,
        "state_changes": 12
    },
    "outputs": { ... }  // 仅当 output_format="full"
}
```

### 7.2 一致性检查接口

```
POST /api/consistency-check
Content-Type: application/json

{
    "start_ts": 1704326400000,
    "end_ts": 1704330000000
}

Response:
{
    "is_consistent": true,
    "original_hash": "abc123...",
    "replay_hash": "abc123...",
    "difference_count": 0,
    "checked_at": "2026-01-04T12:00:00Z"
}
```

---

## 8. 注意事项

### 8.1 随机性消除

系统中所有随机性来源必须消除或可控：

| 来源 | 处理方式 |
|------|----------|
| `uuid.uuid4()` | 使用确定性 ID 生成（基于 sort_key hash） |
| `time.time()` | 回放时替换为事件时间 |
| `random.*` | 禁止使用或固定 seed |
| 浮点精度 | 使用 Decimal 或固定小数位 |

### 8.2 确定性 ID 生成

```python
def generate_deterministic_id(sort_key: tuple, event_type: str) -> str:
    """生成确定性 ID"""
    content = f"{sort_key[0]}:{sort_key[1]}:{event_type}"
    return hashlib.md5(content.encode()).hexdigest()
```

### 8.3 浮点数处理

```python
# 所有比率保留4位小数
refill_ratio = round(refill_ratio, 4)
drop_ratio = round(drop_ratio, 4)

# 价格使用 Decimal
price = Decimal(str(price_float))
```

---

## 9. 测试用例

### 9.1 确定性测试

```python
def test_replay_determinism():
    """回放两次结果应完全相同"""
    start_ts = 1704326400000
    end_ts = 1704330000000

    # 第一次回放
    engine1 = ReplayEngine(db, start_ts, end_ts)
    outputs1 = engine1.run()
    hash1 = compute_output_hash(outputs1)

    # 第二次回放
    engine2 = ReplayEngine(db, start_ts, end_ts)
    outputs2 = engine2.run()
    hash2 = compute_output_hash(outputs2)

    assert hash1 == hash2, "Replay should be deterministic"
```

### 9.2 实时 vs 回放一致性测试

```python
def test_realtime_vs_replay_consistency():
    """实时处理和回放应产生相同结果"""
    # 需要先运行一段时间收集数据
    # 然后对比实时输出和回放输出
    ...
```

---

## 10. Changelog

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-01-04 | 初始规范 |
