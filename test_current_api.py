from utils.polymarket_api import PolymarketAPI
import inspect

api = PolymarketAPI()

# 检查是否有新方法
if hasattr(api, 'get_markets_by_categories'):
    print("✅ 新方法存在：get_markets_by_categories")
    print(f"   官方分类：{[cat[1] for cat in api.main_categories]}")
else:
    print("❌ 新方法不存在！文件还没替换成功！")
    print("   当前方法：", [m for m in dir(api) if not m.startswith('_')])