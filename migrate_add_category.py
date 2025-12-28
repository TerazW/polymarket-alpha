"""
数据库迁移脚本 - 确保 category 字段存在且有默认值
用于从旧版本升级到支持分类的版本
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db import get_session, DATABASE_URL, engine
from sqlalchemy import text

def migrate_add_category():
    """添加或更新 category 字段"""
    session = get_session()
    
    try:
        print("\n🔧 Database Migration - Add Category Support")
        print("="*60)
        print(f"Database: {DATABASE_URL[:50]}...")
        
        # 检查数据库类型
        is_postgres = "postgresql" in DATABASE_URL
        
        if is_postgres:
            # PostgreSQL: 检查字段是否存在
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'markets' AND column_name = 'category'
            """)
            result = session.execute(check_query).fetchone()
            
            if not result:
                print("\n➕ Adding 'category' column...")
                session.execute(text("""
                    ALTER TABLE markets 
                    ADD COLUMN category VARCHAR(50) DEFAULT 'Other'
                """))
                session.commit()
                print("✅ 'category' column added")
            else:
                print("\n✅ 'category' column already exists")
            
            # 更新 NULL 值为 'Other'
            print("\n🔄 Updating NULL categories to 'Other'...")
            update_query = text("""
                UPDATE markets 
                SET category = 'Other' 
                WHERE category IS NULL OR category = ''
            """)
            result = session.execute(update_query)
            session.commit()
            print(f"✅ Updated {result.rowcount} markets")
            
        else:
            # SQLite: 检查字段是否存在
            check_query = text("PRAGMA table_info(markets)")
            result = session.execute(check_query).fetchall()
            columns = [row[1] for row in result]
            
            if 'category' not in columns:
                print("\n➕ Adding 'category' column...")
                session.execute(text("""
                    ALTER TABLE markets 
                    ADD COLUMN category VARCHAR(50) DEFAULT 'Other'
                """))
                session.commit()
                print("✅ 'category' column added")
            else:
                print("\n✅ 'category' column already exists")
            
            # 更新 NULL 值为 'Other'
            print("\n🔄 Updating NULL categories to 'Other'...")
            update_query = text("""
                UPDATE markets 
                SET category = 'Other' 
                WHERE category IS NULL OR category = ''
            """)
            result = session.execute(update_query)
            session.commit()
            print(f"✅ Updated {result.rowcount} markets")
        
        # 验证结果
        print("\n🔍 Verification...")
        stats_query = text("""
            SELECT category, COUNT(*) as count
            FROM markets
            GROUP BY category
            ORDER BY count DESC
        """)
        result = session.execute(stats_query)
        
        print(f"\n📊 Category Distribution:")
        total = 0
        for cat, count in result.fetchall():
            print(f"   {cat}: {count}")
            total += count
        print(f"   Total: {total}")
        
        print(f"\n{'='*60}")
        print("✅ Migration completed successfully!")
        print(f"{'='*60}\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        session.rollback()
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()


if __name__ == "__main__":
    success = migrate_add_category()
    sys.exit(0 if success else 1)
