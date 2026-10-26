from ..core.runtime_support import log_message
import json
from difflib import SequenceMatcher
from typing import List, Tuple, Dict, Any

from qgis.core import QgsMapLayer, QgsVectorLayer, QgsRasterLayer, Qgis, QgsProject, QgsWkbTypes

from ..data.fetch_data import execute_fetch_task
from ..cartography.spatial_process import execute_geoprocessing_task
from ..cartography.style_management import set_layer_style
from ..cartography.retrieve_style_config import retrieve_style_config
from .prompts import (
    agent_a_prompt,
    agent_b_prompt,
    agent_c_prompt,
    agent_d_prompt,
    STYLE_EXTRACTION_PROMPT,
)
from ..services.chat_model import ModelCallError, ModelResponseFormatError, call_qwen_json, validate_object
from ..core.error_handling import error_from_message, failure, execution_boundary, sanitize
from ..services.credentials import CredentialError


def _model_failure_result(exc, failed_node):
    """Convert model exceptions into distinguishable execution results."""
    error = error_from_message(exc, failed_node, getattr(exc, "attempts", 0))
    return {
        "is_process_complete": False,
        "possible_problem": error["user_title"],
        "error_state": error,
    }

# Extract names and fields from QgsMapLayer objects.
def get_layer_name_and_fields(layers: List[QgsMapLayer]) -> Tuple[List[str], str]:
    """Extract all layer names and field lists from QgsMapLayer objects."""
    available_layer_names = []
    layers_info_list = []

    for layer in layers:
        layer_name = layer.name()
        available_layer_names.append(layer_name)
        info_string = f"【{layer_name}】"

        if isinstance(layer, QgsVectorLayer):
            field_names = [field.name() for field in layer.fields()]
            info_string += ' (fields: {v0})'.format(v0=', '.join(field_names))

        layers_info_list.append(info_string)

    return available_layer_names, " | ".join(layers_info_list)


# Extract layer names and types.
def get_layer_info(layers: List[QgsMapLayer]) -> str:
    """Extract layer names and vector/raster types from QgsMapLayer objects."""
    layers_info_list = []
    for layer in layers:
        layer_name = layer.name()
        type_str = 'Unknown type'
        if isinstance(layer, QgsVectorLayer):
            type_str = "vector"
        elif isinstance(layer, QgsRasterLayer):
            type_str = "raster"
        
        layers_info_list.append('[{v0}] (type: {v1})'.format(v0=layer_name, v1=type_str))
        
    return " | ".join(layers_info_list)


# Fuzzy layer-name matching helper for LLM calls.
def fuzzy_match(input_name: str, available_names: List[str]) -> str or None:
    """Fuzzy-match an input layer or field name."""
    if not isinstance(input_name, str) or not available_names: return None

    best_match_name = None
    best_ratio = 0.0
    match_threshold = 0.65

    for layer_name in available_names:
        ratio = SequenceMatcher(None, input_name.lower(), layer_name.lower()).ratio()

        # Handle common abbreviations.
        layer_norm = layer_name.replace("图层", "")
        input_norm = input_name.replace("图层", "")
        ratio_norm = SequenceMatcher(None, input_norm.lower(), layer_norm.lower()).ratio()
        ratio = max(ratio, ratio_norm)

        if ratio > best_ratio:
            best_ratio = ratio
            best_match_name = layer_name

    if best_ratio >= match_threshold:
        return best_match_name

    return None


