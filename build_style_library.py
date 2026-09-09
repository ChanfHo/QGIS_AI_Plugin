from .model_config import API_KEY, BASE_URL, EMBEDDING_URL, VISION_MODEL, EMBEDDING_MODEL
import os
import json
import base64
import requests
import glob
import time

# Configuration
VL_MODEL_NAME = VISION_MODEL
EMBEDDING_MODEL_NAME = EMBEDDING_MODEL

def encode_image(image_path):
    """Encodes an image to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def read_file(path):
    """Reads a file content."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return ""

def get_embeddings(texts):
    """
    Generates embeddings for a list of texts using Qwen text-embedding-v4.
    """
    if not texts:
        return []

    print(f"Generating embeddings for {len(texts)} items...")
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": EMBEDDING_MODEL_NAME,
        "input": {
            "texts": texts
        },
        "parameters": {
            "text_type": "document"
        }
    }
    
    try:
        response = requests.post(EMBEDDING_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        
        if "output" in result and "embeddings" in result["output"]:
            # Sort embeddings by index to ensure order matches input
            embeddings_data = result["output"]["embeddings"]
            embeddings_data.sort(key=lambda x: x["text_index"])
            return [item["embedding"] for item in embeddings_data]
        else:
            print(f"Unexpected embedding response format: {result}")
            return []
            
    except Exception as e:
        print(f"Embedding API Request Failed: {e}")
        if 'response' in locals():
            print(response.text)
        return []

def extract_styles_from_image(image_path):
    """
    Sends the image to Qwen-VL-Max to extract style parameters 
    and returns the result as a list of dictionaries.
    """
    
    # 1. Load Schema and Context
    current_dir = os.path.dirname(os.path.abspath(__file__))
    kb_dir = os.path.join(current_dir, "knowledge_base")
    
    schema = read_file(os.path.join(kb_dir, "qgis_style_output_schema.txt"))
    examples = read_file(os.path.join(kb_dir, "qgis_style_output_examples.txt"))
    
    if not schema:
        print("Error: Could not find schema file.")
        return []

    # 2. Construct Prompt
    system_prompt = """You are an expert GIS cartographer and QGIS style specialist. 
Your task is to analyze a map legend image (containing symbols, line styles, color values like CMYK/RGB, and dimensions) and convert each map symbol into a standardized JSON style definition.

Output Format:
Return a strictly valid JSON list. Each item in the list represents a map symbol and must have the following structure:
{
  "name": "Name of the feature (e.g., Expressway, River)",
  "geometry_type": "point | line | polygon",
  "keywords": ["list", "of", "keywords", "for", "search"],
  "style_config": { ... } // This object MUST strictly follow the 'style_config' structure in the provided QGIS Style Schema.
}

Rules:
1. Extract the name of the feature from the text next to the symbol.
2. Identify the geometry type (point/line/polygon) based on the symbol shape.
3. Convert all colors (CMYK, RGB, or named) to Hex format (e.g., #FF0000). If CMYK is provided (e.g., M50Y80), convert it to RGB Hex accurately.
4. Extract line widths, sizes, and dimensions. Assume units are in millimeters if not specified, but QGIS usually takes map units or mm. Use 'width' or 'size' fields in 'symbol_layer_params'.
5. For 'style_config', fill in 'symbol_layer_params' with details like 'line_color', 'line_width', 'fill_color', 'pen_style' (solid, dash, etc.).
6. Leave empty fields in 'style_config' as per the schema defaults (empty dicts or lists) if not applicable.
7. Do NOT wrap the output in markdown code blocks (```json ... ```). Just return the raw JSON string.
"""

    user_content = f"""
Here is the QGIS Style Schema you must follow for the 'style_config' field:
{schema}

Here are some examples of how 'style_config' is populated (look at the 'style_config' part inside the examples):
{examples}

Please process the attached image. Extract all distinct map symbols/legends found in the image and return the JSON library.
"""

    # 3. Prepare API Request
    base64_image = encode_image(image_path)
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": VL_MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_content
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 4000
    }
    
    print(f"Sending request to {VL_MODEL_NAME} for image: {os.path.basename(image_path)}...")
    
    try:
        response = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        
        result = response.json()
        content = result['choices'][0]['message']['content']
        
        # Clean up potential markdown blocks
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "")
        elif content.startswith("```"):
            content = content.replace("```", "")
            
        content = content.strip()
        
        # Validate JSON
        try:
            parsed_json = json.loads(content)
            print(f"Extracted {len(parsed_json)} styles from {os.path.basename(image_path)}.")
            return parsed_json
            
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response for {os.path.basename(image_path)}.")
            print("Raw output:", content)
            return []
            
    except Exception as e:
        print(f"API Request Failed for {os.path.basename(image_path)}: {e}")
        if 'response' in locals():
            print(response.text)
        return []

