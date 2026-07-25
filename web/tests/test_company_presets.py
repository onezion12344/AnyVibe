from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from web.qoder_company_routes import router


@pytest.fixture
def company_app(tmp_path, monkeypatch):
    monkeypatch.setenv("CV_COMPANY_STATE_FILE", str(tmp_path / "company.json"))
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_company_preset_api_switches_the_active_execution_team(company_app):
    transport = httpx.ASGITransport(app=company_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        initial = await client.get("/api/company/active")
        assert initial.status_code == 200
        assert initial.json()["active"]["preset_id"] == "rapid-startup"

        switched = await client.put("/api/company/active", json={"preset_id": "reliability-team"})
        assert switched.status_code == 200
        data = switched.json()
        assert data["active"]["preset_id"] == "reliability-team"
        assert set(data["active"]["roles"]) == {"architect", "backend", "devops", "qa"}

        board = await client.get("/api/company")
        assert board.status_code == 200
        assert board.json()["company"]["active"]["preset_id"] == "reliability-team"


@pytest.mark.asyncio
async def test_fixture_run_observes_the_active_preset_team(company_app):
    fixture = Path(__file__).resolve().parents[2] / "receptionist" / "adapters" / "fixtures" / "qoder_company_demo.jsonl"
    transport = httpx.ASGITransport(app=company_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.put("/api/company/active", json={"preset_id": "product-polish"})
        response = await client.post(
            "/api/company/run",
            json={"run_id": "preset-fixture-run", "fixture_path": str(fixture), "use_cli": False},
        )
        assert response.status_code == 200
        assert response.json()["company_id"] == "product-polish"
        assert response.json()["fixture_mode"] is True

        for _ in range(30):
            await asyncio.sleep(0.1)
            status = await client.get("/api/company", params={"run_id": "preset-fixture-run"})
            if status.json().get("status") == "done":
                break
        payload = status.json()
        assert payload["status"] == "done"
        assert payload["company"]["active"]["preset_id"] == "product-polish"
        assert payload["network"]["nodes"]
