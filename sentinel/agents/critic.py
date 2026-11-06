from langchain_core.messages import SystemMessage, HumanMessage
from sentinel.config import get_llm
from sentinel.schemas.models import CriticVerdict
from sentinel.schemas.state import AgentState

CRITIC_SYSTEM_PROMPT = """You are the Lead Quality & Security Verification Critic.
Your job is to analyze the test execution results following a proposed patch by the Coder Agent.

Analysis Protocol:
1. Examine the test suite exit code, stdout, and failure tracebacks.
2. If all tests PASSED:
   - Verify that the patch genuinely remediated the root vulnerability rather than deleting test assertions or hardcoding dummy returns.
   - Set decision to 'PASS'.
3. If tests FAILED or errors occurred:
   - Provide deep root-cause diagnostic feedback under `feedback_for_coder`.
   - Highlight the exact assertion failure, unexpected exception, or syntax issue.
   - Set decision to 'RETRY'.
4. If the iteration count has exceeded the maximum limit, mark decision as 'ESCALATE'.
"""

def critic_node(state: AgentState) -> dict:
    """
    Evaluates execution results and decides whether to accept the patch, retry with feedback, or escalate.
    """
    iteration = state.get("iteration_count", 0)
    max_iters = state.get("max_iterations", 3)
    verif_res = state.get("verification_execution")

    # If execution failed or wasn't clean
    if not verif_res or not verif_res.passed:
        if iteration >= max_iters:
            verdict = CriticVerdict(
                decision="ESCALATE",
                passed_tests_verified=False,
                feedback_for_coder=f"Max iteration limit ({max_iters}) reached. Remaining error: {verif_res.stderr if verif_res else 'Unknown'}",
                regressions_detected=True
            )
            log_msg = f"[Critic] Escalation triggered: Max iterations ({max_iters}) reached without passing tests."
            return {
                "critic_verdict": verdict,
                "final_status": "MAX_ITERATIONS_REACHED",
                "activity_log": [log_msg]
            }

    llm = get_llm(temperature=0.0)
    structured_llm = llm.with_structured_output(CriticVerdict)

    exec_info = "No test execution found."
    if verif_res:
        exec_info = f"""
Exit Code: {verif_res.exit_code}
Passed: {verif_res.passed} (Total: {verif_res.total_tests}, Failures: {verif_res.failures}, Errors: {verif_res.errors})
STDOUT:
{verif_res.stdout}
STDERR:
{verif_res.stderr}
"""

    prompt = f"""
Current Iteration: {iteration} / {max_iters}

Patch Summary:
{state.get('latest_patch').explanation if state.get('latest_patch') else 'N/A'}

Test Execution Results:
{exec_info}

Provide your structured verification verdict.
"""

    messages = [
        SystemMessage(content=CRITIC_SYSTEM_PROMPT),
        HumanMessage(content=prompt)
    ]

    verdict: CriticVerdict = structured_llm.invoke(messages)

    if verdict.decision == "PASS":
        log_msg = f"[Critic] Patch ACCEPTED! All tests verified successfully in iteration {iteration}."
        final_status = "SUCCESS"
    elif verdict.decision == "ESCALATE" or iteration >= max_iters:
        verdict.decision = "ESCALATE"
        log_msg = f"[Critic] Iteration {iteration}: Escalating to developer review."
        final_status = "ESCALATED"
    else:
        log_msg = f"[Critic] Iteration {iteration}: Patch rejected. Retrying with targeted feedback."
        final_status = "IN_PROGRESS"

    return {
        "critic_verdict": verdict,
        "final_status": final_status,
        "activity_log": [log_msg]
    }
