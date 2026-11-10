from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from deepeval.models.base_model import DeepEvalBaseLLM

from sentinel.evals.judge import GeminiJudgeModel, evaluate_graph_case


CLEAN_DISCOUNT_CODE = """def calculate_discount(price: float, discount_percent: float) -> float:
    \"\"\"Applies a validated percentage discount to a positive price.\"\"\"
    if price < 0:
        raise ValueError("Price must be non-negative")
    if not (0.0 <= discount_percent <= 100.0):
        raise ValueError("Discount must be between 0 and 100")
    return round(price * (1.0 - discount_percent / 100.0), 2)
"""


def get_default_benchmark_cases(root_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    base = root_dir or Path(__file__).resolve().parent.parent.parent
    cases: List[Dict[str, Any]] = []

    auth_path = base / "tests" / "sample_vulnerable_code" / "auth_service.py"
    if auth_path.exists():
        cases.append(
            {
                "name": "auth_service",
                "code_files": {"auth_service.py": auth_path.read_text(encoding="utf-8")},
                "should_be_vulnerable": True,
                "expected_findings_summary": (
                    "Must identify CWE-89 SQL injection via f-string query interpolation and "
                    "weak MD5 password hashing (CWE-327/CWE-328/CWE-312) + timing comparison risk; "
                    "must remediate with parameterized SQL queries and PBKDF2/HMAC without breaking authenticate_user API."
                ),
            }
        )

    payment_path = base / "tests" / "sample_vulnerable_code" / "payment_processor.py"
    if payment_path.exists():
        cases.append(
            {
                "name": "payment_processor",
                "code_files": {"payment_processor.py": payment_path.read_text(encoding="utf-8")},
                "should_be_vulnerable": True,
                "expected_findings_summary": (
                    "Must identify unsafe eval() code injection (CWE-95/CWE-94) in apply_promo_discount and "
                    "missing negative amount / insufficient balance validation in process_charge."
                ),
            }
        )

    cases.append(
        {
            "name": "clean_discount",
            "code_files": {"clean_discount.py": CLEAN_DISCOUNT_CODE},
            "should_be_vulnerable": False,
            "expected_findings_summary": (
                "Code is already clean and properly validates price >= 0 and 0 <= discount_percent <= 100. "
                "Auditor MUST return an empty vulnerabilities list (0 findings, no false positives)."
            ),
        }
    )

    return cases


def build_scorecard_markdown(results: List[Dict[str, Any]], threshold: float) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_cases = len(results)
    passed_cases = sum(1 for r in results if r["overall_passed"])
    pass_rate = round((passed_cases / total_cases) * 100, 1) if total_cases else 0.0

    total_calls = sum(r["telemetry"]["llm_calls"] for r in results)
    total_tokens = sum(r["telemetry"]["total_tokens"] for r in results)
    total_cost = round(sum(r["telemetry"]["estimated_cost_usd"] for r in results), 6)

    lines = [
        "# 📊 SentinelAI LLMOps & DeepEval Scorecard",
        "",
        f"**Generated:** `{timestamp}` | **Judge Threshold:** `{threshold}` | **Benchmark Pass Rate:** `{passed_cases}/{total_cases} ({pass_rate}%)`  ",
        f"**Total Telemetry Across Benchmark:** `{total_calls}` LLM calls | `{total_tokens}` tokens | Est. Cost `${total_cost:.6f}`",
        "",
        "| Benchmark Case | Type | Findings | Deterministic Check | GEval Overall | Status | Latency | Tokens |",
        "|:---|:---|---:|:---:|---:|:---:|---:|---:|",
    ]

    for r in results:
        case_type = "Vulnerable" if r["should_be_vulnerable"] else "Clean (False-Positive Guard)"
        det = "PASS" if r["deterministic_passed"] else "FAIL"
        g_score = r["judge_evaluation"]["overall_score"]
        status = "✅ PASS" if r["overall_passed"] else "❌ FAIL"
        lat = f"{r['telemetry']['total_latency_seconds']}s"
        toks = r["telemetry"]["total_tokens"]
        lines.append(
            f"| `{r['case']}` | {case_type} | {r['vulnerabilities_found']} | {det} | `{g_score:.3f}` | {status} | {lat} | {toks} |"
        )

    lines.append("")
    lines.append("## 🔍 Per-Metric DeepEval LLM-as-a-Judge Breakdown")
    lines.append("")

    for r in results:
        lines.append(f"### Case: `{r['case']}` (`final_status={r['final_status']}`, iterations=`{r['iterations']}`)")
        lines.append(f"- **Judge Model:** `{r['judge_evaluation']['judge_model']}`")
        for _, metric_data in r["judge_evaluation"]["metrics"].items():
            badge = "✅" if metric_data["passed"] else "❌"
            lines.append(
                f"- {badge} **{metric_data['name']}**: `{metric_data['score']:.3f}` (threshold `{metric_data['threshold']}`) — {metric_data['reason']}"
            )
        lines.append("")

    lines.append("---")
    lines.append("*Evaluated autonomously with DeepEval `GEval` + SentinelAI Multi-Agent Pipeline*")
    return "\n".join(lines)


def run_benchmark_suite(
    case_filter: Optional[str] = None,
    threshold: float = 0.7,
    max_iterations: int = 2,
    output_path: Optional[Path] = Path("EVAL_SCORECARD.md"),
    model: Optional[DeepEvalBaseLLM] = None,
) -> Dict[str, Any]:
    cases = get_default_benchmark_cases()
    if case_filter:
        cases = [c for c in cases if c["name"] == case_filter]
        if not cases:
            raise ValueError(f"Unknown benchmark case '{case_filter}'.")

    judge = model or GeminiJudgeModel()
    results: List[Dict[str, Any]] = []

    for case in cases:
        res = evaluate_graph_case(
            name=case["name"],
            code_files=case["code_files"],
            expected_findings_summary=case["expected_findings_summary"],
            should_be_vulnerable=case["should_be_vulnerable"],
            model=judge,
            max_iterations=max_iterations,
            threshold=threshold,
        )
        results.append(res)

    markdown = build_scorecard_markdown(results, threshold=threshold)
    if output_path is not None:
        output_path.write_text(markdown, encoding="utf-8")

    return {
        "results": results,
        "markdown": markdown,
        "all_passed": all(r["overall_passed"] for r in results) if results else False,
        "output_path": str(output_path) if output_path else None,
    }
