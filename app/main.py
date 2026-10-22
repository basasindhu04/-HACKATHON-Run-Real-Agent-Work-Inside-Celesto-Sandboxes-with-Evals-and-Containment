import os
import re
from typing import List, Dict, Any
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.models import RunCreate, RunRecord, SANDBOX_REGEX, VALID_STATES
from app.db import fetch_all_runs, insert_run

app = FastAPI(
    title="Celesto Run Ledger API",
    version="1.0.0",
    description="Trusted control plane API for recording agent runs inside isolated Celesto sandboxes."
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Requirement 11: Any invalid execution_target, unknown state, or bad sandbox_name returns 400
    errors = exc.errors()
    detail = errors[0].get("msg", "Invalid request body") if errors else "Validation error"
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": detail, "errors": errors}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.get("/health", status_code=status.HTTP_200_OK)
def get_health():
    """Health check endpoint for Docker Compose and operator probes."""
    return {"status": "ok"}

@app.get("/api/runs", status_code=status.HTTP_200_OK)
def list_runs():
    """List all recorded sandbox runs in the Run Ledger."""
    return fetch_all_runs()

@app.post("/api/runs", status_code=status.HTTP_201_CREATED)
def create_run(run: RunCreate):
    """
    Record a new sandbox run state.
    Strictly enforces execution_target == 'celesto_sandbox'.
    """
    if run.execution_target != "celesto_sandbox":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid execution_target '{run.execution_target}'. Must be 'celesto_sandbox'."
        )
    if run.state not in VALID_STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid state '{run.state}'. Allowed states: {sorted(list(VALID_STATES))}"
        )
    if not SANDBOX_REGEX.match(run.sandbox_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sandbox_name '{run.sandbox_name}'. Must match 'sbx-[a-z0-9]{{8,}}'."
        )

    stored = insert_run(
        run_id=run.run_id,
        sandbox_name=run.sandbox_name,
        problem_id=run.problem_id,
        state=run.state,
        execution_target=run.execution_target
    )
    return stored

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8080"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
