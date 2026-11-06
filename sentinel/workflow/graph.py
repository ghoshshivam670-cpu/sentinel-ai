from typing import Literal
from langgraph.graph import StateGraph, START, END

from sentinel.schemas.state import AgentState
from sentinel.agents.planner import planner_node
from sentinel.agents.auditor import auditor_node
from sentinel.agents.test_gen import test_gen_node
from sentinel.agents.coder import coder_node
from sentinel.agents.critic import critic_node
from sentinel.agents.reporter import reporter_node
from sentinel.sandbox.runner import SandboxRunner

# -------------------------------------------------------------
# Sandbox Execution Node Wrappers
# -------------------------------------------------------------

def initial_sandbox_node(state: AgentState) -> dict:
    """
    Executes the generated reproduction test suite against the original, untouched codebase.
    """
    test_suite = state.get("test_suite")
    if not test_suite or not test_suite.test_code.strip():
        return {
            "initial_execution": None,
            "activity_log": ["[Sandbox] No test suite generated to execute."]
        }

    runner = SandboxRunner()
    result = runner.execute_test_suite(
        code_files=state["original_code_files"],
        test_file_name=test_suite.test_file_path,
        test_file_content=test_suite.test_code
    )

    if result.passed:
        log_msg = f"[Sandbox] Initial tests passed. Target code behaves as asserted."
    else:
        log_msg = f"[Sandbox] Vulnerability REPRODUCED! Tests failed as expected ({result.failures} failures, {result.errors} errors)."

    return {
        "initial_execution": result,
        "activity_log": [log_msg]
    }

def verification_sandbox_node(state: AgentState) -> dict:
    """
    Executes the reproduction test suite against the newly patched code to evaluate remediation.
    """
    test_suite = state.get("test_suite")
    if not test_suite:
        return {
            "verification_execution": None,
            "activity_log": ["[Sandbox] No test suite found for verification."]
        }

    runner = SandboxRunner()
    result = runner.execute_test_suite(
        code_files=state["current_code_files"],
        test_file_name=test_suite.test_file_path,
        test_file_content=test_suite.test_code
    )

    log_msg = f"[Sandbox] Verification run finished. Status: {'PASS' if result.passed else 'FAIL'} in {result.execution_time_seconds}s."

    return {
        "verification_execution": result,
        "activity_log": [log_msg]
    }

# -------------------------------------------------------------
# Conditional Routing Functions
# -------------------------------------------------------------

def route_after_initial_sandbox(state: AgentState) -> Literal["coder", "reporter"]:
    """
    Determines whether remediation is required.
    If no tests were generated, or tests unexpectedly passed (no bug reproduced), route to reporter.
    Otherwise, initiate healing in coder.
    """
    audit = state.get("audit_report")
    test_suite = state.get("test_suite")
    init_exec = state.get("initial_execution")

    if not audit or not audit.vulnerabilities or not test_suite:
        return "reporter"
    
    if init_exec and init_exec.passed:
        # The reproduction test didn't fail on initial code
        return "reporter"

    return "coder"

def route_after_critic(state: AgentState) -> Literal["coder", "reporter"]:
    """
    Cyclic loop decision:
    - If critic approves: route to reporter.
    - If critic rejects and iterations remain: loop back to coder.
    - If max iterations reached: route to reporter for escalation.
    """
    verdict = state.get("critic_verdict")
    iters = state.get("iteration_count", 0)
    max_iters = state.get("max_iterations", 3)

    if not verdict:
        return "reporter"

    if verdict.decision == "PASS":
        return "reporter"
    
    if verdict.decision == "RETRY" and iters < max_iters:
        return "coder"

    return "reporter"

# -------------------------------------------------------------
# Graph Assembly
# -------------------------------------------------------------

def build_sentinel_graph():
    """
    Constructs the compiled LangGraph StateGraph with reflection loops.
    """
    workflow = StateGraph(AgentState)

    # 1. Register Nodes
    workflow.add_node("planner", planner_node)
    workflow.add_node("auditor", auditor_node)
    workflow.add_node("test_generator", test_gen_node)
    workflow.add_node("initial_sandbox", initial_sandbox_node)
    workflow.add_node("coder", coder_node)
    workflow.add_node("verification_sandbox", verification_sandbox_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("reporter", reporter_node)

    # 2. Add Fixed Edges
    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "auditor")
    workflow.add_edge("auditor", "test_generator")
    workflow.add_edge("test_generator", "initial_sandbox")

    # 3. Add Conditional Routing from Initial Sandbox
    workflow.add_conditional_edges(
        "initial_sandbox",
        route_after_initial_sandbox,
        {
            "coder": "coder",
            "reporter": "reporter"
        }
    )

    # 4. Add Remediation & Reflection Edges
    workflow.add_edge("coder", "verification_sandbox")
    workflow.add_edge("verification_sandbox", "critic")

    # 5. Add Conditional Routing from Critic (The Loop!)
    workflow.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "coder": "coder",
            "reporter": "reporter"
        }
    )

    workflow.add_edge("reporter", END)

    return workflow.compile()
