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
