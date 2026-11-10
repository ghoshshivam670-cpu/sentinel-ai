from langchain_core.messages import SystemMessage, HumanMessage
from sentinel.config import get_llm
from sentinel.schemas.models import TestGenerationResult
from sentinel.schemas.state import AgentState

TEST_GEN_SYSTEM_PROMPT = """You are a Principal QA & Vulnerability Research Engineer.
Your goal is to write a deterministic, self-contained Python pytest reproduction test suite.

Requirements:
1. Target the vulnerabilities identified in the audit report.
2. The test suite MUST import and test the actual code functions/classes directly (use module name without directories, e.g., `from auth_service import ...` if file is `auth_service.py`).
3. Follow Red-Green TDD strictly: Assert the EXPECTED SECURE & CORRECT behavior so that the test FAILS on the buggy/vulnerable code and PASSES once properly patched!
   - Example (SQL Injection): Assert that malicious input (`"admin' OR '1'='1"`) returns `None` or raises an error rather than bypassing auth.
   - Example (Weak Hash): Assert that stored password hashes are NOT raw unsalted MD5 (`assert stored_hash != hashlib.md5(pw.encode()).hexdigest()`), and valid login still succeeds!
   - CRITICAL: NEVER invert the assertion to assert that the bug exists (never `assert stored_hash == md5(...)`).
4. Only use Python standard library and `pytest`/`unittest.mock`. Do NOT require external packages like `bcrypt` or `argon2`.
5. Return ONLY clean executable Python code inside the structured output test_code field. No markdown fence formatting.
"""

def test_gen_node(state: AgentState) -> dict:
    """
    Generates a targeted pytest suite to verify vulnerabilities and benchmark automated fixes.
    """
    report = state.get("audit_report")
    if not report or not report.vulnerabilities:
        # If no vulnerabilities were identified, return an empty placeholder
        log_msg = "[TestEngineer] No vulnerabilities to target. Skipping test generation."
        return {
            "test_suite": None,
            "activity_log": [log_msg]
        }

    llm = get_llm(temperature=0.0)
    structured_llm = llm.with_structured_output(TestGenerationResult)

    formatted_code = ""
    for path, code in state["current_code_files"].items():
        formatted_code += f"\n--- FILE: {path} ---\n{code}\n"

    vuln_summary = "\n".join([
        f"- [{v.id}] ({v.severity}) {v.category} in {v.file_path}: {v.description}"
        for v in report.vulnerabilities
    ])

    prompt = f"""Target Vulnerabilities:
{vuln_summary}

Target Codebase:
{formatted_code}

Generate a reproduction pytest file named 'test_reproduction.py'.
"""

    messages = [
        SystemMessage(content=TEST_GEN_SYSTEM_PROMPT),
        HumanMessage(content=prompt)
    ]

    test_result: TestGenerationResult = structured_llm.invoke(messages)
    
    # Strip any accidental markdown formatting if present
    cleaned_code = test_result.test_code.strip()
    if cleaned_code.startswith("```python"):
        cleaned_code = cleaned_code[len("```python"):].strip()
    if cleaned_code.startswith("```"):
        cleaned_code = cleaned_code[len("```"):].strip()
    if cleaned_code.endswith("```"):
        cleaned_code = cleaned_code[:-3].strip()
    test_result.test_code = cleaned_code

    log_msg = f"[TestEngineer] Generated reproduction test suite '{test_result.test_file_path}' targeting {len(test_result.targeted_vulnerability_ids)} findings."
    return {
        "test_suite": test_result,
        "activity_log": [log_msg]
    }
