from typing import TypedDict, List, Any, Dict
import json
from langgraph.graph import StateGraph, END

from .chat_model import call_qwen_json, validate_object, ModelContractError
from .prompts import TASK_PLANNER_PROMPT, TASK_ROUTER_PROMPT
from .agents import run_agent_a, run_agent_b, run_agent_c, run_agent_d
from .error_handling import error_from_message, normalize_execution_result, failure, sanitize
from .recovery_session import initialize_session, checkpoint, recovery_context

# ==============================
# LangGraph State
# ==============================

class GraphState(TypedDict):
    state_version: int
    task_id: str
    trace_id: str
    resume_token: str
    failed_step: int
    failed_node: str
    completed_steps: List[int]
    execution_history: List[Dict]
    context_snapshot: List[Dict]
    recovery_mode: str
    recovery_attempts: int
    pending_user_input: str
    recovery_history: List[Dict]
    repair_context: Dict
    operation_results: List[Dict]
    pending_requests: List[Dict]
    layout_snapshot: List[str]
    user_request: str
    task_plan: List[Dict]
    current_step: int
    current_task: str
    assigned_agent: str
    execution_result: Any
    layers: List[Any]  # QGIS Layers
    error: str # 智能体执行后错误信息
    error_state: Dict[str, Any]
    resume_mode: bool
    recovery_input: str
    is_gis_task: bool 
    thought: str # 系统思考过程输出内容
    executor: Any # 智能体执行器

# ==============================
# Node 1: Task Planner
# ==============================

def task_planner_node(state: GraphState):
    initialize_session(state)
    if state.get("resume_mode") and state.get("task_plan") and state.get("recovery_mode") != "replan":
        state["repair_context"] = recovery_context(state)
        state["error"] = ""
        return state

    user_request = state["user_request"]
    layers = state.get("layers", [])
    
    # 提取当前图层信息
    layer_info_str = "当前工程中没有任何图层"
    if layers:
        layer_infos = []
        for layer in layers:
            try:
                name = layer.name()
                layer_type = "矢量" if layer.type() == 0 else "栅格" if layer.type() == 1 else "其他"
                fields = []
                if layer.type() == 0: 
                    fields = [field.name() for field in layer.fields()]
                fields_str = f"，属性字段：{', '.join(fields)}" if fields else ""
                layer_infos.append(f"- {name} ({layer_type}){fields_str}")
            except Exception:
                pass
        if layer_infos:
            layer_info_str = "\n".join(layer_infos)

    # LLM提示词构建
    prompt = TASK_PLANNER_PROMPT.format(
        user_request=user_request,
        project_layers=layer_info_str
    )
    if state.get("resume_mode"):
        prompt += "\n仅规划尚未完成的步骤，不得重做已完成操作。恢复上下文：" + json.dumps(recovery_context(state), ensure_ascii=False)
    
    try:
        parsed_result = call_qwen_json(prompt)
        if isinstance(parsed_result, dict):
            validate_object(parsed_result, {"plan": list})
            if "is_gis_task" in parsed_result and not isinstance(parsed_result["is_gis_task"], bool):
                raise ModelContractError("is_gis_task必须为布尔值", attempts=1)
        elif not isinstance(parsed_result, list):
            raise ModelContractError("规划结果必须包含步骤列表", attempts=1)
        
        # 兼容裸步骤列表，同时单独验证规划元数据。
        metadata = parsed_result if isinstance(parsed_result, dict) else {}
        if "thought" in metadata and not isinstance(metadata["thought"], str):
            raise ModelContractError("thought必须为文本", attempts=1)
        state["thought"] = metadata.get("thought", "")
        state["is_gis_task"] = metadata.get("is_gis_task", True)
        task_plan = metadata["plan"] if metadata else parsed_result

        for item in task_plan:
            validate_object(item, {"task": str})
            if not item["task"].strip():
                raise ModelContractError("计划步骤不能为空", attempts=1)
        if state.get("is_gis_task", True) and not task_plan:
            raise ModelContractError("GIS任务计划不能为空", attempts=1)

        # 初始化系统状态
        prefix = state.get("task_plan", [])[:state.get("current_step", 0)] if state.get("recovery_mode") == "replan" else []
        state["task_plan"] = prefix + task_plan
        state["current_step"] = len(prefix)
        state["error"] = ""
        state["error_state"] = {}
        if task_plan:
            state["current_task"] = task_plan[0].get("task", "")
        else:
            state["current_task"] = ""
            
    except Exception as e:
        state["error"] = sanitize(str(e))
        state["error_state"] = error_from_message(
            e, "task_planner", getattr(e, "attempts", 0)
        )
        checkpoint(state, state["error_state"])
        
    return state

