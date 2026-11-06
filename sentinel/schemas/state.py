from typing import Annotated, Dict, List, Optional, Any
from typing_extensions import TypedDict
import operator

from sentinel.schemas.models import (
    AuditPlan,
    AuditReport,
    Vulnerability,
    TestGenerationResult,
    SandboxExecutionResult,
    PatchProposal,
    CriticVerdict
)

class AgentState(TypedDict):
    """
    Central TypedDict state tracked by the LangGraph StateMachine.
    Maintains complete provenance across all agent reasoning stages.
    """
    project_id: str
    original_code_files: Dict[str, str]      # Initial code: { "app.py": "..." }
    current_code_files: Dict[str, str]       # Evolving code during self-healing: { "app.py": "..." }
    
    plan: Optional[AuditPlan]
    audit_report: Optional[AuditReport]
    
    test_suite: Optional[TestGenerationResult]
    initial_execution: Optional[SandboxExecutionResult]
    
    latest_patch: Optional[PatchProposal]
    verification_execution: Optional[SandboxExecutionResult]
    
    iteration_count: int
    max_iterations: int
    critic_verdict: Optional[CriticVerdict]
    
    final_status: str                         # SUCCESS | MAX_ITERATIONS_REACHED | ESCALATED | CLEAN
    final_summary_report: Optional[str]
    
    # Event logs / thought streaming history
    activity_log: Annotated[List[str], operator.add]
