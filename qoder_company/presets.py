"""Company profiles and reusable employee-team presets.

Company and team are deliberately separate:

* A **company preset** establishes the CEO's operating contract and a sensible
  default crew.
* An **employee-team preset** establishes the specialist roster the CEO may
  delegate to.

The shared Yellow Sheep receptionist reads the active pair at handoff time, so
changing either selector affects the next task without creating a second CS.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _role(label: str, description: str, prompt: str) -> dict[str, str]:
    return {"label": label, "description": description, "prompt": prompt}


COMPANY_PRESETS: dict[str, dict[str, Any]] = {
    "rapid-startup": {
        "id": "rapid-startup",
        "name": "Rapid Startup",
        "tagline": "A product company that ships the smallest useful release.",
        "type": "Product startup",
        "default_team_preset_id": "lean-product",
        "ceo_prompt": (
            "You are the CEO of a lean product startup. Turn the user's request into "
            "a small, testable delivery plan. Delegate concrete work to the selected "
            "employee team, keep scopes non-overlapping, then integrate and verify the "
            "result yourself. Do actual work in the repository; do not merely describe "
            "a plan. Report only factual progress, changed files, and checks run."
        ),
    },
    "product-polish": {
        "id": "product-polish",
        "name": "Product Polish Studio",
        "tagline": "A design-led company focused on clarity and interaction quality.",
        "type": "Design-led product studio",
        "default_team_preset_id": "experience-crew",
        "ceo_prompt": (
            "You are the CEO of a design-led product studio. Translate the brief into "
            "clear user outcomes, delegate to the selected employee team, then verify "
            "the finished interface for usability and accessibility. Do the work in the "
            "repository rather than stopping at a proposal. Keep changes cohesive and "
            "report only facts that you verified."
        ),
    },
    "reliability-team": {
        "id": "reliability-team",
        "name": "Reliability Engineering",
        "tagline": "A platform company for safe, observable, maintainable systems.",
        "type": "Platform and reliability team",
        "default_team_preset_id": "reliability-crew",
        "ceo_prompt": (
            "You are the CEO of a reliability engineering company. Scope changes "
            "conservatively, delegate architecture, implementation, operations, and "
            "verification work to the selected employee team, and require evidence for "
            "claims about correctness. Implement and test the requested improvement in "
            "the repository; do not substitute a written plan for work."
        ),
    },
}


TEAM_PRESETS: dict[str, dict[str, Any]] = {
    "lean-product": {
        "id": "lean-product",
        "name": "Lean Product Crew",
        "tagline": "Research, build, and release a focused product slice.",
        "roles": {
            "researcher": _role(
                "Product Researcher",
                "Clarifies scope, acceptance criteria, and the smallest useful release.",
                "Convert the request into concise acceptance criteria and identify risks. "
                "Do not implement code unless asked by the CEO.",
            ),
            "full_stack": _role(
                "Full-stack Builder",
                "Implements product logic, integrations, and responsive interfaces.",
                "Implement the required application work end to end. Reuse project patterns, "
                "avoid unnecessary dependencies, and run focused checks.",
            ),
            "qa": _role(
                "QA & Release",
                "Verifies behavior, regressions, and edge cases before handoff.",
                "Exercise the relevant paths and report specific pass/fail evidence. "
                "Do not claim validation that was not run.",
            ),
        },
    },
    "experience-crew": {
        "id": "experience-crew",
        "name": "Experience Crew",
        "tagline": "Shape a clear, accessible, and polished product experience.",
        "roles": {
            "ux": _role(
                "UX Lead",
                "Defines interaction hierarchy, content clarity, and accessible UX.",
                "Review the requested experience, propose concrete interaction details, "
                "and give the CEO implementable guidance.",
            ),
            "frontend": _role(
                "Frontend Craftsperson",
                "Builds high-quality responsive UI and interaction details.",
                "Implement semantic, responsive, keyboard-accessible UI work. Keep the "
                "visual system coherent and report files plus checks run.",
            ),
            "qa": _role(
                "Journey QA",
                "Tests user journeys, visual regressions, and accessibility basics.",
                "Run focused UI and behavior checks, including keyboard and small-screen "
                "paths when relevant. Report reproducible evidence.",
            ),
        },
    },
    "reliability-crew": {
        "id": "reliability-crew",
        "name": "Reliability Crew",
        "tagline": "Harden systems through architecture, operations, and verification.",
        "roles": {
            "architect": _role(
                "Systems Architect",
                "Finds safe design boundaries and migration risks.",
                "Assess the existing architecture, identify the smallest safe design, and "
                "give the CEO clear implementation constraints and failure modes.",
            ),
            "backend": _role(
                "Backend Reliability Engineer",
                "Implements APIs, persistence, and correctness-focused service changes.",
                "Implement reliable backend changes with clear error handling, compatibility, "
                "and focused tests.",
            ),
            "devops": _role(
                "Operations Engineer",
                "Owns runtime configuration, deployment safety, and observability.",
                "Review runtime and deployment implications, improve operational safety where "
                "in scope, and never expose secrets in output.",
            ),
            "qa": _role(
                "Failure-mode QA",
                "Runs regression, failure-mode, and acceptance verification.",
                "Exercise the relevant success and failure paths. Give concrete pass/fail "
                "evidence and concise remaining risks.",
            ),
        },
    },
}

DEFAULT_COMPANY_PRESET_ID = "rapid-startup"
DEFAULT_TEAM_PRESET_ID = COMPANY_PRESETS[DEFAULT_COMPANY_PRESET_ID]["default_team_preset_id"]


def get_company_preset(preset_id: str) -> dict[str, Any]:
    """Return a defensive copy of a company profile or raise ``KeyError``."""
    return deepcopy(COMPANY_PRESETS[preset_id])


def get_team_preset(preset_id: str) -> dict[str, Any]:
    """Return a defensive copy of an employee-team preset or raise ``KeyError``."""
    return deepcopy(TEAM_PRESETS[preset_id])


def get_preset(preset_id: str) -> dict[str, Any]:
    """Backward-compatible alias for callers that used company presets before."""
    return get_company_preset(preset_id)


def list_company_presets() -> list[dict[str, Any]]:
    """Return public, prompt-free company summaries suitable for the dashboard."""
    return [
        {
            "id": preset["id"],
            "name": preset["name"],
            "tagline": preset["tagline"],
            "type": preset["type"],
            "default_team_preset_id": preset["default_team_preset_id"],
        }
        for preset in COMPANY_PRESETS.values()
    ]


def list_team_presets() -> list[dict[str, Any]]:
    """Return public employee-team summaries without their internal prompts."""
    return [
        {
            "id": preset["id"],
            "name": preset["name"],
            "tagline": preset["tagline"],
            "roles": [
                {
                    "id": role_id,
                    "label": role["label"],
                    "description": role["description"],
                }
                for role_id, role in preset["roles"].items()
            ],
        }
        for preset in TEAM_PRESETS.values()
    ]


def list_presets() -> list[dict[str, Any]]:
    """Backward-compatible company-only listing for older dashboard clients."""
    return list_company_presets()


def build_ceo_prompt(company: dict[str, Any], team: dict[str, Any]) -> str:
    """Combine the selected company contract and employee roster for the CEO."""
    roster = "\n".join(
        f"- {role_id} ({role['label']}): {role['description']}"
        for role_id, role in team["roles"].items()
    )
    return (
        f"{company['ceo_prompt']}\n\n"
        f"The active employee preset is {team['name']}. Delegate only to these "
        f"available specialist roles:\n{roster}"
    )
