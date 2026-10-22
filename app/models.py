import re
from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from fastapi import HTTPException, status

SANDBOX_REGEX = re.compile(r"^sbx-[a-z0-9]{8,}$")
VALID_STATES = {"created", "ready", "running", "succeeded", "failed", "deleted"}

class RunCreate(BaseModel):
    run_id: str = Field(..., min_length=1, description="Unique run identifier")
    sandbox_name: str = Field(..., description="Sandbox identifier matching sbx-[a-z0-9]{8,}")
    problem_id: str = Field(..., min_length=1, description="Associated problem identifier")
    state: str = Field(..., description="Current lifecycle state of the sandbox")
    execution_target: str = Field(..., description="Target execution zone, must be celesto_sandbox")

    @field_validator("execution_target")
    @classmethod
    def validate_execution_target(cls, v: str) -> str:
        if v != "celesto_sandbox":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid execution_target '{v}'. Only 'celesto_sandbox' is permitted."
            )
        return v

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if v not in VALID_STATES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state '{v}'. Must be one of: {sorted(list(VALID_STATES))}"
            )
        return v

    @field_validator("sandbox_name")
    @classmethod
    def validate_sandbox_name(cls, v: str) -> str:
        if not SANDBOX_REGEX.match(v):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sandbox_name '{v}'. Must match pattern 'sbx-[a-z0-9]{{8,}}'."
            )
        return v

class RunRecord(BaseModel):
    run_id: str
    sandbox_name: str
    problem_id: str
    state: str
    execution_target: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
