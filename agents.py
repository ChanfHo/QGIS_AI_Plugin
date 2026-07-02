import json
import logging
from difflib import SequenceMatcher
from typing import List, Tuple, Dict, Any

import requests
from qgis.core import QgsMapLayer, QgsVectorLayer, QgsRasterLayer, Qgis, QgsMessageLog, QgsProject, QgsWkbTypes

from .fetch_data import execute_fetch_task
from .spatial_process import execute_geoprocessing_task
from .style_management import set_layer_style
from .retrieve_style_config import retrieve_style_config
from .prompts import agent_a_prompt, agent_b_prompt, agent_c_prompt, agent_d_prompt
from .chat_model import call_qwen_with_prompt

# --- 辅助函数：图层名称与字段提取 (从 QgsMapLayer 对象列表提取名称和字段) ---
def get_layer_name_and_fields(layers: List[QgsMapLayer]) -> Tuple[List[str], str]:
    """
    从 QgsMapLayer 对象列表中提取所有图层名称及其字段列表。
    """
    available_layer_names = []
    layers_info_list = []

    for layer in layers:
        layer_name = layer.name()
        available_layer_names.append(layer_name)
        info_string = f"【{layer_name}】"

        if isinstance(layer, QgsVectorLayer):
            field_names = [field.name() for field in layer.fields()]
            info_string += f" (字段: {', '.join(field_names)})"

        layers_info_list.append(info_string)

    return available_layer_names, " | ".join(layers_info_list)


# --- 辅助函数：图层信息提取 (提取图层名称和类型) ---
def get_layer_info(layers: List[QgsMapLayer]) -> str:
    """
    从 QgsMapLayer 对象列表中提取图层名称和属性（矢量/栅格）。
    """
    layers_info_list = []
    for layer in layers:
        layer_name = layer.name()
        type_str = "未知类型"
        if isinstance(layer, QgsVectorLayer):
            type_str = "矢量"
        elif isinstance(layer, QgsRasterLayer):
            type_str = "栅格"
        
        layers_info_list.append(f"【{layer_name}】(类型: {type_str})")
        
    return " | ".join(layers_info_list)


# --- 辅助函数：图层名称模糊匹配 (工具函数，供 LLM 调用) ---
def fuzzy_match(input_name: str, available_names: List[str]) -> str or None:
    """对输入的图层名称或字段名称进行模糊匹配。"""
    if not available_names: return None

    best_match_name = None
    best_ratio = 0.0
    match_threshold = 0.65

    for layer_name in available_names:
        ratio = SequenceMatcher(None, input_name.lower(), layer_name.lower()).ratio()

        # 常见省略词处理
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


