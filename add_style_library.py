import os
import json
import requests

# Configuration
API_KEY = "sk-a2cddd46f8924031b2888c97c73c6e43"
EMBEDDING_URL = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
EMBEDDING_MODEL_NAME = "text-embedding-v4"


def get_embedding(text):
    """
    Generates embedding for a single text using Qwen text-embedding-v4.
    """
    if not text:
        return None

    print(f"Generating embedding for: '{text}'...")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": EMBEDDING_MODEL_NAME,
        "input": {
            "texts": [text]
        },
        "parameters": {
            "text_type": "document"
        }
    }

    try:
        response = requests.post(EMBEDDING_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        if "output" in result and "embeddings" in result["output"] and len(result["output"]["embeddings"]) > 0:
            return result["output"]["embeddings"][0]["embedding"]
        else:
            print(f"Unexpected embedding response format: {result}")
            return None

    except Exception as e:
        print(f"Embedding API Request Failed: {e}")
        if 'response' in locals():
            print(response.text)
        return None


def add_style_to_library():
    """
    Reads existing library, vectorizes the new manual entry, and appends it to the library.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_json_path = os.path.join(current_dir, "knowledge_base", "style_library.json")

    # =========================================================================
    # 手动在此处修改你要添加的样式配置
    # =========================================================================
    new_style_entry = {
        "name": "市级行政区划注记",
        "geometry_type": "polygon",
        "keywords": [
            "行政区划",
            "市级",
            "设区市",
            "界线",
            "标注"
        ],
        "style_config": {
            "layer_name_input": "市级行政区划注记",
            "style_type": "annotation",
            "style_config": {
                "field_intend": ["city_name", "city", "name"],
                "edit_style_config": {},
                "categories_config": {},
                "graduated_config": {},
                "annotation_config": {
                    "font_family": "Microsoft YaHei",
                    "font_size": 11.5,
                    "font_color": "#000000",
                    "is_bold": True,
                    "is_italic": False,
                    "draw_buffer": False,
                    "buffer_size": 1.0,
                    "buffer_color": "#FFFFFF",
                    "mode": "horizontal",
                    "offset_xy": [
                        5.0,
                        5.0
                    ]
                },
                "raster_config": {},
                "symbol_layer_params": {}
            }
        }
    }
    # =========================================================================

    # 1. 向量化文本 (Name + Keywords)
    name = new_style_entry.get("name", "")
    keywords = " ".join(new_style_entry.get("keywords", []))
    text_to_embed = f"{name} {keywords}".strip()

    vector = get_embedding(text_to_embed)
    if not vector:
        print("Failed to generate vector. Aborting addition.")
        return

    new_style_entry["vector"] = vector

    # 2. 读取现有 JSON
    existing_library = []
    if os.path.exists(output_json_path):
        try:
            with open(output_json_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if content.strip():
                    existing_library = json.loads(content)
            print(f"Loaded existing library with {len(existing_library)} entries.")
        except Exception as e:
            print(f"Error reading existing library: {e}")
            print("Aborting to prevent accidental overwrite.")
            return
    else:
        print(f"Library not found at {output_json_path}. Creating new library.")

    # 3. 检查是否重复 (根据 name 简单判断，可选)
    # for item in existing_library:
    #     if item.get("name") == new_style_entry.get("name"):
    #         print(f"Warning: An entry with name '{new_style_entry.get('name')}' already exists.")
    #         # break

    # 4. 追加并保存
    existing_library.append(new_style_entry)

    try:
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(existing_library, f, ensure_ascii=False, indent=4)
        print(f"Successfully added '{new_style_entry.get('name')}' to library.")
        print(f"Total entries now: {len(existing_library)}")
    except Exception as e:
        print(f"Error saving updated library: {e}")


if __name__ == "__main__":
    add_style_to_library()
