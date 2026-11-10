import json
import os
from typing import Any, Dict, List, Optional, Type

# Opt out of external Confident/DeepEval telemetry pings in local & CI runs
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

from sentinel.config import get_llm, settings
from sentinel.observability.tracer import get_run_callbacks
from sentinel.workflow.graph import build_sentinel_graph


def _extract_text_content(response: Any) -> str:
    """Normalizes string, AIMessage, or structured Gemini content lists into a plain string."""
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


class GeminiJudgeModel(DeepEvalBaseLLM):
    """
    Custom DeepEval LLM-as-a-Judge adapter backed by SentinelAI's multi-provider `get_llm()` factory.
    Enables zero-OpenAI evaluation workflows using the configured Gemini (or Anthropic/OpenAI) model.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        llm: Optional[Any] = None,
        callbacks: Optional[List[Any]] = None,
    ):
        self._custom_llm = llm
        self._callbacks = callbacks or []
        resolved_name = model_name or settings.model_name or "gemini-3.5-flash-lite"
        super().__init__(model=resolved_name)

    def load_model(self) -> Any:
        if self._custom_llm is not None:
            return self._custom_llm
        return get_llm(temperature=0.0)

    def _invoke_kwargs(self) -> Dict[str, Any]:
        return {"config": {"callbacks": self._callbacks}} if self._callbacks else {}

    def generate(self, prompt: str, schema: Optional[Type[BaseModel]] = None) -> Any:
        kwargs = self._invoke_kwargs()
        if schema is not None:
            if hasattr(self.model, "with_structured_output"):
                try:
                    structured = self.model.with_structured_output(schema)
                    res = structured.invoke([HumanMessage(content=prompt)], **kwargs)
                    if isinstance(res, schema):
                        return res
                except Exception:
                    pass

            json_prompt = (
                f"{prompt}\n\nRespond ONLY with a valid JSON object matching this schema:\n"
                f"{json.dumps(schema.model_json_schema())}"
            )
            res = self.model.invoke([HumanMessage(content=json_prompt)], **kwargs)
            return _extract_text_content(res)

        res = self.model.invoke([HumanMessage(content=prompt)], **kwargs)
        return _extract_text_content(res)

    async def a_generate(self, prompt: str, schema: Optional[Type[BaseModel]] = None) -> Any:
        kwargs = self._invoke_kwargs()
        if schema is not None:
            if hasattr(self.model, "with_structured_output"):
                try:
                    structured = self.model.with_structured_output(schema)
                    res = await structured.ainvoke([HumanMessage(content=prompt)], **kwargs)
                    if isinstance(res, schema):
                        return res
                except Exception:
                    pass

            json_prompt = (
                f"{prompt}\n\nRespond ONLY with a valid JSON object matching this schema:\n"
                f"{json.dumps(schema.model_json_schema())}"
            )
            res = await self.model.ainvoke([HumanMessage(content=json_prompt)], **kwargs)
            return _extract_text_content(res)

        res = await self.model.ainvoke([HumanMessage(content=prompt)], **kwargs)
        return _extract_text_content(res)

    def get_model_name(self) -> str:
        return f"SentinelJudge({self.name})"

    def supports_log_probs(self) -> bool:
        return False

    def supports_structured_outputs(self) -> bool:
        return True

    def supports_json_mode(self) -> bool:
        return True


def create_auditor_precision_metric(
    model: Optional[DeepEvalBaseLLM] = None,
    threshold: float = 0.7,
) -> GEval:
    """Evaluates whether the Auditor identified real vulnerabilities accurately without false positives."""
    judge = model or GeminiJudgeModel()
    return GEval(
        name="Auditor Precision & Recall",
        criteria=(
            "Evaluate whether the security audit report accurately identifies real security "
            "or logic vulnerabilities in the input code (including relevant OWASP/CWE categories "
            "and concrete mitigations), and gives zero vulnerabilities when the input code is "
            "already safe and properly validated (zero false positives / hallucinations). "
            "Compare Actual Output against Expected Output carefully."
        ),
        evaluation_steps=[
            "Inspect the target source code in Input and the ground-truth expectation in Expected Output.",
            "Check whether Actual Output identifies the expected critical flaws accurately or correctly reports clean code when Expected Output indicates safe code.",
            "Penalize missed critical vulnerabilities or fabricated/hallucinated issues on safe code.",
            "Verify that recommendations and severity ratings are technically accurate and actionable.",
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=threshold,
        async_mode=False,
    )


def create_test_quality_metric(
    model: Optional[DeepEvalBaseLLM] = None,
    threshold: float = 0.7,
) -> GEval:
    """Evaluates Red-Green TDD quality of generated pytest reproduction tests."""
    judge = model or GeminiJudgeModel()
    return GEval(
        name="Reproduction Test Quality",
        criteria=(
            "Evaluate whether the generated pytest code uses strict Red-Green TDD assertions "
            "that fail on the vulnerable code and pass once patched, avoids third-party uninstalled "
            "dependencies beyond Python stdlib + pytest, and targets the actual vulnerability without "
            "asserting buggy behavior."
        ),
        evaluation_steps=[
            "Review the vulnerable source code and findings provided in Input.",
            "Inspect the generated pytest test suite in Actual Output for syntactic validity and complete imports (no missing imports causing NameError/ImportError).",
            "Verify Red-Green TDD correctness: tests MUST assert EXPECTED SECURE behavior (e.g., asserting an injection attempt returns None or raises ValueError) so they intentionally FAIL on the vulnerable code in Context and PASS after patching.",
            "Check that only Python standard library modules and pytest are imported, and never assert the buggy behavior.",
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.CONTEXT,
        ],
        model=judge,
        threshold=threshold,
        async_mode=False,
    )


def create_remediation_security_metric(
    model: Optional[DeepEvalBaseLLM] = None,
    threshold: float = 0.7,
) -> GEval:
    """Evaluates whether the healed code eliminates vulnerabilities without regressions."""
    judge = model or GeminiJudgeModel()
    return GEval(
        name="Remediation Security & Correctness",
        criteria=(
            "Evaluate whether the autonomous code patch completely eliminates all reported security "
            "and logic vulnerabilities (e.g., parameterized SQL queries instead of f-strings, PBKDF2/HMAC "
            "instead of MD5, ast.literal_eval or safe parsing instead of eval(), strict input validation) "
            "while preserving the original public API signatures and functionality."
        ),
        evaluation_steps=[
            "Compare the original vulnerable code in Input with the patched code and explanation in Actual Output.",
            "Verify every reported flaw from Context is securely fixed with no remaining injection, weak crypto, or validation bypass.",
            "Ensure original class names, method signatures, and return types remain backward-compatible.",
            "Confirm verification sandbox execution results in Context indicate tests pass.",
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.CONTEXT,
        ],
        model=judge,
        threshold=threshold,
        async_mode=False,
    )


def _format_code_bundle(code_files: Dict[str, str]) -> str:
    return "\n".join(f"--- FILE: {path} ---\n{content}" for path, content in code_files.items())


def evaluate_sentinel_run(
    code_files: Dict[str, str],
    final_state: Dict[str, Any],
    expected_findings_summary: str = "",
    model: Optional[DeepEvalBaseLLM] = None,
    threshold: float = 0.7,
) -> Dict[str, Any]:
    """
    Scores a completed SentinelAI workflow run using DeepEval GEval LLM-as-a-Judge metrics.
    Returns per-metric scores, pass flags, judge reasoning, and aggregate pass status.
    """
    judge = model or GeminiJudgeModel()
    raw_source = _format_code_bundle(code_files)

    audit_report = final_state.get("audit_report")
    test_suite = final_state.get("test_suite")
    patch = final_state.get("latest_patch")
    verif = final_state.get("verification_execution")
    healed_files = final_state.get("current_code_files") or code_files

    metrics_results: Dict[str, Dict[str, Any]] = {}

    # 1. Auditor Precision & Recall
    audit_payload = (
        audit_report.model_dump_json(indent=2)
        if audit_report is not None
        else "No AuditReport generated."
    )
    expected_text = expected_findings_summary.strip() or (
        "Identify genuine security/logic vulnerabilities accurately with CWE categories and mitigations, "
        "or report 0 vulnerabilities if code is clean."
    )
    auditor_metric = create_auditor_precision_metric(model=judge, threshold=threshold)
    auditor_tc = LLMTestCase(
        input=raw_source,
        actual_output=audit_payload,
        expected_output=expected_text,
    )
    auditor_score = float(auditor_metric.measure(auditor_tc, _show_indicator=False))
    metrics_results["auditor_precision"] = {
        "name": auditor_metric.name,
        "score": round(auditor_score, 3),
        "threshold": threshold,
        "passed": bool(auditor_metric.is_successful()),
        "reason": auditor_metric.reason or "",
    }

    # 2. Reproduction Test Quality (if a test suite was generated)
    if test_suite is not None and getattr(test_suite, "test_code", "").strip():
        test_metric = create_test_quality_metric(model=judge, threshold=threshold)
        init_exec = final_state.get("initial_execution")
        exec_note = (
            f"Initial sandbox run: passed={init_exec.passed}, failures={init_exec.failures}, errors={init_exec.errors}"
            if init_exec
            else "Initial sandbox result not available."
        )
        test_tc = LLMTestCase(
            input=f"Source Code:\n{raw_source}\n\nAudit Findings:\n{audit_payload}",
            actual_output=f"# Rationale: {test_suite.rationale}\n{test_suite.test_code}",
            context=[exec_note, f"Targeted IDs: {test_suite.targeted_vulnerability_ids}"],
        )
        test_score = float(test_metric.measure(test_tc, _show_indicator=False))
        metrics_results["test_quality"] = {
            "name": test_metric.name,
            "score": round(test_score, 3),
            "threshold": threshold,
            "passed": bool(test_metric.is_successful()),
            "reason": test_metric.reason or "",
        }

    # 3. Remediation Security & Correctness (if a patch was produced)
    if patch is not None:
        remediation_metric = create_remediation_security_metric(model=judge, threshold=threshold)
        patched_source = _format_code_bundle(healed_files)
        verif_note = (
            f"Verification sandbox: passed={verif.passed}, total_tests={verif.total_tests}, failures={verif.failures}"
            if verif
            else "Verification sandbox not run."
        )
        rem_tc = LLMTestCase(
            input=raw_source,
            actual_output=f"Patch Explanation: {patch.explanation}\n\nPatched Code:\n{patched_source}",
            context=[audit_payload, verif_note],
        )
        rem_score = float(remediation_metric.measure(rem_tc, _show_indicator=False))
        metrics_results["remediation_security"] = {
            "name": remediation_metric.name,
            "score": round(rem_score, 3),
            "threshold": threshold,
            "passed": bool(remediation_metric.is_successful()),
            "reason": remediation_metric.reason or "",
        }

    scores = [m["score"] for m in metrics_results.values()]
    overall_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    all_passed = all(m["passed"] for m in metrics_results.values()) if metrics_results else False

    return {
        "judge_model": judge.get_model_name(),
        "overall_score": overall_score,
        "all_passed": all_passed,
        "metrics": metrics_results,
    }


def evaluate_graph_case(
    name: str,
    code_files: Dict[str, str],
    expected_findings_summary: str,
    should_be_vulnerable: bool = True,
    model: Optional[DeepEvalBaseLLM] = None,
    max_iterations: int = 2,
    threshold: float = 0.7,
) -> Dict[str, Any]:
    """
    Runs the full SentinelAI StateGraph end-to-end on a benchmark case, computes deterministic
    pipeline assertions, attaches LLMOps telemetry, and runs DeepEval GEval LLM-as-a-Judge scoring.
    """
    graph = build_sentinel_graph()
    initial_state: Dict[str, Any] = {
        "project_id": f"eval-{name}",
        "original_code_files": code_files,
        "current_code_files": dict(code_files),
        "plan": None,
        "audit_report": None,
        "test_suite": None,
        "initial_execution": None,
        "latest_patch": None,
        "verification_execution": None,
        "iteration_count": 0,
        "max_iterations": max_iterations,
        "critic_verdict": None,
        "final_status": "PENDING",
        "final_summary_report": None,
        "activity_log": [],
    }

    callbacks, telemetry = get_run_callbacks(project_id=f"eval-{name}")
    terminal_state = dict(initial_state)

    for event in graph.stream(initial_state, config={"callbacks": callbacks}):
        for _, state_update in event.items():
            for k, v in state_update.items():
                if k == "activity_log":
                    terminal_state["activity_log"].extend(v)
                else:
                    terminal_state[k] = v

    audit = terminal_state.get("audit_report")
    init_exec = terminal_state.get("initial_execution")
    verif_exec = terminal_state.get("verification_execution")
    vuln_count = len(audit.vulnerabilities) if audit else 0

    if should_be_vulnerable:
        deterministic_ok = (
            vuln_count > 0
            and init_exec is not None
            and not init_exec.passed
            and terminal_state.get("final_status") == "SUCCESS"
            and verif_exec is not None
            and verif_exec.passed
        )
    else:
        deterministic_ok = vuln_count == 0

    judge = model or GeminiJudgeModel()
    judge_eval = evaluate_sentinel_run(
        code_files=code_files,
        final_state=terminal_state,
        expected_findings_summary=expected_findings_summary,
        model=judge,
        threshold=threshold,
    )

    return {
        "case": name,
        "should_be_vulnerable": should_be_vulnerable,
        "vulnerabilities_found": vuln_count,
        "final_status": terminal_state.get("final_status"),
        "iterations": terminal_state.get("iteration_count", 0),
        "deterministic_passed": deterministic_ok,
        "judge_evaluation": judge_eval,
        "overall_passed": bool(deterministic_ok and judge_eval["all_passed"]),
        "telemetry": telemetry.get_summary(),
    }
