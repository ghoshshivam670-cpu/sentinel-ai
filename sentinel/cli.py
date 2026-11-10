import os
import sys

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax

from sentinel.workflow.graph import build_sentinel_graph
from sentinel.observability.tracer import get_run_callbacks

app = typer.Typer(help="SentinelAI: Autonomous Multi-Agent Code Audit & Self-Healing Engine", no_args_is_help=True)
console = Console()

@app.command(name="audit")
def audit(
    target_path: str = typer.Argument(..., help="Path to code file or directory to audit"),
    max_iterations: int = typer.Option(3, "--max-iterations", "-m", help="Maximum self-healing retry iterations"),
    eval_judge: bool = typer.Option(False, "--eval", "-e", help="Run DeepEval GEval LLM-as-a-Judge scoring after audit"),
):
    """
    Runs the full SentinelAI autonomous audit, reproduction, and self-healing pipeline on a target file.
    """
    target = Path(target_path)
    if not target.exists():
        console.print(f"[bold red]Error:[/bold red] Target path '{target_path}' does not exist.")
        raise typer.Exit(code=1)

    # Read files
    code_files = {}
    if target.is_file():
        code_files[target.name] = target.read_text(encoding="utf-8")
    else:
        for py_file in target.glob("**/*.py"):
            code_files[py_file.name] = py_file.read_text(encoding="utf-8")

    if not code_files:
        console.print("[bold red]Error:[/bold red] No Python files found to inspect.")
        raise typer.Exit(code=1)

    console.print(Panel.fit(
        "[bold cyan]SentinelAI Autonomous Engine[/bold cyan]\n"
        f"[dim]Inspecting target:[/dim] {target_path}\n"
        f"[dim]Total files ingested:[/dim] {len(code_files)}",
        border_style="cyan"
    ))

    # Initialize Graph & Initial State
    graph = build_sentinel_graph()
    initial_state = {
        "project_id": target.name,
        "original_code_files": code_files,
        "current_code_files": code_files,
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
        "activity_log": []
    }

    callbacks, telemetry = get_run_callbacks(project_id=target.name)
    if len(callbacks) > 1:
        console.print("[green][OK][/green] Langfuse observability + local telemetry connected.")
    else:
        console.print("[cyan][INFO][/cyan] Local LLMOps telemetry active (logs/traces.jsonl). Set LANGFUSE keys in .env to stream to Langfuse Cloud.")

    config = {"callbacks": callbacks}

    # Stream agent state execution
    console.print("\n[yellow]Executing multi-agent state graph...[/yellow]")
    terminal_state = dict(initial_state)
    for event in graph.stream(initial_state, config=config):
        for node_name, state_update in event.items():
            for k, v in state_update.items():
                if k == "activity_log":
                    terminal_state["activity_log"].extend(v)
                else:
                    terminal_state[k] = v
            if "activity_log" in state_update and state_update["activity_log"]:
                latest_msg = state_update["activity_log"][-1]
                console.print(f"[bold cyan]▶ {node_name.upper()}:[/bold cyan] {latest_msg}")

    # Display Executive Summary Table
    audit_report = terminal_state.get("audit_report")
    if audit_report and audit_report.vulnerabilities:
        table = Table(title="🚨 Identified Security & Logic Vulnerabilities", border_style="red")
        table.add_column("ID", style="bold cyan")
        table.add_column("Severity", style="bold")
        table.add_column("Category", style="magenta")
        table.add_column("Location", style="yellow")
        table.add_column("Description")

        for v in audit_report.vulnerabilities:
            sev_color = "red" if v.severity in ["HIGH", "CRITICAL"] else "yellow"
            table.add_row(
                v.id,
                f"[{sev_color}]{v.severity}[/{sev_color}]",
                v.category,
                f"{v.file_path}:{v.line_number or 'N/A'}",
                v.description[:80] + "..." if len(v.description) > 80 else v.description
            )
        console.print(table)

    # Display Patch Diff
    patch = terminal_state.get("latest_patch")
    if patch:
        console.print(Panel(f"[bold green]Autonomous Patch Applied:[/bold green] {patch.explanation}", border_style="green"))

    # Display LLMOps Observability Telemetry
    t_summary = telemetry.get_summary()
    tel_table = Table(title="📊 LLMOps Observability Telemetry", border_style="cyan")
    tel_table.add_column("LLM Calls", justify="right", style="bold")
    tel_table.add_column("Prompt Tokens", justify="right")
    tel_table.add_column("Completion Tokens", justify="right")
    tel_table.add_column("Total Tokens", justify="right", style="cyan")
    tel_table.add_column("LLM Latency", justify="right")
    tel_table.add_column("Est. Cost (USD)", justify="right", style="green")
    tel_table.add_row(
        str(t_summary["llm_calls"]),
        str(t_summary["prompt_tokens"]),
        str(t_summary["completion_tokens"]),
        str(t_summary["total_tokens"]),
        f"{t_summary['total_latency_seconds']}s",
        f"${t_summary['estimated_cost_usd']:.6f}"
    )
    console.print(tel_table)

    # Optional DeepEval LLM-as-a-Judge Scoring
    if eval_judge:
        from sentinel.evals.judge import evaluate_sentinel_run

        console.print("\n[yellow]Running DeepEval GEval LLM-as-a-Judge evaluation...[/yellow]")
        eval_res = evaluate_sentinel_run(code_files=code_files, final_state=terminal_state)
        eval_table = Table(
            title=f"🧪 DeepEval GEval Quality Scorecard (Overall: {eval_res['overall_score']:.3f})",
            border_style="magenta",
        )
        eval_table.add_column("Metric", style="bold")
        eval_table.add_column("Score", justify="right")
        eval_table.add_column("Threshold", justify="right")
        eval_table.add_column("Status", justify="center")
        eval_table.add_column("Judge Reason")
        for _, m in eval_res["metrics"].items():
            status_badge = "[green]PASS[/green]" if m["passed"] else "[red]FAIL[/red]"
            eval_table.add_row(
                m["name"],
                f"{m['score']:.3f}",
                f"{m['threshold']:.2f}",
                status_badge,
                m["reason"][:100] + "..." if len(m["reason"]) > 100 else m["reason"],
            )
        console.print(eval_table)

    # Display Final Report
    report_text = terminal_state.get("final_summary_report")
    if report_text:
        report_output_path = Path("SENTINEL_AUDIT_REPORT.md")
        report_output_path.write_text(report_text, encoding="utf-8")
        console.print(f"\n[bold green][OK] Report generated successfully:[/bold green] {report_output_path.resolve()}")

