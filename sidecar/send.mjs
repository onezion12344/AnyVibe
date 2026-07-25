/**
 * Loopback-only Spectrum sender for coding-vibe.
 *
 * The Python web process never receives Photon project credentials.  It sends
 * already-established conversation spaces to this local process, which owns
 * the official Spectrum SDK and refuses all unauthenticated requests.
 */

import crypto from "node:crypto";
import http from "node:http";

import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { telegram } from "spectrum-ts/providers/telegram";

const projectId = process.env.PHOTON_PROJECT_ID || "";
const projectSecret = process.env.PHOTON_PROJECT_SECRET || "";
const sidecarToken = process.env.PHOTON_SIDECAR_TOKEN || "";
const requestedPort = Number(process.env.PHOTON_SIDECAR_PORT || "8790");
const port = Number.isInteger(requestedPort) && requestedPort > 0 && requestedPort < 65536
  ? requestedPort
  : 8790;
const maxBodyBytes = 64 * 1024;

if (!projectId || !projectSecret || !sidecarToken) {
  throw new Error(
    "PHOTON_PROJECT_ID, PHOTON_PROJECT_SECRET, and PHOTON_SIDECAR_TOKEN are required",
  );
}

const spectrum = await Spectrum({
  projectId,
  projectSecret,
  providers: [imessage.config(), telegram.config()],
});

function constantTimeTokenMatches(value) {
  if (typeof value !== "string") return false;
  const received = Buffer.from(value, "utf8");
  const expected = Buffer.from(sidecarToken, "utf8");
  return received.length === expected.length && crypto.timingSafeEqual(received, expected);
}

function writeJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > maxBodyBytes) {
      const error = new Error("payload too large");
      error.statusCode = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

const server = http.createServer(async (req, res) => {
  if (req.method !== "POST" || req.url !== "/send") {
    writeJson(res, 404, { error: "not found" });
    return;
  }
  if (!constantTimeTokenMatches(req.headers["x-photon-sidecar-token"])) {
    writeJson(res, 401, { error: "unauthorized" });
    return;
  }

  try {
    const body = JSON.parse(await readBody(req));
    if (
      !body ||
      typeof body !== "object" ||
      Array.isArray(body) ||
      !body.space ||
      typeof body.space !== "object" ||
      Array.isArray(body.space) ||
      typeof body.text !== "string" ||
      !body.text.trim() ||
      body.text.length > 2000
    ) {
      writeJson(res, 400, { error: "invalid payload" });
      return;
    }
    await spectrum.send(body.space, body.text.trim());
    writeJson(res, 200, { ok: true });
  } catch (error) {
    const status = Number.isInteger(error?.statusCode) ? error.statusCode : 502;
    // Never put an SDK credential or stack trace into a locally observable
    // response.  The Python caller only needs a delivery boolean.
    writeJson(res, status, { error: status === 413 ? "payload too large" : "send failed" });
  }
});

// Do not make this configurable: binding to all interfaces would turn a local
// credentialed transport into a network message relay.
server.listen(port, "127.0.0.1", () => {
  console.log(`[photon-sidecar] listening on http://127.0.0.1:${port}/send`);
});