# --- 核心执行函数 (Agent A) ---
def run_agent_a(user_text: str, progress_callback=None) -> Dict[str, Any]:
    """
        Agent A 的核心逻辑：调用 LLM 解析数据获取任务，并执行数据获取。
    """
    # 1. 使用预定义的 Agent A 提示词（包含数据库结构）
    final_prompt = agent_a_prompt

    # 3. 调用 LLM
    try:
        # 构建完整 Prompt：System Prompt + User Input
        full_prompt = f"{final_prompt}\n\n用户输入: {user_text}"
        json_content = call_qwen_with_prompt(full_prompt)
        json_content = json_content.strip()

    except Exception as e:
        return {"is_process_complete": False, "possible_problem": f"AI模型或通信错误: {str(e)}"}

    # 解析 JSON
    try:
        # 简单清洗 markdown 标记
        if "```json" in json_content:
            json_content = json_content.split("```json")[1].split("```")[0].strip()
        elif "```" in json_content:
            json_content = json_content.split("```")[1].split("```")[0].strip()
            
        fetch_request = json.loads(json_content)
    except json.JSONDecodeError:
        return {"is_process_complete": False,
                "possible_problem": f"LLM返回的JSON格式错误。原始内容: {json_content[:100]}..."}

    # 统一将结果包装为列表以支持多任务执行
    if not isinstance(fetch_request, list):
        fetch_request = [fetch_request]
        
    if len(fetch_request) == 0:
        return {"is_process_complete": False, "possible_problem": "AI返回了空的任务列表。"}

    results = []
    layer_names = []

    for req in fetch_request:
        # 检查 LLM 是否返回了错误消息
        if "error_message" in req:
            return {"is_process_complete": False, "possible_problem": req["error_message"]}

        source_type = req.get("source_type")
        query_params = req.get("query_params", {})

        if not source_type or not query_params:
            return {"is_process_complete": False, "possible_problem": "JSON缺少关键参数 (source_type/query_params)。"}
            
        QgsMessageLog.logMessage(f"数据查询任务参数:{req}", tag='AI_AGENT_DEBUG', level=Qgis.Info)

        # 调用实际执行函数
        fetch_result = execute_fetch_task(source_type, query_params, progress_callback)

        if fetch_result.startswith("Success"):
            target_name = query_params.get('target_name', '新图层')
            results.append(fetch_result)
            layer_names.append(target_name)
        else:
            return {"is_process_complete": False, "possible_problem": fetch_result.replace("Error: ", "")}

    # 所有任务执行成功后返回汇总结果
    return {"is_process_complete": True, "tool_result": " | ".join(results), "layer_name": ", ".join(layer_names)}


# --- 核心执行函数 (Agent B) ---
def run_agent_b(user_text: str, layers: List[QgsMapLayer]) -> Dict[str, Any]:
    """
        Agent B 的核心逻辑：调用 LLM 解析空间分析任务，进行图层名称模糊匹配，并执行 QGIS 空间分析。
    """

    # 1. 获取当前图层信息
    current_project = QgsProject.instance()
    # 重新获取最新的图层列表引用
    current_layers_list = list(current_project.mapLayers().values())
    available_names, layer_info_str = get_layer_name_and_fields(current_layers_list)

    # 2. 构造动态 Prompt
    dynamic_sys_prompt = agent_b_prompt + f"\n\n【当前 QGIS 项目中的可用图层列表】\n{layer_info_str}\n\n请根据以上列表选择图层名。"

    # 3. 调用 LLM
    try:
        full_prompt = f"{dynamic_sys_prompt}\n\n用户输入: {user_text}"
        json_content = call_qwen_with_prompt(full_prompt)
        json_content = json_content.strip()
    except Exception as e:
        return {"is_process_complete": False, "possible_problem": f"AI模型错误: {str(e)}"}

    # 4. 解析 JSON
    try:
        if "```json" in json_content:
            json_content = json_content.split("```json")[1].split("```")[0].strip()
        elif "```" in json_content:
            json_content = json_content.split("```")[1].split("```")[0].strip()
            
        analysis_request = json.loads(json_content)
        QgsMessageLog.logMessage(f"agent_b任务:{analysis_request}", tag='AI_AGENT_DEBUG', level=Qgis.Info)
    except json.JSONDecodeError:
        return {"is_process_complete": False, "possible_problem": "LLM返回JSON格式错误。"}

    if "error_message" in analysis_request:
        return {"is_process_complete": False, "possible_problem": analysis_request["error_message"]}

    alg_id = analysis_request.get("alg_id")
    params = analysis_request.get("params", {})
    layers_to_remove = analysis_request.get("layers_to_remove", [])  # 获取待删除列表

    if not alg_id or not params:
        return {"is_process_complete": False, "possible_problem": "缺少关键参数 alg_id 或 params。"}

    # 5. 图层参数模糊匹配 (Params)
    matched_params = params.copy()
    # 这里使用 available_names 进行匹配
    for k, v in params.items():
        if isinstance(v, str) and (k.upper() in ['INPUT', 'OVERLAY', 'JOIN', 'CLIP'] or k.endswith('_LAYER')):
            matched_name = fuzzy_match(v, available_names)
            if not matched_name:
                return {"is_process_complete": False, "possible_problem": f"图层 '{v}' 匹配失败。"}
            matched_params[k] = matched_name

    # 6. 执行空间分析
    analysis_result = execute_geoprocessing_task(alg_id, matched_params)

    # 7. 处理执行结果与后续清理
    if analysis_result.startswith("Success"):
        deleted_log = []
        # 如果分析成功，且有需要删除的图层
        if layers_to_remove:
            for del_target in layers_to_remove:
                # 再次模糊匹配确认图层名 (防止用户输入简称)
                matched_del_name = fuzzy_match(del_target, available_names)
                if matched_del_name:
                    # 获取当前项目中该名称的所有图层
                    layers_to_del = current_project.mapLayersByName(matched_del_name)
                    if layers_to_del:
                        # 避免误删刚刚生成的新图层
                        # 找出新生成的图层ID（如果有）
                        new_layer_name = matched_params.get("CUSTOM_LAYER_NAME")
                        
                        ids_to_remove = []
                        for l in layers_to_del:
                            ids_to_remove.append(l.id())
                            
                        if new_layer_name == matched_del_name and len(layers_to_del) > 1:
                            # 如果新图层名字和要删除的图层名字一样，且项目中有多个同名图层，则不删除最新图层。
                            ids_to_remove.pop() # 移除列表最后一个（即新图层）的ID
                            
                        if ids_to_remove:
                            current_project.removeMapLayers(ids_to_remove)
                            deleted_log.append(matched_del_name)

        # 构造最终返回信息
        final_msg = analysis_result
        if deleted_log:
            final_msg += f" (已按指令移除原始图层: {', '.join(deleted_log)})"

        return {"is_process_complete": True, "tool_result": final_msg}
    else:
        return {"is_process_complete": False, "possible_problem": analysis_result.replace("Error: ", "")}


