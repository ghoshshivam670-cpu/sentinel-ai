import json
from langchain_core.messages import SystemMessage, HumanMessage
from sentinel.config import get_llm
from sentinel.schemas.models import AuditPlan
from sentinel.schemas.state import AgentState

PLANNER_SYSTEM_PROMPT = """You are the Lead Security & Systems Architect for SentinelAI.
Your role is to inspect the submitted codebase snapshot, identify high-risk logic modules,
and construct a precise, structured audit strategy.

You must return a structured AuditPlan with:
- summary: High-level architectural understanding of the code
- focus_areas: Specific risks (e.g., Auth logic, SQL injection, concurrency, input validation)
- steps: Step-by-step actions for the auditing and reproduction pipeline
"""

def planner_node(state: AgentState) -> dict:
    """
    Analyzes the initial code files and produces an AuditPlan.
    """
    llm = get_llm(temperature=0.0)
    structured_llm = llm.with_structured_output(AuditPlan)

    # Format files for inspection
    formatted_code = ""
    for path, code in state["current_code_files"].items():
        formatted_code += f"\n--- FILE: {path} ---\n{code}\n"

    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=f"Codebase files to analyze:\n{formatted_code}")
    ]

    plan: AuditPlan = structured_llm.invoke(messages)

    log_msg = f"[Planner] Architecture plan formulated. Focus areas: {', '.join(plan.focus_areas)}"
    return {
        "plan": plan,
        "activity_log": [log_msg]
    }