def process_all_images(image_folder, output_path):
    """
    Iterates through all images, extracts styles, generates vectors, and saves to JSON.
    """
    all_styles = []
    
    # 1. Find images
    image_files = []
    for ext in ['*.png', '*.jpg', '*.jpeg', '*.PNG', '*.JPG', '*.JPEG']:
        image_files.extend(glob.glob(os.path.join(image_folder, ext)))
        
    if not image_files:
        print(f"No image files found in {image_folder}")
        return

    print(f"Found {len(image_files)} images to process.")

    # 2. Process each image (Extraction)
    for img_path in image_files:
        print(f"Processing: {img_path}")
        styles = extract_styles_from_image(img_path)
        if styles:
            all_styles.extend(styles)
        
        # Rate limit friendly pause
        time.sleep(1)

    print(f"Total extracted styles: {len(all_styles)}")
    if not all_styles:
        print("No styles extracted. Exiting.")
        return

    # 3. Generate Vectors (Batch)
    # Prepare texts: "Name Keyword1 Keyword2 ..."
    texts_to_embed = []
    for style in all_styles:
        name = style.get("name", "")
        keywords = " ".join(style.get("keywords", []))
        text = f"{name} {keywords}".strip()
        texts_to_embed.append(text)
    
    # Batch embedding (DashScope supports batch, but check limits. 
    # Usually 25 max per batch for some APIs, text-embedding-v4 supports more but let's be safe)
    BATCH_SIZE = 10
    vectors = []
    
    for i in range(0, len(texts_to_embed), BATCH_SIZE):
        batch_texts = texts_to_embed[i:i+BATCH_SIZE]
        print(f"Vectorizing batch {i//BATCH_SIZE + 1}...")
        batch_vectors = get_embeddings(batch_texts)
        if batch_vectors:
            vectors.extend(batch_vectors)
        else:
            # Handle error or empty return by padding with None or skipping
            print(f"Warning: Batch {i//BATCH_SIZE + 1} failed or returned empty.")
            vectors.extend([None] * len(batch_texts))
        time.sleep(0.5)

    # 4. Attach vectors to styles
    if len(vectors) != len(all_styles):
        print(f"Warning: Vector count ({len(vectors)}) mismatch with styles count ({len(all_styles)})")
    
    valid_styles = []
    for i, style in enumerate(all_styles):
        if i < len(vectors) and vectors[i] is not None:
            style["vector"] = vectors[i]
            valid_styles.append(style)
        else:
            print(f"Skipping style '{style.get('name')}' due to missing vector.")

    # 5. Save merged result
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(valid_styles, f, ensure_ascii=False, indent=4)
        print(f"Successfully saved {len(valid_styles)} vectorized styles to {output_path}")
        
    except Exception as e:
        print(f"Error saving output file: {e}")

if __name__ == "__main__":
    # Define paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    style_image_dir = os.path.join(current_dir, "style_image")
    output_json_path = os.path.join(current_dir, "knowledge_base", "style_library.json")
    
    print(f"Style Images Directory: {style_image_dir}")
    print(f"Output JSON Path: {output_json_path}")
    
    if not os.path.exists(style_image_dir):
        os.makedirs(style_image_dir)
        print(f"Created directory: {style_image_dir}")
        print("Please place your legend images (png, jpg) in this folder and run the script again.")
    else:
        process_all_images(style_image_dir, output_json_path)
