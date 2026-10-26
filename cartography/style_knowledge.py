"""Runtime style reads and embeddings, with lazy legacy maintenance exports."""
from typing import Dict, List
from ..services.credentials import model_post
from ..data.database import connect_database, database_is_read_only
from ..services import model_config

STYLE_SCHEMA = "public"
STYLE_TABLE = "style_knowledge"
EXPECTED_VECTOR_DIMENSION = 1024
DEFAULT_BATCH_SIZE = 10

def _parse_vector(vector_text: str) -> List[float]:
    """Convert pgvector text to a list of floats."""
    if not vector_text:
        return []
    return [float(value) for value in vector_text.strip("[]").split(",")]


def load_style_library() -> List[Dict]:
    """Read complete style knowledge from remote PostgreSQL."""
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
    """Generate vectors in batches using the current embedding model."""
    if not texts:
        return []
    headers = {
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_config.EMBEDDING_MODEL,
        "input": {"texts": texts},
        "parameters": {"text_type": text_type},
    }
    response = model_post(
        model_config.EMBEDDING_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )
    embeddings = response.json()["output"]["embeddings"]
    embeddings.sort(key=lambda item: item["text_index"])
    return [item["embedding"] for item in embeddings]


def __getattr__(name):
    if name in ('_vector_literal', '_embedding_text', '_validate_style_entry', '_build_style_key', '_attach_embeddings', 'upsert_style_entries', 'add_manual_styles', '_read_file', '_encode_image', 'extract_styles_from_image', 'add_vlm_images', '_load_manual_entries', 'main'):
        if database_is_read_only():
            raise AttributeError("Style maintenance is unavailable in the public read-only distribution")
        from ..maintenance import style_knowledge_tools
        return getattr(style_knowledge_tools, name)
    raise AttributeError(name)


if __name__ == "__main__":
    if database_is_read_only():
        raise SystemExit("Style maintenance is available in the private distribution only.")
    from ..maintenance.style_knowledge_tools import main
    main()
