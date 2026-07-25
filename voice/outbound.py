"""voice/outbound.py — place an outbound Twilio call that bridges to StepFun.

Dials TO_NUMBER from FROM_NUMBER and hands the media stream to the StepFun
Realtime bridge via inline TwiML (<Connect><Stream url=PUBLIC_WSS/>).

Requirements:
  * ``pip install twilio "requests[socks]"``
  * HTTPS_PROXY must point at a working SOCKS5 proxy so the Twilio REST call can
    egress (defaulted below to socks5h://127.0.0.1:1080). The "requests[socks]"
    extra installs PySocks, which is what lets requests speak socks5h://.

Environment:
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, TWILIO_TO_VERIFIED,
  CV_PUBLIC_WSS (public wss:// URL of the /twilio-stream endpoint).
"""

import os
from twilio.rest import Client

os.environ.setdefault("HTTPS_PROXY", "socks5h://127.0.0.1:1080")

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN", "")
FROM_NUMBER = os.environ.get("TWILIO_FROM", "")
TO_NUMBER   = os.environ.get("TWILIO_TO_VERIFIED", "")
PUBLIC_WSS  = os.environ.get("CV_PUBLIC_WSS", "wss://twilio.onezion.top/twilio-stream")

def call_me_back() -> str:
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    twiml = f'<Response><Connect><Stream url="{PUBLIC_WSS}" /></Connect></Response>'
    call = client.calls.create(to=TO_NUMBER, from_=FROM_NUMBER, twiml=twiml)
    print(f"[outbound] dialing {TO_NUMBER}, callSid={call.sid}")
    return call.sid

if __name__ == "__main__":
    call_me_back()
