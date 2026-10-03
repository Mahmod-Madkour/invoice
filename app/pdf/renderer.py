"""View model → HTML → PDF bytes. The PDF engine (WeasyPrint) is isolated in this module.

Rendering happens entirely in memory: ``write_pdf()`` returns bytes; nothing is written to disk.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from weasyprint import CSS, HTML
from weasyprint.document import Document
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher, URLFetcherResponse

from app.pdf.viewmodel import InvoiceView

LOGGER = logging.getLogger(__name__)

PDF_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PDF_DIR.parent / "assets"
TEMPLATES_DIR = PDF_DIR / "templates"
STYLESHEET = PDF_DIR / "styles" / "invoice.css"


class AssetURLFetcher(URLFetcher):
    """Serves local files from one directory only; every other URL is refused.

    Prevents SSRF and arbitrary file reads through anything that ends up in the HTML/CSS.
    A refused URL raises, which WeasyPrint logs and skips (the resource is not loaded).
    """

    def __init__(self, root: Path) -> None:
        super().__init__(allowed_protocols={"file"}, allow_redirects=False)
        self._root = root.resolve()
        self._cache: dict[Path, bytes] = {}

    def resolve(self, url: str) -> Path:
        parts = urlsplit(url)
        if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
            raise PermissionError(f"URL refused (only local assets are allowed): {url[:120]}")
        path = Path(url2pathname(parts.path)).resolve()
        if not path.is_relative_to(self._root) or not path.is_file():
            raise PermissionError(f"URL refused (outside the asset directory): {url[:120]}")
        return path

    def fetch(self, url: str, headers: dict | None = None) -> URLFetcherResponse:
        try:
            path = self.resolve(url)
        except PermissionError:
            LOGGER.warning("Blocked resource request from the PDF renderer")
            raise
        body = self._cache.get(path)
        if body is None:
            body = self._cache[path] = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return URLFetcherResponse(url, body=body, headers={"Content-Type": content_type})


class InvoicePdfRenderer:
    def __init__(self, assets_dir: Path = ASSETS_DIR) -> None:
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=True,  # item names are user input
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._template = self._env.get_template("invoice.html")
        self._stylesheet = STYLESHEET.read_text(encoding="utf-8")
        self._fetcher = AssetURLFetcher(assets_dir)
        self._base_url = assets_dir.resolve().as_uri() + "/"

    def render_html(self, view: InvoiceView) -> str:
        return self._template.render(invoice=view)

    def layout(self, view: InvoiceView) -> Document:
        """Lay the document out (no PDF bytes yet); tests use this to inspect the geometry."""
        # A fresh FontConfiguration per render: it is not shared between threads.
        font_config = FontConfiguration()
        stylesheet = CSS(
            string=self._stylesheet,
            base_url=self._base_url,
            url_fetcher=self._fetcher,
            font_config=font_config,
        )
        html = HTML(string=self.render_html(view), base_url=self._base_url, url_fetcher=self._fetcher)
        return html.render(stylesheets=[stylesheet], font_config=font_config)

    def render_pdf(self, view: InvoiceView) -> bytes:
        return self.layout(view).write_pdf()
