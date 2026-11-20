"""HTTP client for the .NET Roslyn scanner service (``scanner-dotnet/``)."""
from __future__ import annotations

import httpx

from app.core.codescan import Route


class CSharpScannerError(RuntimeError):
    """The C# scanner could not be reached or returned an unusable response."""


def scan_csharp(files: dict[str, str], base_url: str, timeout: float = 30.0,
                transport: httpx.BaseTransport | None = None) -> list[Route]:
    """Send ``{path: source}`` C# files to the scanner and return the routes it found."""
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport) as client:
            resp = client.post("/scan", json={"files": files})
            resp.raise_for_status()
            return [Route.from_dict(r) for r in resp.json()["routes"]]
    except httpx.HTTPStatusError as exc:
        raise CSharpScannerError(f"C# scanner returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise CSharpScannerError(f"C# scanner unreachable: {exc.__class__.__name__}") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise CSharpScannerError("C# scanner returned an unexpected response") from exc
