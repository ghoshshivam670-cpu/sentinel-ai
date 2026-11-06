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
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax

from sentinel.workflow.graph import build_sentinel_graph
from sentinel.observability.tracer import get_langfuse_callback_handler

app = typer.Typer(help="SentinelAI: Autonomous Multi-Agent Code Audit & Self-Healing Engine", no_args_is_help=True)
console = Console()

@app.command(name="audit")
def audit(
    target_path: str = typer.Argument(..., help="Path to code file or directory to audit"),
    max_iterations: int = typer.Option(3, "--max-iterations", "-m", help="Maximum self-healing retry iterations")
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

    callbacks = []
    langfuse_cb = get_langfuse_callback_handler()
    if langfuse_cb:
        callbacks.append(langfuse_cb)
        console.print("[green][OK][/green] Langfuse observability connected.")

    config = {"callbacks": callbacks} if callbacks else {}

    # Stream agent state execution
    console.print("\n[yellow]Executing multi-agent state graph...[/yellow]")
    final_state = None
    for event in graph.stream(initial_state, config=config):
        for node_name, state_update in event.items():
            if "activity_log" in state_update and state_update["activity_log"]:
                latest_msg = state_update["activity_log"][-1]
                console.print(f"[bold cyan]▶ {node_name.upper()}:[/bold cyan] {latest_msg}")
        final_state = event

    # Extract final consolidated state
    if not final_state:
        console.print("[bold red]Execution ended with no state output.[/bold red]")
        return

    # Grab the terminal node output
    terminal_state = list(final_state.values())[0]

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

    # Display Final Report
    report_text = terminal_state.get("final_summary_report")
    if report_text:
        report_output_path = Path("SENTINEL_AUDIT_REPORT.md")
        report_output_path.write_text(report_text, encoding="utf-8")
        console.print(f"\n[bold green][OK] Report generated successfully:[/bold green] {report_output_path.resolve()}")

@app.command(name="version")
def version():
    """Prints SentinelAI version."""
    console.print("[cyan]SentinelAI version 0.1.0 (Production Multi-Agent Engine)[/cyan]")

if __name__ == "__main__":
    app()
