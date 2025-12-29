# test_tags_api.py
import requests

# 获取所有 tags
response = requests.get(
    "https://gamma-api.polymarket.com/tags",
    params={'limit': 100},
    timeout=30
)

if response.status_code == 200:
    tags = response.json()
    
    print(f"获取到 {len(tags)} 个 tags\n")
    print("前 50 个 tags：\n")
    
    for i, tag in enumerate(tags[:50], 1):
        label = tag.get('label', 'N/A')
        slug = tag.get('slug', 'N/A')
        tag_id = tag.get('id', 'N/A')
        print(f"{i}. {label} (slug: {slug}, id: {tag_id})")
else:
    print(f"请求失败: {response.status_code}")