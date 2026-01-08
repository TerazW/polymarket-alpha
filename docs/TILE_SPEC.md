# Heatmap Tile Specification v1

> Evidence-first 深度热力图瓦片编码规范

## 概述

Heatmap Tiles 是 Evidence Player 的核心可视化数据结构。设计目标：
1. **低延迟**: 前端秒级加载完整时间窗口
2. **高保真**: 保留 250ms 时间分辨率的深度变化
3. **可扩展**: 支持多 LOD (Level of Detail) 按需加载

## LOD (Level of Detail)

| LOD | 时间分辨率 | 用途 | 典型瓦片大小 |
|-----|-----------|------|-------------|
| 250ms | 250ms/列 | 详细分析 | ~40列/10s |
| 1s | 1s/列 | 中等缩放 | ~10列/10s |
| 5s | 5s/列 | 概览模式 | ~2列/10s |

## 瓦片结构

### 元数据 (JSON)

```json
{
  "tile_id": "token123:250:1735960000000:FULL",
  "token_id": "0x1234...abcd",
  "lod_ms": 250,
  "tile_ms": 10000,
  "band": "FULL",
  "t_start": 1735960000000,
  "t_end": 1735960010000,
  "tick_size": 0.01,
  "price_min": 0.45,
  "price_max": 0.55,
  "rows": 10,
  "cols": 40,
  "encoding": {
    "dtype": "uint16",
    "layout": "row_major",
    "scale": "log1p_clip",
    "clip_pctl": 0.95,
    "clip_value": 50000,
    "endian": "little"
  },
  "compression": {
    "algo": "zstd",
    "level": 3
  },
  "payload_b64": "KLUv/QDAWQAA...",
  "checksum": {
    "algo": "xxh3_64",
    "value": "a1b2c3d4e5f6"
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `tile_id` | string | 唯一标识: `{token_id}:{lod_ms}:{t_start}:{band}` |
| `lod_ms` | int | 时间分辨率 (250, 1000, 5000) |
| `tile_ms` | int | 瓦片时间跨度 (5000, 10000, 15000) |
| `band` | string | 价格带: FULL, BEST_5, BEST_10, BEST_20 |
| `rows` | int | 价格档位数 (Y轴) |
| `cols` | int | 时间桶数 (X轴) |

### Band 说明

| Band | 说明 |
|------|------|
| `FULL` | 完整价格范围 (price_min ~ price_max) |
| `BEST_5` | 最优 5 档 (bid/ask 各 5 档) |
| `BEST_10` | 最优 10 档 |
| `BEST_20` | 最优 20 档 |

## 编码规范

### 1. 数据类型: uint16

每个深度值用 16-bit 无符号整数表示。

### 2. 缩放函数: log1p_clip

```python
def encode(size: float, clip_value: float) -> int:
    """将深度值编码为 uint16"""
    if size <= 0:
        return 0
    # Clip at 95th percentile
    clipped = min(size, clip_value)
    # Log1p scaling to [0, 65535]
    scaled = math.log1p(clipped) / math.log1p(clip_value)
    return int(scaled * 65535)

def decode(encoded: int, clip_value: float) -> float:
    """将 uint16 解码为深度值"""
    if encoded == 0:
        return 0.0
    scaled = encoded / 65535.0
    return math.expm1(scaled * math.log1p(clip_value))
```

### 3. 布局: row_major

矩阵按行存储：
- 第一行 = 最高价格
- 最后一行 = 最低价格
- 第一列 = t_start
- 最后一列 = t_end - lod_ms

```
索引计算: offset = row * cols + col
字节偏移: byte_offset = offset * 2  # uint16 = 2 bytes
```

### 4. 字节序: little-endian

所有 uint16 值使用小端序存储。

## 压缩

### 算法: zstd

推荐配置：
- `level`: 3 (平衡压缩率和速度)
- 典型压缩率: 3-5x

### 备选算法

| 算法 | 压缩率 | 速度 | 适用场景 |
|------|--------|------|----------|
| `zstd` | 高 | 中 | 默认推荐 |
| `lz4` | 中 | 快 | 实时流 |
| `none` | 无 | 最快 | 调试 |

## 校验

### 算法: xxh3_64

对**解压后**的原始字节计算 xxHash3 64-bit：

```python
import xxhash

