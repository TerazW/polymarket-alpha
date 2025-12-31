"""
数据库迁移脚本
升级现有数据库以支持新功能：
- 添加 closed/active 字段
- 添加 categories 字段（JSON 数组）

运行方式：
    python migrate_schema.py
"""

import os
import sys

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.db import get_session, DATABASE_URL, engine, migrate_schema, IS_POSTGRES
from sqlalchemy import text


def run_migration():
    """执行完整迁移"""
    print("\n" + "=" * 60)
    print("🔧 Database Migration Script")
    print("=" * 60)
    print(f"\nDatabase: {'PostgreSQL' if IS_POSTGRES else 'SQLite'}")
    print(f"URL: {DATABASE_URL[:50]}...")
    
    # 运行迁移
    migrate_schema()
    
    # 验证
    session = get_session()
    try:
        print("\n🔍 Verifying schema...")
        
        if IS_POSTGRES:
            result = session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'markets'
                ORDER BY ordinal_position
            """)).fetchall()
        else:
            result = session.execute(text("PRAGMA table_info(markets)")).fetchall()
        
        columns = [row[0] if IS_POSTGRES else row[1] for row in result]
        print(f"   Columns: {columns}")
        
        required = ['token_id', 'market_id', 'title', 'category', 'categories', 
                    'current_price', 'volume_24h', 'closed', 'active']
        missing = [c for c in required if c not in columns]
        
        if missing:
            print(f"   ⚠️ Missing: {missing}")
        else:
            print("   ✅ All required columns present")
        
        # 统计
        total = session.execute(text("SELECT COUNT(*) FROM markets")).scalar() or 0
        print(f"\n   📊 Total markets: {total}")
        
        if total > 0:
            try:
                active = session.execute(text(
                    "SELECT COUNT(*) FROM markets WHERE closed = false OR closed IS NULL"
                )).scalar() or 0
                print(f"   📊 Active markets: {active}")
            except:
                pass
            
            try:
                with_cats = session.execute(text(
                    "SELECT COUNT(*) FROM markets WHERE categories IS NOT NULL AND categories != '[]'"
                )).scalar() or 0
                print(f"   📊 Markets with categories: {with_cats}")
            except:
                pass
        
        print("\n" + "=" * 60)
        print("✅ Migration completed successfully!")
        print("=" * 60 + "\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
