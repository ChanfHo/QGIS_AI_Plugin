"""定义工作流错误状态、恢复方式和用户可见反馈。"""

import re
import json
from uuid import uuid4
from functools import wraps
from inspect import signature
from typing import Any, Dict, Optional, Union


ToolResult = Union[str, Dict[str, Any]]


ERROR_CATALOG = {
    "MODEL_UNAVAILABLE": {
        "title": "AI模型服务暂时不可用",
        "reason": "系统已尝试连接3次，但仍未获得有效响应。",
        "action": "请检查网络连接和模型服务配置，确认恢复后重新发送原任务。",
        "example": "请重新执行刚才的任务。",
        "recovery_mode": "restart",
    },
    "INVALID_JSON": {
        "title": "AI返回的任务参数格式不正确",
        "reason": "系统已重新请求3次，但返回内容仍无法转换为可执行参数。",
        "action": "当前步骤尚未执行QGIS操作。请换一种更明确的说法重新运行当前任务。",
        "example": "请重新执行当前步骤：对“道路”图层按“类型”字段分类渲染。",
        "recovery_mode": "restart",
    },
    "ROUTE_FAILED": {
        "title": "系统无法判断任务应由哪个功能处理",
        "reason": "当前描述不足以区分数据获取、空间分析、样式设置或布局操作。",
        "action": "请明确说明操作对象和操作类型，系统将继续处理当前步骤。",
        "example": "继续当前步骤：对“道路”图层执行缓冲区分析，距离为100米。",
        "recovery_mode": "resume",
    },
    "MISSING_PARAMETER": {
        "title": "当前步骤缺少必要信息",
        "reason": "系统无法在缺少关键参数的情况下安全执行操作。",
        "action": "请补充提示中缺少的图层、字段、路径、范围或参数值，然后继续当前步骤。",
        "example": "继续当前步骤：目标图层为“道路”，距离为100米，输出名称为“道路缓冲区”。",
        "recovery_mode": "resume",
    },
    "LAYER_NOT_FOUND": {
        "title": "没有找到当前步骤需要的图层或字段",
        "reason": "任务引用的名称与当前QGIS工程中的图层或字段不匹配。",
        "action": "请先加载所需图层，或确认图层和字段的准确名称，再继续当前步骤。",
        "example": "继续当前步骤：使用图层“道路中心线”，字段使用“道路等级”。",
        "recovery_mode": "resume",
    },
    "SQL_EMPTY_RESULT": {
        "title": "数据查询没有找到符合条件的结果",
        "reason": "数据库连接正常，但当前查询范围或筛选条件没有匹配到数据。",
        "action": "请放宽或修正地区、时间、类型等查询条件，然后继续当前步骤。",
        "example": "继续当前步骤：将查询范围改为武汉市全部区域，不限制道路等级。",
        "recovery_mode": "resume",
    },
    "DATA_ACCESS_FAILED": {
        "title": "数据源当前无法读取",
        "reason": "文件、数据库或远程数据服务未能提供有效数据。",
        "action": "请检查数据路径、数据库连接或数据有效性，修复后继续当前步骤。",
        "example": "继续当前步骤：本地文件路径改为D:\\data\\roads.shp。",
        "recovery_mode": "resume",
    },
    "NETWORK_FAILED": {
        "title": "远程数据服务暂时无法访问",
        "reason": "系统已尝试连接3次，但下载或远程请求仍未成功。",
        "action": "请检查网络和远程服务状态。恢复后可继续当前步骤，无需重做已完成步骤。",
        "example": "继续执行当前步骤，重新获取刚才的远程数据。",
        "recovery_mode": "resume",
    },
    "PROCESSING_FAILED": {
        "title": "QGIS空间分析未能完成",
        "reason": "输入图层或算法参数不满足当前Processing算法的执行要求。",
        "action": "请检查输入图层、距离、字段、坐标系或输出参数，并在修正后继续当前步骤。",
        "example": "继续当前步骤：输入图层改为“道路”，缓冲距离改为100米。",
        "recovery_mode": "resume",
    },
    "STYLE_FAILED": {
        "title": "图层样式未能应用",
        "reason": "目标图层、字段或样式参数与当前图层结构不匹配。",
        "action": "请确认图层和字段名称，或简化样式要求，然后继续当前步骤。",
        "example": "继续当前步骤：对“行政区”图层按“名称”字段分类渲染。",
        "recovery_mode": "resume",
    },
    "LAYOUT_FAILED": {
        "title": "地图布局或导出操作未能完成",
        "reason": "目标布局、图层、页面元素或导出位置不满足操作要求。",
        "action": "请确认布局名称、所需图层和导出位置，然后继续当前步骤。",
        "example": "继续当前步骤：使用布局“AI自动布局”，重新添加图例。",
        "recovery_mode": "resume",
    },
    "USER_CANCELLED": {
        "title": "当前操作已取消",
        "reason": "系统检测到保存、布局或其他交互操作被取消。",
        "action": "已完成步骤会保留。如需继续，请重新说明当前步骤并完成弹出的确认操作。",
        "example": "继续执行当前步骤，并重新选择导出位置。",
        "recovery_mode": "resume",
    },
    "UNKNOWN_AGENT": {
        "title": "当前任务类型无法识别",
        "reason": "系统没有找到能够安全执行该步骤的领域功能。",
        "action": "请将要求改写为数据获取、空间分析、样式设置或地图布局中的一种。",
        "example": "继续当前步骤：这是一个空间分析任务，请对道路生成100米缓冲区。",
        "recovery_mode": "resume",
    },
    "INTERNAL_ERROR": {
        "title": "插件内部处理失败",
        "reason": "当前错误无法通过补充任务参数安全恢复。",
        "action": "请停止本次任务并查看QGIS消息日志；重新运行插件后再提交原任务。",
        "example": "请重新执行原任务。",
        "recovery_mode": "stop",
    },
}