# --- 核心执行函数 (Agent C) ---
def run_agent_c(user_text: str, layers: List[QgsMapLayer]) -> dict:
    """
    Agent C 的核心逻辑：集成 RAG 检索与 LLM 生成。
    1. 识别目标图层与语义推断
    2. 向量检索最佳样式模版
    3. 动态构建 Prompt 生成最终样式配置
    """

    # 获取当前图层信息
    current_project = QgsProject.instance()
    current_layers_list = list(current_project.mapLayers().values())
    available_names, _ = get_layer_name_and_fields(current_layers_list)
    layer_info_str = get_layer_info(current_layers_list)

    # --- Step 1: 提取目标图层与语义 (Extraction) ---
    target_layer_name = None
    content_inference = None
    
    try:
        extract_sys_prompt = (
            "你是一个GIS助手。请根据用户输入和可用图层列表，提取用户想要操作的目标图层名称，并推断其高度概括的、标准的泛化地理语义（中文）。\n"
            "重要：为了与标准样式库匹配，请去除具体的行政区划或地名修饰词，提取其核心地理要素类别。\n"
            "特别注意：如果用户的指令是给图层“添加注记/标记/标签”，请务必在地理语义后加上“注记”。如果不是，**严禁添加**。\n"
            "例如：'给湖北省河流配置样式' -> '河流'；'给湖北省河流添加注记' -> '河流注记'；'湖北省省界' -> '省级行政区界线'；'湖北省DEM' -> 'DEM' '给湖北省各市行政中心点位配置样式' -> '市级行政中心' '给湖北省各市行政中心点位添加注记' -> '行政中心注记'。\n"
            "请仅返回标准的 JSON 格式，不要包含 Markdown 标记或其他文本：\n"
            "{\"target_layer_name\": \"精确匹配的图层名称\", \"content_inference\": \"泛化的地理语义关键词\"}"
        )
        extract_input = f"{extract_sys_prompt}\n\n用户输入: {user_text}\n可用图层列表: {available_names}"
        extract_res = call_qwen_with_prompt(extract_input).strip()
        
        if "```json" in extract_res:
            extract_res = extract_res.split("```json")[1].split("```")[0].strip()
        elif "```" in extract_res:
            extract_res = extract_res.split("```")[1].split("```")[0].strip()
        
        extract_json = json.loads(extract_res)
        target_layer_name = extract_json.get("target_layer_name")
        content_inference = extract_json.get("content_inference")
        
        # 验证提取的图层名是否存在
        target_layer_name = fuzzy_match(target_layer_name, available_names)
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Agent C Extraction Error: {e}", tag='AI_AGENT_DEBUG', level=Qgis.Warning)
        # Fallback: Proceed without specific extraction

    # --- Step 2: 向量检索 (Retrieval) ---
    retrieved_style = None
    if target_layer_name:
        # 获取图层几何类型
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
        
        # 调用检索
        QgsMessageLog.logMessage(f"RAG Retrieval Start: {target_layer_name}, {geo_type_str}, {content_inference}", tag='AI_AGENT_DEBUG', level=Qgis.Info)
        retrieved_style = retrieve_style_config(query=target_layer_name, geometry_type=geo_type_str, inferred_keyword=content_inference)

    # --- Step 3: 动态构建 Prompt (Prompt Injection) ---
    rag_context = ""
    if retrieved_style:
        QgsMessageLog.logMessage(f"RAG Style Found: {retrieved_style}", tag='AI_AGENT_DEBUG', level=Qgis.Info)
        rag_context = (
            f"\n\n【参考样式模版 (RAG Retrieval)】\n"
            f"系统根据语义分析，为您检索到了一个相似的参考样式配置：\n"
            f"{json.dumps(retrieved_style, ensure_ascii=False)}\n"
            f"规则：\n"
            f"1. 如果用户输入中没有指定具体的颜色/符号细节，请直接采纳上述参考样式。\n"
            f"2. 如果用户输入了具体要求（如'红色'），请以用户要求为准，覆盖参考样式中的对应参数。\n"
        )
    else:
        QgsMessageLog.logMessage("RAG Style Not Found or Below Threshold", tag='AI_AGENT_DEBUG', level=Qgis.Info)

    # 构造动态 Prompt
    dynamic_agent_c_prompt = agent_c_prompt + f"\n\n【当前 QGIS 项目中的可用图层列表】\n{layer_info_str}。" + rag_context

    # --- Step 4: 执行生成 (Generation) ---
    try:
        full_prompt = f"{dynamic_agent_c_prompt}\n\n用户输入: {user_text}"
        json_content = call_qwen_with_prompt(full_prompt).strip()

        # 简单清洗 markdown 标记
        if "```json" in json_content:
            json_content = json_content.split("```json")[1].split("```")[0].strip()
        elif "```" in json_content:
            json_content = json_content.split("```")[1].split("```")[0].strip()

    except Exception as e:
        return {"is_process_complete": False, "possible_problem": f"AI模型或通信错误: {str(e)}"}

    # 解析 JSON
    try:
        style_request = json.loads(json_content)
        # 补全 content_inference (可选)
        if content_inference and "content_inference" not in style_request:
            style_request["content_inference"] = content_inference
            
        QgsMessageLog.logMessage(f"Agent C 最终请求: {style_request}", tag='AI_AGENT_DEBUG', level=Qgis.Info)
    except json.JSONDecodeError:
        return {"is_process_complete": False, "possible_problem": f"LLM返回的JSON格式错误。"}

    if "error_message" in style_request:
        return {"is_process_complete": False, "possible_problem": style_request["error_message"]}

    # 1. 匹配图层名称 (Final Validation)
    layer_input_name = style_request.get("layer_name_input")
    matched_layer_name = fuzzy_match(layer_input_name, available_names) 

    if not matched_layer_name:
        if target_layer_name:
            matched_layer_name = target_layer_name
        else:
            return {"is_process_complete": False, "possible_problem": f"无法找到图层 '{layer_input_name}'。"}

    # 2. 匹配字段名称 (针对 Categorized / Graduated / Annotation)
    style_type = style_request.get("style_type")
    style_config = style_request.get("style_config", {})

    if style_type in ['categorized', 'graduated', 'annotation']:
        field_intends = style_config.get("field_intend", [])  # 获取 LLM 推理的一组可能的字段名
        
        matched_layers_list = current_project.mapLayersByName(matched_layer_name)
        if matched_layers_list and len(matched_layers_list) > 0:
            target_layer = matched_layers_list[0]
            
        QgsMessageLog.logMessage(f"matched_layer_name: {matched_layer_name}", tag='AI_AGENT_DEBUG', level=Qgis.Info)
        if not target_layer:
            return {"is_process_complete": False, "possible_problem": "图层对象丢失。"}

        real_fields = [f.name() for f in target_layer.fields()]
        matched_field = None

        # 遍历 LLM 给出的候选字段列表，逐一尝试匹配
        for intend in field_intends:
            matched_field = fuzzy_match(intend, real_fields)  # 复用模糊匹配函数
            if matched_field:
                QgsMessageLog.logMessage(f"字段匹配成功: '{intend}' -> '{matched_field}'", tag='AI_AGENT_DEBUG',
                                         level=Qgis.Info)
                break

        if matched_field:
            # 将匹配到的真实字段名写入 config，供 style_management 使用
            style_config["target_field_actual"] = matched_field
        else:
            return {"is_process_complete": False,
                    "possible_problem": f"在图层 '{matched_layer_name}' 中未找到类似 {field_intends} 的字段，无法进行分类/分级渲染。"}

    # 3. 执行样式设置
    # 将修正后的 layer_name 和整个 request 传给 style_management
    style_result = set_layer_style(matched_layer_name, style_request)

    if style_result.startswith("Success"):
        return {"is_process_complete": True, "tool_result": style_result}
    else:
        return {"is_process_complete": False, "possible_problem": style_result.replace("Error: ", "")}


