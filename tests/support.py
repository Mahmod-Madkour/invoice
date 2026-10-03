"""Shared helpers for tests and scripts/render_samples.py."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from app.domain.models import Invoice, LineItem, clean_name
from app.domain.numbers import parse_decimal

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def fixture_path(name: str) -> Path:
    return FIXTURES_DIR / f"{name}.json"


def load_fixture(name: str) -> dict:
    """The raw request payload stored in tests/fixtures/<name>.json."""
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))


def payload_to_invoice(payload: dict) -> Invoice:
    """Strict conversion of a valid fixture payload; any invalid value raises."""
    items = []
    for raw in payload["items"]:
        values = [parse_decimal(raw[key] or "0") for key in ("quantity", "unit_price", "discount_percent")]
        if any(v is None for v in values):
            raise ValueError(f"invalid number in fixture row {raw!r}")
        quantity, unit_price, discount = values
        items.append(LineItem(clean_name(raw["name"]), quantity, unit_price, discount))
    return Invoice(date=datetime.date.fromisoformat(payload["date"]), items=tuple(items))


def fixture_invoice(name: str) -> Invoice:
    return payload_to_invoice(load_fixture(name))
