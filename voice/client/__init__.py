"""voice/client/ — Minimal browser client for the Pipecat voice backend.

Two options are provided:

1. **Prebuilt SmallWebRTC client** (recommended for local dev)
   — Pipecat ships a CDN-hosted prebuilt page at
   ``https://unpkg.com/@pipecat-ai/small-webrtc@latest/dist/index.html``.
   Point your browser there and enter the bot's transport URL.

2. **Embedded client** (``index.html``)
   — Self-contained HTML that uses the Pipecat SmallWebRTC JS SDK from the
   CDN to open the mic, connect to the bot, and display call state.
   Drop this file next to your bot and open it directly in a browser.

Both options use P2P WebRTC — no server required between browser and bot.
"""
