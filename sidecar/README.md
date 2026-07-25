# Photon outbound sidecar

This small Node process is the outbound half of the Photon Spectrum transport.
It binds only to `127.0.0.1:8790`; the Python web process sends it a completed
task's already-established Spectrum space.

## Run

From this directory, with Node 20+ installed:

```bash
npm install
export PHOTON_PROJECT_ID=...
export PHOTON_PROJECT_SECRET=...
export PHOTON_SIDECAR_TOKEN="$(openssl rand -hex 32)"
npm start
```

Set only `PHOTON_SIDECAR_TOKEN` in the Python web-server environment; the
Photon project credentials can remain exclusive to this sidecar.  Optional:

```bash
export PHOTON_SIDECAR_URL=http://127.0.0.1:8790/send
export PHOTON_SIDECAR_PORT=8790
```

`PHOTON_SIGNING_SECRET` is also required by the Python process for inbound
webhook verification, but is not needed by this sidecar.  Do not commit any of
these values.  If the sidecar is absent or unreachable, completion delivery is
skipped without affecting the browser callback or task result.
