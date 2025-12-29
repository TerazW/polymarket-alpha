"""
数据库迁移脚本 - Metrics v2.0
添加新的指标字段到 daily_metrics 表
"""

from sqlalchemy import text
from utils.db import engine, get_session

def migrate_database():
    """
    执行数据库迁移
    
    新增字段：
    - VAH (Value Area High)
    - VAL (Value Area Low) 
    - mid_probability (共识带中点)
    - band_width (带宽)
    - POMD (最大分歧点)
    - AR (Aggressive Ratio)
    - volume_delta (成交量差值)
    - ECR (Expected Convergence Rate)
    - ACR (Actual Convergence Rate)
    """
    
    print("\n" + "="*70)
    print("📊 Database Migration - Metrics v2.0")
    print("="*70)
    
    session = get_session()
    
    try:
        print("\n🔍 Checking current schema...")
        
        # 检查表是否存在
        check_table = text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'daily_metrics'
            ORDER BY ordinal_position
        """)
        
        result = session.execute(check_table)
        existing_columns = {row[0] for row in result.fetchall()}
        
        print(f"   Found {len(existing_columns)} existing columns")
        
        # 定义新字段
        new_columns = {
            'vah': 'DECIMAL(10,4)',
            'val': 'DECIMAL(10,4)',
            'mid_probability': 'DECIMAL(10,4)',
            'band_width': 'DECIMAL(10,4)',
            'pomd': 'DECIMAL(10,4)',
            'ar': 'DECIMAL(10,4)',
            'volume_delta': 'DECIMAL(20,8)',
            'ecr': 'DECIMAL(10,4)',
            'acr': 'DECIMAL(10,4)',
        }
        
        # 检查哪些字段需要添加
        columns_to_add = {}
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                columns_to_add[col_name] = col_type
        
        if not columns_to_add:
            print("\n✅ All columns already exist! No migration needed.")
            return True
        
        print(f"\n📝 Need to add {len(columns_to_add)} new columns:")
        for col_name in columns_to_add:
            print(f"   - {col_name}")
        
        # 执行迁移
        print("\n🚀 Executing migration...")
        
        for col_name, col_type in columns_to_add.items():
            try:
                alter_query = text(f"""
                    ALTER TABLE daily_metrics 
                    ADD COLUMN {col_name} {col_type}
                """)
                
                session.execute(alter_query)
                session.commit()
                
                print(f"   ✅ Added column: {col_name}")
                
            except Exception as e:
                # 如果字段已存在，忽略错误
                if "already exists" in str(e).lower():
                    print(f"   ⚠️  Column {col_name} already exists, skipping")
                else:
                    raise e
        
        print("\n" + "="*70)
        print("✅ Migration completed successfully!")
        print("="*70)
        
        # 显示最终 schema
        print("\n📋 Updated schema:")
        result = session.execute(check_table)
        
        print("\n   Column Name          Data Type")
        print("   " + "-"*40)
        for row in result.fetchall():
            col_name, col_type = row
            print(f"   {col_name:<20} {col_type}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        session.rollback()
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        session.close()


def rollback_migration():
    """
    回滚迁移（删除新增的列）
    
    警告：这会删除所有 v2 指标数据！
    """
    print("\n" + "="*70)
    print("⚠️  Database Rollback - Metrics v2.0")
    print("="*70)
    
    confirm = input("\n⚠️  This will DELETE all v2 metrics data! Continue? (yes/no): ").strip().lower()
    
    if confirm != "yes":
        print("\n✅ Rollback cancelled.")
        return False
    
    session = get_session()
    
    try:
        # 要删除的列
        columns_to_remove = [
            'vah', 'val', 'mid_probability', 'band_width', 'pomd',
            'ar', 'volume_delta', 'ecr', 'acr'
        ]
        
        print("\n🔄 Rolling back migration...")
        
        for col_name in columns_to_remove:
            try:
                alter_query = text(f"""
                    ALTER TABLE daily_metrics 
                    DROP COLUMN IF EXISTS {col_name}
                """)
                
                session.execute(alter_query)
                session.commit()
                
                print(f"   ✅ Removed column: {col_name}")
                
            except Exception as e:
                print(f"   ⚠️  Error removing {col_name}: {e}")
        
        print("\n✅ Rollback completed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Rollback failed: {e}")
        session.rollback()
        return False
        
    finally:
        session.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--rollback":
        rollback_migration()
    else:
        migrate_database()