NODE_LABELS = {
    "task_planner": "任务规划",
    "task_router": "任务路由",
    "agent_a": "数据获取",
    "agent_b": "空间分析",
    "agent_c": "样式设置",
    "agent_d": "地图布局",
    "agent_executor": "任务执行",
    "workflow_runtime": "工作流运行",
}

# 明确的错误来源优先于旧接口的关键词兼容。
for _code, _title, _mode in [
    ("FILE_NOT_FOUND", "本地文件不存在", "correct_object"),
    ("FILE_INVALID", "文件格式无效", "correct_object"),
    ("DATABASE_FAILED", "数据库连接或查询失败", "parameters"),
    ("LAYER_LOAD_FAILED", "输出图层加载失败", "parameters"),
    ("FIELD_NOT_FOUND", "目标字段不存在", "correct_object"),
    ("ALGORITHM_NOT_FOUND", "空间算法不存在", "parameters"),
    ("INVALID_PARAMETER", "执行参数不合法", "parameters"),
    ("STYLE_UNSUPPORTED", "不支持该样式类型", "parameters"),
    ("LAYOUT_NOT_FOUND", "目标布局不存在", "correct_object"),
    ("LAYOUT_ITEM_NOT_FOUND", "布局整饰元素不存在", "correct_object"),
    ("EXPORT_PATH_INVALID", "导出位置不可写", "parameters"),
    ("EXPORT_FAILED", "布局导出失败", "parameters"),
    ("MODEL_AUTH_FAILED", "模型认证或权限检查失败", "model_retry"),
    ("MODEL_NETWORK_FAILED", "模型网络连接失败", "model_retry"),
    ("MODEL_SERVER_FAILED", "模型服务端异常", "model_retry"),
    ("MODEL_EMPTY_RESPONSE", "模型返回空响应", "model_retry"),
    ("INVALID_CONTRACT", "模型返回的结构化字段不符合要求", "parameters"),
]:
    ERROR_CATALOG[_code] = dict(ERROR_CATALOG["MISSING_PARAMETER"],
                                title=_title, reason=_title, recovery_mode=_mode)

for _code, _mode in {"MODEL_UNAVAILABLE": "model_retry", "INVALID_JSON": "model_retry",
                     "NETWORK_FAILED": "network_retry", "LAYER_NOT_FOUND": "correct_object",
                     "MISSING_PARAMETER": "parameters", "ROUTE_FAILED": "parameters",
                     "USER_CANCELLED": "stop"}.items():
    ERROR_CATALOG[_code]["recovery_mode"] = _mode

