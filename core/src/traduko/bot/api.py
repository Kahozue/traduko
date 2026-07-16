"""Async client for the core HTTP API.

The bot deliberately goes through the same API surface as the GUI and CLI
(design doc section 2: every entry point is a client, features exist once).
Inside the service process the transport is ASGI, so requests never leave
the process but still exercise auth, preflight gating and status
validation exactly like an external client would.
"""
from __future__ import annotations

import httpx


class CoreApiError(Exception):
    def __init__(self, status_code: int, detail: object) -> None:
        super().__init__(f"core api error {status_code}")
        self.status_code = status_code
        self.detail = detail


class CoreApi:
    def __init__(
        self,
        token: str,
        base_url: str = "http://core",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    @classmethod
    def for_app(cls, app) -> "CoreApi":
        return cls(token=app.state.token, transport=httpx.ASGITransport(app=app))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = response.text
            raise CoreApiError(response.status_code, detail)
        return response

    async def list_tasks(self) -> list[dict]:
        return (await self._request("GET", "/tasks")).json()

    async def find_task(self, task_id: str) -> dict | None:
        for row in await self.list_tasks():
            if row["id"] == task_id:
                return row
        return None

    async def get_task(self, project: str, task_id: str) -> dict:
        return (await self._request("GET", f"/tasks/{project}/{task_id}")).json()

    async def run_task(self, project: str, task_id: str) -> dict:
        return (
            await self._request("POST", f"/tasks/{project}/{task_id}/run", json={})
        ).json()

    async def cancel_task(self, project: str, task_id: str) -> dict:
        return (await self._request("POST", f"/tasks/{project}/{task_id}/cancel")).json()

    async def pause_task(self, project: str, task_id: str) -> dict:
        return (await self._request("POST", f"/tasks/{project}/{task_id}/pause")).json()

    async def get_budget(self) -> dict:
        return (await self._request("GET", "/budget")).json()

    async def update_budget(self, updates: dict[str, float | None]) -> dict:
        config = (await self._request("GET", "/config")).json()
        config["budget"] = {**config.get("budget", {}), **updates}
        return (await self._request("PUT", "/config", json=config)).json()
