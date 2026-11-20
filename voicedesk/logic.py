"""Conservative, deterministic receptionist intent logic; never claims to be an LLM."""
import re
import html

def classify(message):
    msg = re.sub(r"\s+", " ", str(message or "").strip()).lower()
    if not msg:
        return ("clarify", "Could you tell me whether you need an appointment, pricing information, business hours, or a callback?")
    rules = (
        ("human", r"\b(human|person|agent|staff|representative|manager|call\s?back|speak to)\b",
         "I can take your details for a staff callback. A team member will confirm availability."),
        ("booking", r"\b(book|appointment|schedule|reservation|visit|consultation|available slot)\b",
         "I can help request an appointment. The team will confirm the slot; no booking is confirmed until that happens."),
        ("pricing", r"\b(price|cost|fee|quote|insurance|payment|how much)\b",
         "Pricing depends on the service. I can forward your question to the team for an accurate quote."),
        ("hours", r"\b(hours?|open|close|weekend|when are you)\b",
         "The demo business lists Monday to Friday, 9 AM to 5 PM. Please verify hours before using this in production."),
        ("location", r"\b(where|address|location|direction|parking)\b",
         "I can ask the team to send accurate location and parking information."),
    )
    for intent, pattern, answer in rules:
        if re.search(pattern, msg):
            return intent, answer
    return "general", "Thanks for sharing. I can pass your request to the team, or help you request an appointment."

def xml_escape(value):
    return html.escape(str(value or ""), quote=True)
