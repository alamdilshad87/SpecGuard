"""Execute generated test cases against a running API."""
from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.testgen import TestCase


def status_matches(actual: int, expected: list[str]) -> bool:
    code = str(actual)
    for exp in expected:
        exp = exp.upper()
        if exp == code:
            return True
        # Patterns like "2XX" from OpenAPI
        if len(exp) == 3 and exp.endswith("XX") and code[0] == exp[0]:
            return True
    return False


def run_case(client: httpx.Client, case: TestCase) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {"id": case.id, "name": case.name, "category": case.category,
                              "operation": case.operation, "expected_status": case.expected_status}
    try:
        kwargs: dict[str, Any] = {"params": case.query, "headers": case.headers}
        if case.body is not None:
            kwargs["json"] = case.body
        response = client.request(case.method, case.path, **kwargs)
        result["status"] = response.status_code
        result["passed"] = status_matches(response.status_code, case.expected_status)
        result["response_excerpt"] = response.text[:300]
    except httpx.HTTPError as exc:
        result["status"] = None
        result["passed"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


def run_tests(cases: list[TestCase], base_url: str, timeout: float = 10.0,
              transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Run ``cases`` against ``base_url``. ``transport`` lets tests inject a fake server."""
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport) as client:
        results = [run_case(client, case) for case in cases]
    passed = sum(1 for r in results if r["passed"])
    return {
        "base_url": base_url,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(100 * passed / len(results), 1) if results else 0.0,
        "results": results,
    }
