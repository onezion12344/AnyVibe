from __future__ import annotations

import json

from qoder_company import company_state


def test_active_company_context_uses_preset_and_persists_per_company_avatar(tmp_path, monkeypatch):
    state_file = tmp_path / "state" / "company.json"
    monkeypatch.setenv("CV_COMPANY_STATE_FILE", str(state_file))

    default = company_state.get_active_company()
    assert default["preset_id"] == "rapid-startup"

    startup = company_state.activate_preset("rapid-startup")
    company_state.update_active_avatar("/api/company/avatar/startup.png")
    polish = company_state.activate_preset("product-polish")
    context = company_state.active_dispatch_context()

    assert polish["id"] == "product-polish"
    assert context["backend"] == "qoder"
    assert context["persistent_cli"] is True
    assert context["permission_mode"] == "accept_edits"
    assert set(context["roles"]) == {"ux", "frontend", "qa"}
    assert "design-led product studio" in context["ceo_prompt"]

    # Switching back reuses the original company/session, including its avatar.
    returned = company_state.activate_preset("rapid-startup")
    assert returned["avatar"] == "/api/company/avatar/startup.png"
    assert returned["qoder_session_id"] == startup["qoder_session_id"]
    assert len(returned["qoder_session_id"]) == 36

    public = company_state.public_company_state()
    assert public["active"]["preset_id"] == "rapid-startup"
    assert "ceo_prompt" not in public["active"]
    assert {preset["id"] for preset in public["presets"]} == {
        "rapid-startup", "product-polish", "reliability-team"
    }
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["active_company_id"] == "rapid-startup"
