# SDD Progress — feat/qoder-company

Plan: docs/QODER-COMPANY-PLAN.md

- Task T1: complete — QoderAdapter (receptionist/adapters/qoder.py) + registry + fixture + 17 tests pass; full suite 67 pass, no regressions. Fixture-first works; live mode written to documented SDK shape, needs `qodercli login` verification. Minor (deferred): live-mode double `done` event; `cancel()` sets `"cancelled"` status not awaited by `result()`.
- Task T3: complete — observer + summarizer + POST /api/company/run; 16 tests pass, suite 67 pass; route E2E-verified (28 card-ops, status done). Deferred: visible board rendering. Flags: new routes lack _check_auth; `board_update` not in signaling EVENT_TYPES.
- Task T3b: complete — company board view (company.html + company.js) + route auth + board_update event type.
  - `GET /company` returns 200; `GET /static/company.js` and `GET /static/call.css` return 200.
  - Auth: `_check_auth(request: Request)` applied to POST /api/company/run and GET /api/company.
  - `board_update` already in EVENT_TYPES (verified before start — no change needed in signaling.py).
  - WS frame check: 27 board_update frames (card_created ×4, card_moved ×4, edge_added ×3, card_updated ×12, card_done ×4) arrive live when WS client connects before POSTing a run.
  - 83 tests still green (no regressions).
  - Human-eyeball items: open http://localhost:8811/company in a real browser to verify rendered layout; test with CV_API_TOKEN set to confirm auth gate returns 401 without token.
- Task T2: pending — company/task mode registry + recruiter/reorg + profile loading.
- Task T4: pending — CS↔CEO dispatch + mode toggle UI.
- Task T5: pending (stretch) — marketplace import / auto-gen roles.
