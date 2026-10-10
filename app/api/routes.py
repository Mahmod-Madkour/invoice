"""HTTP routes (spec §10): the UI page, the PDF endpoint and the health check."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException

from app.api.limits import MSG_RATE_LIMITED, retry_after_header
from app.api.schemas import ErrorResponse, InvoiceRequest
from app.pdf.viewmodel import build_invoice_view

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=WEB_DIR / "templates")  # autoescape is on for .html

router = APIRouter()

ERROR_RESPONSES = {
    413: {"model": ErrorResponse, "description": "Request body larger than 256 KB"},
    422: {"model": ErrorResponse, "description": "Validation errors, one per invalid cell"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
    503: {"model": ErrorResponse, "description": "All render slots are busy"},
}


async def enforce_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"  # set by uvicorn --proxy-headers
    wait = request.app.state.rate_limiter.hit(client_ip)
    if wait:
        raise HTTPException(status_code=429, detail=MSG_RATE_LIMITED, headers=retry_after_header(wait))


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "max_items": settings.max_items,
            "rows_per_page": settings.rows_per_table * settings.tables_per_page,
        },
    )


@router.post(
    "/api/invoice/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, **ERROR_RESPONSES},
    dependencies=[Depends(enforce_rate_limit)],
)
def create_invoice_pdf(payload: InvoiceRequest, request: Request) -> Response:
    # Plain `def`: FastAPI runs it in the threadpool, so CPU-bound rendering never blocks the event loop.
    state = request.app.state
    invoice = payload.to_invoice(state.settings.max_items)  # raises InvoiceValidationError → 422
    request.state.item_count = len(invoice.items)
    view = build_invoice_view(invoice, state.settings.rows_per_table, state.settings.tables_per_page)
    with state.render_slots.acquire():  # 503 if no slot frees up within ~10 s
        pdf = state.renderer.render_pdf(view)
    filename = f"invoice-{invoice.date.isoformat()}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}
