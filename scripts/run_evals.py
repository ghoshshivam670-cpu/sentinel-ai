import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from sentinel.evals.benchmark import run_benchmark_suite

app = typer.Typer(help="SentinelAI DeepEval LLM-as-a-Judge Benchmark Runner")
console = Console()


@app.command()
def main(
    case: Optional[str] = typer.Option(None, "--case", "-c", help="Run a specific case (auth_service, payment_processor, clean_discount)"),
    threshold: float = typer.Option(0.7, "--threshold", "-t", help="Minimum GEval pass threshold (0.0 - 1.0)"),
    max_iterations: int = typer.Option(2, "--max-iterations", "-m", help="Max self-healing loop iterations"),
    output: Path = typer.Option(Path("EVAL_SCORECARD.md"), "--output", "-o", help="Markdown scorecard output path"),
):
    console.print("[bold cyan]SentinelAI DeepEval LLM-as-a-Judge Benchmark Suite[/bold cyan]")
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
    console.print(f"[green][OK][/green] Evaluation scorecard saved to {output.resolve()}")

    if not suite["all_passed"]:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
