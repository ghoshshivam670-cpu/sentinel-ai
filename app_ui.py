import os
import sys
import difflib
from pathlib import Path
import streamlit as st

# Configure sys.path so sentinel modules resolve
sys.path.insert(0, str(Path(__file__).parent))

from sentinel.workflow.graph import build_sentinel_graph
from sentinel.config import settings
from sentinel.observability.tracer import get_run_callbacks

# Page Configuration
st.set_page_config(
    page_title="SentinelAI - Multi-Agent Code Audit & Self-Healing",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom High-Tech Styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #00d2ff;
        margin-bottom: 0px;
    }
    .sub-header {
        font-size: 1.0rem;
        color: #8892b0;
        margin-bottom: 25px;
    }
    .metric-card {
        background: #112240;
        border-radius: 8px;
        padding: 15px;
        border-left: 4px solid #00d2ff;
    }
    .vuln-critical {
        border-left: 5px solid #ff4b4b;
        background: rgba(255, 75, 75, 0.1);
        padding: 12px;
        border-radius: 6px;
        margin-bottom: 10px;
    }
    .vuln-high {
        border-left: 5px solid #ffa500;
        background: rgba(255, 165, 0, 0.1);
        padding: 12px;
        border-radius: 6px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# App Header
st.markdown("<div class='main-header'>🛡️ SentinelAI Engine Dashboard</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='sub-header'>Autonomous Multi-Agent Code Auditing, Reproduction & Self-Healing Pipeline</div>", 
    unsafe_allow_html=True
)

# Sidebar
st.sidebar.title("⚙️ Engine Configuration")
active_model = settings.model_name or "gemini-3.5-flash-lite"
langfuse_configured = bool(
    (settings.langfuse_public_key or os.getenv("LANGFUSE_PUBLIC_KEY"))
    and (settings.langfuse_secret_key or os.getenv("LANGFUSE_SECRET_KEY"))
)
obs_mode = "Langfuse Cloud + Local Traces" if langfuse_configured else "Local JSONL (`logs/traces.jsonl`)"
st.sidebar.info(
    f"**Active Model:** `{active_model}`\n\n"
    f"**Provider:** `{settings.default_llm_provider.upper()}`\n\n"
    f"**Observability:** {obs_mode}"
)

max_iterations = st.sidebar.slider("Max Self-Healing Iterations", min_value=1, max_value=5, value=3)
run_deepeval = st.sidebar.checkbox(
    "Run DeepEval LLM-as-a-Judge",
    value=False,
    help="Evaluates audit precision, test quality, and patch security via GEval after workflow completion.",
)

# Sample Code Loader
sample_path = Path("tests/sample_vulnerable_code/auth_service.py")
sample_code = ""
if sample_path.exists():
    sample_code = sample_path.read_text(encoding="utf-8")

input_mode = st.sidebar.radio(
    "Input Source",
    ["Preloaded Vulnerable Sample (SQLi)", "Upload Python File(s)", "Custom Code Input"]
)

code_files = {}
if input_mode == "Preloaded Vulnerable Sample (SQLi)":
    filename = "auth_service.py"
    code_files[filename] = sample_code
elif input_mode == "Upload Python File(s)":
    uploaded_files = st.sidebar.file_uploader("Upload .py file(s)", type=["py"], accept_multiple_files=True)
    if uploaded_files:
        for uf in uploaded_files:
            code_files[uf.name] = uf.read().decode("utf-8")
        filename = uploaded_files[0].name
    else:
        filename = "uploaded.py"
else:
    filename = st.sidebar.text_input("Filename", value="app.py")
    code_content = st.sidebar.text_area(
        "Paste Python Code Here", 
        height=300,
        value="def query_user(username):\n    # Vulnerable to SQL injection\n    return db.execute(f'SELECT * FROM users WHERE name = {username}')"
    )
    code_files[filename] = code_content

# Execution Button
run_audit = st.sidebar.button("🚀 Run Autonomous Audit & Healing", type="primary", use_container_width=True)

# Main Dashboard Tabs
tab_exec, tab_findings, tab_tests, tab_patch, tab_report = st.tabs([
    "⚡ Live Multi-Agent Execution",
    "🚨 Security Vulnerabilities",
    "🧪 Reproduction & Sandbox",
    "🛠️ Self-Healing Patch Diff",
    "📄 Executive Markdown Report"
])

if "audit_state" not in st.session_state:
    st.session_state.audit_state = None

if run_audit:
    if not code_files:
        st.sidebar.error("Please upload at least one .py file first.")
    else:
        with tab_exec:
            st.subheader("Agent Workflow In Progress...")
            status_container = st.container()
            progress_bar = st.progress(0.0)
            
            graph = build_sentinel_graph()
            initial_state = {
                "project_id": filename,
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
                "activity_log": []
            }

            step_weights = {
                "planner": 0.15,
                "auditor": 0.35,
                "test_generator": 0.50,
                "initial_sandbox": 0.65,
                "coder": 0.80,
                "verification_sandbox": 0.90,
                "critic": 0.95,
                "reporter": 1.0
            }

            callbacks, telemetry = get_run_callbacks(project_id=filename)
            terminal_state = dict(initial_state)

            for event in graph.stream(initial_state, config={"callbacks": callbacks}):
                for node_name, state_update in event.items():
                    for k, v in state_update.items():
                        if k == "activity_log":
                            terminal_state["activity_log"].extend(v)
                        else:
                            terminal_state[k] = v
                    if "activity_log" in state_update and state_update["activity_log"]:
                        latest_msg = state_update["activity_log"][-1]
                        with status_container:
                            st.write(f"▶ **{node_name.upper()}**: {latest_msg}")
                    if node_name in step_weights:
                        progress_bar.progress(step_weights[node_name])

            progress_bar.progress(1.0)
            terminal_state["telemetry"] = telemetry.get_summary()
            terminal_state["langfuse_connected"] = len(callbacks) > 1

            if run_deepeval:
                with st.spinner("Running DeepEval GEval LLM-as-a-Judge quality scoring..."):
                    from sentinel.evals.judge import evaluate_sentinel_run

                    terminal_state["deepeval_report"] = evaluate_sentinel_run(
                        code_files=code_files,
                        final_state=terminal_state,
                    )

            st.success("✅ Multi-Agent Workflow Execution Complete!")
            st.session_state.audit_state = terminal_state

# Display State if Available
state = st.session_state.audit_state

if state:
    audit = state.get("audit_report")
    patch = state.get("latest_patch")
    test_suite = state.get("test_suite")
    verif = state.get("verification_execution")
    report_text = state.get("final_summary_report")

    # Tab 1: Live Execution Log + LLMOps Telemetry
    with tab_exec:
        tel = state.get("telemetry")
        if tel:
            st.subheader("📊 LLMOps Observability Telemetry")
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("LLM Calls", tel.get("llm_calls", 0))
            t2.metric("Total Tokens", tel.get("total_tokens", 0))
            t3.metric("LLM Latency", f"{tel.get('total_latency_seconds', 0.0)}s")
            t4.metric("Est. Cost (USD)", f"${tel.get('estimated_cost_usd', 0.0):.6f}")
            st.caption(
                f"Trace Log: `{tel.get('trace_log_path', 'logs/traces.jsonl')}` | "
                f"Langfuse Synced: `{'Yes' if state.get('langfuse_connected') else 'Local Mode'}`"
            )
            st.divider()

        eval_rep = state.get("deepeval_report")
        if eval_rep:
            st.subheader(f"🧪 DeepEval GEval Judge Scorecard (Overall: {eval_rep['overall_score']:.3f})")
            eval_cols = st.columns(len(eval_rep["metrics"]) or 1)
            for idx, (_, m_data) in enumerate(eval_rep["metrics"].items()):
                badge = "PASS" if m_data["passed"] else "FAIL"
                eval_cols[idx].metric(m_data["name"], f"{m_data['score']:.3f}", badge)
            with st.expander("View DeepEval Judge Rationales"):
                for _, m_data in eval_rep["metrics"].items():
                    st.markdown(f"- **{m_data['name']} (`{m_data['score']:.3f}`):** {m_data['reason']}")
            st.divider()

        st.subheader("Step-by-Step Provenance Log")
        for log_entry in state.get("activity_log", []):
            st.info(log_entry)

    # Tab 2: Findings
    with tab_findings:
        st.subheader("Security & Logic Audit Findings")
        if audit:
            col1, col2, col3 = st.columns(3)
            col1.metric("Risk Score", f"{audit.risk_score} / 10.0")
            col2.metric("Total Findings", len(audit.vulnerabilities))
            col3.metric("Critical Findings", "Yes" if audit.has_critical_findings else "No")
            
            st.markdown(f"**Executive Summary:** {audit.summary}")
            st.divider()

            for v in audit.vulnerabilities:
                css_class = "vuln-critical" if v.severity in ["HIGH", "CRITICAL"] else "vuln-high"
                cwe_str = f" ({v.cwe_id})" if v.cwe_id else ""
                st.markdown(f"""
                <div class='{css_class}'>
                    <h4 style='margin:0;'>[{v.id}] {v.severity}: {v.category}{cwe_str}</h4>
                    <p><b>Location:</b> <code>{v.file_path}:{v.line_number or 'N/A'}</code></p>
                    <p><b>Description:</b> {v.description}</p>
                    <p><b>Mitigation:</b> {v.recommendation}</p>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No vulnerabilities recorded.")

    # Tab 3: Reproduction & Sandbox
    with tab_tests:
        st.subheader("Automated Pytest Reproduction Harness")
        if test_suite:
            st.markdown(f"**Target Reproduction File:** `{test_suite.test_file_path}`")
            st.markdown(f"**Targeted Findings:** `{', '.join(test_suite.targeted_vulnerability_ids)}`")
            st.info(f"**Test Strategy & Rationale:** {test_suite.rationale}")
            st.code(test_suite.test_code, language="python")
        else:
            st.info("No reproduction test suite was needed.")

        if verif:
            st.divider()
            st.subheader("Sandbox Telemetry")
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Verification Status", "PASSED" if verif.passed else "FAILED")
            col_b.metric("Tests Evaluated", verif.total_tests)
            col_c.metric("Execution Latency", f"{verif.execution_time_seconds}s")
            
            with st.expander("View Raw Sandbox Pytest Output"):
                st.text(verif.stdout)
                if verif.stderr:
                    st.text(verif.stderr)

    # Tab 4: Patch Diff
    with tab_patch:
        st.subheader("Autonomous Code Remediation")
        if patch:
            st.success(f"**Remediation Explanation:** {patch.explanation}")
            
            for mod_file in patch.files_modified:
                orig = state["original_code_files"].get(mod_file, "")
                healed = state["current_code_files"].get(mod_file, "")
                
                orig_lines = orig.splitlines(keepends=True)
                healed_lines = healed.splitlines(keepends=True)
                diff = "".join(difflib.unified_diff(orig_lines, healed_lines, fromfile=f"original/{mod_file}", tofile=f"healed/{mod_file}"))

                st.markdown(f"#### Unified Diff: `{mod_file}`")
                st.code(diff, language="diff")

                col_orig, col_healed = st.columns(2)
                with col_orig:
                    st.caption("Original Vulnerable Code")
                    st.code(orig, language="python")
                with col_healed:
                    st.caption("Autonomously Healed Code")
                    st.code(healed, language="python")
        else:
            st.info("No patch generated.")

    # Tab 5: Executive Report
    with tab_report:
        st.subheader("Executive Markdown Report")
        if report_text:
            st.markdown(report_text)
            st.download_button(
                label="📥 Download Audit Report (.md)",
                data=report_text,
                file_name=f"SENTINEL_AUDIT_{filename}.md",
                mime="text/markdown"
            )
        else:
            st.info("No report generated.")
else:
    with tab_exec:
        st.info("👈 Configure options in the sidebar and click **'Run Autonomous Audit & Healing'** to initiate the multi-agent pipeline.")
        st.markdown("""
        ### Multi-Agent StateGraph Architecture:
        1. **Planner Agent:** Formulates security inspection plan and focuses on high-risk surfaces.
        2. **Auditor Agent:** Discovers CWE/OWASP vulnerabilities with strict Pydantic schemas.
        3. **Test Engineer Agent:** Writes targeted reproduction `pytest` suites to prove flaws.
        4. **Sandbox Runner:** Runs tests in isolated subprocess environments with timeout guards.
        5. **Coder Agent:** Synthesizes surgical patches.
        6. **Critic Agent:** Verifies remediation results and triggers reflection loops if needed.
        7. **Reporter Agent:** Generates executive Markdown reports and unified diffs.
        """)
