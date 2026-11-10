import json
import asyncio
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from sentinel.workflow.graph import build_sentinel_graph
from sentinel.observability.tracer import get_run_callbacks

app = FastAPI(
    title="SentinelAI Engine API",
    description="Production Multi-Agent Code Auditing & Self-Healing REST and Streaming Engine",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AuditRequest(BaseModel):
    project_id: str = Field(default="custom-project")
    code_files: Dict[str, str] = Field(description="Dictionary mapping relative filenames to file contents")
    max_iterations: int = Field(default=3, ge=1, le=10)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "sentinel-ai-engine"}

@app.post("/api/v1/audit/stream")
async def stream_audit(payload: AuditRequest):
    """
    Executes the multi-agent workflow and streams step-by-step agent events,
    tool execution logs, and self-healing state transitions via Server-Sent Events (SSE).
    """
    if not payload.code_files:
        raise HTTPException(status_code=400, detail="code_files cannot be empty")

    async def event_generator():
        graph = build_sentinel_graph()
        initial_state = {
            "project_id": payload.project_id,
            "original_code_files": payload.code_files,
            "current_code_files": payload.code_files,
            "plan": None,
            "audit_report": None,
            "test_suite": None,
            "initial_execution": None,
            "latest_patch": None,
            "verification_execution": None,
            "iteration_count": 0,
            "max_iterations": payload.max_iterations,
            "critic_verdict": None,
            "final_status": "PENDING",
            "final_summary_report": None,
            "activity_log": []
        }

        callbacks, telemetry = get_run_callbacks(project_id=payload.project_id)
        config = {"callbacks": callbacks} if callbacks else {}

        yield {
            "event": "lifecycle",
            "data": json.dumps({
                "status": "STARTED",
                "message": f"Ingested {len(payload.code_files)} code files.",
                "langfuse_enabled": len(callbacks) > 1,
            })
        }

        try:
            # Run graph stream in threadpool to prevent blocking asyncio loop
            for event in graph.stream(initial_state, config=config):
                for node_name, state_update in event.items():
                    log_messages = state_update.get("activity_log", [])
                    latest_msg = log_messages[-1] if log_messages else f"Executed {node_name}"
                    
                    # Yield structured node event
                    yield {
                        "event": "node_update",
                        "data": json.dumps({
                            "node": node_name,
                            "message": latest_msg,
                            "iteration": state_update.get("iteration_count", 0),
                            "final_status": state_update.get("final_status", "IN_PROGRESS")
                        })
                    }

            telemetry_summary = telemetry.get_summary()
            telemetry_summary["langfuse_enabled"] = len(callbacks) > 1
            yield {
                "event": "telemetry",
                "data": json.dumps(telemetry_summary)
            }

            yield {
                "event": "complete",
                "data": json.dumps({"status": "FINISHED", "message": "SentinelAI workflow finished."})
            }

        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"status": "FAILED", "error": str(exc)})
            }

    return EventSourceResponse(event_generator())
