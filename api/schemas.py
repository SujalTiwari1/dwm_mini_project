"""Minimal response shapes. Rows are passed through from the warehouse/reports, so only the envelopes are typed."""
from typing import Any

from pydantic import BaseModel


class Health(BaseModel):
    status: str


class Ready(BaseModel):
    status: str
    database: str


class ListResponse(BaseModel):
    data: list[dict[str, Any]]
    count: int          # rows in this response
    total: int          # rows matching the filters before limit/offset


class ObjectResponse(BaseModel):
    data: dict[str, Any]