ERROR_CATALOG["MODEL_UNAVAILABLE"]["action"] = "请检查网络和模型配置，恢复后点击重试；已完成步骤会保留。"
ERROR_CATALOG["INVALID_JSON"]["action"] = "当前步骤尚未执行QGIS操作，可补充明确参数或点击重试。"
ERROR_CATALOG["USER_CANCELLED"]["action"] = "当前任务已取消，已完成的操作保留，可发起新任务。"
for _code, _action in {
    "FILE_NOT_FOUND": "请确认文件存在并补充正确路径，再恢复当前步骤。",
    "FILE_INVALID": "请检查文件格式及配套文件，提供可由QGIS正常打开的数据。",
    "FIELD_NOT_FOUND": "请按当前图层字段列表补充准确字段名，再恢复当前步骤。",
    "ALGORITHM_NOT_FOUND": "请确认Processing提供程序已启用，或补充可用的算法标识。",
    "DATABASE_FAILED": "请检查数据库连接及查询条件，修正后恢复当前步骤。",
    "MODEL_AUTH_FAILED": "请检查模型密钥和访问权限，修正配置后点击重试。",
    "MODEL_NETWORK_FAILED": "请检查网络连接，恢复后点击重试。",
    "MODEL_SERVER_FAILED": "请稍后重试当前步骤，或检查模型服务状态。",
    "MODEL_EMPTY_RESPONSE": "模型未返回内容，可点击重试当前步骤。",
    "EXPORT_PATH_INVALID": "请在恢复操作后选择存在且可写的导出目录。",
    "EXPORT_FAILED": "请检查布局及导出设置，修正后重新选择导出位置。",
    "LAYOUT_NOT_FOUND": "请先创建布局或补充现有布局的准确名称。",
    "LAYOUT_ITEM_NOT_FOUND": "请先在目标布局中添加地图元素，再恢复当前步骤。",
}.items():
    ERROR_CATALOG[_code]["action"] = _action


