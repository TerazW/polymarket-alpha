# check_categories.py
from utils.db import get_session
from sqlalchemy import text

session = get_session()

query = text("""
    SELECT 
        COALESCE(category, 'NULL') as category,
        COUNT(*) as count
    FROM markets
    GROUP BY category
    ORDER BY count DESC
""")

result = session.execute(query)

print("\n分类分布：\n")
print(f"{'分类':<20} {'数量':>10}")
print("=" * 35)

total = 0
for category, count in result:
    # 处理 NULL 值
    cat_name = category if category else 'NULL'
    print(f"{cat_name:<20} {count:>10}")
    total += count

print("=" * 35)
print(f"{'总计':<20} {total:>10}\n")

session.close()