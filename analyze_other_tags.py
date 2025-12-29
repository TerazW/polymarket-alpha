# analyze_other_tags.py
from utils.db import get_session
from sqlalchemy import text
import json

session = get_session()

# 获取一些 Other 分类的市场
query = text("""
    SELECT title, category 
    FROM markets 
    WHERE category = 'Other'
    LIMIT 20
""")

result = session.execute(query)
print("Other 分类的市场示例：\n")
for i, (title, cat) in enumerate(result.fetchall(), 1):
    print(f"{i}. {title[:60]}...")
    print(f"   Category: {cat}\n")

session.close()
