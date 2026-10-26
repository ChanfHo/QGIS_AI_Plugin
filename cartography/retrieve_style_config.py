from ..services import model_config
from .style_knowledge import load_style_library
from ..core.runtime_support import SanitizedLogger
logging = SanitizedLogger(__name__)
from ..services.credentials import CredentialError, model_post
import numpy as np

from difflib import SequenceMatcher
from typing import Dict, Optional


# Core vector RAG retrieval.
def retrieve_style_config(query: str, geometry_type: str = None, inferred_keyword: str = None) -> Optional[Dict]:
    """Retrieve the best matching style for the query and geometry type using hybrid vector similarity and keyword matching."""
    model_config.get_api_key()

    # Configuration.
    EMBEDDING_MODEL_NAME = model_config.EMBEDDING_MODEL
    SIMILARITY_THRESHOLD = 0.45  # Vector similarity threshold.

    # 1. Load the style library from remote PostgreSQL.
    try:
        library = load_style_library()
    except Exception as e:
        logging.error("Failed to load style library from PostgreSQL: %s", e)
        return None
    if not library:
        return None

    # 2. Construct the query text.
    # Prefer LLM-extracted generalized geographic semantics for vector retrieval to remove place-name noise.
    # For example, infer a provincial boundary category from a province boundary name and embed that category.
    search_text = inferred_keyword if inferred_keyword else query

    # 3. Get the query embedding.
    query_vector = None
    try:
        headers = {
            "Content-Type": "application/json"
        }
        payload = {
            "model": EMBEDDING_MODEL_NAME,
            "input": {"texts": [search_text]},
            "parameters": {"text_type": "query"}
        }
        response = model_post(model_config.EMBEDDING_URL, headers=headers, json=payload, timeout=5)
        if response.status_code == 200:
            result = response.json()
            if "output" in result and "embeddings" in result["output"]:
                query_vector = result["output"]["embeddings"][0]["embedding"]
    except CredentialError as exc:
        if exc.error_code not in ("MODEL_NETWORK_FAILED", "MODEL_SERVER_FAILED"):
            raise
        logging.error("Embedding API connection failed; using keyword matching")
    except Exception:
        logging.error("Embedding API connection failed")
        # Fall back to keyword-only matching if the API fails.
        pass

    # 4. Retrieve using vectors and rule filters.
    best_match = None
    best_score = -1.0

    # Prepare NumPy vectors for faster calculation when a query vector exists.
    if query_vector:
        q_vec = np.array(query_vector)
        q_norm = np.linalg.norm(q_vec)

    for item in library:
        # Calculate the match score.
        score = 0.0

        # A. Vector similarity (primary weight).
        item_vector = item.get("vector")
        if query_vector and item_vector:
            i_vec = np.array(item_vector)
            i_norm = np.linalg.norm(i_vec)
            if q_norm > 0 and i_norm > 0:
                cosine_sim = np.dot(q_vec, i_vec) / (q_norm * i_norm)
                score = cosine_sim
        else:
            # Fallback: fuzzy keyword matching.
            query_lower = query.lower()
            name_score = SequenceMatcher(None, query_lower, item.get("name", "").lower()).ratio()
            score = name_score * 0.8  # Reduce the weight.

            keywords = item.get("keywords", [])
            for kw in keywords:
                if kw.lower() in query_lower:
                    score = max(score, 0.9)  # Give exact keyword matches a higher score.
                elif inferred_keyword and (inferred_keyword.lower() in kw.lower() or kw.lower() in inferred_keyword.lower()):
                    score = max(score, 0.85)

        if score > best_score:
            best_score = score
            best_match = item

    logging.info(f"RAG Best Match: {best_match.get('name') if best_match else 'None'}, Score: {best_score}")

    if best_score >= SIMILARITY_THRESHOLD and best_match:
        return best_match.get("style_config")

    return None
