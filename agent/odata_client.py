"""Thin OData client: query building, retries with exponential backoff, error mapping.

Accepts any httpx.Client-compatible object (a real httpx.Client against a BTP/S4
destination, or Starlette's TestClient against the local mock) so the same code
path is exercised in tests and in production.
"""
import time
from typing import Any, Callable

import httpx

RETRYABLE_STATUS = {502, 503, 504}


class ODataClientError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"[{status}] {code}: {message}")
        self.status, self.code, self.message = status, code, message


class ODataClient:
    def __init__(self, http: httpx.Client, base_path: str = "/odata", max_retries: int = 3,
                 backoff_s: float = 0.2, sleep: Callable[[float], None] = time.sleep):
        self.http, self.base_path = http, base_path.rstrip("/")
        self.max_retries, self.backoff_s, self._sleep = max_retries, backoff_s, sleep
        self.retry_count = 0  # exposed for tests / observability

    def _request(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.http.request(method, url, **kwargs)
            except httpx.TransportError as exc:  # connection reset, timeout, ...
                last_err = exc
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    if resp.status_code >= 400:
                        err = resp.json().get("error", {}) if resp.content else {}
                        raise ODataClientError(resp.status_code, err.get("code", "HTTP_ERROR"),
                                               err.get("message", {}).get("value", resp.text[:200]))
                    return resp.json()
                last_err = ODataClientError(resp.status_code, "UNAVAILABLE", "upstream unavailable")
            if attempt < self.max_retries:
                self.retry_count += 1
                self._sleep(self.backoff_s * (2 ** attempt))
        raise ODataClientError(503, "RETRIES_EXHAUSTED", str(last_err))

    def query(self, entity: str, filter: str | None = None, top: int | None = None,
              select: list[str] | None = None, orderby: str | None = None) -> list[dict]:
        params: dict[str, Any] = {}
        if filter: params["$filter"] = filter
        if top: params["$top"] = top
        if select: params["$select"] = ",".join(select)
        if orderby: params["$orderby"] = orderby
        data = self._request("GET", f"{self.base_path}/{entity}", params=params)
        return data["d"]["results"]

    def create(self, entity: str, payload: dict) -> dict:
        return self._request("POST", f"{self.base_path}/{entity}", json=payload)["d"]


def odata_quote(value: str) -> str:
    """Escape a string literal for use inside an OData $filter."""
    return "'" + value.replace("'", "''") + "'"
