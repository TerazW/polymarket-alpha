"""
清理错误的旧记录（token_id = '['）
"""
import sqlite3
from pathlib import Path

db_path = Path("data/market_sensemaking.db")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("清理前:")
cur.execute("SELECT COUNT(*) FROM markets")
print(f"  markets: {cur.fetchone()[0]} 条")

# 删除错误记录
cur.execute("DELETE FROM markets WHERE token_id = '['")
deleted = cur.rowcount

conn.commit()

print(f"\n已删除 {deleted} 条错误记录\n")

print("清理后:")
cur.execute("SELECT COUNT(*) FROM markets")
print(f"  markets: {cur.fetchone()[0]} 条")

# 显示所有市场
print("\n当前市场列表:")
cur.execute("SELECT token_id, title FROM markets ORDER BY volume_24h DESC")
for i, (tid, title) in enumerate(cur.fetchall(), 1):
    print(f"  {i}. {title[:60]}... (token: {tid[:20]}...)")

conn.close()
print("\n✅ 清理完成!")