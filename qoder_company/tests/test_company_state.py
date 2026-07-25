from __future__ import annotations

import json

from qoder_company import company_state


def test_company_and_employee_presets_switch_independently_and_persist(tmp_path, monkeypatch):
    state_file = tmp_path / "state" / "company.json"
    monkeypatch.setenv("CV_COMPANY_STATE_FILE", str(state_file))

    default = company_state.get_active_company()
    assert default["company_preset_id"] == "rapid-startup"
    assert default["team_preset_id"] == "lean-product"

    startup = company_state.activate_company_preset("rapid-startup")
    company_state.update_active_avatar("/api/company/avatar/startup.png")
    company_state.select_team_preset("reliability-crew")
    startup_context = company_state.active_dispatch_context()
    assert startup_context["team_preset_id"] == "reliability-crew"
    assert set(startup_context["roles"]) == {"architect", "backend", "devops", "qa"}

    polish = company_state.activate_company_preset("product-polish")
    context = company_state.active_dispatch_context()

    assert polish["id"] == "product-polish"
    assert polish["team_preset_id"] == "experience-crew"
    assert context["backend"] == "qoder"
    assert context["persistent_cli"] is True
    assert context["permission_mode"] == "accept_edits"
    assert set(context["roles"]) == {"ux", "frontend", "qa"}
    assert "design-led product studio" in context["ceo_prompt"]

    # Switching back reuses the original company/session, including its avatar.
    returned = company_state.activate_company_preset("rapid-startup")
    assert returned["avatar"] == "/api/company/avatar/startup.png"
    assert returned["qoder_session_id"] == startup["qoder_session_id"]
    assert returned["team_preset_id"] == "reliability-crew"
    assert len(returned["qoder_session_id"]) == 36

    public = company_state.public_company_state()
    assert public["active"]["preset_id"] == "rapid-startup"
    assert public["active"]["team_preset_id"] == "reliability-crew"
    assert "ceo_prompt" not in public["active"]
    assert {preset["id"] for preset in public["company_presets"]} == {
        "rapid-startup", "product-polish", "reliability-team"
    }
    assert {preset["id"] for preset in public["team_presets"]} == {
        "lean-product", "experience-crew", "reliability-crew"
    }
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["active_company_id"] == "rapid-startup"


def test_legacy_one_layer_state_migrates_to_company_and_default_team(tmp_path, monkeypatch):
    state_file = tmp_path / "company.json"
    monkeypatch.setenv("CV_COMPANY_STATE_FILE", str(state_file))
    state_file.write_text(
        json.dumps(
            {
                "active_company_id": "product-polish",
                "companies": {
                    "product-polish": {
                        "id": "product-polish",
                        "preset_id": "product-polish",
                        "avatar": "/saved.png",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    company = company_state.get_active_company()
    assert company["company_preset_id"] == "product-polish"
    assert company["team_preset_id"] == "experience-crew"
    assert company["avatar"] == "/saved.png"
