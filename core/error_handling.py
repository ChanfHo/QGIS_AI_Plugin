"""Define workflow error state, recovery modes and user-visible feedback."""
from .localization import t, response_language, response_scope, canonical_message

import re
import json
from uuid import uuid4
from functools import wraps
from inspect import signature
from typing import Any, Dict, Optional, Union


ToolResult = Union[str, Dict[str, Any]]


ERROR_CATALOG = {
    "MODEL_UNAVAILABLE": {
        "title": 'The AI model service is temporarily unavailable',
        "reason": 'The system tried connecting 3 times but received no valid response.',
        "action": 'Check the network and model service configuration, then resend the original task once restored.',
        "example": 'Run the previous task again.',
        "recovery_mode": "restart",
    },
    "INVALID_JSON": {
        "title": 'The AI returned incorrectly formatted task parameters',
        "reason": 'The system requested regeneration 3 times, but the response still cannot be converted to executable parameters.',
        "action": 'No QGIS operations have been performed for this step. Rephrase the task more clearly and run it again.',
        "example": 'Run this step again: categorize layer “道路” by field “类型”.',
        "recovery_mode": "restart",
    },
    "ROUTE_FAILED": {
        "title": 'The system cannot determine which function should handle this task',
        "reason": 'The description does not distinguish data acquisition, spatial analysis, styling or layout operations.',
        "action": 'Specify the target and operation type so the system can continue this step.',
        "example": 'Continue this step: buffer layer “道路” by 100 meters.',
        "recovery_mode": "resume",
    },
    "MISSING_PARAMETER": {
        "title": 'This step is missing required information',
        "reason": 'The system cannot safely execute the operation without required parameters.',
        "action": 'Supply the missing layer, field, path, extent or parameter values, then continue this step.',
        "example": 'Continue this step: target layer “道路”, distance 100 meters, output name “道路缓冲区”.',
        "recovery_mode": "resume",
    },
    "LAYER_NOT_FOUND": {
        "title": 'The layer or field required by this step was not found',
        "reason": 'The referenced names do not match layers or fields in the current QGIS project.',
        "action": 'Load the required layer or confirm exact layer and field names, then continue this step.',
        "example": 'Continue this step: use layer “道路中心线” and field “道路等级”.',
        "recovery_mode": "resume",
    },
    "SQL_EMPTY_RESULT": {
        "title": 'The data query found no matching results',
        "reason": 'The database connection works, but the query extent or filters matched no data.',
        "action": 'Broaden or correct region, time, type or other query conditions, then continue this step.',
        "example": 'Continue this step: query all of 武汉市 without restricting road class.',
        "recovery_mode": "resume",
    },
    "DATA_ACCESS_FAILED": {
        "title": 'The data source cannot currently be read',
        "reason": 'The file, database or remote service did not provide valid data.',
        "action": 'Check the data path, database connection or data validity, then continue this step after fixing it.',
        "example": "Continue this step: change the local path to D:\\data\\roads.shp.",
        "recovery_mode": "resume",
    },
    "NETWORK_FAILED": {
        "title": 'The remote data service is temporarily unreachable',
        "reason": 'The system tried connecting 3 times, but the download or remote request still failed.',
        "action": 'Check the network and remote service. Once restored, continue this step without repeating completed steps.',
        "example": 'Continue this step and fetch the remote data again.',
        "recovery_mode": "resume",
    },
    "PROCESSING_FAILED": {
        "title": 'QGIS spatial analysis could not be completed',
        "reason": "The input layer or parameters do not meet the Processing algorithm's requirements.",
        "action": 'Check input layers, distances, fields, CRS or output parameters, then correct them and continue this step.',
        "example": 'Continue this step: input layer “道路”, buffer distance 100 meters.',
        "recovery_mode": "resume",
    },
    "STYLE_FAILED": {
        "title": 'The layer style could not be applied',
        "reason": 'The target layer, field or style parameters do not match the current layer structure.',
        "action": 'Confirm layer and field names or simplify the style request, then continue this step.',
        "example": 'Continue this step: categorize layer “行政区” by field “名称”.',
        "recovery_mode": "resume",
    },
    "LAYOUT_FAILED": {
        "title": 'The map layout or export operation could not be completed',
        "reason": 'The target layout, layer, page item or export location does not meet operation requirements.',
        "action": 'Confirm the layout name, required layers and export location, then continue this step.',
        "example": 'Continue this step: use layout “AI自动布局” and add the legend again.',
        "recovery_mode": "resume",
    },
    "USER_CANCELLED": {
        "title": 'The current operation was cancelled',
        "reason": 'The system detected cancellation of a save, layout or other interactive operation.',
        "action": 'Completed steps are retained. To continue, describe this step again and complete the confirmation dialog.',
        "example": 'Continue this step and select the export location again.',
        "recovery_mode": "resume",
    },
    "UNKNOWN_AGENT": {
        "title": 'The current task type is unrecognized',
        "reason": 'The system found no domain function that can safely execute this step.',
        "action": 'Rephrase the request as data acquisition, spatial analysis, styling or map layout.',
        "example": 'Continue this step: this is spatial analysis; generate a 100-meter road buffer.',
        "recovery_mode": "resume",
    },
    "INTERNAL_ERROR": {
        "title": 'Internal plugin processing failed',
        "reason": 'This error cannot be safely recovered by supplying task parameters.',
        "action": 'Stop this task and inspect the QGIS message log. Restart the plugin and resubmit the original task.',
        "example": 'Run the original task again.',
        "recovery_mode": "stop",
    },
}

