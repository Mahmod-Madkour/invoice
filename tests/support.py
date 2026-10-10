"""Shared helpers for tests and scripts/render_samples.py."""

from __future__ import annotations

import json
from pathlib import Path

from app.api.schemas import InvoiceRequest
from app.domain.models import Invoice

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def fixture_path(name: str) -> Path:
    return FIXTURES_DIR / f"{name}.json"


def load_fixture(name: str) -> dict:
    """The raw request payload stored in tests/fixtures/<name>.json."""
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))


def payload_to_invoice(payload: dict, max_items: int = 1000) -> Invoice:
    """Convert a fixture through the real request validation (the same path as the API)."""
    return InvoiceRequest.model_validate(payload).to_invoice(max_items)


def fixture_invoice(name: str) -> Invoice:
    return payload_to_invoice(load_fixture(name))
