from langchain_core.messages import SystemMessage, HumanMessage
from sentinel.config import get_llm
from sentinel.schemas.models import AuditReport
from sentinel.schemas.state import AgentState

AUDITOR_SYSTEM_PROMPT = """You are a Principal Application Security & Reliability Engineer.
Your task is to conduct an in-depth security and logic audit of the provided codebase.

Look for:
1. Security Flaws: OWASP Top 10, CWE-89 (SQLi), CWE-79 (XSS), CWE-22 (Path Traversal), Insecure Deserialization, Hardcoded Secrets.
2. Reliability & Edge Cases: Off-by-one errors, Unhandled Exceptions, Resource Leaks, Race conditions, NoneType dereferences.
3. Logical Bugs: Incorrect calculations, broken state transitions, inverted booleans.

Rules:
- Be rigorous and objective.
- For every issue found, identify the file_path, approximate line_number, severity (LOW, MEDIUM, HIGH, CRITICAL), and actionable recommendation.
- Provide an overall risk_score from 0.0 to 10.0.
- If no critical issues are found, state so cleanly.
"""

def auditor_node(state: AgentState) -> dict:
    """
    Scans the code files and outputs a structured AuditReport with identified vulnerabilities.
    """
    llm = get_llm(temperature=0.0)
    structured_llm = llm.with_structured_output(AuditReport)

    formatted_code = ""
    for path, code in state["current_code_files"].items():
        formatted_code += f"\n--- FILE: {path} ---\n{code}\n"

    plan_context = ""
    if state.get("plan"):
        plan_context = f"\nAudit Plan Context:\nFocus Areas: {state['plan'].focus_areas}\nSteps: {state['plan'].steps}\n"

    messages = [
        SystemMessage(content=AUDITOR_SYSTEM_PROMPT),
        HumanMessage(content=f"{plan_context}\nInspect the following codebase:\n{formatted_code}")
    ]

    report: AuditReport = structured_llm.invoke(messages)
    
    # Calculate has_critical_findings
    report.has_critical_findings = any(
        v.severity in ["HIGH", "CRITICAL"] for v in report.vulnerabilities
    )

    vuln_count = len(report.vulnerabilities)
    log_msg = f"[Auditor] Audit complete. Found {vuln_count} vulnerabilities (Risk Score: {report.risk_score}/10)."

    return {
        "audit_report": report,
        "activity_log": [log_msg]
    }
