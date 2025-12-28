"""
数据库迁移脚本
添加 closed 和 active 字段到 markets 表
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db import get_session
from sqlalchemy import text

def migrate_database():
    """添加缺失的字段"""
    session = get_session()
    
    try:
        print("\n🔧 Database Migration")
        print("="*60)
        
        # 检查字段是否存在
        result = session.execute(text("PRAGMA table_info(markets)")).fetchall()
        columns = [row[1] for row in result]
        
        print(f"\n当前 markets 表的列：")
        for col in columns:
            print(f"  - {col}")
        
        # 添加 closed 字段
        if 'closed' not in columns:
            print("\n➕ 添加 'closed' 列...")
            session.execute(text("""
                ALTER TABLE markets 
                ADD COLUMN closed BOOLEAN DEFAULT 0
            """))
            session.commit()
            print("✅ 'closed' 列已添加")
        else:
            print("\n✅ 'closed' 列已存在")
        
        # 添加 active 字段
        if 'active' not in columns:
            print("➕ 添加 'active' 列...")
            session.execute(text("""
                ALTER TABLE markets 
                ADD COLUMN active BOOLEAN DEFAULT 1
            """))
            session.commit()
            print("✅ 'active' 列已添加")
        else:
            print("✅ 'active' 列已存在")
        
        # 验证
        print("\n🔍 验证迁移结果...")
        result = session.execute(text("PRAGMA table_info(markets)")).fetchall()
        columns = [row[1] for row in result]
        
        print(f"\n更新后的 markets 表列：")
        for col in columns:
            print(f"  - {col}")
        
        if 'closed' in columns and 'active' in columns:
            print(f"\n{'='*60}")
            print("✅ 数据库迁移成功！")
            print(f"{'='*60}\n")
            return True
        else:
            print("\n❌ 迁移失败！")
            return False
            
    except Exception as e:
        print(f"\n❌ 迁移出错: {e}")
        session.rollback()
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()


if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)