# ==============================
# Node 2: Task Router
# ==============================

def task_router_node(state: GraphState):
    if state.get("error"):
        return state
    
    # 如果不是GIS任务，直接跳过路由
    if not state.get("is_gis_task", True):
        return state

    # 获取当前任务执行步骤
    step = state["current_step"]
    if step < len(state["task_plan"]):
        
        # 从当前系统状态中读取信息并构造提示词
        task = state["task_plan"][step]["task"]
        state["current_task"] = task
        if state.get("repair_context") and state.get("recovery_mode") in ("network_retry", "model_retry"):
            failed_agent = state.get("failed_node")
            if failed_agent in ("agent_a", "agent_b", "agent_c", "agent_d"):
                state["assigned_agent"] = failed_agent
                state["resume_mode"] = False
                return state
        prompt = TASK_ROUTER_PROMPT.format(task=task)
        if state.get("repair_context"):
            prompt += "\n修复上下文：" + json.dumps(state["repair_context"], ensure_ascii=False)
        
        try:
            router_output = call_qwen_json(prompt)
            validate_object(router_output, {"agent": str})
            agent = router_output.get("agent", "unknown")
            if state.get("operation_results") and state.get("assigned_agent") != agent:
                error = failure("ROUTE_FAILED", "task_router", "当前步骤已有成功的子操作，恢复时不能切换领域智能体。")["error_state"]
                checkpoint(state, error)
                state["error"] = error["user_title"]
                return state
            if agent not in ("agent_a", "agent_b", "agent_c", "agent_d"):
                error = failure("ROUTE_FAILED", "task_router", "路由未返回有效智能体")["error_state"]
                checkpoint(state, error)
                state["error"] = error["user_title"]
                return state
            
            # 将输出结果写回共享状态
            state["assigned_agent"] = agent
            state["current_task"] = task
            state["resume_mode"] = False
            
            if "step" in state["task_plan"][step]:
                pass 
        except Exception as e:
            state["error"] = sanitize(str(e))
            state["error_state"] = error_from_message(
                e, "task_router", getattr(e, "attempts", 0)
            )
            checkpoint(state, state["error_state"])
    
    return state

# ==============================
# Node 3: Agent Executor
# ==============================