@app.command(name="evals")
def evals(
    case: Optional[str] = typer.Option(None, "--case", "-c", help="Run a specific benchmark case (auth_service, payment_processor, clean_discount)"),
    threshold: float = typer.Option(0.7, "--threshold", "-t", help="Minimum GEval score threshold (0.0 - 1.0)"),
    max_iterations: int = typer.Option(2, "--max-iterations", "-m", help="Maximum self-healing iterations per case"),
    output: Path = typer.Option(Path("EVAL_SCORECARD.md"), "--output", "-o", help="Markdown scorecard output path"),
):
    """
    Executes the full DeepEval LLM-as-a-Judge + deterministic benchmark suite across vulnerable & clean targets.
    """
    from sentinel.evals.benchmark import run_benchmark_suite

    console.print("[bold cyan]Running SentinelAI DeepEval Benchmark Suite...[/bold cyan]")
    suite = run_benchmark_suite(
        case_filter=case,
        threshold=threshold,
        max_iterations=max_iterations,
        output_path=output,
    )

    table = Table(title="DeepEval Benchmark Scorecard", border_style="cyan")
    table.add_column("Case", style="bold")
    table.add_column("Type")
    table.add_column("Findings", justify="right")
    table.add_column("Det. Check", justify="center")
    table.add_column("GEval Score", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Tokens", justify="right")

    for r in suite["results"]:
        case_type = "Vulnerable" if r["should_be_vulnerable"] else "Clean Guard"
        det = "[green]PASS[/green]" if r["deterministic_passed"] else "[red]FAIL[/red]"
        score = f"{r['judge_evaluation']['overall_score']:.3f}"
        status = "[bold green]PASS[/bold green]" if r["overall_passed"] else "[bold red]FAIL[/bold red]"
        table.add_row(
            r["case"],
            case_type,
            str(r["vulnerabilities_found"]),
            det,
            score,
            status,
            str(r["telemetry"]["total_tokens"]),
        )

    console.print(table)
    console.print(f"[green][OK][/green] Evaluation scorecard written to {output.resolve()}")

    if not suite["all_passed"]:
        raise typer.Exit(code=1)

@app.command(name="version")
def version():
    """Prints SentinelAI version."""
    console.print("[cyan]SentinelAI version 0.1.0 (Production Multi-Agent Engine)[/cyan]")

if __name__ == "__main__":
    app()
