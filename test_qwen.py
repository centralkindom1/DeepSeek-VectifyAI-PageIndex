import openai
import requests
import json
import os

# 配置信息
API_KEY = ""
BASE_URL = ""
MODEL_NAME = "Qwen2.5-32B"

def test_with_openai_library():
    print(f"--- 方法 1: 使用 OpenAI 库测试 ---")
    # 强制禁用代理，防止 Win7 系统代理干扰
    os.environ['HTTP_PROXY'] = ''
    os.environ['HTTPS_PROXY'] = ''
    
    client = openai.OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
    )
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "你好，请回答‘连接成功’"}],
            temperature=0.6,
            timeout=30
        )
        print("✅ OpenAI 库连接成功！")
        print(f"模型回复: {response.choices[0].message.content}")
    except Exception as e:
        print(f"❌ OpenAI 库连接失败: {e}")

def test_with_requests_raw():
    print(f"\n--- 方法 2: 使用底层 Requests 库测试 (绕过所有 SDK) ---")
    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": "你好"}],
        "temperature": 0.6,
        "stream": False
    }
    
    try:
        # verify=False 忽略 SSL 证书错误（Win7 常见问题）
        response = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
        if response.status_code == 200:
            print("✅ 底层 API 调用成功！")
            print(f"返回内容: {response.json()['choices'][0]['message']['content']}")
        else:
            print(f"❌ API 返回错误状态码: {response.status_code}")
            print(f"错误详情: {response.text}")
    except Exception as e:
        print(f"❌ 底层网络连接失败: {e}")

if __name__ == "__main__":
    print(f"开始测试内网模型: {MODEL_NAME}")
    print(f"目标 URL: {BASE_URL}")
    print("-" * 30)
    test_with_openai_library()

    test_with_requests_raw()