NODE_LABELS = {
    "task_planner": 'Task planning',
    "task_router": 'Task routing',
    "agent_a": 'Data acquisition',
    "agent_b": 'Spatial analysis',
    "agent_c": 'Styling',
    "agent_d": 'Map layout',
    "agent_executor": 'Task execution',
    "workflow_runtime": 'Workflow runtime',
}

# Explicit error sources take precedence over legacy keyword matching.
for _code, _title, _mode in [
    ("FILE_NOT_FOUND", 'The local file does not exist', "correct_object"),
    ("FILE_INVALID", 'Invalid file format', "correct_object"),
    ("DATABASE_FAILED", 'Database connection or query failed', "parameters"),
    ("LAYER_LOAD_FAILED", 'Output layer loading failed', "parameters"),
    ("FIELD_NOT_FOUND", 'The target field does not exist', "correct_object"),
    ("ALGORITHM_NOT_FOUND", 'The spatial algorithm does not exist', "parameters"),
    ("INVALID_PARAMETER", 'Invalid execution parameters', "parameters"),
    ("STYLE_UNSUPPORTED", 'Unsupported style type', "parameters"),
    ("LAYOUT_NOT_FOUND", 'The target layout does not exist', "correct_object"),
    ("LAYOUT_ITEM_NOT_FOUND", 'The layout decoration item does not exist', "correct_object"),
    ("EXPORT_PATH_INVALID", 'The export location is not writable', "parameters"),
    ("EXPORT_FAILED", 'Layout export failed', "parameters"),
    ("MODEL_AUTH_FAILED", 'Model authentication or permission check failed', "model_retry"),
    ("MODEL_PERMISSION_FAILED", 'This key cannot access the model', "model_retry"),
    ("MODEL_QUOTA_FAILED", 'Insufficient model quota or rate limit reached', "model_retry"),
    ("MODEL_NETWORK_FAILED", 'Model network connection failed', "model_retry"),
    ("MODEL_SERVER_FAILED", 'Model server error', "model_retry"),
    ("MODEL_EMPTY_RESPONSE", 'The model returned an empty response', "model_retry"),
    ("INVALID_CONTRACT", "The model's structured fields do not meet the contract", "parameters"),
]:
    ERROR_CATALOG[_code] = dict(ERROR_CATALOG["MISSING_PARAMETER"],
                                title=_title, reason=_title, recovery_mode=_mode)

