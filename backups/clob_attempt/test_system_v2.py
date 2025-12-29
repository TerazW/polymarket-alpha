#!/usr/bin/env python
"""
Market Sensemaking v2.0 - End-to-End Test
测试完整的系统流程
"""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from dotenv import load_dotenv

def test_step(step_name: str, func):
    """执行测试步骤"""
    print(f"\n{'='*70}")
    print(f"🧪 {step_name}")
    print(f"{'='*70}")
    
    try:
        result = func()
        if result:
            print(f"\n✅ {step_name} - PASSED")
            return True
        else:
            print(f"\n❌ {step_name} - FAILED")
            return False
    except Exception as e:
        print(f"\n❌ {step_name} - ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_environment():
    """测试环境配置"""
    print("\n📋 Checking environment variables...")
    
    # 加载 .env
    load_dotenv()
    
    private_key = os.getenv("PRIVATE_KEY")
    database_url = os.getenv("DATABASE_URL")
    
    checks = []
    
    if private_key:
        print(f"   ✅ PRIVATE_KEY: {private_key[:10]}...{private_key[-6:]}")
        checks.append(True)
    else:
        print(f"   ❌ PRIVATE_KEY: Not found")
        checks.append(False)
    
    if database_url:
        print(f"   ✅ DATABASE_URL: Configured")
        checks.append(True)
    else:
        print(f"   ⚠️  DATABASE_URL: Not found (optional for API testing)")
        checks.append(None)
    
    return all(c for c in checks if c is not None)


def test_clob_client():
    """测试 CLOB API 客户端"""
    print("\n📡 Testing CLOB API Client...")
    
    try:
        from utils.polymarket_clob_api import PolymarketCLOBClient
        
        private_key = os.getenv("PRIVATE_KEY")
        
        if not private_key:
            print("   ❌ PRIVATE_KEY not set in .env")
            return False
        
        # 初始化客户端
        client = PolymarketCLOBClient(private_key)
        print(f"   ✅ Client initialized for: {client.address[:10]}...{client.address[-6:]}")
        
        # 初始化 API 凭证
        if client.initialize_api_credentials():
            print(f"   ✅ API credentials ready")
            print(f"      API Key: {client.api_key[:8]}...")
            return True
        else:
            print(f"   ❌ Failed to initialize API credentials")
            return False
            
    except ImportError as e:
        print(f"   ❌ Import error: {e}")
        print(f"   💡 Make sure polymarket_clob_api.py is in the project root")
        return False


def test_clob_trades():
    """测试获取交易数据"""
    print("\n📊 Testing trade data fetch...")
    
    try:
        from utils.polymarket_clob_api import PolymarketCLOBClient
        
        private_key = os.getenv("PRIVATE_KEY")
        client = PolymarketCLOBClient(private_key)
        
        # 使用一个测试市场
        test_market = "0x5543372edec0f4bd2a6d191a495b25dc69ed24f9c9d7018f"
        
        print(f"   🎯 Test market: {test_market[:10]}...")
        
        trades = client.get_trades_for_market(test_market, hours=1, limit=50)
        
        if trades:
            print(f"   ✅ Fetched {len(trades)} trades")
            
            # 检查数据结构
            sample = trades[0]
            required_fields = ['type', 'side', 'price', 'size', 'timestamp']
            
            missing = [f for f in required_fields if f not in sample]
            
            if missing:
                print(f"   ❌ Missing fields: {missing}")
                return False
            
            print(f"   ✅ All required fields present")
            
            # 检查 type 字段
            taker_count = sum(1 for t in trades if t['type'] == 'TAKER')
            maker_count = sum(1 for t in trades if t['type'] == 'MAKER')
            
            print(f"   📈 TAKER trades: {taker_count}")
            print(f"   📉 MAKER trades: {maker_count}")
            
            if taker_count > 0:
                print(f"   ✅ Aggressor data available")
                return True
            else:
                print(f"   ⚠️  No TAKER trades (may be low-volume market)")
                return True
        else:
            print(f"   ⚠️  No trades fetched (market may be inactive)")
            return True
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def test_metrics_calculation():
    """测试指标计算"""
    print("\n🧮 Testing metrics calculation...")
    
    try:
        from utils.metrics_v2 import calculate_all_metrics
        from datetime import datetime
        
        # 创建模拟数据
        print("   📝 Creating mock data...")
        
        mock_trades = [
            {'type': 'TAKER', 'side': 'BUY', 'price': 0.65, 'size': 100, 'timestamp': int(datetime.now().timestamp())},
            {'type': 'MAKER', 'side': 'SELL', 'price': 0.65, 'size': 100, 'timestamp': int(datetime.now().timestamp())},
            {'type': 'TAKER', 'side': 'BUY', 'price': 0.66, 'size': 150, 'timestamp': int(datetime.now().timestamp())},
            {'type': 'TAKER', 'side': 'SELL', 'price': 0.64, 'size': 80, 'timestamp': int(datetime.now().timestamp())},
            {'type': 'MAKER', 'side': 'BUY', 'price': 0.64, 'size': 80, 'timestamp': int(datetime.now().timestamp())},
        ]
        
        # 计算指标
        print("   🔄 Calculating metrics...")
        
        metrics = calculate_all_metrics(
            trades_all=mock_trades,
            trades_24h=mock_trades,
            current_price=0.65,
            days_remaining=30,
            band_width_7d_ago=0.15
        )
        
        # 检查关键指标
        key_metrics = ['UI', 'CER', 'AR', 'CS', 'status']
        
        print(f"\n   📊 Calculated metrics:")
        for metric in key_metrics:
            value = metrics.get(metric)
            if value is not None:
                if isinstance(value, float):
                    print(f"      {metric}: {value:.4f}")
                else:
                    print(f"      {metric}: {value}")
            else:
                print(f"      {metric}: None")
        
        # 验证
        if metrics.get('AR') is not None:
            print(f"\n   ✅ AR calculation working (aggressor data processed)")
        else:
            print(f"\n   ⚠️  AR is None (expected if no TAKER trades)")
        
        if metrics.get('status'):
            print(f"   ✅ Status determination working")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database():
    """测试数据库连接（可选）"""
    print("\n🗄️  Testing database connection...")
    
    try:
        from utils.db import get_session
        
        session = get_session()
        
        print("   ✅ Database connection established")
        
        session.close()
        return True
        
    except Exception as e:
        print(f"   ⚠️  Database not available: {e}")
        print(f"   💡 This is optional for API testing")
        return None


def main():
    """主测试流程"""
    print("\n" + "="*70)
    print("🚀 Market Sensemaking v2.0 - System Test")
    print("="*70)
    
    results = {}
    
    # 测试步骤
    results['Environment'] = test_step("Test 1: Environment Setup", test_environment)
    
    if results['Environment']:
        results['CLOB Client'] = test_step("Test 2: CLOB API Client", test_clob_client)
        
        if results['CLOB Client']:
            results['CLOB Trades'] = test_step("Test 3: Fetch Trade Data", test_clob_trades)
        else:
            print("\n⏭️  Skipping Test 3 (CLOB Client failed)")
            results['CLOB Trades'] = None
    else:
        print("\n⏭️  Skipping remaining tests (Environment setup failed)")
        results['CLOB Client'] = None
        results['CLOB Trades'] = None
    
    results['Metrics'] = test_step("Test 4: Metrics Calculation", test_metrics_calculation)
    results['Database'] = test_step("Test 5: Database Connection (Optional)", test_database)
    
    # 总结
    print("\n" + "="*70)
    print("📊 Test Summary")
    print("="*70)
    
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"\n   ✅ Passed: {passed}")
    print(f"   ❌ Failed: {failed}")
    print(f"   ⏭️  Skipped: {skipped}")
    
    print(f"\n   Detailed results:")
    for test_name, result in results.items():
        if result is True:
            status = "✅ PASS"
        elif result is False:
            status = "❌ FAIL"
        else:
            status = "⏭️  SKIP"
        print(f"      {test_name:<20}: {status}")
    
    # 最终结论
    print("\n" + "="*70)
    
    if failed == 0:
        print("🎉 All critical tests passed!")
        print("\n✅ Your system is ready to use.")
        print("\n📝 Next steps:")
        print("   1. Run: python migrate_database.py (if using database)")
        print("   2. Update your sync script to use CLOB API")
        print("   3. Start collecting accurate metrics!")
    else:
        print("⚠️  Some tests failed.")
        print("\n🔍 Troubleshooting:")
        
        if not results.get('Environment'):
            print("   → Check .env file configuration")
            print("   → Run: python setup_wallet.py")
        
        if not results.get('CLOB Client'):
            print("   → Verify PRIVATE_KEY in .env")
            print("   → Check internet connection")
        
        print("\n💡 See SETUP_GUIDE.md for detailed instructions")
    
    print("="*70 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏸️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
