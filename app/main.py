"""FastAPI surface for the GS1 element string parser."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .gs1 import GS1ParseError, parse_element_string

app = FastAPI(
    title="GS1 Element String Parser",
    version="1.0.0",
    description=(
        "Parses raw GS1 scan strings (AI 01 / 10 / 17 / 21) separated by "
        "ASCII 29 (GS) into ordered, validated elements."
    ),
)


class ParseRequest(BaseModel):
    data: str = Field(
        ...,
        description="Raw scan string; variable-length fields are terminated "
        "by ASCII 29 (GS, \\u001d) unless they are the last element.",
    )


class ElementOut(BaseModel):
    ai: str
    title: str
    value: str
    offset: int = Field(..., description="Byte offset of the AI in the input")
    date: str | None = Field(None, description="ISO date, AI 17 only")


class ParseResponse(BaseModel):
    elements: list[ElementOut]


@app.exception_handler(GS1ParseError)
async def handle_gs1_error(_request: Request, exc: GS1ParseError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.to_dict()})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/parse",
    response_model=ParseResponse,
    response_model_exclude_none=True,
    responses={
        200: {"description": "Elements in their original order"},
        422: {"description": "Parse/validation error with byte offset and rule"},
    },
)
def parse(req: ParseRequest) -> ParseResponse:
    elements = parse_element_string(req.data)
    return ParseResponse(
        elements=[
            ElementOut(
                ai=e.ai,
                title=e.title,
                value=e.value,
                offset=e.offset,
                date=e.date.isoformat() if e.date else None,
            )
            for e in elements
        ]
    )