for _code, _mode in {"MODEL_UNAVAILABLE": "model_retry", "INVALID_JSON": "model_retry",
                     "NETWORK_FAILED": "network_retry", "LAYER_NOT_FOUND": "correct_object",
                     "MISSING_PARAMETER": "parameters", "ROUTE_FAILED": "parameters",
                     "USER_CANCELLED": "stop"}.items():
    ERROR_CATALOG[_code]["recovery_mode"] = _mode

ERROR_CATALOG["MODEL_UNAVAILABLE"]["action"] = 'Check the network and model configuration, then retry once restored. Completed steps are retained.'
ERROR_CATALOG["INVALID_JSON"]["action"] = 'No QGIS operations have been performed for this step. Supply clear parameters or click retry.'
ERROR_CATALOG["USER_CANCELLED"]["action"] = 'The current task was cancelled. Completed operations are retained; you can start a new task.'
for _code, _action in {
    "FILE_NOT_FOUND": 'Confirm the file exists and supply the correct path, then resume this step.',
    "FILE_INVALID": 'Check the file format and companion files. Supply data that QGIS can open normally.',
    "FIELD_NOT_FOUND": "Supply an exact field name from the current layer's fields, then resume this step.",
    "ALGORITHM_NOT_FOUND": 'Ensure the Processing provider is enabled or supply an available algorithm ID.',
    "DATABASE_FAILED": 'Check the database connection and query conditions, then correct them and resume this step.',
    "MODEL_AUTH_FAILED": 'Check the model key and access permissions, correct the configuration and click retry.',
    "MODEL_PERMISSION_FAILED": 'Check model activation and key authorization, then retry this step.',
    "MODEL_QUOTA_FAILED": 'Check the account balance, service quota and request frequency, then retry this step once restored.',
    "MODEL_NETWORK_FAILED": 'Check the network connection, then click retry once restored.',
    "MODEL_SERVER_FAILED": 'Retry this step later or check model service status.',
    "MODEL_EMPTY_RESPONSE": 'The model returned no content. Click to retry this step.',
    "EXPORT_PATH_INVALID": 'After resuming, select an existing writable export directory.',
    "EXPORT_FAILED": 'Check and correct the layout and export settings, then select the export location again.',
    "LAYOUT_NOT_FOUND": "Create a layout first or supply an existing layout's exact name.",
    "LAYOUT_ITEM_NOT_FOUND": 'Add a map item to the target layout first, then resume this step.',
}.items():
    ERROR_CATALOG[_code]["action"] = _action


