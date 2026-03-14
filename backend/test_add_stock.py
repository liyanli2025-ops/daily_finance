import requests

# 测试添加自选股 API
url = "http://localhost:8000/api/stocks/watchlist"

data = {
    "code": "688535",
    "name": "华海诚科",
    "market": "A"
}

try:
    response = requests.post(url, json=data)
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.text}")
except Exception as e:
    print(f"请求失败: {e}")
