"""
查找项目中所有的 .db 文件
"""
import os
from pathlib import Path

project_root = Path(__file__).parent
print(f"搜索目录: {project_root}")
print("=" * 60)

db_files = list(project_root.rglob("*.db"))

if db_files:
    print(f"找到 {len(db_files)} 个 .db 文件:\n")
    for db in db_files:
        size_kb = db.stat().st_size / 1024
        print(f"📁 {db.relative_to(project_root)}")
        print(f"   绝对路径: {db}")
        print(f"   大小: {size_kb:.2f} KB")
        print()
else:
    print("⚠️ 没有找到 .db 文件")

print("=" * 60)