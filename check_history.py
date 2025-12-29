# check_history.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.db import get_session
from sqlalchemy import text

def check_historical_data():
    session = get_session()
    try:
        # 检查是否有多天的数据
        query = text("""
            SELECT 
                DATE(date) as record_date,
                COUNT(*) as market_count,
                MIN(created_at) as first_record,
                MAX(created_at) as last_record
            FROM daily_metrics
            GROUP BY DATE(date)
            ORDER BY record_date DESC
            LIMIT 10
        """)
        
        result = session.execute(query)
        rows = result.fetchall()
        
        print("\n" + "="*70)
        print("📊 Historical Data Check")
        print("="*70)
        
        if not rows:
            print("❌ No data found in daily_metrics table")
            print("\n💡 This means you need to run sync.py daily to build history")
            return False
        
        print(f"\n✅ Found data for {len(rows)} different dates:\n")
        
        for row in rows:
            print(f"Date: {row[0]} | Markets: {row[1]:>4} | "
                  f"First: {row[2]} | Last: {row[3]}")
        
        if len(rows) >= 7:
            print(f"\n✅ Great! You have {len(rows)} days of history")
            print("   → Can build Consensus Band Evolution chart")
        elif len(rows) > 1:
            print(f"\n⚠️  Only {len(rows)} days of history")
            print("   → Need at least 7 days for full CER calculation")
            print("   → Can still show partial evolution")
        else:
            print(f"\n⚠️  Only 1 day of data")
            print("   → Run sync.py daily to build history")
            print("   → CER calculation needs 7-day history")
        
        # 检查某个市场的历史记录
        print("\n" + "="*70)
        print("📈 Sample Market History Check")
        print("="*70)
        
        sample_query = text("""
            SELECT token_id, COUNT(DISTINCT date) as days_tracked
            FROM daily_metrics
            GROUP BY token_id
            ORDER BY days_tracked DESC
            LIMIT 5
        """)
        
        result = session.execute(sample_query)
        samples = result.fetchall()
        
        if samples:
            print("\nTop markets by tracking history:")
            for token_id, days in samples:
                print(f"  {token_id[:20]}... → {days} days")
        
        return len(rows) >= 7
        
    finally:
        session.close()

if __name__ == "__main__":
    has_history = check_historical_data()
    
    if not has_history:
        print("\n" + "="*70)
        print("💡 Recommendation:")
        print("="*70)
        print("1. Set up a daily cron job to run: python jobs/sync.py --markets 5000")
        print("2. After 7 days, you'll have full historical data")
        print("3. Then we can enable the Consensus Band Evolution feature")
        print("="*70)
        