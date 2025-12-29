import requests

# 尝试常见的主分类 tag slugs
main_categories = [
    'politics',
    'sports', 
    'crypto',
    'finance',
    'business',
    'economy',
    'tech',
    'culture',
    'geopolitics',
    'science'
]

print("测试主分类 tags：\n")

for category in main_categories:
    try:
        response = requests.get(
            "https://gamma-api.polymarket.com/events",
            params={
                'tag_slug': category,
                'limit': 1,
                'closed': 'false'
            },
            timeout=10
        )
        
        if response.status_code == 200:
            events = response.json()
            if events:
                print(f"✅ {category}: 找到 events")
            else:
                print(f"❌ {category}: 无结果")
        else:
            print(f"❌ {category}: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ {category}: {str(e)}")