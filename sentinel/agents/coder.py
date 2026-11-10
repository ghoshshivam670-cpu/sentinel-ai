from langchain_core.messages import SystemMessage, HumanMessage
from sentinel.config import get_llm
from sentinel.schemas.models import PatchProposal
from sentinel.schemas.state import AgentState

CODER_SYSTEM_PROMPT = """You are a Principal Software Engineer & Security Remediator.
Your objective is to produce surgical, production-ready code fixes that eliminate the security/logic vulnerabilities AND make the reproduction test suite pass.

Guidelines:
1. Fix the root cause without introducing breaking changes or regressions.
2. Maintain existing coding style, variable names, and function signatures unless security requires change.
3. Prefer Python standard library security primitives (`hashlib.pbkdf2_hmac`, `hashlib.scrypt`, `secrets`, `hmac.compare_digest`, parameterized `sqlite3` queries) rather than external libraries like `bcrypt` or `argon2` that may not be installed in the sandbox.
4. Keep seeded/initialized accounts and valid inputs working seamlessly with your upgraded implementation (e.g., if password hashing format changes in `authenticate_user`, update `_init_db` / user seeding to store the matching salted PBKDF2 format so valid login tests pass).
5. You must return the COMPLETE updated file content for every modified file under `patched_files` dictionary (mapping filepath to full source string).
6. If this is a retry iteration, carefully read the Critic's feedback and the exact failure traceback to adjust your patch.
"""

def coder_node(state: AgentState) -> dict:
    """
    Synthesizes a targeted patch based on test failure traces and prior critic feedback.
    """
    llm = get_llm(temperature=0.0)
    structured_llm = llm.with_structured_output(PatchProposal)

    iteration = state.get("iteration_count", 0) + 1

    formatted_code = ""
    for path, code in state["current_code_files"].items():
        formatted_code += f"\n--- FILE: {path} ---\n{code}\n"

    test_context = ""
    if state.get("test_suite"):
        test_context = f"\nTarget Reproduction Test:\n{state['test_suite'].test_code}\n"

    execution_context = ""
    # Use latest verification execution if available, otherwise initial execution
    exec_res = state.get("verification_execution") or state.get("initial_execution")
    if exec_res:
        execution_context = f"\nTest Execution Output (Traceback / Failures):\nSTDOUT:\n{exec_res.stdout}\nSTDERR:\n{exec_res.stderr}\n"

    critic_context = ""
    if state.get("critic_verdict") and state["critic_verdict"].feedback_for_coder:
        critic_context = f"\nCritic Feedback from Previous Iteration:\n{state['critic_verdict'].feedback_for_coder}\n"

    prompt = f"""Codebase Snapshot:
{formatted_code}

{test_context}
{execution_context}
{critic_context}

Iteration: {iteration} of {state.get('max_iterations', 3)}
Generate the minimal, safe patch that resolves the failures and passes all assertions.
"""

    messages = [
        SystemMessage(content=CODER_SYSTEM_PROMPT),
        HumanMessage(content=prompt)
    ]

    patch: PatchProposal = structured_llm.invoke(messages)

    # Update code files state with the new patch
    new_code_files = dict(state["current_code_files"])
    for modified_file, new_content in patch.patched_files.items():
        new_code_files[modified_file] = new_content

    log_msg = f"[Coder] Iteration {iteration}: Applied patch modifying {len(patch.files_modified)} file(s): {', '.join(patch.files_modified)}."

    return {
        "latest_patch": patch,
        "current_code_files": new_code_files,
        "iteration_count": iteration,
        "activity_log": [log_msg]
    }
