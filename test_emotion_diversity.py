import requests
import json
import re
import time

BASE_URL = "http://127.0.0.1:8000"

def test_emotion(prompt, expected_emotion_hint=None):
    url = f"{BASE_URL}/api/v1/message"
    headers = {"Content-Type": "application/json"}
    payload = {
        "message": {
            "type": "text",
            "content": prompt
        },
        "conversation_id": "test_emotion_diversity_v1"
    }

    print(f"\n[-] 发送消息: {prompt}")
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        if response.status_code == 200:
            data = response.json()
            reply = data.get("response", "")
            emotion_field = data.get("emotion", "None")
            
            # Extract emotion from text if present (redundant check, but good for verification)
            text_emotion = "None"
            emo_match = re.search(r'\[EMO:\s*\{?([a-zA-Z0-9_]+)\}?\]', reply)
            if not emo_match:
                emo_match = re.search(r'\{([a-zA-Z]+)\}', reply)
            if not emo_match:
                emo_match = re.search(r'\[([a-zA-Z]+)\]', reply)
                
            if emo_match:
                text_emotion = emo_match.group(1)

            print(f"    [+] 回复内容: {reply[:100]}..." if len(reply) > 100 else f"    [+] 回复内容: {reply}")
            print(f"    [+] API返回情绪: {emotion_field}")
            print(f"    [+] 文本提取情绪: {text_emotion}")
            
            return emotion_field, text_emotion
        else:
            print(f"    [!] 请求失败: {response.status_code} - {response.text}")
            return None, None
    except Exception as e:
        print(f"    [!] 发生错误: {e}")
        return None, None

def main():
    print("=== 开始测试 LLM 情绪响应多样性 ===")
    
    test_cases = [
        ("你好，今天天气真好！", "happy"),
        ("我今天丢了钱包，好难过。", "sad/lost"),
        ("你为什么一直不听我的话？我很生气！", "angry"),
        ("这件衣服真漂亮，我好喜欢！", "excited/happy"),
        ("我被老板骂了，心里很委屈。", "wronged"),
        ("你可以做我的女朋友吗？", "shy/coquetry"),
        ("哼，不理你了。", "coquetry/angry")
    ]
    
    results = []
    
    for prompt, hint in test_cases:
        api_emo, text_emo = test_emotion(prompt, hint)
        results.append({
            "prompt": prompt,
            "api_emo": api_emo,
            "text_emo": text_emo
        })
        time.sleep(1) # Avoid rate limiting if any

    print("\n=== 测试总结 ===")
    emotions_found = set()
    for res in results:
        emo = res['api_emo']
        if emo and emo != "None":
            emotions_found.add(emo)
        print(f"输入: {res['prompt'][:10]}... | 情绪: {res['api_emo']}")

    print(f"\n捕获到的不同情绪数量: {len(emotions_found)}")
    print(f"情绪列表: {emotions_found}")
    
    if len(emotions_found) <= 1:
        print("\n[警告] LLM 似乎只返回单一情绪，可能需要检查 Prompt 或 模型配置。")
    else:
        print("\n[成功] LLM 能够返回多种情绪。")

if __name__ == "__main__":
    main()
