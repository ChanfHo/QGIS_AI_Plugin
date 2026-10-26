"""Run the existing graph and bridge its signals to the GUI controller."""
from ..core.runtime_support import log_message
from PyQt5.QtCore import QThread, pyqtSignal
from qgis.core import QgsProject, Qgis
from ..services.chat_model import chat_with_openai, call_qwen_with_prompt
from .workflow_graph import create_workflow_graph
from ..core.error_handling import error_from_message, sanitize
from .recovery_session import initialize_session, checkpoint, save_checkpoint
from .prompts import FINAL_SUMMARY_PROMPT
from ..core.localization import choose_response_language, response_scope, t

class AgentsWorkgroupThread(QThread):
    """Run the LangGraph workgroup logic in the background."""
    # Message signal: (text, sender, msg_type).
    message_signal = pyqtSignal(str, str, str)
    
    # Additional signals.
    thought_signal = pyqtSignal(str) # Reasoning content.
    init_steps_signal = pyqtSignal(list) # Initialize the step list.
    update_step_signal = pyqtSignal(int, str, str) # Update step status (index, status, result).
    final_response_signal = pyqtSignal(str) # Final natural-language response.
    error_report_signal = pyqtSignal(dict) # Pass the shared error instance.
    recovery_state_signal = pyqtSignal(dict)
    
    refresh_map_canvas_signal = pyqtSignal()

    # Download progress signal: target_name, percent.
    download_progress_signal = pyqtSignal(str, int)

    # Signal carrying the layout task list.
    layout_task_signal = pyqtSignal(list)
    # Stop signal.
    stop_signal = pyqtSignal()

    def __init__(self, user_text, layers, resume_state=None, parent=None):
        super().__init__(parent)
        self.user_text = user_text
        self.layers = layers
        self.resume_state = resume_state
        self.response_language = choose_response_language(
            user_text, (resume_state or {}).get("response_language"))
        self.layout_snapshot = [layout.name() for layout in QgsProject.instance().layoutManager().layouts()]
        # Variable receiving main-thread execution results.
        self.layout_op_result = None
        self._is_stopped = False
        self.execution_log = [] # Record execution logs for the summary.

    def stop(self):
        """Stop the thread's task."""
        self._is_stopped = True
        self.stop_signal.emit()

    def emit_download_progress(self, target_name: str, percent: int):
        """Emit download progress."""
        self.download_progress_signal.emit(target_name, percent)

    def execute_layout_op(self, tasks, operation_results=None):
        """Execute layout operations on the main thread."""
        self.layout_op_result = None
        self.layout_operation_results = operation_results if operation_results is not None else []
        if self._is_stopped: return "Task stopped"
        
        # Emit the layout task signal.
        self.layout_task_signal.emit(tasks)
        
        # Poll until the main thread finishes and returns a result.
        while self.layout_op_result is None:
            if self._is_stopped: return "Task stopped"
            self.msleep(50)
            
        return self.layout_op_result
        
    def refresh_layers(self):
        """Refresh and return the current layer list."""
        if self._is_stopped: return []
        # Request a main-thread UI refresh.
        self.refresh_map_canvas_signal.emit()
        # Get current layers; accessing QgsProject across threads may be unsafe, although reads usually work.
        self.layers = list(QgsProject.instance().mapLayers().values())
        return self.layers

    def generate_final_summary(self, thought):
        """Generate the final natural-language summary."""
        log_str = "\n".join(self.execution_log)
        prompt = FINAL_SUMMARY_PROMPT.format(
            user_request=self.user_text,
            thought=thought,
            execution_log=log_str
        )
        try:
            summary = call_qwen_with_prompt(prompt)
            return summary
        except Exception:
            return t('Task completed.')

    def generate_error_report(self, error_state):
        """Generate user feedback without raw exceptions."""
        log_message(
            f"[{error_state.get('trace_id')}/{error_state.get('error_id')}] "
            f"{error_state.get('error_code')}: {sanitize(error_state.get('technical_detail'))}",
            tag="AI_AGENT_ERROR",
            level=Qgis.Critical,
        )
        return error_state

    def save_recovery_state(self, state_update, error_state):
        """Save the current step checkpoint only for recoverable errors."""
        if not error_state.get("can_continue"):
            self.recovery_state_signal.emit({})
            return
        self.recovery_state_signal.emit(save_checkpoint(state_update))

    @staticmethod
    def failure_status(error_state):
        """Distinguish waiting for parameters, waiting for retry and stopped states."""
        if not error_state.get("can_continue"):
            return "fail"
        code = error_state.get("error_code", "")
        return "waiting_retry" if code.startswith("MODEL_") or code in ("NETWORK_FAILED", "INVALID_JSON") else "waiting"

    # Run the agent workgroup.
    def run(self):
        with response_scope(self.response_language):
            self._run_workflow()

    def _run_workflow(self):
        # Initial state.
        inputs = {
            "user_request": self.user_text,
            "response_language": self.response_language,
            "layers": self.layers,
            "task_plan": [],
            "current_step": 0,
            "current_task": "",
            "assigned_agent": "",
            "execution_result": None,
            "error": "",
            "error_state": {},
            "resume_mode": False,
            "recovery_input": "",
            "is_gis_task": True,
            "thought": "",
            "executor": self
        }
        if self.resume_state:
            inputs.update(self.resume_state)
            inputs["layers"] = self.layers
            inputs["executor"] = self
            inputs["execution_result"] = None
            inputs["error"] = ""
            inputs["resume_mode"] = True
            inputs["recovery_input"] = self.user_text
        initialize_session(inputs)
        inputs["layout_snapshot"] = self.layout_snapshot

        current_thought = ""
        task_plan = []
        latest_state = inputs

        try:
            app = create_workflow_graph()
            # Run in streaming mode.
            config = {"recursion_limit": 150}
            for event in app.stream(inputs, config=config):
                if self._is_stopped:
                    self.message_signal.emit('The user manually stopped the workflow.', "ai", "text")
                    return

                for node_name, state_update in event.items():
                    if self._is_stopped: return
                    latest_state = state_update
                    
                    # Error handling.
                    if "error" in state_update and state_update["error"]:
                        err_msg = state_update["error"]
                        error_state = state_update.get("error_state") or error_from_message(err_msg, node_name)
                        report = self.generate_error_report(error_state)
                        self.save_recovery_state(state_update, error_state)
                        status = self.failure_status(error_state)
                        self.update_step_signal.emit(state_update.get("current_step", 0), status, t(error_state["user_title"]))
                        self.error_report_signal.emit(report)
                        return 

                    # Handle task planner output.
                    if node_name == "task_planner":
                        # Emit reasoning first when available, for both GIS and non-GIS tasks.
                        current_thought = state_update.get("thought", "")
                        if current_thought:
                             self.thought_signal.emit(current_thought)

                        if not state_update.get("is_gis_task", True):
                            # Use ordinary chat for non-GIS tasks.
                            ai_response = chat_with_openai(self.user_text)
                            self.final_response_signal.emit(ai_response)
                            return 

                        # Emit the planned steps.
                        task_plan = state_update.get("task_plan", [])
                        self.init_steps_signal.emit(task_plan)
                        if self.resume_state:
                            completed_count = state_update.get("current_step", 0)
                            for completed_index in range(completed_count):
                                self.update_step_signal.emit(completed_index, "success", t('Completed before the checkpoint'))
                        
                        # Record logs.
                        self.execution_log.append('Task planning: {v0} steps'.format(v0=len(task_plan)))

                    # 2. Router node: task start.
                    elif node_name == "task_router":
                        step_idx = state_update.get("current_step", 0)
                        task_desc = state_update.get("current_task", "")
                        
                        # Set the UI to running.
                        self.update_step_signal.emit(step_idx, "running", "")
                        self.execution_log.append('Step {v0} started: {v1}'.format(v0=step_idx + 1, v1=task_desc))

                    # 3. Executor node: task completion.
                    elif node_name == "agent_executor":
                        result = state_update.get("execution_result", {})
                        step_idx = state_update.get("current_step", 0) # This is still the current step index.
                        
                        if result.get("is_process_complete"):
                            tool_res = result.get("tool_result", 'Completed')
                            self.update_step_signal.emit(step_idx, "success", tool_res)
                            self.execution_log.append('Step {v0} succeeded: {v1}'.format(v0=step_idx + 1, v1=tool_res))
                            self.refresh_map_canvas_signal.emit()
                        else:
                            error_state = result.get("error_state") or error_from_message(
                                result.get("possible_problem", 'Unknown error'), node_name
                            )
                            status = self.failure_status(error_state)
                            self.update_step_signal.emit(step_idx, status, t(error_state["user_title"]))
                            report = self.generate_error_report(error_state)
                            self.save_recovery_state(state_update, error_state)
                            self.error_report_signal.emit(report)
                            return
                            
            # Workflow completed normally.
            if not self._is_stopped and task_plan:
                summary = self.generate_final_summary(current_thought)
                self.final_response_signal.emit(summary)

        except Exception as e:
            if not self._is_stopped:
                error_state = error_from_message(e, "workflow_runtime")
                checkpoint(latest_state, error_state)
                self.save_recovery_state(latest_state, error_state)
                report = self.generate_error_report(error_state)
                self.error_report_signal.emit(report)
