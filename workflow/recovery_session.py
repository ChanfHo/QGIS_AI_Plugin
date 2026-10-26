"""Keep task checkpoints and multi-turn repair context in the current process."""

from copy import deepcopy
from uuid import uuid4

from ..core.error_handling import sanitize
from ..core.localization import command_id, choose_response_language


STATE_VERSION = 1
PENDING_SESSIONS = {}


def layer_snapshot(layers):
    """Record layer IDs and fields only; do not read source credentials."""
    result = []
    for layer in layers:
        try:
            result.append({"id": layer.id(), "name": layer.name(),
                           "fields": [f.name() for f in layer.fields()] if layer.type() == 0 else []})
        except (AttributeError, RuntimeError):
            continue
    return result


def initialize_session(state):
    """Assign stable task IDs and retain existing recovery history."""
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
    """Link one error instance to state, reports and session checkpoints."""
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
    """Retain checkpoints without runtime objects; original recovery inputs stay in memory only."""
    return deepcopy({key: value for key, value in state.items() if key not in ("layers", "executor")})


def resume_session(saved, user_input, token):
    """Validate the recovery entry and retain the original task and accumulated updates."""
    if saved.get("state_version") != STATE_VERSION or token != saved.get("resume_token"):
        raise ValueError('The task checkpoint has expired. Start a new task.')
    state = deepcopy(saved)
    state["recovery_attempts"] += 1
    state["pending_user_input"] = user_input
    state["response_language"] = choose_response_language(user_input, state.get("response_language"))
    state["recovery_history"].append({"input": user_input, "mode": state.get("recovery_mode")})
    state["pending_requests"] = state.get("execution_result", {}).get("request_sequence", []) if state.get("execution_result") else []
    if command_id(user_input) == "replan" and not state.get("operation_results"):
        state["recovery_mode"] = "replan"
    elif state.get("recovery_mode") == "network_retry" and command_id(user_input) != "retry":
        state["recovery_mode"] = "parameters"
    state.update(resume_mode=True, recovery_input=user_input, error="", execution_result=None)
    return state


def recovery_context(state):
    """Provide repair context as a separate structure to routing and domain agents."""
    return sanitize({"original_request": state["user_request"],
                     "failed_task": state.get("current_task"),
                     "failed_request": state.get("error_state", {}).get("parameters"),
                     "error": state.get("error_state"),
                     "completed_steps": state.get("completed_steps", []),
                     "completed_operations": state.get("operation_results", []),
                     "user_updates": state.get("recovery_history", []),
                     "current_layouts": state.get("layout_snapshot", []),
                     "current_layers": state.get("context_snapshot", [])})
