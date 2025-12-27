from utils.db import get_session
from sqlalchemy import text

print("Clearing database...\n")

session = get_session()

# 清空表
session.execute(text('DELETE FROM markets'))
session.execute(text('DELETE FROM daily_metrics'))
session.commit()

print("✅ Database cleared!\n")

# 验证
markets = session.execute(text('SELECT COUNT(*) FROM markets')).fetchone()
metrics = session.execute(text('SELECT COUNT(*) FROM daily_metrics')).fetchone()

print(f"Markets: {markets[0]}")
print(f"Metrics: {metrics[0]}")

session.close()