def compute_checksum(payload_bytes: bytes) -> str:
    return xxhash.xxh3_64(payload_bytes).hexdigest()
```

## 前端解码流程

```typescript
async function decodeTile(tile: HeatmapTileMeta): Promise<Float32Array> {
  // 1. Base64 decode
  const compressed = base64ToBytes(tile.payload_b64);

  // 2. Decompress (zstd)
  const raw = await decompress(compressed, tile.compression.algo);

  // 3. Verify checksum
  const checksum = await xxh3_64(raw);
  if (checksum !== tile.checksum.value) {
    throw new Error('Checksum mismatch');
  }

  // 4. Parse uint16 little-endian
  const uint16View = new Uint16Array(
    raw.buffer, raw.byteOffset, tile.rows * tile.cols
  );

  // 5. Decode log1p to float32
  const decoded = new Float32Array(tile.rows * tile.cols);
  const clipValue = tile.encoding.clip_value || 50000;
  const logClip = Math.log1p(clipValue);

  for (let i = 0; i < uint16View.length; i++) {
    if (uint16View[i] === 0) {
      decoded[i] = 0;
    } else {
      const scaled = uint16View[i] / 65535;
      decoded[i] = Math.expm1(scaled * logClip);
    }
  }

  return decoded;
}
```

## API 端点

### GET /v1/heatmap/tiles

请求参数：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `token_id` | string | ✓ | 市场 token ID |
| `from_ts` | int64 | ✓ | 起始时间 (ms) |
| `to_ts` | int64 | ✓ | 结束时间 (ms) |
| `lod` | int | - | LOD: 250, 1000, 5000 (默认 250) |
| `tile_ms` | int | - | 瓦片跨度: 5000, 10000, 15000 (默认 10000) |
| `band` | string | - | FULL, BEST_5, BEST_10, BEST_20 (默认 FULL) |

响应示例：
```json
{
  "manifest": {
    "token_id": "0x1234...abcd",
    "from_ts": 1735960000000,
    "to_ts": 1735960090000,
    "lod_ms": 250,
    "tile_ms": 10000,
    "band": "FULL"
  },
  "tiles": [
    { "tile_id": "...", "t_start": 1735960000000, ... },
    { "tile_id": "...", "t_start": 1735960010000, ... },
    ...
  ]
}
```

## 服务端生成

### 预计算策略

1. **实时 LOD (250ms)**: 写入时立即生成
2. **降采样 LOD (1s, 5s)**: 后台 worker 定期聚合
3. **缓存**: 瓦片存入 `heatmap_tiles` 表，TTL 24h

### 生成伪代码

```python
def generate_tile(
    token_id: str,
    t_start: int,  # ms
    lod_ms: int,
    tile_ms: int,
    band: str
) -> HeatmapTile:
    # 1. 查询 book_bins 或降采样视图
    if lod_ms == 250:
        source = 'book_bins'
    elif lod_ms == 1000:
        source = 'book_bins_1s'
    else:
        source = 'book_bins_1m'  # 需要再聚合

    # 2. 构建矩阵
    t_end = t_start + tile_ms
    cols = tile_ms // lod_ms

    # 根据 band 确定价格范围
    if band == 'FULL':
        prices = get_full_price_range(token_id, t_start, t_end)
    else:
        prices = get_best_n_prices(token_id, t_start, t_end, band)

    rows = len(prices)
    matrix = np.zeros((rows, cols), dtype=np.float32)

    # 3. 填充数据
    for record in query(source, token_id, t_start, t_end):
        row = price_to_row(record.price, prices)
        col = (record.bucket_ts - t_start) // lod_ms
        matrix[row, col] = record.size

    # 4. 计算 clip_value (95th percentile)
    clip_value = np.percentile(matrix[matrix > 0], 95)

    # 5. 编码为 uint16
    encoded = encode_log1p(matrix, clip_value)

    # 6. 压缩
    payload = zstd.compress(encoded.tobytes(), level=3)

    # 7. 计算校验
    checksum = xxhash.xxh3_64(encoded.tobytes()).hexdigest()

    return HeatmapTile(...)
```

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-01 | 初始规范 |

---

*"看存在没意义，看反应才有意义"*