# --- 核心执行函数 (Agent D) ---
def run_agent_d(user_text: str, layers: List[QgsMapLayer]) -> Dict[str, Any]:
    """
    Agent D: 视图与布局控制
    只负责解析任务，不直接执行任务，将任务列表返回给主线程执行。
    """
    try:
        # 1. 调用 LLM
        full_prompt = f"{agent_d_prompt}\n\n用户输入: {user_text}"
        json_content = call_qwen_with_prompt(full_prompt).strip()

        # 2. 解析 JSON
        if "```json" in json_content:
            import re
            match = re.search(r'\[.*\]', json_content, re.DOTALL)
            if match:
                json_content = match.group()
            else:
                match_obj = re.search(r'\{.*\}', json_content, re.DOTALL)
                if match_obj: json_content = f"[{match_obj.group()}]"
        elif "```" in json_content:
            json_content = json_content.split("```")[1].split("```")[0].strip()

        try:
            requests = json.loads(json_content)
            QgsMessageLog.logMessage(f"Agent D JSON Output: {json.dumps(requests, ensure_ascii=False)}", tag='AI_AGENT_DEBUG', level=Qgis.Info)
        except json.JSONDecodeError:
            QgsMessageLog.logMessage(f"Agent D JSON Decode Error: {json_content}", tag='AI_AGENT_DEBUG', level=Qgis.Warning)
            return {"is_process_complete": False, "possible_problem": f"JSON解析失败: {json_content}"}

        if isinstance(requests, dict): requests = [requests]

        return {
            "is_process_complete": True,
            "tasks": requests,  # 把任务包带回去
            "tool_result": "指令已解析，正在主界面执行..."
        }

    except Exception as e:
        return {"is_process_complete": False, "possible_problem": f"Agent D 解析异常: {str(e)}"}
