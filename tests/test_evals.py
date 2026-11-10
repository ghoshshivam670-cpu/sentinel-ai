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

    md = build_pr_comment(
        mock_state,
        ["app.py"],
        telemetry_summary={
            "llm_calls": 5,
            "total_tokens": 3200,
            "total_latency_seconds": 4.2,
            "estimated_cost_usd": 0.00045,
        },
    )
    assert "SELF-HEALED & VERIFIED" in md
    assert "VULN-001" in md
    assert "SQL Injection" in md
    assert "```diff" in md
    assert "LLMOps Observability Telemetry" in md
    assert "3200" in md


def test_local_telemetry_callback_handler_tracks_tokens_cost_and_jsonl(tmp_path):
    """
    Verifies LocalTelemetryCallbackHandler captures latency, tokens, errors, USD cost,
    and writes structured JSONL events without external Langfuse credentials.
    """
    from uuid import uuid4
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult
    from sentinel.observability.tracer import LocalTelemetryCallbackHandler

    trace_path = tmp_path / "traces.jsonl"
    handler = LocalTelemetryCallbackHandler(project_id="unit-test", trace_file=trace_path)

    run_id = uuid4()
    handler.on_chat_model_start(
        serialized={"kwargs": {"model": "gemini-3.5-flash-lite"}},
        messages=[[]],
        run_id=run_id,
        invocation_params={"model": "gemini-3.5-flash-lite"},
    )
    ai_msg = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
    )
    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=ai_msg)]]), run_id=run_id)

    err_id = uuid4()
    handler.on_chat_model_start(serialized={}, messages=[[]], run_id=err_id)
    handler.on_llm_error(RuntimeError("transient error"), run_id=err_id)

    summary = handler.get_summary()
    assert summary["llm_calls"] == 1
    assert summary["prompt_tokens"] == 1000
    assert summary["completion_tokens"] == 500
    assert summary["total_tokens"] == 1500
    assert summary["errors"] == 1
    assert summary["estimated_cost_usd"] > 0.0
    assert trace_path.exists()
    lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_get_run_callbacks_graceful_fallback(monkeypatch):
    """
    Verifies get_run_callbacks always provides LocalTelemetryCallbackHandler even without Langfuse keys.
    """
    from sentinel.observability.tracer import get_run_callbacks, LocalTelemetryCallbackHandler
    from sentinel.config import settings

    monkeypatch.setattr(settings, "langfuse_public_key", None)
    monkeypatch.setattr(settings, "langfuse_secret_key", None)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    callbacks, telemetry = get_run_callbacks(project_id="fallback-check")
    assert len(callbacks) == 1
    assert isinstance(callbacks[0], LocalTelemetryCallbackHandler)
    assert callbacks[0] is telemetry


def test_deepeval_geval_pipeline_with_mock_gemini_judge():
    """
    Verifies DeepEval GEval metrics + GeminiJudgeModel run deterministically without OpenAI keys.
    """
    from deepeval.metrics.g_eval import schema as gschema
    from sentinel.schemas.models import TestGenerationResult, SandboxExecutionResult
    from sentinel.evals.judge import GeminiJudgeModel, evaluate_sentinel_run

    class FakeStructuredInvoker:
        def __init__(self, schema_cls):
            self.schema_cls = schema_cls

        def invoke(self, _messages, **_kwargs):
            if self.schema_cls.__name__ == "Steps":
                return gschema.Steps(steps=["Check vulnerabilities", "Check patch correctness"])
            if self.schema_cls.__name__ == "ReasonScore":
                return gschema.ReasonScore(
                    score=9.0,
                    reason="Audit accurately caught SQLi and parameterized patch passed all checks.",
                )
            return None

    class FakeLLM:
        def with_structured_output(self, schema_cls):
            return FakeStructuredInvoker(schema_cls)

        def invoke(self, _messages, **_kwargs):
            return '{"score": 9.0, "reason": "ok"}'

    judge = GeminiJudgeModel(model_name="mock-gemini-judge", llm=FakeLLM())
    assert judge.supports_log_probs() is False
    assert "SentinelJudge" in judge.get_model_name()

    mock_state = {
        "audit_report": AuditReport(
            summary="Found SQL injection vulnerability.",
            risk_score=9.0,
            has_critical_findings=True,
            vulnerabilities=[
                Vulnerability(
                    id="VULN-001",
                    severity="CRITICAL",
                    category="SQL Injection",
                    cwe_id="CWE-89",
                    file_path="app.py",
                    line_number=4,
                    description="Unsafe f-string SQL execution.",
                    recommendation="Use parameterized cursor queries.",
                )
            ],
        ),
        "test_suite": TestGenerationResult(
            test_file_path="test_reproduction.py",
            test_code="def test_sqli(): assert True",
            targeted_vulnerability_ids=["VULN-001"],
            rationale="Proves SQL injection payload cannot bypass auth.",
        ),
        "initial_execution": SandboxExecutionResult(
            passed=False, total_tests=1, failures=1, errors=0, exit_code=1, execution_time_seconds=0.1
        ),
        "latest_patch": PatchProposal(
            explanation="Replaced f-string SQL with parameterized query.",
            files_modified=["app.py"],
            patched_files={"app.py": "cursor.execute('SELECT * FROM users WHERE username = ?', (username,))"},
        ),
        "current_code_files": {"app.py": "cursor.execute('SELECT * FROM users WHERE username = ?', (username,))"},
        "verification_execution": SandboxExecutionResult(
            passed=True, total_tests=1, failures=0, errors=0, exit_code=0, execution_time_seconds=0.1
        ),
    }

    eval_result = evaluate_sentinel_run(
        code_files={"app.py": SAMPLE_VULNERABLE_CODE},
        final_state=mock_state,
        expected_findings_summary="Must detect SQL injection.",
        model=judge,
        threshold=0.7,
    )

    assert eval_result["all_passed"] is True
    assert eval_result["overall_score"] == pytest.approx(0.9, rel=1e-3)
    assert set(eval_result["metrics"].keys()) == {
        "auditor_precision",
        "test_quality",
        "remediation_security",
    }


def test_ensure_stdlib_imports_repairs_missing_hashlib():
    """
    Verifies AST safety guard adds missing stdlib imports so generated pytest suites never NameError.
    """
    from sentinel.agents.test_gen import _ensure_stdlib_imports

    broken = "def test_hash():\n    assert hashlib.md5(b'a').hexdigest() != ''\n"
    repaired = _ensure_stdlib_imports(broken)
    assert "import hashlib" in repaired
    ns = {}
    exec(repaired, ns)
    ns["test_hash"]()


