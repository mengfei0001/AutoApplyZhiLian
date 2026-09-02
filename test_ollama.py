import requests
import json

# Ollama API 的地址
url = "http://localhost:11434/api/generate"

# 请求的数据
payload = {
    "model": "qwen2.5:7b",
    "prompt": "用一句话解释什么是大语言模型。",
    "stream": False  # 设为 False，一次性获取完整响应
}

# 发送 POST 请求
response = requests.post(url, json=payload)

# 检查并打印结果
if response.status_code == 200:
    result = response.json()
    # 从返回的 JSON 中提取 'response' 字段
    print("模型回答：", result["response"])
else:
    print(f"请求失败，状态码：{response.status_code}")
    print("错误信息：", response.text)