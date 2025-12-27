#!/usr/bin/env python
"""
数据库初始化脚本
在 Render 部署后运行一次
"""
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.db import init_db

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("✅ Database initialized successfully!")