def sanitize(value):
    """递归隐藏凭据、完整查询和堆栈，只保存可展示的摘要。"""
    if isinstance(value, dict):
        return {str(k): ("[已隐藏]" if re.search(
            r"password|passwd|secret|token|api.?key|authorization|sql|uri|dsn", str(k), re.I)
            else sanitize(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if not isinstance(value, (str, int, float, bool, type(None))):
        return type(value).__name__
    if not isinstance(value, str):
        return value
    value = re.sub(r"Traceback[\s\S]*", "[堆栈已隐藏]", value)
    value = re.sub(r"(?is)\b(?:select\s+.+?\s+from\b|insert\s+into\b|update\s+\S+\s+set\b|delete\s+from\b|with\s+\S+\s+as\s*\()[\s\S]*", "[查询已隐藏]", value)
    value = re.sub(r"(?i)\b(?:Bearer|Basic)\s+\S+", "[密钥已隐藏]", value)
    value = re.sub(r"(?i)(password|passwd|secret|api[_-]?key|token|authorization)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1=[已隐藏]", value)
    value = re.sub(r"(?i)\bBearer\s+\S+|\bsk-[\w-]+", "[密钥已隐藏]", value)
    value = re.sub(r"(://)[^/@\s]+:[^/@\s]+@", r"\1[凭据已隐藏]@", value)
    return value[:1500]


def failure(code, node, detail, **context):
    """在失败产生位置创建统一业务结果。"""
    error = build_error_state(code, node, detail)
    error.update(sanitize(context))
    return {"is_process_complete": False, "possible_problem": error["user_title"],
            "error_state": error}


def execution_boundary(node, default_code):
    """在业务入口捕获异常并保留原始请求的安全摘要。"""
    def decorate(func):
        @wraps(func)
        def execute(*args, **kwargs):
            bound = signature(func).bind_partial(*args, **kwargs).arguments
            request = {key: value for key, value in bound.items()
                       if key not in ("progress_callback", "layers", "operation_results", "requests_override")}
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                code = "INVALID_PARAMETER" if isinstance(exc, (TypeError, ValueError)) else default_code
                result = failure(code, node, str(exc))
            if result is None:
                result = failure(default_code, node, "执行接口未返回结果")
            if isinstance(result, dict) and result.get("error_state"):
                error = result["error_state"]
                if not error.get("failed_action"):
                    error["failed_action"] = str(request.get("alg_id") or request.get("source_type") or
                                                  (request.get("params", {}).get("action_type") if isinstance(request.get("params"), dict) else "") or func.__name__)
                if not error.get("parameters"):
                    error["parameters"] = sanitize(request)
                error["target_layer"] = error.get("target_layer") or sanitize(request.get("layer_name", ""))
                if not error["target_layer"]:
                    query = request.get("query_params", {})
                    params = request.get("params", {})
                    error["target_layer"] = sanitize(query.get("target_name", "") if isinstance(query, dict) else "")
                    if not error["target_layer"] and isinstance(params, dict):
                        error["target_layer"] = sanitize(params.get("INPUT", params.get("layer_name", "")))
                if isinstance(request.get("full_config"), dict):
                    config = request["full_config"].get("style_config", {})
                    if isinstance(config, dict):
                        error["target_field"] = sanitize(config.get("target_field_actual", ""))
                result.setdefault("request_context", request)
            return result
        return execute
    return decorate


def classify_error(message: str, failed_node: str = "") -> str:
    """将既有错误文本归一化为稳定错误码。"""
    text = str(message or "").lower()
    node = failed_node.lower()
    if "json" in text or "无法解析" in text:
        return "INVALID_JSON"
    if any(key in text for key in ("取消", "已停止", "cancel")):
        return "USER_CANCELLED"
    if any(key in text for key in ("模型调用", "模型服务", "api key", "聊天接口")):
        return "MODEL_UNAVAILABLE"
    if any(key in text for key in ("查询结果为空", "要素数量为 0", "要素数量为0", "no rows")):
        return "SQL_EMPTY_RESULT"
    if any(key in text for key in ("找不到", "未找到", "不存在", "匹配失败", "not found", "对象丢失")):
        return "LAYER_NOT_FOUND"
    if any(key in text for key in ("缺少", "必须为", "requires a valid", "missing")):
        return "MISSING_PARAMETER"
    if any(key in text for key in ("http", "下载", "远程服务", "network")):
        return "NETWORK_FAILED"
    if any(key in text for key in ("connection", "timeout", "timed out")):
        return "NETWORK_FAILED"
    if "unknown agent" in text or "未知智能体" in text:
        return "UNKNOWN_AGENT"
    if "agent_b" in node or any(key in text for key in ("qgis 算法", "qgis算法", "processing")):
        return "PROCESSING_FAILED"
    if "agent_c" in node or any(key in text for key in ("style", "renderer", "渲染", "样式")):
        return "STYLE_FAILED"
    if "agent_d" in node or any(key in text for key in ("layout", "布局", "导出")):
        return "LAYOUT_FAILED"
    if any(key in text for key in ("数据无效", "文件", "数据库", "sql", "栅格")):
        return "DATA_ACCESS_FAILED"
    if "router" in node:
        return "ROUTE_FAILED"
    return "INTERNAL_ERROR"


def extract_safe_context(message: str, code: str) -> str:
    """从技术错误中提取可安全展示的对象信息。"""
    text = str(message or "")
    quoted_values = re.findall(r"['\"]([^'\"\r\n]{1,80})['\"]", text)
    if code == "LAYER_NOT_FOUND" and quoted_values:
        return f"涉及名称：{quoted_values[0]}"
    if code == "MISSING_PARAMETER":
        identifiers = re.findall(r"\b(?:source_type|query_params|target_name|sql_query|alg_id|params|INPUT|FIELD)\b", text)
        if identifiers:
            return f"缺少参数：{', '.join(dict.fromkeys(identifiers))}"
    if code == "PROCESSING_FAILED":
        algorithm = re.search(r"(?:算法|algorithm)\s*['\"]?([a-zA-Z0-9_:-]+)", text, re.I)
        if algorithm:
            return f"涉及算法：{algorithm.group(1)}"
    if code == "NETWORK_FAILED":
        status = re.search(r"HTTP\s*(\d{3})", text, re.I)
        if status:
            return f"远程服务状态：HTTP {status.group(1)}"
    return ""


def build_error_state(
    code: str,
    failed_node: str,
    technical_detail: str,
    retry_count: int = 0,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """构建内部诊断和用户反馈分离的错误状态。"""
    definition = dict(ERROR_CATALOG.get(code, ERROR_CATALOG["INTERNAL_ERROR"]))
    if overrides:
        definition.update({key: value for key, value in overrides.items() if value})
    recovery_mode = definition["recovery_mode"]
    return {
        "error_id": uuid4().hex,
        "error_code": code,
        "node_id": failed_node,
        "failed_node": NODE_LABELS.get(failed_node, failed_node),
        "failed_action": "",
        "task_id": "",
        "step_id": 0,
        "target_layer": "",
        "target_field": "",
        "parameters": {},
        "context_snapshot": {},
        "technical_detail": sanitize(str(technical_detail or "未提供技术详情")),
        "safe_context": extract_safe_context(sanitize(technical_detail), code),
        "retry_count": retry_count,
        "user_title": definition["title"],
        "user_reason": definition["reason"],
        "user_action": definition["action"],
        "example_input": definition["example"],
        "recovery_mode": recovery_mode,
        "message": definition["title"],
        "recoverable": recovery_mode != "stop",
        "can_continue": recovery_mode != "stop",
    }


def error_from_message(message: str, failed_node: str, retry_count: int = 0) -> Dict[str, Any]:
    """将自由文本错误转换为统一错误状态。"""
    if not retry_count and "连续3次" in str(message):
        retry_count = 3
    code = getattr(message, "error_code", None) or classify_error(message, failed_node)
    error = build_error_state(code, failed_node, str(message), getattr(message, "attempts", retry_count))
    for key in ("model_name", "phase", "request_id", "response_summary", "missing_fields"):
        if hasattr(message, key):
            error[key] = sanitize(getattr(message, key))
    return error


def normalize_execution_result(result: Any, failed_node: str) -> Dict[str, Any]:
    """兼容既有Agent结果并补齐错误状态。"""
    if not isinstance(result, dict):
        result = {"is_process_complete": False, "possible_problem": str(result or "未知错误")}
    if result.get("is_process_complete"):
        result.pop("error_state", None)
        return result
    error_state = result.get("error_state")
    if not isinstance(error_state, dict):
        error_state = error_from_message(result.get("possible_problem", "未知错误"), failed_node)
    result["error_state"] = error_state
    result["possible_problem"] = error_state["user_title"]
    return result


def format_user_report(error_state: Dict[str, Any]) -> str:
    """默认只展示普通用户处理错误所需的五项信息。"""
    error_state = sanitize(error_state)
    progress_text = (
        "是否可以继续：可以。已完成的步骤会保留，您补充信息后将从当前失败步骤继续。"
        if error_state.get("can_continue")
        else "是否可以继续：不可以直接继续，请按下方说明处理。"
    )
    resume_tip = (
        "\n提示：可直接补充信息或点击恢复按钮断点续做；输入“新任务：…”开始其他任务。"
        if error_state.get("can_continue")
        else "\n提示：当前任务已终止，可在处理问题后发起新任务。"
    )
    return (
        f"问题说明：{error_state.get('user_title', '任务执行失败')}\n"
        f"具体原因：{error_state.get('user_reason', '系统无法完成当前步骤。')}\n"
        f"{progress_text}\n"
        f"您需要做什么：{error_state.get('user_action', '请检查任务条件后重试。')}"
        f"{resume_tip}"
    )


def format_technical_report(error_state: Dict[str, Any]) -> str:
    """将诊断信息及上下文放入默认折叠的详情区域。"""
    error = sanitize(error_state)
    fields = {
        "错误实例": error.get("error_id", ""),
        "任务标识": error.get("task_id", ""),
        "追踪标识": error.get("trace_id", ""),
        "问题编号": error.get("error_code", "INTERNAL_ERROR"),
        "发生位置": error.get("failed_node", "未知环节"),
        "任务步骤": f"{error.get('step_id', 0) + 1}，{error.get('task_name', '')}",
        "已完成步骤": error.get("completed_steps", []),
        "失败动作": error.get("failed_action", ""),
        "涉及图层": error.get("target_layer", ""),
        "涉及字段": error.get("target_field", ""),
        "对象摘要": error.get("safe_context", ""),
        "系统尝试次数": error.get("retry_count", 0),
        "建议输入": error.get("example_input", ""),
        "技术详情": error.get("technical_detail", ""),
        "执行参数": error.get("parameters", {}),
        "上下文": error.get("context_snapshot", {}),
    }
    for key in ("model_name", "phase", "request_id", "response_summary", "missing_fields"):
        if key in error:
            fields[key] = error[key]
    return "\n".join(f"{label}：{json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else value}"
                     for label, value in fields.items())
