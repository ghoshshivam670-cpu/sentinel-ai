import ast
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
5. Ensure EVERY used module or name (such as `pytest`, `hashlib`, `hmac`, `sqlite3`, `inspect`, `re`, `json`) is explicitly imported at the top of `test_code`. Zero undefined NameError/ImportError bugs!
6. Return ONLY clean executable Python code inside the structured output test_code field. No markdown fence formatting.
"""


def _ensure_stdlib_imports(test_code: str) -> str:
    """Adds missing top-level imports for common stdlib modules referenced via attribute access."""
    common_modules = ("pytest", "hashlib", "hmac", "sqlite3", "inspect", "re", "json", "os", "secrets")
    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return test_code

    imported = set()
    referenced_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            referenced_roots.add(node.value.id)

    missing = [mod for mod in common_modules if mod in referenced_roots and mod not in imported]
    if not missing:
        return test_code

    import_header = "\n".join(f"import {mod}" for mod in missing)
    return f"{import_header}\n{test_code}"

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
    test_result.test_code = _ensure_stdlib_imports(cleaned_code)

    log_msg = f"[TestEngineer] Generated reproduction test suite '{test_result.test_file_path}' targeting {len(test_result.targeted_vulnerability_ids)} findings."
    return {
        "test_suite": test_result,
        "activity_log": [log_msg]
    }
