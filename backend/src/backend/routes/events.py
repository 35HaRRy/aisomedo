"""Authenticated foreground invalidation stream."""

import json
from collections.abc import AsyncIterator

from dojo import Client
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.responses import StreamingResponse

from backend.deps import get_current_client
from backend.live import LiveHub

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events", response_class=StreamingResponse)
async def events(
    request: Request, response: Response, client: Client = Depends(get_current_client),
) -> StreamingResponse:
    hub: LiveHub | None = getattr(request.app.state, "live_hub", None)
    if hub is None or not hub.ready or request.state.live_generation != hub.generation:
        raise HTTPException(503, "live subscription unavailable")
    expires_at = request.state.authorization_expires_at
    generation = hub.generation

    async def frames() -> AsyncIterator[str]:
        if generation != hub.generation:
            yield 'event: resync\ndata: {"reason": "listener_lost"}\n\n'
            return
        async for message in hub.subscribe(client.id, expires_at=expires_at):
            yield f"event: {message.event}\ndata: {json.dumps(message.data)}\n\n"

    stream = StreamingResponse(frames(), media_type="text/event-stream", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no",
    })
    # FastAPI's temporary Response holds renewed browser cookies.
    stream.raw_headers.extend(response.raw_headers)
    return stream
