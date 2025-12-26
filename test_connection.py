import openai
import os
import json

# 配置你的内网 API 信息
API_KEY = ""  # 如果内网不需要KEY，可以随便填个"None"
BASE_URL = ""
MODEL_NAME = "DeepSeek-R1"

def test_api():
    print(f"正在连接内网服务器: {BASE_URL}...")
    
    # 初始化客户端
    client = openai.OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL
    )

    try:
        # 尝试非流式请求（先验证通不通）
        print(f"发送测试请求 [模型: {MODEL_NAME}]...")
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "你好"}
            ],
            stream=False, # 先测试非流式，更易观察报错
            temperature=0.6,
            timeout=30    # 设置30秒超时
        )
        
        print("\n--- 连接成功！---")
        print(f"模型回复: {response.choices[0].message.content}")
        print("------------------")
        
    except openai.APIConnectionError as e:
        print("\n[错误] 无法连接到服务器！")
        print(f"请检查 Win7 是否能访问: {BASE_URL}")
        print(f"报错详情: {e}")
    except openai.AuthenticationError as e:
        print("\n[错误] API Key 验证失败！")
        print(f"报错详情: {e}")
    except Exception as e:
        print(f"\n[错误] 发生未知错误: {type(e).__name__}")
        print(f"详情: {e}")

if __name__ == "__main__":

    test_api()