def sanitize(value):
    """Recursively hide credentials, full queries and stacks, retaining displayable summaries only."""
    if isinstance(value, dict):
        return {str(k): ('[hidden]' if re.search(
            r"password|passwd|secret|token|api.?key|authorization|sql|uri|dsn", str(k), re.I)
            else sanitize(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if not isinstance(value, (str, int, float, bool, type(None))):
        return type(value).__name__
    if not isinstance(value, str):
        return value
    value = re.sub(r"Traceback[\s\S]*", '[stack hidden]', value)
    value = re.sub(r"(?is)\b(?:select\s+.+?\s+from\b|insert\s+into\b|update\s+\S+\s+set\b|delete\s+from\b|with\s+\S+\s+as\s*\()[\s\S]*", '[query hidden]', value)
    value = re.sub(r"(?i)\b(?:Bearer|Basic)\s+\S+", '[key hidden]', value)
    value = re.sub(r"(?i)(password|passwd|secret|api[_-]?key|token|authorization)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1=[hidden]", value)
    value = re.sub(r"(?i)\bBearer\s+\S+|\bsk-[\w-]+", '[key hidden]', value)
    value = re.sub(r"(://)[^/@\s]+:[^/@\s]+@", r"\1[credentials hidden]@", value)
    return value[:1500]


def failure(code, node, detail, **context):
    """Create a standard business result at the failure source."""
    error = build_error_state(code, node, detail)
    error.update(sanitize(context))
    return {"is_process_complete": False, "possible_problem": error["user_title"],
            "error_state": error}


def execution_boundary(node, default_code):
    """Catch exceptions at business entry points and retain safe request summaries."""
    def decorate(func):
        @wraps(func)
        def execute(*args, **kwargs):
            bound = signature(func).bind_partial(*args, **kwargs).arguments
            request = {key: value for key, value in bound.items()
                       if key not in ("progress_callback", "layers", "operation_results", "requests_override")}
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                code = getattr(exc, "error_code", None) or (
                    "INVALID_PARAMETER" if isinstance(exc, (TypeError, ValueError)) else default_code)
                result = failure(code, node, str(exc))
            if result is None:
                result = failure(default_code, node, 'The execution interface returned no result')
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
    """Normalize legacy error text to stable error codes."""
    text = str(message or "").lower()
    node = failed_node.lower()
    if "json" in text or "无法解析" in text:
        return "INVALID_JSON"
    if any(key in text for key in ("取消", "已停止", "cancel", "task stopped")):
        return "USER_CANCELLED"
    if any(key in text for key in ("模型调用", "模型服务", "api key", "聊天接口", "model service", "model call")):
        return "MODEL_UNAVAILABLE"
    if any(key in text for key in ("查询结果为空", "要素数量为 0", "要素数量为0", "no rows", "feature count is 0")):
        return "SQL_EMPTY_RESULT"
    if any(key in text for key in ("找不到", "未找到", "不存在", "匹配失败", "not found", "对象丢失", "does not exist", "matching failed", "object is missing")):
        return "LAYER_NOT_FOUND"
    if any(key in text for key in ("缺少", "必须为", "requires a valid", "missing", "must be", "is required")):
        return "MISSING_PARAMETER"
    if any(key in text for key in ("http", "下载", "远程服务", "network", "download", "remote service")):
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
    if any(key in text for key in ("数据无效", "文件", "数据库", "sql", "栅格", "invalid data", "file", "database", "raster")):
        return "DATA_ACCESS_FAILED"
    if "router" in node:
        return "ROUTE_FAILED"
    return "INTERNAL_ERROR"


def extract_safe_context(message: str, code: str) -> str:
    """Extract safely displayable object information from technical errors."""
    text = str(message or "")
    quoted_values = re.findall(r"['\"]([^'\"\r\n]{1,80})['\"]", text)
    if code == "LAYER_NOT_FOUND" and quoted_values:
        return 'Referenced name: {v0}'.format(v0=quoted_values[0])
    if code == "MISSING_PARAMETER":
        identifiers = re.findall(r"\b(?:source_type|query_params|target_name|sql_query|alg_id|params|INPUT|FIELD)\b", text)
        if identifiers:
            return 'Missing parameters: {v0}'.format(v0=', '.join(dict.fromkeys(identifiers)))
    if code == "PROCESSING_FAILED":
        algorithm = re.search(r"(?:算法|algorithm)\s*['\"]?([a-zA-Z0-9_:-]+)", text, re.I)
        if algorithm:
            return 'Referenced algorithm: {v0}'.format(v0=algorithm.group(1))
    if code == "NETWORK_FAILED":
        status = re.search(r"HTTP\s*(\d{3})", text, re.I)
        if status:
            return 'Remote service status: HTTP {v0}'.format(v0=status.group(1))
    return ""


def build_error_state(
    code: str,
    failed_node: str,
    technical_detail: str,
    retry_count: int = 0,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build error state separating internal diagnostics from user feedback."""
    definition = dict(ERROR_CATALOG.get(code, ERROR_CATALOG["INTERNAL_ERROR"]))
    if overrides:
        definition.update({key: value for key, value in overrides.items() if value})
    recovery_mode = definition["recovery_mode"]
    return {
        "error_id": uuid4().hex,
        "response_language": response_language(),
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
        "technical_detail": sanitize(str(technical_detail or 'No technical details provided')),
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
    """Convert free-text errors to standard error state."""
    if not retry_count and ("连续3次" in str(message) or "3 consecutive" in str(message)):
        retry_count = 3
    code = getattr(message, "error_code", None) or classify_error(message, failed_node)
    error = build_error_state(code, failed_node, str(message), getattr(message, "attempts", retry_count))
    for key in ("model_name", "phase", "request_id", "response_summary", "missing_fields"):
        if hasattr(message, key):
            error[key] = sanitize(getattr(message, key))
    return error


def normalize_execution_result(result: Any, failed_node: str) -> Dict[str, Any]:
    """Accept existing agent results and populate error state."""
    if not isinstance(result, dict):
        result = {"is_process_complete": False, "possible_problem": str(result or 'Unknown error')}
    if result.get("is_process_complete"):
        result.pop("error_state", None)
        return result
    error_state = result.get("error_state")
    if not isinstance(error_state, dict):
        error_state = error_from_message(result.get("possible_problem", 'Unknown error'), failed_node)
    result["error_state"] = error_state
    result["possible_problem"] = error_state["user_title"]
    return result


def format_user_report(error_state: Dict[str, Any]) -> str:
    with response_scope(error_state.get("response_language") or response_language()):
        return _format_user_report(error_state)


def _format_user_report(error_state: Dict[str, Any]) -> str:
    """Show only the five items ordinary users need to handle an error by default."""
    error_state = sanitize(error_state)
    definition = ERROR_CATALOG.get(error_state.get("error_code"), {})
    for field, key in (("user_title", "title"), ("user_reason", "reason"), ("user_action", "action")):
        error_state[field] = t(canonical_message(error_state.get(field) or definition.get(key, "")))
    progress_text = (
        t('Can continue: Yes. Completed steps are retained. Supply information to resume from the failed step.')
        if error_state.get("can_continue")
        else t('Can continue: Not directly. Follow the instructions below.')
    )
    resume_tip = (
        t('\nTip: Supply information or click resume to continue from the checkpoint. Enter “New task: …” to start another task.')
        if error_state.get("can_continue")
        else t('\nTip: This task has stopped. Start a new task after resolving the problem.')
    )
    return (
        t('Problem: {v0}\nReason: {v1}\n{v2}\nWhat to do: {v3}{v4}', v0=error_state.get('user_title', t('Task execution failed')), v1=error_state.get('user_reason', t('The system cannot complete this step.')), v2=progress_text, v3=error_state.get('user_action', t('Check task conditions and retry.')), v4=resume_tip)
    )


def format_technical_report(error_state: Dict[str, Any]) -> str:
    with response_scope(error_state.get("response_language") or response_language()):
        return _format_technical_report(error_state)


def _format_technical_report(error_state: Dict[str, Any]) -> str:
    """Place diagnostics and context in the initially collapsed details area."""
    error = sanitize(error_state)
    fields = {
        'Error instance': error.get("error_id", ""),
        'Task ID': error.get("task_id", ""),
        'Trace ID': error.get("trace_id", ""),
        'Error code': error.get("error_code", "INTERNAL_ERROR"),
        'Location': t(canonical_message(error.get("failed_node", 'Unknown stage'))),
        'Task step': t('{v0}, {v1}', v0=error.get('step_id', 0) + 1, v1=error.get('task_name', '')),
        'Completed steps': error.get("completed_steps", []),
        'Failed action': error.get("failed_action", ""),
        'Target layer': error.get("target_layer", ""),
        'Target field': error.get("target_field", ""),
        'Object summary': error.get("safe_context", ""),
        'System attempts': error.get("retry_count", 0),
        'Suggested input': t(canonical_message(error.get("example_input", ""))),
        'Technical details': error.get("technical_detail", ""),
        'Execution parameters': error.get("parameters", {}),
        'Context': error.get("context_snapshot", {}),
    }
    for key in ("model_name", "phase", "request_id", "response_summary", "missing_fields"):
        if key in error:
            fields[key] = error[key]
    return "\n".join(f"{t(label)}: {json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else value}"
                     for label, value in fields.items())
