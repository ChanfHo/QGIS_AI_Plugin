"""统一管理远程样式知识库的查询、向量化和入库。"""

import argparse
import base64
import glob
import hashlib
import json
import os
import time
from typing import Dict, Iterable, List

import requests
from psycopg2.extras import Json

from .database import connect_database
from .model_config import API_KEY, BASE_URL, EMBEDDING_MODEL, EMBEDDING_URL, VISION_MODEL


STYLE_SCHEMA = "public"
STYLE_TABLE = "style_knowledge"
EXPECTED_VECTOR_DIMENSION = 1024
DEFAULT_BATCH_SIZE = 10


def _parse_vector(vector_text: str) -> List[float]:
    """将pgvector文本转换为浮点数列表。"""
    if not vector_text:
        return []
    return [float(value) for value in vector_text.strip("[]").split(",")]


def _vector_literal(vector: List[float]) -> str:
    """将浮点数列表转换为pgvector输入文本。"""
    return "[{}]".format(",".join(str(value) for value in vector))


def _embedding_text(entry: Dict) -> str:
    """按现有规则构造样式向量化文案。"""
    name = entry.get("name", "")
    keywords = " ".join(entry.get("keywords", []))
    return f"{name} {keywords}".strip()


def _validate_style_entry(entry: Dict) -> None:
    """校验远程样式知识表的必需字段。"""
    required_fields = {"name", "geometry_type", "keywords", "style_config", "vector"}
    missing_fields = required_fields.difference(entry)
    if missing_fields:
        raise ValueError(f"样式条目缺少字段: {sorted(missing_fields)}")
    if len(entry["vector"]) != EXPECTED_VECTOR_DIMENSION:
        raise ValueError(
            f"样式'{entry['name']}'的向量维度为{len(entry['vector'])}，"
            f"预期为{EXPECTED_VECTOR_DIMENSION}"
        )


def _build_style_key(entry: Dict) -> str:
    """基于样式原始字段生成稳定去重键。"""
    payload = {
        "name": entry["name"],
        "geometry_type": entry["geometry_type"],
        "keywords": entry["keywords"],
        "style_config": entry["style_config"],
    }
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_style_library() -> List[Dict]:
    """从远程PostgreSQL读取完整样式知识。"""
    sql = f"""
        SELECT name, geometry_type, keywords, style_config, vector::text
        FROM {STYLE_SCHEMA}.{STYLE_TABLE}
        ORDER BY source_order NULLS LAST, id
    """
    with connect_database() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
    return [
        {
            "name": row[0],
            "geometry_type": row[1],
            "keywords": row[2],
            "style_config": row[3],
            "vector": _parse_vector(row[4]),
        }
        for row in rows
    ]


def generate_embeddings(texts: List[str], text_type: str = "document") -> List[List[float]]:
    """使用当前Embedding模型批量生成向量。"""
    if not texts:
        return []
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": EMBEDDING_MODEL,
        "input": {"texts": texts},
        "parameters": {"text_type": text_type},
    }
    response = requests.post(
        EMBEDDING_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    embeddings = response.json()["output"]["embeddings"]
    embeddings.sort(key=lambda item: item["text_index"])
    return [item["embedding"] for item in embeddings]


def _attach_embeddings(entries: List[Dict], batch_size: int = DEFAULT_BATCH_SIZE) -> List[Dict]:
    """为待入库样式生成并附加向量。"""
    texts = [_embedding_text(entry) for entry in entries]
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        batch_vectors = generate_embeddings(batch)
        if len(batch_vectors) != len(batch):
            raise RuntimeError(f"第{start // batch_size + 1}批向量返回数量不一致")
        vectors.extend(batch_vectors)
        time.sleep(0.5)
    prepared_entries = []
    for entry, vector in zip(entries, vectors):
        prepared_entry = dict(entry)
        prepared_entry["vector"] = vector
        _validate_style_entry(prepared_entry)
        prepared_entries.append(prepared_entry)
    return prepared_entries


def upsert_style_entries(
    entries: Iterable[Dict],
    source_type: str,
    embedding_model: str = EMBEDDING_MODEL,
) -> List[int]:
    """在同一事务中批量新增或更新远程样式知识。"""
    sql = f"""
        INSERT INTO {STYLE_SCHEMA}.{STYLE_TABLE} (
            style_key, name, geometry_type, keywords, style_config, vector,
            source_type, embedding_model, source_order
        )
        VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
        ON CONFLICT (style_key) DO UPDATE SET
            vector = EXCLUDED.vector,
            source_type = EXCLUDED.source_type,
            embedding_model = EXCLUDED.embedding_model,
            source_order = {STYLE_SCHEMA}.{STYLE_TABLE}.source_order,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
    """
    row_ids = []
    with connect_database() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COALESCE(MAX(source_order), 0) FROM {STYLE_SCHEMA}.{STYLE_TABLE}"
            )
            next_source_order = cursor.fetchone()[0] + 1
            for source_order, entry in enumerate(entries, start=next_source_order):
                _validate_style_entry(entry)
                cursor.execute(
                    sql,
                    (
                        _build_style_key(entry),
                        entry["name"],
                        entry["geometry_type"],
                        Json(entry["keywords"]),
                        Json(entry["style_config"]),
                        _vector_literal(entry["vector"]),
                        source_type,
                        embedding_model,
                        source_order,
                    ),
                )
                row_ids.append(cursor.fetchone()[0])
    return row_ids


