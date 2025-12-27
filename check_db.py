from utils.db import get_session
from sqlalchemy import text

print("Checking database...\n")

session = get_session()

# 1. 检查市场数量
markets_count = session.execute(text('SELECT COUNT(*) FROM markets')).fetchone()
print(f"📊 Total markets in DB: {markets_count[0]}\n")

# 2. 检查指标数量
metrics_count = session.execute(text('SELECT COUNT(*) FROM daily_metrics')).fetchone()
print(f"📊 Total metrics in DB: {metrics_count[0]}\n")

# 3. 显示所有市场
print("Markets list:")
print("-" * 80)
result = session.execute(text('''
    SELECT title, current_price, volume_24h, updated_at 
    FROM markets 
    ORDER BY volume_24h DESC 
    LIMIT 20
''')).fetchall()

for i, r in enumerate(result, 1):
    title = r[0][:60] if r[0] else "Unknown"
    price = r[1] * 100 if r[1] else 0
    volume = r[2] if r[2] else 0
    print(f"{i}. {title}...")
    print(f"   Price: {price:.1f}% | Volume: ${volume:,.0f}")
    print()

# 4. 显示指标统计
print("\n" + "=" * 80)
print("Status distribution:")
print("-" * 80)
status_stats = session.execute(text('''
    SELECT status, COUNT(*) as count
    FROM daily_metrics
    WHERE date = DATE('now')
    GROUP BY status
''')).fetchall()

for status, count in status_stats:
    print(f"{status}: {count}")

session.close()

print("\n✅ Check completed!")