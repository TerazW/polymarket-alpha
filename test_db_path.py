"""
测试脚本：验证 SQLite 实际打开的文件路径
"""
import os
import sys
from pathlib import Path
import sqlite3

# 添加项目根目录到 path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.db import DATABASE_URL

print("=" * 60)
print("当前工作目录 (CWD):", os.getcwd())
print("DATABASE_URL:", DATABASE_URL)
print("=" * 60)

# 解析 DATABASE_URL
if DATABASE_URL.startswith("sqlite:///"):
    db_path_str = DATABASE_URL.replace("sqlite:///", "")
    db_path = Path(db_path_str)
    
    print(f"\n相对/绝对路径: {db_path}")
    print(f"是否为绝对路径: {db_path.is_absolute()}")
    print(f"解析后的绝对路径: {db_path.resolve()}")
    print(f"文件是否存在: {db_path.exists()}")
    
    if db_path.exists():
        print(f"文件大小: {db_path.stat().st_size / 1024:.2f} KB")
        
        # 连接并查询
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # 检查表
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cur.fetchall()
        print(f"\n数据库中的表: {[t[0] for t in tables]}")
        
        # 如果有 markets 表，查询数量
        if any('markets' in t for t in tables):
            cur.execute("SELECT COUNT(*) FROM markets")
            count = cur.fetchone()[0]
            print(f"markets 表记录数: {count}")
            
            # 显示前几条记录
            cur.execute("SELECT id, question FROM markets LIMIT 3")
            markets = cur.fetchall()
            print("\n前3个市场:")
            for m in markets:
                print(f"  - {m[0]}: {m[1][:50]}...")
        
        conn.close()
    else:
        print("\n⚠️ 数据库文件不存在！")

print("=" * 60)