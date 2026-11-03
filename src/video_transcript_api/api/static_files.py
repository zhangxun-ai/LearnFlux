"""Serve application code with explicit browser cache revalidation."""

from pathlib import Path

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class RevalidatingStaticFiles(StaticFiles):
    """Revalidate frontend documents and code, including conditional responses."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if Path(path).suffix.lower() in {".html", ".css", ".js", ".mjs"}:
            response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
        return response
