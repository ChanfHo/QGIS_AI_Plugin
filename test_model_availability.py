"""不启动QGIS，测试项目配置的千问模型是否可用。"""

import base64
import json
import sys
from pathlib import Path

import requests
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qgis_ai_private.model_config import (
    API_KEY,
    ASR_MODEL,
    BASE_URL,
    EMBEDDING_MODEL,
    EMBEDDING_URL,
    TEXT_MODEL,
    VISION_MODEL,
)


def test_text(client):
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": "只回复OK"}],
        max_tokens=8,
    )
    return response.choices[0].message.content


def test_vision(client):
    image_path = PROJECT_ROOT / "qgis_ai_private" / "icon.png"
    if not image_path.is_file():
        raise FileNotFoundError(f"找不到视觉测试图片: {image_path}")
    image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "只回复OK"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_data}},
            ],
        }],
        max_tokens=8,
    )
    return response.choices[0].message.content


def test_embedding():
    response = requests.post(
        EMBEDDING_URL,
        headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"},
        json={
            "model": EMBEDDING_MODEL,
            "input": {"texts": ["QGIS地图图层"]},
            "parameters": {"text_type": "query"},
        },
        timeout=30,
    )
    response.raise_for_status()
    vector = response.json()["output"]["embeddings"][0]["embedding"]
    if not vector:
        raise ValueError("Embedding接口未返回向量")
    return {"dimension": len(vector), "first_values": vector[:3]}


def test_asr():
    import dashscope
    from dashscope.audio.asr import Recognition, RecognitionCallback

    class Callback(RecognitionCallback):
        def on_event(self, result):
            pass

        def on_error(self, result):
            pass

    dashscope.api_key = API_KEY
    recognition = Recognition(
        model=ASR_MODEL,
        format="pcm",
        sample_rate=16000,
        callback=Callback(),
    )
    recognition.start()
    recognition.stop()
    return "ASR会话已成功建立并关闭"


def main():
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    tests = {
        "文本模型": test_text,
        "视觉模型": test_vision,
        "Embedding模型": test_embedding,
        "ASR模型": test_asr,
    }
    results = {}
    print("开始测试千问模型接口，不启动QGIS。")
    for name, test in tests.items():
        try:
            detail = test(client) if name in ("文本模型", "视觉模型") else test()
            results[name] = {"ok": True, "detail": detail}
            print(f"[成功] {name}: {detail}")
        except Exception as exc:
            results[name] = {"ok": False, "detail": str(exc)}
            print(f"[失败] {name}: {exc}")
    print("\n测试汇总：")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
