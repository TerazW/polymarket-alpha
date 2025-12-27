"""
检查数据库表结构和内容
"""
import sys
from pathlib import Path
import sqlite3

# 添加项目根目录到 path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.db import DATABASE_URL

db_path_str = DATABASE_URL.replace("sqlite:///", "")
db_path = Path(db_path_str)

print("=" * 60)
print(f"数据库: {db_path.resolve()}")
print("=" * 60)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 查看 markets 表结构
print("\n📋 markets 表结构:")
cur.execute("PRAGMA table_info(markets)")
columns = cur.fetchall()
for col in columns:
    print(f"  - {col[1]} ({col[2]})")

# 查看所有记录
print(f"\n📊 markets 表内容 (共 {cur.execute('SELECT COUNT(*) FROM markets').fetchone()[0]} 条):")
cur.execute("SELECT * FROM markets")
records = cur.fetchall()

if records:
    # 获取列名
    column_names = [desc[0] for desc in cur.description]
    print(f"\n列名: {column_names}\n")
    
    for i, record in enumerate(records, 1):
        print(f"记录 {i}:")
        for col_name, value in zip(column_names, record):
            # 截断太长的字段
            if isinstance(value, str) and len(value) > 100:
                value = value[:100] + "..."
            print(f"  {col_name}: {value}")
        print()
else:
    print("  (空表)")

# 检查其他表
print("\n📊 其他表的记录数:")
for table in ['trade_histogram', 'daily_metrics', 'status_changes']:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    print(f"  - {table}: {count} 条")

conn.close()
print("=" * 60)