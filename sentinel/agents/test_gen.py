from langchain_core.messages import SystemMessage, HumanMessage
from sentinel.config import get_llm
from sentinel.schemas.models import TestGenerationResult
from sentinel.schemas.state import AgentState

TEST_GEN_SYSTEM_PROMPT = """You are a Principal QA & Vulnerability Research Engineer.
Your goal is to write a deterministic, self-contained Python pytest reproduction test suite.

Requirements:
1. Target the vulnerabilities identified in the audit report.
2. The test suite MUST import and test the actual code functions/classes directly.
3. Assert the EXPECTED SECURE & CORRECT behavior.
   - Example: If SQL injection allows ' OR 1=1 --, the test should assert that malicious input raises an exception or returns empty/safe output.
   - Example: If off-by-one causes IndexError or wrong sum, the test must assert the correct boundary calculation.
4. The test must be runnable via `pytest` without external internet dependencies or manual mocks of everything. Use mock/unittest.mock if testing DB or external HTTP.
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
