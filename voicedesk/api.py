"""Small-footprint secure admin API and optional validated Twilio webhook receiver.

Run behind TLS for any external access. Admin endpoints are disabled without a secret.
Public demo frontend never transmits data to this API automatically.
"""
import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

from .logic import classify
from .store import Store, ValidationError, ConflictError

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
STATIC_FILES = {"/": "index.html", "/index.html": "index.html",
                "/app.js": "app.js", "/styles.css": "styles.css"}
MAX_REQUEST = 8192

def twilio_valid(signature, url, params, token):
    """Twilio form-encoded request signature (URL + sorted name/value pairs)."""
    if not signature or not token or not url.startswith("https://"):
        return False
    raw = url + "".join(k + params[k] for k in sorted(params))
    expect = base64.b64encode(hmac.new(token.encode("utf-8"), raw.encode("utf-8"), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expect, signature)

def twiml_intro():
    root = Element("Response")
    gather = SubElement(root, "Gather", input="speech", action="/twilio/collect",
                        method="POST", timeout="6", speechTimeout="auto")
    SubElement(gather, "Say").text = ("Hello. This is the automated receptionist for our demo business. "
       "You can ask about appointments, pricing, or opening hours, or request a human callback. "
       "What can I help you with?")
    SubElement(root, "Say").text = "Sorry I didn't hear anything. Please try calling again. Goodbye."
    return tostring(root, encoding="unicode")

def twiml_reply(intent, answer):
    root = Element("Response")
    SubElement(root, "Say").text = answer
    if intent != "hours":
        SubElement(root, "Say").text = "Your message was noted for staff follow-up. Goodbye."
    return tostring(root, encoding="unicode")

def make_handler(store, admin_key="", twilio_token="", public_base_url=""):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VoiceDesk/1.0"

        def log_message(self, fmt, *args):
            # Avoid logging query strings or caller PII.
            pass

        def send(self, status, content, mime="application/json; charset=utf-8"):
            payload = content if isinstance(content, bytes) else content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def respond(self, status, data):
            self.send(status, json.dumps(data, ensure_ascii=False))

        def fail(self, status, message):
            self.respond(status, {"error":message})

        def admin_authorized(self):
            if not admin_key or len(admin_key) < 24:
                self.fail(503, "Admin API is not configured")
                return False
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + admin_key):
                self.fail(401, "Unauthorized")
                return False
            return True

        def body(self, content_type):
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                raise ValidationError("Invalid Content-Length")
            if size < 0 or size > MAX_REQUEST:
                raise ValidationError("Payload size out of bounds")
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != content_type:
                raise ValidationError("Unsupported Content-Type")
            return self.rfile.read(size)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/health":
                self.respond(200, {"status":"ok", "product":"NextGen VoiceDesk",
                                  "assistant_mode":"rules", "telephony_enabled":bool(twilio_token and public_base_url)})
                return
            if path in ("/api/leads", "/api/appointments", "/api/summary"):
                if not self.admin_authorized():
                    return
                if path == "/api/leads":
                    self.respond(200, {"items":store.list_leads()})
                elif path == "/api/appointments":
                    self.respond(200, {"items":store.list_appointments()})
                else:
                    self.respond(200, store.summary())
                return
            if path in STATIC_FILES:
                file = WEB_ROOT / STATIC_FILES[path]
                if not file.is_file():
                    self.fail(404, "Not found")
                    return
                kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                self.send(200, file.read_bytes(), kind + "; charset=utf-8")
                return
            self.fail(404, "Not found")

        def do_POST(self):
            path = urlsplit(self.path).path
            if path.startswith("/twilio/"):
                self.twilio(path)
                return
            if path not in ("/api/leads", "/api/appointments", "/api/message"):
                self.fail(404, "Not found")
                return
            if not self.admin_authorized():
                return
            try:
                data = json.loads(self.body("application/json"))
                if not isinstance(data, dict):
                    raise ValidationError("JSON object expected")
                if path == "/api/leads":
                    self.respond(201, store.create_lead(data))
                elif path == "/api/appointments":
                    self.respond(201, store.create_appointment(data))
                elif path == "/api/message":
                    message = data.get("message", "")
                    if not isinstance(message, str) or len(message) > 1000:
                        raise ValidationError("message must be text (max 1000 chars)")
                    intent, answer = classify(message)
                    self.respond(200, {"intent":intent,"answer":answer,
                                       "mode":"rules","booking_confirmed":False})
            except ConflictError as exc:
                self.fail(409, str(exc))
            except (ValidationError, json.JSONDecodeError) as exc:
                self.fail(400, str(exc))
            except (BrokenPipeError, ConnectionResetError):
                pass

        def twilio(self, path):
            if path not in ("/twilio/voice", "/twilio/collect"):
                self.fail(404, "Not found")
                return
            if not twilio_token or not public_base_url or not public_base_url.startswith("https://"):
                self.fail(503, "Telephony integration is not configured")
                return
            try:
                payload = self.body("application/x-www-form-urlencoded")
                form = parse_qs(payload.decode("utf-8"), keep_blank_values=True)
                if any(len(values) != 1 for values in form.values()):
                    raise ValidationError("Duplicate fields")
                params = {k: v[0] for k, v in form.items()}
                exact_url = public_base_url.rstrip("/") + self.path
                if not twilio_valid(self.headers.get("X-Twilio-Signature", ""), exact_url, params, twilio_token):
                    self.fail(403, "Invalid signature")
                    return
                if path == "/twilio/voice":
                    self.send(200, twiml_intro(), "application/xml; charset=utf-8")
                    return
                speech = str(params.get("SpeechResult", "")).strip()[:1000]
                caller = str(params.get("From", "")).strip()[:50]
                sid = str(params.get("CallSid", "")).strip()[:70]
                if not speech:
                    answer = "Sorry, I did not catch that. Please call again or contact the team directly."
                    self.send(200, twiml_reply("clarify", answer), "application/xml; charset=utf-8")
                    return
                intent, answer = classify(speech)
                # Do not record caller ID-less requests as actionable leads.
                if caller and sid:
                    store.create_lead({"name":"Caller follow-up","contact":caller,
                                       "interest":intent,"source":"twilio",
                                       "notes":"Speech request: " + speech[:600]})
                self.send(200, twiml_reply(intent, answer), "application/xml; charset=utf-8")
            except ValidationError as exc:
                self.fail(400, str(exc))
            except UnicodeDecodeError:
                self.fail(400, "Malformed form")

    return Handler

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST","127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT","8974")))
    parser.add_argument("--db", default=os.environ.get("VOICEDESK_DB","./data/voicedesk.sqlite3"))
    parser.add_argument("--timezone", default=os.environ.get("BUSINESS_TIMEZONE","UTC"))
    args = parser.parse_args()
    store = Store(args.db, args.timezone)
    handler = make_handler(store,
        admin_key=os.environ.get("VOICEDESK_ADMIN_KEY",""),
        twilio_token=os.environ.get("TWILIO_AUTH_TOKEN",""),
        public_base_url=os.environ.get("PUBLIC_BASE_URL",""))
    httpd = ThreadingHTTPServer((args.host,args.port), handler)
    print("NextGen VoiceDesk listening on http://%s:%d (mode: rules)"%(args.host,args.port),flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()

if __name__ == "__main__":
    run()
