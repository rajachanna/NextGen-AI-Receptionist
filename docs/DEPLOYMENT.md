# VoiceDesk deployment and productization checklist

## Demo / GitHub Pages

The static files in web/ are safe to publish as a standalone browser showcase. The initial metrics and sample contacts are fictional. All additional demo data is stored in the visitor browser localStorage. Phone service, real AI, CRM, calendar, notifications and external storage are not activated.

Browser speech synthesis is optional and speech recognition depends on browser support and microphone permission. Some browsers may send recognition audio to their configured speech provider; no claim of on-device processing is made. Typed conversations always work.

## API

Run Python 3.10+ behind a TLS reverse proxy; keep Python bound to localhost. Set VOICEDESK_ADMIN_KEY (24+ random chars) through server secrets; the backend refuses protected endpoints otherwise. Configure BUSINESS_TIMEZONE with a valid IANA timezone. Set VOICEDESK_DB to a private persistent path. Never publish SQLite data or secrets.

Before production deploy: protect administrative endpoints with stronger authentication or VPN, authorization and access logs with privacy redaction; external rate limiting, replay/duplicate-call protection, graceful restarts, backups and restores, retention/deletion, user access controls, incident monitoring and an applicable privacy policy.

Booking requests are NOT integrated with a real Google or Microsoft Calendar. The local database only prevents internal duplicate time slots. Adapt hours, services, localization and scheduling rules for each real customer.

## Twilio inbound voice (optional, unconfigured)

Set TWILIO_AUTH_TOKEN as a protected server secret and PUBLIC_BASE_URL to the exact externally requested HTTPS origin, e.g. https://voice.example.com. Point the Twilio phone number voice webhook at https://voice.example.com/twilio/voice using POST. The backend verifies X-Twilio-Signature for the full URL and sorted POST parameters.

The voice webhook asks for a caller's reason (via Twilio Gather input=speech), classifies the response, and stores the caller's phone and message as a follow-up lead. It does not book appointments, transfer calls to staff or conduct multi-turn LLM conversations.

Add business-specific consent and privacy notices before collecting call speech and personal data. Implement CallSid idempotency to avoid repeated leads on Twilio retries; implement actual human escalation, language handling, diagnostics, non-business-hours paths and phone-number provisioning.

## Real AI model addition

The code deliberately defaults to a deterministic safety fallback. For an LLM assistant, add provider configuration, business source-of-truth knowledge base, constrained tools for appointments, appropriate system prompts, redaction/PII handling, explicit human escalation, hallucination/failure controls, evaluation scripts, token spending limits and timeouts. Test with the target business before enabling live customer conversations.

## CI and delivery

Run Python tests with:

    python3 -m unittest discover -s tests -v

Run JavaScript syntax validation with:

    node --check web/app.js

No third-party pip packages are required by the demo backend. GitHub Actions validates code and deploys the web/ folder to GitHub Pages once Pages is configured to GitHub Actions.