# Agent A execution.
@execution_boundary("agent_a", "INTERNAL_ERROR")
def run_agent_a(user_text: str, progress_callback=None, operation_results=None, requests_override=None) -> Dict[str, Any]:
    """Agent A: parse data acquisition tasks with the LLM and acquire the data."""
    # 1. Use Agent A's predefined prompt, including the database schema.
    final_prompt = agent_a_prompt

    # 3. Call the LLM.
    try:
        # Build the complete prompt: system prompt + user input.
        full_prompt = f"{final_prompt}\n\nUser input: {user_text}"
        fetch_request = requests_override if requests_override else call_qwen_json(full_prompt)
        for request in fetch_request if isinstance(fetch_request, list) else [fetch_request]:
            validate_object(request, {"source_type": str, "query_params": dict})

    except Exception as e:
        return _model_failure_result(e, "agent_a")

    # Wrap results in a list to support multiple tasks.
    if not isinstance(fetch_request, list):
        fetch_request = [fetch_request]
        
    if len(fetch_request) == 0:
        return failure("MISSING_PARAMETER", "agent_a", 'The AI returned an empty task list.')

    results = []
    layer_names = []

    operation_results = operation_results if operation_results is not None else []
    if operation_results and (len(fetch_request) <= len(operation_results) or any(
            fetch_request[i] != item["request"] for i, item in enumerate(operation_results))):
        return failure("INVALID_CONTRACT", "agent_a", 'The recovery plan changed completed data operations. Keep completed requests unchanged and correct only the failed request.')
    for index, req in enumerate(fetch_request):
        if index < len(operation_results):
            previous = operation_results[index]
            results.append(previous["result"])
            layer_names.append(previous["target_name"])
            continue
        # Check whether the LLM returned an error message.
        if "error_message" in req:
            return failure("MISSING_PARAMETER", "agent_a", req["error_message"])

        source_type = req.get("source_type")
        query_params = req.get("query_params", {})

        if not source_type or not query_params:
            return failure("MISSING_PARAMETER", "agent_a", 'JSON is missing required parameters (source_type/query_params).')
            
        log_message(sanitize('Data query task parameters: {v0}'.format(v0=sanitize(req))), tag='AI_AGENT_DEBUG', level=Qgis.Info)

        # Call the execution function.
        fetch_result = execute_fetch_task(source_type, query_params, progress_callback)

        if isinstance(fetch_result, dict):
            fetch_result["request_sequence"] = fetch_request
            return fetch_result

        if fetch_result.startswith("Success"):
            target_name = query_params.get('target_name', '新图层')
            results.append(fetch_result)
            layer_names.append(target_name)
            operation_results.append({"request": req, "result": fetch_result, "target_name": target_name})
        else:
            return failure("DATA_ACCESS_FAILED", "agent_a", fetch_result.replace("Error: ", ""))

    # Return the summary after all tasks succeed.
    return {"is_process_complete": True, "tool_result": " | ".join(results), "layer_name": ", ".join(layer_names)}


# Agent B execution.
@execution_boundary("agent_b", "INTERNAL_ERROR")
def run_agent_b(user_text: str, layers: List[QgsMapLayer]) -> Dict[str, Any]:
    """Agent B: parse spatial analysis with the LLM, fuzzy-match layer names and run QGIS spatial analysis."""

    # 1. Get current layer information.
    current_project = QgsProject.instance()
    # Refresh the layer list reference.
    current_layers_list = list(current_project.mapLayers().values())
    available_names, layer_info_str = get_layer_name_and_fields(current_layers_list)

    # 2. Build the dynamic prompt.
    dynamic_sys_prompt = agent_b_prompt + f"\n\n[Available layers in the current QGIS project]\n{layer_info_str}\n\nSelect layer names from the list above."

    # 3. Call the LLM.
    try:
        full_prompt = f"{dynamic_sys_prompt}\n\nUser input: {user_text}"
        analysis_request = call_qwen_json(full_prompt)
        validate_object(analysis_request, {"alg_id": str, "params": dict})
    except Exception as e:
        return _model_failure_result(e, "agent_b")

    log_message(sanitize('agent_b task: {v0}'.format(v0=sanitize(analysis_request))), tag='AI_AGENT_DEBUG', level=Qgis.Info)

    if "error_message" in analysis_request:
        return failure("MISSING_PARAMETER", "agent_b", analysis_request["error_message"])

    alg_id = analysis_request.get("alg_id")
    params = analysis_request.get("params", {})
    layers_to_remove = analysis_request.get("layers_to_remove", [])  # Get the removal list.

    if not alg_id or not params:
        return failure("MISSING_PARAMETER", "agent_b", 'Missing required parameters alg_id or params.')

    # 5. Fuzzy-match layer parameters.
    matched_params = params.copy()
    # Match against available_names.
    for k, v in params.items():
        if isinstance(v, str) and (k.upper() in ['INPUT', 'OVERLAY', 'JOIN', 'CLIP'] or k.endswith('_LAYER')):
            matched_name = fuzzy_match(v, available_names)
            if not matched_name:
                return failure("LAYER_NOT_FOUND", "agent_b", 'Input layer matching failed', target_layer=v, parameters=params)
            matched_params[k] = matched_name

    # 6. Execute spatial analysis.
    analysis_result = execute_geoprocessing_task(alg_id, matched_params)

    # 7. Handle results and subsequent cleanup.
    if isinstance(analysis_result, dict):
        return analysis_result

    if analysis_result.startswith("Success"):
        deleted_log = []
        # If analysis succeeded and layers need removal.
        if layers_to_remove:
            for del_target in layers_to_remove:
                # Fuzzy-match again to resolve abbreviated layer names.
                matched_del_name = fuzzy_match(del_target, available_names)
                if matched_del_name:
                    # Get all project layers with this name.
                    layers_to_del = current_project.mapLayersByName(matched_del_name)
                    if layers_to_del:
                        # Avoid deleting the newly generated layer.
                        # Find newly generated layer IDs, if any.
                        new_layer_name = matched_params.get("CUSTOM_LAYER_NAME")
                        
                        ids_to_remove = []
                        for l in layers_to_del:
                            ids_to_remove.append(l.id())
                            
                        if new_layer_name == matched_del_name and len(layers_to_del) > 1:
                            # If new and removed layers share a name and multiple matches exist, retain the newest layer.
                            ids_to_remove.pop() # Remove the final ID (the new layer) from the list.
                            
                        if ids_to_remove:
                            current_project.removeMapLayers(ids_to_remove)
                            deleted_log.append(matched_del_name)

        # Build the final return message.
        final_msg = analysis_result
        if deleted_log:
            final_msg += ' (original layers removed as requested: {v0})'.format(v0=', '.join(deleted_log))

        return {"is_process_complete": True, "tool_result": final_msg}
    else:
        return failure("PROCESSING_FAILED", "agent_b", analysis_result.replace("Error: ", ""))


