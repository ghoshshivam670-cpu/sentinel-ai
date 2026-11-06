from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class Vulnerability(BaseModel):
    id: str = Field(description="Unique identifier e.g. VULN-001")
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(
        description="Severity level of the security or logic issue"
    )
    category: str = Field(description="OWASP, CWE, or logic category e.g. SQL Injection, Race Condition, Off-by-one")
    cwe_id: Optional[str] = Field(default=None, description="Standard CWE identifier if applicable (e.g. CWE-89)")
    file_path: str = Field(description="Target file path containing the issue")
    line_number: Optional[int] = Field(default=None, description="Approximate line number")
    description: str = Field(description="Detailed explanation of the flaw and exploit vector")
    recommendation: str = Field(description="Actionable mitigation advice")

class AuditPlan(BaseModel):
    summary: str = Field(description="Overview of code purpose and architecture")
    focus_areas: List[str] = Field(description="Specific high-risk components to inspect")
    steps: List[str] = Field(description="Ordered list of analysis and testing steps")

class AuditReport(BaseModel):
    summary: str = Field(description="Brief high-level overview of the security posture")
    risk_score: float = Field(ge=0.0, le=10.0, description="Overall risk rating from 0.0 (clean) to 10.0 (critical danger)")
    vulnerabilities: List[Vulnerability] = Field(
        description="List of ALL discovered security, reliability, and logic vulnerabilities. If issues exist, they MUST be listed here."
    )
    has_critical_findings: bool = False

class TestGenerationResult(BaseModel):
    test_file_path: str = Field(default="test_reproduction.py", description="Name of the reproduction test file")
    test_code: str = Field(description="Self-contained executable pytest code that isolates and triggers the bug")
    targeted_vulnerability_ids: List[str] = Field(default_factory=list)
    rationale: str = Field(description="Why this test proves the existence of the vulnerability")

class SandboxExecutionResult(BaseModel):
    passed: bool
    total_tests: int = 0
    failures: int = 0
    errors: int = 0
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time_seconds: float = 0.0

class PatchProposal(BaseModel):
    explanation: str = Field(description="Clear explanation of the bug fix")
    files_modified: List[str] = Field(description="List of filenames modified by this patch")
    patched_files: dict[str, str] = Field(
        description="Dictionary mapping file_path to the complete new patched file content"
    )

class CriticVerdict(BaseModel):
    decision: Literal["PASS", "RETRY", "ESCALATE"] = Field(
        description="PASS if all tests succeed with no regressions; RETRY if tests still fail; ESCALATE if unresolvable"
    )
    passed_tests_verified: bool
    feedback_for_coder: Optional[str] = Field(
        default=None, 
        description="Precise technical analysis of failure traceback and corrective instructions for the Coder"
    )
    regressions_detected: bool = False
