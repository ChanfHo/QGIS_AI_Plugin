from .model_config import API_KEY, EMBEDDING_URL, EMBEDDING_MODEL
import os
import json
import logging
import requests
import numpy as np

from difflib import SequenceMatcher
from typing import Dict, Optional


# --- RAG 核心检索函数 (向量版) ---
def retrieve_style_config(query: str, geometry_type: str = None, inferred_keyword: str = None) -> Optional[Dict]:
    """
    根据用户输入的查询词和几何类型，从知识库中检索最匹配的样式配置。
    使用混合检索策略：向量相似度 + 关键词匹配。
    """
    # 配置
    EMBEDDING_MODEL_NAME = EMBEDDING_MODEL
    SIMILARITY_THRESHOLD = 0.45  # 向量相似度阈值

    # 1. 加载样式库
    current_dir = os.path.dirname(os.path.abspath(__file__))
    library_path = os.path.join(current_dir, "knowledge_base", "style_library.json")

    if not os.path.exists(library_path):
        logging.warning(f"Style library not found at {library_path}")
        return None

    try:
        with open(library_path, 'r', encoding='utf-8') as f:
            library = json.load(f)
    except Exception as e:
        logging.error(f"Failed to load style library: {e}")
        return None

    if not library:
        return None

    # 2. 构造查询文本 (Query Construction)
    # 策略: 优先使用 LLM 提取的泛化地理语义进行向量检索，去除具体地名带来的噪音
    # 例如: "湖北省省界" 推断出 "省级行政区界线" -> 使用 "省级行政区界线" 向量化
    search_text = inferred_keyword if inferred_keyword else query

    # 3. 获取 Query 向量
    query_vector = None
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": EMBEDDING_MODEL_NAME,
            "input": {"texts": [search_text]},
            "parameters": {"text_type": "query"}
        }
        response = requests.post(EMBEDDING_URL, headers=headers, json=payload, timeout=5)
        if response.status_code == 200:
            result = response.json()
            if "output" in result and "embeddings" in result["output"]:
                query_vector = result["output"]["embeddings"][0]["embedding"]
    except Exception as e:
        logging.error(f"Embedding API Error: {e}")
        # API 失败时回退到仅关键词匹配
        pass

    # 4. 执行检索 (Vector + Rule Filter)
    best_match = None
    best_score = -1.0

    # 准备 Numpy 向量以加速计算 (如果有 Query 向量)
    if query_vector:
        q_vec = np.array(query_vector)
        q_norm = np.linalg.norm(q_vec)

    for item in library:
        # (1) 计算匹配分数
        score = 0.0

        # A. 向量相似度 (主要权重)
        item_vector = item.get("vector")
        if query_vector and item_vector:
            i_vec = np.array(item_vector)
            i_norm = np.linalg.norm(i_vec)
            if q_norm > 0 and i_norm > 0:
                cosine_sim = np.dot(q_vec, i_vec) / (q_norm * i_norm)
                score = cosine_sim
        else:
            # 回退：关键词模糊匹配
            query_lower = query.lower()
            name_score = SequenceMatcher(None, query_lower, item.get("name", "").lower()).ratio()
            score = name_score * 0.8  # 降权

            keywords = item.get("keywords", [])
            for kw in keywords:
                if kw.lower() in query_lower:
                    score = max(score, 0.9)  # 关键词全匹配给高分
                elif inferred_keyword and (inferred_keyword.lower() in kw.lower() or kw.lower() in inferred_keyword.lower()):
                    score = max(score, 0.85)

        if score > best_score:
            best_score = score
            best_match = item

    logging.info(f"RAG Best Match: {best_match.get('name') if best_match else 'None'}, Score: {best_score}")

    if best_score >= SIMILARITY_THRESHOLD and best_match:
        return best_match.get("style_config")

    return None