# Agent C execution.
@execution_boundary("agent_c", "INTERNAL_ERROR")
def run_agent_c(user_text: str, layers: List[QgsMapLayer]) -> dict:
    """Agent C: identify the target layer and semantics, retrieve the best vector style template, then build a dynamic prompt to generate the final configuration."""

    # Get current layer information.
    current_project = QgsProject.instance()
    current_layers_list = list(current_project.mapLayers().values())
    available_names, _ = get_layer_name_and_fields(current_layers_list)
    layer_info_str = get_layer_info(current_layers_list)

    # Step 1: Extract the target layer and semantics.
    target_layer_name = None
    content_inference = None
    
    try:
        extract_sys_prompt = STYLE_EXTRACTION_PROMPT
        extract_input = f"{extract_sys_prompt}\n\nUser input: {user_text}\nAvailable layers: {available_names}"
        extract_json = call_qwen_json(extract_input)
        validate_object(extract_json, {"target_layer_name": str, "content_inference": str})
        target_layer_name = extract_json.get("target_layer_name")
        content_inference = extract_json.get("content_inference")
        
        # Validate that the extracted layer name exists.
        target_layer_name = fuzzy_match(target_layer_name, available_names)
        
    except (ModelCallError, ModelResponseFormatError, CredentialError) as e:
        return _model_failure_result(e, "agent_c")
    except Exception as e:
        log_message(sanitize(f"Agent C Extraction Error: {e}"), tag='AI_AGENT_DEBUG', level=Qgis.Warning)
        # Fallback: Proceed without specific extraction

    # Step 2: Vector retrieval.
    retrieved_style = None
    if target_layer_name:
        # Get layer geometry type.
        target_layer = None
        target_layers = current_project.mapLayersByName(target_layer_name)
        if target_layers:
            target_layer = target_layers[0]
        
        geo_type_str = "unknown"
        if target_layer and isinstance(target_layer, QgsVectorLayer):
            geo_type_int = target_layer.geometryType()
            if geo_type_int == QgsWkbTypes.PointGeometry:
                geo_type_str = "point"
            elif geo_type_int == QgsWkbTypes.LineGeometry:
                geo_type_str = "line"
            elif geo_type_int == QgsWkbTypes.PolygonGeometry:
                geo_type_str = "polygon"
        
        # Call retrieval.
        log_message(sanitize(f"RAG Retrieval Start: {target_layer_name}, {geo_type_str}, {content_inference}"), tag='AI_AGENT_DEBUG', level=Qgis.Info)
        retrieved_style = retrieve_style_config(query=target_layer_name, geometry_type=geo_type_str, inferred_keyword=content_inference)

    # Step 3: Build the dynamic prompt.
    rag_context = ""
    if retrieved_style:
        log_message(sanitize(f"RAG Style Found: {retrieved_style}"), tag='AI_AGENT_DEBUG', level=Qgis.Info)
        rag_context = (
            f"\n\n[Reference style template (RAG Retrieval)]\n"
            f"Semantic analysis retrieved a similar reference style configuration:\n"
            f"{json.dumps(retrieved_style, ensure_ascii=False)}\n"
            f"Rules:\n"
            f"1. If the user specified no color/symbol details, adopt the reference style directly.\n"
            f"2. Explicit user requirements (e.g. red) override the corresponding reference style parameters.\n"
        )
    else:
        log_message(sanitize("RAG Style Not Found or Below Threshold"), tag='AI_AGENT_DEBUG', level=Qgis.Info)

    # Build the dynamic prompt.
    dynamic_agent_c_prompt = agent_c_prompt + f"\n\n[Available layers in the current QGIS project]\n{layer_info_str}." + rag_context

    # Step 4: Generate the configuration.
    try:
        full_prompt = f"{dynamic_agent_c_prompt}\n\nUser input: {user_text}"
        style_request = call_qwen_json(full_prompt)
        validate_object(style_request, {"layer_name_input": str, "style_type": str, "style_config": dict})

    except Exception as e:
        return _model_failure_result(e, "agent_c")

    target_layer = None
    if content_inference and "content_inference" not in style_request:
        style_request["content_inference"] = content_inference
    log_message(sanitize('Agent C final request: {v0}'.format(v0=sanitize(style_request))), tag='AI_AGENT_DEBUG', level=Qgis.Info)

    if "error_message" in style_request:
        return failure("MISSING_PARAMETER", "agent_c", style_request["error_message"])

    # 1. Match layer names for final validation.
    layer_input_name = style_request.get("layer_name_input")
    matched_layer_name = fuzzy_match(layer_input_name, available_names) 

    if not matched_layer_name:
        if target_layer_name:
            matched_layer_name = target_layer_name
        else:
            return failure("LAYER_NOT_FOUND", "agent_c", 'The target layer does not exist', target_layer=layer_input_name)

    # 2. Match fields for categorized / graduated / annotation styles.
    style_type = style_request.get("style_type")
    style_config = style_request.get("style_config", {})

    if style_type in ['categorized', 'graduated', 'annotation']:
        field_intends = style_config.get("field_intend", [])  # Get the candidate field names inferred by the LLM.
        
        matched_layers_list = current_project.mapLayersByName(matched_layer_name)
        if matched_layers_list and len(matched_layers_list) > 0:
            target_layer = matched_layers_list[0]
            
        log_message(sanitize(f"matched_layer_name: {matched_layer_name}"), tag='AI_AGENT_DEBUG', level=Qgis.Info)
        if not target_layer:
            return failure("LAYER_NOT_FOUND", "agent_c", 'The layer object is missing.')

        real_fields = [f.name() for f in target_layer.fields()]
        matched_field = None

        # Try matching each field candidate provided by the LLM.
        for intend in field_intends:
            matched_field = fuzzy_match(intend, real_fields)  # Reuse the fuzzy matching helper.
            if matched_field:
                log_message(sanitize("Field matched: '{v0}' -> '{v1}'".format(v0=intend, v1=matched_field)), tag='AI_AGENT_DEBUG',
                                         level=Qgis.Info)
                break

        if matched_field:
            # Write the matched real field name into config for style_management.
            style_config["target_field_actual"] = matched_field
        else:
            return failure("FIELD_NOT_FOUND", "agent_c", 'Candidate fields could not be matched', target_layer=matched_layer_name, target_field=field_intends, parameters=style_request)

    # 3. Apply the style.
    # Pass the corrected layer_name and full request to style_management.
    style_result = set_layer_style(matched_layer_name, style_request)

    if isinstance(style_result, dict):
        return style_result

    if style_result.startswith("Success"):
        return {"is_process_complete": True, "tool_result": style_result}
    else:
        return failure("STYLE_FAILED", "agent_c", style_result.replace("Error: ", ""))