def agent_executor_node(state: GraphState):
    if state.get("error"):
        return state
    
    # 如果不是GIS任务，直接跳过执行
    if not state.get("is_gis_task", True):
        return state

    agent = state["assigned_agent"]
    task = state["current_task"]
    state["execution_history"].append({"node": "agent_executor", "step": state["current_step"],
                                        "input": sanitize(task)})
    if state.get("repair_context"):
        task += "\n修复上下文（仅修复当前失败步骤）：" + json.dumps(state["repair_context"], ensure_ascii=False)
    layers = state.get("layers", [])
    
    # 获取外部执行器，用于主线程操作
    executor = state.get("executor")
    result = failure("UNKNOWN_AGENT", "agent_executor", "未分配领域智能体")
    
    try:
        if agent == "agent_a":
            result = run_agent_a(task, progress_callback=executor.emit_download_progress if executor else None,
                                 operation_results=state["operation_results"],
                                 requests_override=state.get("pending_requests") if state.get("recovery_mode") == "network_retry" else None)
        elif agent == "agent_b":
            result = run_agent_b(task, layers)
        elif agent == "agent_c":
            result = run_agent_c(task, layers)
        elif agent == "agent_d":
            plan = run_agent_d(task, layers)
            if plan.get("is_process_complete"):
                tasks = plan.get("tasks", [])
                if tasks and executor:
                    # 调用外部执行器执行布局任务
                    exec_res = executor.execute_layout_op(tasks, state["operation_results"])
                    if isinstance(exec_res, dict):
                        result = exec_res
                    elif isinstance(exec_res, str) and ("Error:" in exec_res or "取消" in exec_res or "任务已停止" in exec_res):
                        result = {"is_process_complete": False, "possible_problem": exec_res}
                    else:
                        result = {"is_process_complete": True, "tool_result": exec_res}
                elif not tasks:
                    result = failure("INVALID_CONTRACT", "agent_d", "未生成布局任务")
                else:
                    result = failure("INTERNAL_ERROR", "agent_d", "未提供主线程布局执行器")
            else:
                 result = plan
        else:
            result = failure("UNKNOWN_AGENT", "agent_executor", f"未知智能体：{agent}")
            
        state["execution_result"] = normalize_execution_result(result, agent)
        if not state["execution_result"].get("is_process_complete"):
            checkpoint(state, state["execution_result"]["error_state"])
        else:
            state["execution_history"].append({"node": agent, "step": state["current_step"],
                                                "result": sanitize(result)})
        
    except Exception as e:
        state["error"] = sanitize(str(e))
        state["error_state"] = error_from_message(
            e, "agent_executor", getattr(e, "attempts", 0)
        )
        checkpoint(state, state["error_state"])
        state["execution_result"] = normalize_execution_result(
            {"is_process_complete": False, "error_state": state["error_state"]}, "agent_executor"
        )

    return state

# ==============================
# Node 4: Step Updater
# ==============================

def step_updater_node(state: GraphState):
    """
    更新任务步骤的节点
    """
    if state.get("error"):
        return state
    result = state.get("execution_result") or {}
    if result.get("is_process_complete", False):
        if state["current_step"] not in state["completed_steps"]:
            state["completed_steps"].append(state["current_step"])
        state["current_step"] += 1
        state["repair_context"] = {}
        state["error_state"] = {}
        state["operation_results"] = []
        state["pending_requests"] = []
        state["recovery_mode"] = ""
    return state

# ==============================
# Conditional Logic
# ==============================

def check_loop_condition(state: GraphState):
    """
    检查循环条件，决定下一步走向
    """
    if state.get("error"):
        return "error"
    
    if not state.get("is_gis_task", True):
        return "end"

    result = state.get("execution_result") or {}
    
    if not result.get("is_process_complete", False):
        # 任务失败
        return "error"
    
    if state["current_step"] < len(state["task_plan"]):
        return "continue"
    else:
        return "end"

# ==============================
# Build Graph
# ==============================

def create_workflow_graph():
    workflow = StateGraph(GraphState)
    # 添加节点
    workflow.add_node("task_planner", task_planner_node)
    workflow.add_node("task_router", task_router_node)
    workflow.add_node("agent_executor", agent_executor_node)
    workflow.add_node("step_updater", step_updater_node)
    # 设置入口点
    workflow.set_entry_point("task_planner")
    # 添加边
    workflow.add_conditional_edges("task_planner", lambda state: "stop" if state.get("error") or not state.get("is_gis_task", True) else "continue",
                                   {"stop": END, "continue": "task_router"})
    workflow.add_conditional_edges("task_router", lambda state: "stop" if state.get("error") else "continue",
                                   {"stop": END, "continue": "agent_executor"})
    workflow.add_edge("agent_executor", "step_updater")
    # 添加条件边
    workflow.add_conditional_edges(
        "step_updater",
        check_loop_condition,
        {
            "continue": "task_router",
            "end": END,
            "error": END
        }
    )

    app = workflow.compile()
    return app