def add_manual_styles(entries: List[Dict]) -> List[int]:
    """向量化并写入手工定义的样式知识。"""
    return upsert_style_entries(_attach_embeddings(entries), source_type="manual")


def _read_file(path: str) -> str:
    """读取VLM提示所需的知识文件。"""
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


def _encode_image(image_path: str) -> str:
    """将图例图片编码为Base64。"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def extract_styles_from_image(image_path: str) -> List[Dict]:
    """使用VLM从图例图片提取样式结构。"""
    knowledge_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")
    schema = _read_file(os.path.join(knowledge_dir, "qgis_style_output_schema.txt"))
    examples = _read_file(os.path.join(knowledge_dir, "qgis_style_output_examples.txt"))
    system_prompt = """You are an expert GIS cartographer and QGIS style specialist.
Your task is to analyze a map legend image (containing symbols, line styles, color values like CMYK/RGB, and dimensions) and convert each map symbol into a standardized JSON style definition.

Output Format:
Return a strictly valid JSON list. Each item in the list represents a map symbol and must have the following structure:
{
  "name": "Name of the feature (e.g., Expressway, River)",
  "geometry_type": "point | line | polygon",
  "keywords": ["list", "of", "keywords", "for", "search"],
  "style_config": { ... }
}

Rules:
1. Extract the name of the feature from the text next to the symbol.
2. Identify the geometry type (point/line/polygon) based on the symbol shape.
3. Convert all colors (CMYK, RGB, or named) to Hex format (e.g., #FF0000). If CMYK is provided, convert it to RGB Hex accurately.
4. Extract line widths, sizes, and dimensions. Assume units are in millimeters if not specified, but QGIS usually takes map units or mm. Use 'width' or 'size' fields in 'symbol_layer_params'.
5. For 'style_config', fill in 'symbol_layer_params' with details like 'line_color', 'line_width', 'fill_color', 'pen_style' (solid, dash, etc.).
6. Leave empty fields in 'style_config' as per the schema defaults (empty dicts or lists) if not applicable.
7. Do NOT wrap the output in markdown code blocks. Just return the raw JSON string."""
    user_text = f"""Here is the QGIS Style Schema you must follow for the 'style_config' field:
{schema}

Here are some examples of how 'style_config' is populated:
{examples}

Please process the attached image. Extract all distinct map symbols/legends found in the image and return the JSON library."""
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(image_path)}"},
                    },
                ],
            },
        ],
        "max_tokens": 4000,
    }
    response = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    styles = json.loads(content.strip())
    if not isinstance(styles, list):
        raise ValueError("VLM样式结果必须是JSON列表")
    return styles


def add_vlm_images(image_paths: List[str]) -> List[int]:
    """识别图例图片并将样式统一写入远程数据库。"""
    entries = []
    for image_path in image_paths:
        print(f"正在识别图例: {image_path}")
        entries.extend(extract_styles_from_image(image_path))
        time.sleep(1)
    if not entries:
        return []
    return upsert_style_entries(_attach_embeddings(entries), source_type="vlm")


def _load_manual_entries(path: str) -> List[Dict]:
    """读取不含vector的手动样式JSON。"""
    with open(path, "r", encoding="utf-8") as file:
        entries = json.load(file)
    if not isinstance(entries, list) or not entries:
        raise ValueError("手动样式文件必须是非空JSON列表")
    return entries


def main() -> None:
    """提供统一的手动入库和VLM入库入口。"""
    parser = argparse.ArgumentParser(description="向远程PostgreSQL添加样式知识")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    manual_parser = subparsers.add_parser("manual")
    manual_parser.add_argument("json_path")
    vlm_parser = subparsers.add_parser("vlm")
    vlm_parser.add_argument("image_path")
    arguments = parser.parse_args()

    if arguments.mode == "manual":
        row_ids = add_manual_styles(_load_manual_entries(arguments.json_path))
    else:
        image_path = os.path.abspath(arguments.image_path)
        if os.path.isdir(image_path):
            patterns = ("*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG")
            image_paths = []
            for pattern in patterns:
                image_paths.extend(glob.glob(os.path.join(image_path, pattern)))
        else:
            image_paths = [image_path]
        row_ids = add_vlm_images(image_paths)
    print(f"已写入或更新{len(row_ids)}条样式知识")


if __name__ == "__main__":
    main()
