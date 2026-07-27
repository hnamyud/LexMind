from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.responses import ApiError, envelope
from app.core.security import current_user
from app.schemas import RunBatchBody

router = APIRouter(tags=["Integration"])
eval_router = APIRouter(prefix="/eval", tags=["Evaluation"], dependencies=[Depends(current_user)])


def client_headers(settings: Settings) -> dict[str, str]:
    return {"INTERNAL-SECRET": settings.internal_secret}


async def ai_request(settings: Settings, method: str, path: str, **kwargs):
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(method, settings.ai_base_url + path, headers=client_headers(settings), **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(502, f"AI Service Error: {exc}", "Bad Gateway")
    if response.status_code >= 400:
        try: detail = response.json()
        except ValueError: detail = response.text
        raise ApiError(response.status_code, detail, "Http Exception")
    return response.json()


@router.get("/graph/demo")
async def graph_demo(id: str | None = None, settings: Annotated[Settings, Depends(get_settings)] = None):
    data = await ai_request(settings, "GET", "/graph/demo", params={"id": (id or "nd168_2024_d7_k7")})
    return envelope(data, "Get Graph Demo Data")


@eval_router.get("/datasets")
async def datasets(settings: Annotated[Settings, Depends(get_settings)]):
    return envelope(await ai_request(settings, "GET", "/eval/datasets"))


@eval_router.post("/run-batch")
async def run_batch(body: RunBatchBody, settings: Annotated[Settings, Depends(get_settings)]):
    return envelope(await ai_request(settings, "POST", "/eval/run-batch", json=body.model_dump(by_alias=True, exclude_none=True)))


@eval_router.get("/sessions")
async def sessions(limit: int = 20, settings: Annotated[Settings, Depends(get_settings)] = None):
    return envelope(await ai_request(settings, "GET", "/eval/sessions", params={"limit": limit}))


@eval_router.get("/results/{session_id}")
async def results(session_id: str, settings: Annotated[Settings, Depends(get_settings)]):
    return envelope(await ai_request(settings, "GET", f"/eval/results/{session_id}"))


@eval_router.get("/stats/{session_id}")
async def stats(session_id: str, settings: Annotated[Settings, Depends(get_settings)]):
    return envelope(await ai_request(settings, "GET", f"/eval/stats/{session_id}"))
