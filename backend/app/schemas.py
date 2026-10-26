"""Validated request schemas and response contracts."""
from __future__ import annotations

from typing import Any
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class JobCreate(BaseModel):
    task_type: str = Field(min_length=1, max_length=180, pattern=r"^[a-zA-Z0-9_.:-]+$")
    queue: str = Field(default="default", min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    priority: int = Field(default=5, ge=0, le=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=20)


class JobRetry(BaseModel):
    reason: str = Field(default="operator_retry", max_length=300)


class JobCancel(BaseModel):
    reason: str = Field(default="operator_cancel", max_length=300)


class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")
    title: str = Field(min_length=1, max_length=180)
    task_type: str = Field(min_length=1, max_length=180, pattern=r"^[a-zA-Z0-9_.:-]+$")
    payload: dict[str, Any] = Field(default_factory=dict)
    queue: str = Field(default="workflows", min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    priority: int = Field(default=5, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)


class WorkflowEdge(BaseModel):
    source: str = Field(min_length=1, max_length=100, validation_alias=AliasChoices("source", "from"))
    target: str = Field(min_length=1, max_length=100, validation_alias=AliasChoices("target", "to"))


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    nodes: list[WorkflowNode] = Field(min_length=1, max_length=250)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=1000)


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    scopes: list[str] = Field(default_factory=lambda: ["jobs:read", "jobs:write"])


class ErrorResponse(BaseModel):
    detail: str