# Agent D execution.
@execution_boundary("agent_d", "INTERNAL_ERROR")
def run_agent_d(user_text: str, layers: List[QgsMapLayer]) -> Dict[str, Any]:
    """Agent D: parse view and layout tasks without executing them; return the task list to the main thread."""
    try:
        # 1. Call the LLM.
        full_prompt = f"{agent_d_prompt}\n\nUser input: {user_text}"
        layout_requests = call_qwen_json(full_prompt)
        if not isinstance(layout_requests, (dict, list)) or not layout_requests:
            return failure("INVALID_CONTRACT", "agent_d", 'Layout tasks must be a non-empty object or list')
        for request in layout_requests if isinstance(layout_requests, list) else [layout_requests]:
            validate_object(request, {"action_type": str})
        log_message(sanitize(f"Agent D JSON Output: {json.dumps(sanitize(layout_requests), ensure_ascii=False)}"), tag='AI_AGENT_DEBUG', level=Qgis.Info)

        if isinstance(layout_requests, dict):
            layout_requests = [layout_requests]

        return {
            "is_process_complete": True,
            "tasks": layout_requests,  # Return the task bundle.
            "tool_result": 'Instruction parsed; executing in the main interface...'
        }

    except Exception as e:
        return _model_failure_result(e, "agent_d")
