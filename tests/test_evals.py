"""
SentinelAI LLMOps Automated Evaluation Benchmark Suite.
Measures agent precision, hallucination avoidance, and patch validity.
"""

import pytest
from sentinel.schemas.models import Vulnerability, AuditReport, PatchProposal
from sentinel.sandbox.runner import SandboxRunner

SAMPLE_SAFE_CODE = """
def calculate_discount(price: float, discount_percent: float) -> float:
    if not (0 <= discount_percent <= 100):
        raise ValueError("Discount must be between 0 and 100")
    return price * (1 - discount_percent / 100.0)
"""

SAMPLE_VULNERABLE_CODE = """
def authenticate_insecure(username, password, db):
    # Injection flaw
    cursor = db.cursor()
    cursor.execute(f"SELECT * FROM users WHERE username = '{username}'")
    return cursor.fetchone()
"""

def test_sandbox_runner_clean_execution():
    """
    Verifies that the isolated SandboxRunner executes valid pytest assertions safely.
    """
    runner = SandboxRunner(timeout_seconds=10)
    code_files = {"math_lib.py": "def add(a, b): return a + b\n"}
    test_code = "from math_lib import add\ndef test_add(): assert add(2, 3) == 5\n"

    result = runner.execute_test_suite(
        code_files=code_files,
        test_file_name="test_math.py",
        test_file_content=test_code
    )

    assert result.passed is True
    assert result.total_tests == 1
    assert result.failures == 0
    assert result.exit_code == 0

def test_sandbox_runner_detects_intentional_failure():
    """
    Verifies that the isolated SandboxRunner detects failed assertions and extracts tracebacks.
    """
    runner = SandboxRunner(timeout_seconds=10)
    code_files = {"math_lib.py": "def add(a, b): return a - b\n"} # Buggy implementation
    test_code = "from math_lib import add\ndef test_add(): assert add(2, 3) == 5\n"

    result = runner.execute_test_suite(
        code_files=code_files,
        test_file_name="test_math.py",
        test_file_content=test_code
    )

    assert result.passed is False
    assert result.failures >= 1
    assert "assert -1 == 5" in result.stdout or "assert" in result.stdout

def test_sandbox_runner_timeout_enforcement():
    """
    Verifies that the sandbox halts infinite loops or denial-of-service payloads.
    """
    runner = SandboxRunner(timeout_seconds=2)
    code_files = {"dos.py": "import time\ndef hang(): time.sleep(10)\n"}
    test_code = "from dos import hang\ndef test_hang(): hang()\n"

    result = runner.execute_test_suite(
        code_files=code_files,
        test_file_name="test_dos.py",
        test_file_content=test_code
    )

    assert result.passed is False
    assert "timed out" in result.stderr.lower() or result.exit_code == -1


def test_sandbox_runner_blocks_path_traversal():
    """
    Verifies that SandboxRunner rejects file paths attempting directory traversal outside the sandbox.
    """
    runner = SandboxRunner(timeout_seconds=10)
    result = runner.execute_test_suite(
        code_files={"../../escape.py": "print('pwned')"},
        test_file_name="test_sec.py",
        test_file_content="def test_noop(): assert True"
    )
    assert result.passed is False
    assert "unsafe file path" in result.stderr.lower()


def test_sandbox_runner_nested_package_import():
    """
    Verifies that nested module paths resolve cleanly inside the sandbox PYTHONPATH.
    """
    runner = SandboxRunner(timeout_seconds=10)
    result = runner.execute_test_suite(
        code_files={"services/auth/helper.py": "def verify(ok): return bool(ok)\n"},
        test_file_name="test_nested.py",
        test_file_content="from helper import verify\ndef test_v(): assert verify(True) is True\n"
    )
    assert result.passed is True
    assert result.total_tests == 1


def test_graph_compilation_and_pr_comment_builder():
    """
    Verifies LangGraph StateGraph compiles cleanly and GitHub PR review markdown renders valid diffs.
    """
    from sentinel.workflow.graph import build_sentinel_graph
    from sentinel.schemas.models import SandboxExecutionResult
    from scripts.pr_audit import build_pr_comment

    graph = build_sentinel_graph()
    assert graph is not None

    mock_state = {
        "final_status": "SUCCESS",
        "iteration_count": 1,
        "original_code_files": {"app.py": "q = f'SELECT * FROM t WHERE x={u}'\n"},
        "current_code_files": {"app.py": "q = 'SELECT * FROM t WHERE x=?'\n"},
        "audit_report": AuditReport(
            summary="SQL injection detected and remediated.",
            risk_score=9.0,
            has_critical_findings=True,
            vulnerabilities=[
                Vulnerability(
                    id="VULN-001",
                    severity="CRITICAL",
                    category="SQL Injection",
                    cwe_id="CWE-89",
                    file_path="app.py",
                    line_number=1,
                    description="Unsanitized input in SQL query",
                    recommendation="Use parameterized query",
                )
            ],
        ),
        "latest_patch": PatchProposal(
            explanation="Converted raw string interpolation to parameterized query.",
            files_modified=["app.py"],
            patched_files={"app.py": "q = 'SELECT * FROM t WHERE x=?'\n"},
        ),
        "verification_execution": SandboxExecutionResult(
            passed=True, total_tests=1, failures=0, errors=0, exit_code=0, execution_time_seconds=0.12
        ),
    }

    md = build_pr_comment(mock_state, ["app.py"])
    assert "SELF-HEALED & VERIFIED" in md
    assert "VULN-001" in md
    assert "SQL Injection" in md
    assert "```diff" in md
