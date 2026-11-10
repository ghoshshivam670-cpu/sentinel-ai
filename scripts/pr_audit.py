import sys
import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional
import typer

# Ensure project root is importable
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from sentinel.workflow.graph import build_sentinel_graph
from sentinel.observability.tracer import get_run_callbacks

app = typer.Typer(help="SentinelAI GitHub PR Autonomous Audit Runner")


def build_pr_comment(
    final_state: dict,
    target_files: List[str],
    telemetry_summary: Optional[Dict[str, Any]] = None,
) -> str:
    audit = final_state.get("audit_report")
    status = final_state.get("final_status", "COMPLETED")
    iters = final_state.get("iteration_count", 0)
    verif = final_state.get("verification_execution")
    patch = final_state.get("latest_patch")

    if status == "SUCCESS":
        status_badge = "✅ **SELF-HEALED & VERIFIED**"
    elif status in ("CLEAN", "PENDING") and (not audit or not audit.vulnerabilities):
        status_badge = "✅ **CLEAN (No Critical Findings)**"
    else:
        status_badge = f"⚠️ **{status}**"

    lines = [
        "## 🛡️ SentinelAI Autonomous PR Security & Logic Review",
        "",
        f"**Status:** {status_badge} | **Self-Healing Iterations:** `{iters}` | **Files Audited:** `{len(target_files)}`",
        "",
    ]

    if audit:
        lines.append(f"**Overall Risk Score:** `{audit.risk_score} / 10.0`")
        lines.append(f"> {audit.summary}")
        lines.append("")

        if audit.vulnerabilities:
            lines.append("### 🚨 Identified Findings")
            lines.append("| ID | Severity | Category | Location | Description |")
            lines.append("|:---|:---|:---|:---|:---|")
            for v in audit.vulnerabilities:
                loc = f"`{v.file_path}:{v.line_number or 'N/A'}`"
                desc = v.description.replace("\n", " ").replace("|", "\\|")
                lines.append(f"| `{v.id}` | **{v.severity}** | {v.category} | {loc} | {desc} |")
            lines.append("")

    if patch and final_state.get("original_code_files"):
        lines.append("### 🛠️ Proposed Autonomous Remediation Patch")
        lines.append(f"**Fix Summary:** {patch.explanation}")
        lines.append("")
        for filename in patch.files_modified:
            orig = final_state["original_code_files"].get(filename, "")
            patched = final_state["current_code_files"].get(filename, "")
            diff = "".join(
                difflib.unified_diff(
                    orig.splitlines(keepends=True),
                    patched.splitlines(keepends=True),
                    fromfile=f"a/{filename}",
                    tofile=f"b/{filename}",
                )
            )
            if diff.strip():
                lines.append(f"<details><summary>View Patch Diff for <code>{filename}</code></summary>\n")
                lines.append("```diff")
                lines.append(diff)
                lines.append("```")
                lines.append("</details>\n")

    if verif:
        verif_emoji = "✅ PASSED" if verif.passed else "❌ FAILED"
        lines.append("### 🧪 Isolated Sandbox Verification")
        lines.append(
            f"- **Result:** {verif_emoji} (`{verif.total_tests}` tests, `{verif.failures}` failures, `{verif.execution_time_seconds}s`)"
        )
        lines.append("")

    if telemetry_summary:
        lines.append("### 📊 LLMOps Observability Telemetry")
        lines.append(
            f"- **LLM Calls:** `{telemetry_summary.get('llm_calls', 0)}` | "
            f"**Total Tokens:** `{telemetry_summary.get('total_tokens', 0)}` | "
            f"**LLM Latency:** `{telemetry_summary.get('total_latency_seconds', 0.0)}s` | "
            f"**Est. Cost:** `${telemetry_summary.get('estimated_cost_usd', 0.0):.6f}`"
        )
        lines.append("")

    lines.append("---")
    lines.append("*Automated review powered by [SentinelAI](https://github.com/ghoshshivam670-cpu/sentinel-ai) (LangGraph + Sandboxed Execution)*")
    return "\n".join(lines)


@app.command()
def run(
    files: List[str] = typer.Argument(..., help="List of Python file paths changed in the PR"),
    output: Path = typer.Option(Path("pr_comment.md"), "--output", "-o", help="Markdown output path"),
    max_iterations: int = typer.Option(3, "--max-iterations", "-m", help="Max self-healing iterations"),
    fail_on_unhealed: bool = typer.Option(False, "--fail-on-unhealed", help="Exit non-zero if critical bugs remain unhealed"),
):
    code_files = {}
    for file_str in files:
        p = Path(file_str)
        if p.exists() and p.is_file() and p.suffix == ".py":
            # Use relative path cleanly
            code_files[p.as_posix()] = p.read_text(encoding="utf-8")

    if not code_files:
        output.write_text(
            "## 🛡️ SentinelAI Autonomous PR Review\n\n✅ No Python files modified in this PR. Audit skipped.",
            encoding="utf-8",
        )
        typer.echo("No Python files to audit. Wrote clean skip comment.")
        raise typer.Exit(code=0)

    graph = build_sentinel_graph()
    initial_state = {
        "project_id": "github-pr-audit",
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

    callbacks, telemetry = get_run_callbacks(project_id="github-pr-audit")
    config = {"callbacks": callbacks} if callbacks else {}
    final_state = initial_state

    for event in graph.stream(initial_state, config=config):
        for node_name, state_update in event.items():
            # Merge updates into final_state snapshot
            for k, v in state_update.items():
                if k == "activity_log":
                    final_state["activity_log"].extend(v)
                else:
                    final_state[k] = v
            if "activity_log" in state_update and state_update["activity_log"]:
                typer.echo(f"[{node_name.upper()}] {state_update['activity_log'][-1]}")

    comment_md = build_pr_comment(
        final_state,
        list(code_files.keys()),
        telemetry_summary=telemetry.get_summary(),
    )
    output.write_text(comment_md, encoding="utf-8")
    typer.echo(f"PR audit comment written to {output}")

    if fail_on_unhealed:
        audit = final_state.get("audit_report")
        status = final_state.get("final_status")
        if audit and audit.has_critical_findings and status != "SUCCESS":
            typer.echo("Failing check: critical findings could not be automatically healed.", err=True)
            raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
