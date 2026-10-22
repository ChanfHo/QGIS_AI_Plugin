"""保存当前进程中的任务断点及多轮修复上下文。"""

from copy import deepcopy
from uuid import uuid4

from .error_handling import sanitize


STATE_VERSION = 1
PENDING_SESSIONS = {}


def layer_snapshot(layers):
    """仅记录图层标识和字段，不读取数据源凭据。"""
    result = []
    for layer in layers:
        try:
            result.append({"id": layer.id(), "name": layer.name(),
                           "fields": [f.name() for f in layer.fields()] if layer.type() == 0 else []})
        except (AttributeError, RuntimeError):
            continue
    return result


def initialize_session(state):
    """为任务分配稳定标识，并保留已有恢复历史。"""
    for key, value in {"state_version": STATE_VERSION, "task_id": uuid4().hex,
                       "trace_id": uuid4().hex, "resume_token": uuid4().hex,
                       "completed_steps": [], "execution_history": [],
                       "recovery_history": [], "recovery_attempts": 0,
                       "pending_user_input": "", "recovery_mode": "",
                       "operation_results": []}.items():
        state.setdefault(key, value)
    state["context_snapshot"] = layer_snapshot(state.get("layers", []))
    return state


def checkpoint(state, error):
    """将同一个错误实例关联到状态、报告和会话断点。"""
    initialize_session(state)
    state["resume_token"] = uuid4().hex
    error.update(task_id=state["task_id"], trace_id=state["trace_id"],
                 step_id=state.get("current_step", 0), task_name=state.get("current_task") or state.get("user_request", ""),
                 completed_steps=list(state["completed_steps"]),
                 context_snapshot=state["context_snapshot"], resume_token=state["resume_token"])
    state.update(error_state=error, failed_step=state.get("current_step", 0),
                 failed_node=error.get("node_id", "agent_executor"), recovery_mode=error["recovery_mode"])
    state["execution_history"].append({"node": state["failed_node"], "error": deepcopy(error)})
    return state


def save_checkpoint(state):
    """移除运行时对象后保留断点；恢复所需原始输入仅驻留内存。"""
    return deepcopy({key: value for key, value in state.items() if key not in ("layers", "executor")})


def resume_session(saved, user_input, token):
    """验证恢复入口，保留原任务及累计补充信息。"""
    if saved.get("state_version") != STATE_VERSION or token != saved.get("resume_token"):
        raise ValueError("任务断点已失效，请重新发起任务。")
    state = deepcopy(saved)
    state["recovery_attempts"] += 1
    state["pending_user_input"] = user_input
    state["recovery_history"].append({"input": user_input, "mode": state.get("recovery_mode")})
    state["pending_requests"] = state.get("execution_result", {}).get("request_sequence", []) if state.get("execution_result") else []
    if user_input.strip() == "重新规划剩余步骤" and not state.get("operation_results"):
        state["recovery_mode"] = "replan"
    elif state.get("recovery_mode") == "network_retry" and user_input.strip() not in ("重试当前步骤", "继续", "重试"):
        state["recovery_mode"] = "parameters"
    state.update(resume_mode=True, recovery_input=user_input, error="", execution_result=None)
    return state


def recovery_context(state):
    """将修复上下文作为独立结构提供给路由及领域智能体。"""
    return sanitize({"original_request": state["user_request"],
                     "failed_task": state.get("current_task"),
                     "failed_request": state.get("error_state", {}).get("parameters"),
                     "error": state.get("error_state"),
                     "completed_steps": state.get("completed_steps", []),
                     "completed_operations": state.get("operation_results", []),
                     "user_updates": state.get("recovery_history", []),
                     "current_layouts": state.get("layout_snapshot", []),
                     "current_layers": state.get("context_snapshot", [])})
