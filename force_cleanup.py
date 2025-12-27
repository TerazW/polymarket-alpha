"""
强制清理错误记录
"""
import sqlite3
from pathlib import Path

db_path = Path("data/market_sensemaking.db")

print(f"连接数据库: {db_path}")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 查看所有记录
print("\n清理前的所有记录:")
cur.execute("SELECT token_id, title FROM markets ORDER BY updated_at")
for i, (tid, title) in enumerate(cur.fetchall(), 1):
    print(f"  {i}. token_id='{tid[:30]}...' | {title[:40]}...")

# 删除 token_id 长度小于 10 的记录（正常的应该是 77 位数字）
cur.execute("DELETE FROM markets WHERE length(token_id) < 10")
deleted = cur.rowcount
print(f"\n已删除 {deleted} 条异常记录")

# 同时清理对应的 daily_metrics
cur.execute("DELETE FROM daily_metrics WHERE token_id = '['")
deleted_metrics = cur.rowcount
print(f"已删除 {deleted_metrics} 条关联的 daily_metrics")

conn.commit()

# 显示清理后的结果
print("\n清理后的记录:")
cur.execute("SELECT token_id, title, volume_24h FROM markets ORDER BY volume_24h DESC")
for i, (tid, title, vol) in enumerate(cur.fetchall(), 1):
    print(f"  {i}. {title[:50]:50s} | Vol: ${vol:,.0f}")

cur.execute("SELECT COUNT(*) FROM markets")
total = cur.fetchone()[0]
print(f"\n✅ 清理完成！当前共有 {total} 条市场记录")

conn.close()