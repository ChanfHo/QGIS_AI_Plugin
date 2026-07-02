import json
import logging
from typing import TypedDict, List, Any, Dict
from langgraph.graph import StateGraph, END
from colorama import Fore

from .chat_model import call_qwen_with_prompt, safe_json_loads
from .prompts import TASK_PLANNER_PROMPT, TASK_ROUTER_PROMPT
from .agents import run_agent_a, run_agent_b, run_agent_c, run_agent_d

# ==============================
# LangGraph State
# ==============================

class GraphState(TypedDict):
    user_request: str
    task_plan: List[Dict]
    current_step: int
    current_task: str
    assigned_agent: str
    execution_result: Any
    layers: List[Any]  # QGIS Layers
    error: str # 智能体执行后错误信息
    is_gis_task: bool 
    thought: str # 系统思考过程输出内容
    executor: Any # 智能体执行器

# ==============================
# Node 1: Task Planner
# ==============================

def task_planner_node(state: GraphState):
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
    
    try:
        result = call_qwen_with_prompt(prompt)
        parsed_result = safe_json_loads(result)
        
        # 处理包含thought和plan的返回结构
        if "thought" in parsed_result:
            state["thought"] = parsed_result["thought"]
        if "is_gis_task" in parsed_result:
            state["is_gis_task"] = parsed_result["is_gis_task"]
        else:
            state["is_gis_task"] = True

        if "plan" in parsed_result:
            task_plan = parsed_result["plan"]
        elif isinstance(parsed_result, list):
            task_plan = parsed_result
        else:
            task_plan = [parsed_result]

        # 初始化系统状态
        state["task_plan"] = task_plan
        state["current_step"] = 0
        if task_plan:
            state["current_task"] = task_plan[0].get("task", "")
        else:
            state["current_task"] = ""
            
    except Exception as e:
        state["error"] = f"TaskPlanner Error: {str(e)}"
        
    return state

# ==============================
# Node 2: Task Router
# ==============================

def task_router_node(state: GraphState):
    
    # 如果不是GIS任务，直接跳过路由
    if not state.get("is_gis_task", True):
        return state

    # 获取当前任务执行步骤
    step = state["current_step"]
    if step < len(state["task_plan"]):
        
        # 从当前系统状态中读取信息并构造提示词
        task = state["task_plan"][step]["task"]
        prompt = TASK_ROUTER_PROMPT.format(task=task)
        
        try:
            result = call_qwen_with_prompt(prompt)
            router_output = safe_json_loads(result)
            agent = router_output.get("agent", "unknown")
            
            # 将输出结果写回共享状态
            state["assigned_agent"] = agent
            state["current_task"] = task
            
            if "step" in state["task_plan"][step]:
                pass 
        except Exception as e:
            state["error"] = f"TaskRouter Error: {str(e)}"
    
    return state

# ==============================
# Node 3: Agent Executor
# ==============================

def agent_executor_node(state: GraphState):
    
    # 如果不是GIS任务，直接跳过执行
    if not state.get("is_gis_task", True):
        return state

    agent = state["assigned_agent"]
    task = state["current_task"]
    layers = state["layers"]
    
    # 获取外部执行器，用于主线程操作
    executor = state.get("executor")
    result = {"is_process_complete": False, "possible_problem": "Unknown agent"}
    
    try:
        if agent == "agent_a":
            result = run_agent_a(task, progress_callback=executor.emit_download_progress if executor else None)
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
                    exec_res = executor.execute_layout_op(tasks)
                    if isinstance(exec_res, str) and "Error:" in exec_res:
                        result = {"is_process_complete": False, "possible_problem": exec_res}
                    else:
                        result = {"is_process_complete": True, "tool_result": exec_res}
                elif not tasks:
                     result = {"is_process_complete": False, "possible_problem": "No layout tasks generated"}
                else:
                    result = {"is_process_complete": False, "possible_problem": "Executor not provided for layout task"}
            else:
                 result = plan
        else:
            result = {"is_process_complete": False, "possible_problem": f"Unknown agent: {agent}"}
            
        state["execution_result"] = result
        
    except Exception as e:
        state["error"] = f"AgentExecutor Error: {str(e)}"
        state["execution_result"] = {"is_process_complete": False, "possible_problem": str(e)}

    return state

# ==============================
# Node 4: Step Updater
# ==============================

def step_updater_node(state: GraphState):
    """
    更新任务步骤的节点
    """
    result = state.get("execution_result", {})
    if result.get("is_process_complete", False):
        state["current_step"] += 1
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

    result = state.get("execution_result", {})
    
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
    workflow.add_edge("task_planner", "task_router")
    workflow.add_edge("task_router", "agent_executor")
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
