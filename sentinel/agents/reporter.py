import difflib
from sentinel.schemas.state import AgentState

def generate_unified_diff(original: str, patched: str, filename: str) -> str:
    """
    Computes a clean git-compatible unified diff.
    """
    orig_lines = original.splitlines(keepends=True)
    patch_lines = patched.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        patch_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}"
    )
    return "".join(diff)

def reporter_node(state: AgentState) -> dict:
    """
    Generates the final comprehensive SentinelAI Audit & Self-Healing Report in GitHub Flavored Markdown.
    """
    project_id = state.get("project_id", "unnamed-project")
    audit = state.get("audit_report")
    status = state.get("final_status", "COMPLETED")
    iters = state.get("iteration_count", 0)
    verif = state.get("verification_execution")
    patch = state.get("latest_patch")

    lines = [
        f"# SentinelAI Autonomous Audit & Remediator Report",
        f"**Target Project:** `{project_id}`  ",
        f"**Final Status:** `{status}`  ",
        f"**Self-Healing Iterations Completed:** `{iters}`  ",
        "",
        "---",
        "## 1. Executive Security & Reliability Summary",
    ]

    if audit:
        lines.append(f"- **Overall Risk Score:** `{audit.risk_score} / 10.0`")
        lines.append(f"- **Total Identified Findings:** `{len(audit.vulnerabilities)}`")
        lines.append(f"- **Summary:** {audit.summary}")
        lines.append("")
        lines.append("### Identified Vulnerabilities")
        if audit.vulnerabilities:
            for v in audit.vulnerabilities:
                cwe = f" ({v.cwe_id})" if v.cwe_id else ""
                lines.append(f"#### [{v.id}] {v.severity}: {v.category}{cwe}")
                lines.append(f"- **Location:** `{v.file_path}:{v.line_number or 'N/A'}`")
                lines.append(f"- **Description:** {v.description}")
                lines.append(f"- **Recommendation:** {v.recommendation}")
                lines.append("")
        else:
            lines.append("✅ *No critical vulnerabilities or logic flaws detected.*")
    else:
        lines.append("No audit findings recorded.")

    lines.append("---")
    lines.append("## 2. Automated Reproduction Test Suite")
    if state.get("test_suite"):
        lines.append(f"The Test Engineer Agent authored a targeted test harness (`{state['test_suite'].test_file_path}`):")
        lines.append(f"> **Rationale:** {state['test_suite'].rationale}")
        lines.append("")
        lines.append("```python")
        lines.append(state["test_suite"].test_code)
        lines.append("```")
    else:
        lines.append("No reproduction test suite was required.")

    lines.append("")
    lines.append("---")
    lines.append("## 3. Autonomous Patch & Verification Diff")
    
    if patch and state.get("original_code_files"):
        lines.append(f"**Patch Explanation:** {patch.explanation}")
        lines.append("")
        for filename in patch.files_modified:
            orig = state["original_code_files"].get(filename, "")
            patched = state["current_code_files"].get(filename, "")
            diff_text = generate_unified_diff(orig, patched, filename)
            lines.append(f"### Diff for `{filename}`")
            lines.append("```diff")
            lines.append(diff_text if diff_text.strip() else "(No textual changes)")
            lines.append("```")
    else:
        lines.append("No patch generated.")

    lines.append("")
    lines.append("---")
    lines.append("## 4. Final Sandbox Execution Results")
    if verif:
        status_emoji = "✅ PASSED" if verif.passed else "❌ FAILED"
        lines.append(f"- **Status:** {status_emoji}")
        lines.append(f"- **Tests Evaluated:** `{verif.total_tests}`")
        lines.append(f"- **Failures:** `{verif.failures}` | **Errors:** `{verif.errors}`")
        lines.append(f"- **Execution Latency:** `{verif.execution_time_seconds}s`")
        lines.append("")
        lines.append("<details><summary>Click to view sandbox pytest output</summary>")
        lines.append("")
        lines.append("```text")
        lines.append(verif.stdout)
        if verif.stderr:
            lines.append(verif.stderr)
        lines.append("```")
        lines.append("</details>")
    
    report_text = "\n".join(lines)
    log_msg = "[Reporter] Final executive security & patch report generated."

    return {
        "final_summary_report": report_text,
        "activity_log": [log_msg]
    }
