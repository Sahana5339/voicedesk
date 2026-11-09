"""
VoiceDesk core: turns a complaint transcript into a structured, triaged ticket.

Rule-based on purpose (fast, explainable, no extra model needed). Covers English, Hinglish (Latin),
Hindi (Devanagari) and Kannada script. Other languages are still transcribed, but classified as "Other".

Run the built-in evaluation:   python core.py --eval test_complaints.csv
Run all logic tests:           python core.py --selftest
"""
import csv
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime

# ------------------------------------------------------------------ categories & keywords
CATS = ["Fraud / Unauthorised transaction", "Safety hazard", "Billing / Payment", "Refund / Return",
        "Product defect", "Delivery / Order", "Network / Service", "Account / Login",
        "Staff behaviour", "Other"]
CRITICAL_CATS = {CATS[0], CATS[1]}
TIE_ORDER = {c: i for i, c in enumerate(CATS)}  # on equal score, the earlier category wins

KW = {
    CATS[0]: [  # fraud: weight 3
        "fraud", "scam", "unauthori", "hacked", "hack", "phishing", "stolen", "without my permission",
        "without permission", "bina permission", "bina anumati", "not me who", "i did not make", "didn't make",
        "chori", "dhokha", "thagi", "otp share", "बिना अनुमति", "धोखा", "धोखाधड़ी", "फ्रॉड", "हैक", "चोरी",
        "ठगी", "अनधिकृत", "ವಂಚನೆ", "ಮೋಸ", "ಹ್ಯಾಕ್", "ಕದ್ದ", "ಅನಧಿಕೃತ", "ಅನುಮತಿ ಇಲ್ಲದೆ"],
    CATS[1]: [  # safety: weight 3
        "fire", "spark", "smoke", "shock", "burn", "gas leak", "explod", "blast", "injur", "hospital",
        "emergency", "आग", "चिंगारी", "करंट", "धुआं", "धुँआ", "जल गया", "ಬೆಂಕಿ", "ಹೊಗೆ", "ಶಾಕ್", "ಸ್ಪಾರ್ಕ್"],
    CATS[2]: [
        "bill", "charged", "overcharg", "charge", "deducted", "debited", "payment", "invoice", "amount",
        "extra money", "kat gaya", "kat gaye", "paisa kat", "paise kat", "बिल", "पेमेंट", "भुगतान", "कट गया",
        "कट गए", "कटे", "चार्ज", "ಬಿಲ್", "ಪಾವತಿ", "ಹಣ ಕಡಿತ", "ಚಾರ್ಜ್", "ಹೆಚ್ಚುವರಿ"],
    CATS[3]: [
        "refund", "return", "money back", "replace", "cancel", "paisa wapas", "paise wapas", "wapas karo",
        "रिफंड", "वापसी", "रिटर्न", "रद्द", "पैसे वापस", "पैसा वापस", "ರಿಫಂಡ್", "ವಾಪಸ್", "ಹಿಂತಿರುಗಿ", "ರದ್ದು"],
    CATS[4]: [
        "broken", "damaged", "defect", "faulty", "stopped working", "not working properly", "kharab",
        "tuta", "toot", "खराब", "टूटा", "टूट", "डैमेज", "खराबी", "ದೋಷ", "ಹಾಳಾ", "ಮುರಿ"],
    CATS[5]: [
        "deliver", "order", "parcel", "courier", "package", "shipment", "tracking", "not received",
        "nahi mila", "nahi aaya", "deri", "delay", "ऑर्डर", "डिलीवरी", "पार्सल", "नहीं मिला", "नहीं आया",
        "देरी", "ಆರ್ಡರ್", "ಡೆಲಿವರಿ", "ಪಾರ್ಸೆಲ್", "ಬಂದಿಲ್ಲ", "ತಡ"],
    CATS[6]: [
        "network", "signal", "internet", "wifi", "wi-fi", "broadband", "no service", "outage", "call drop",
        "slow speed", "re:\\bnet\\b", "नेटवर्क", "सिग्नल", "इंटरनेट", "re:(?<!\\w)नेट(?!\\w)", "ನೆಟ್ವರ್ಕ್",
        "ಸಿಗ್ನಲ್", "ಇಂಟರ್ನೆಟ್"],
    CATS[7]: [
        "login", "log in", "password", "account blocked", "locked", "otp not", "otp nahi", "kyc",
        "लॉगिन", "पासवर्ड", "ओटीपी", "ಲಾಗಿನ್", "ಪಾಸ್ವರ್ಡ್", "ಒಟಿಪಿ", "ಖಾತೆ ಬ್ಲಾಕ್"],
    CATS[8]: [  # staff: rude/behaviour weight 2
        "rude", "behaviour", "behavior", "misbehav", "badtameez", "बदतमीज", "व्यवहार", "ಅಸಭ್ಯ", "ವರ್ತನೆ",
        "ವರ್ತಿಸ", "customer care", "staff", "agent", "nobody", "no one", "स्टाफ", "कस्टमर केयर", "ಸಿಬ್ಬಂದಿ"],
}
WEIGHT_OVERRIDE = {
    CATS[0]: 3, CATS[1]: 3,
}
HEAVY_WORDS = {  # individually stronger words
    "refund": 2, "रिफंड": 2, "ರಿಫಂಡ್": 2, "rude": 2, "behaviour": 2, "behavior": 2, "misbehav": 3,
    "badtameez": 2, "बदतमीज": 2, "व्यवहार": 2, "ಅಸಭ್ಯ": 2, "ವರ್ತನೆ": 2, "ವರ್ತಿಸ": 2, "account blocked": 2,
}

FRUSTRATED = ["frustrat", "angry", "worst", "pathetic", "fed up", "terrible", "harass", "third time",
              "again and again", "many times", "no response", "baar baar", "pareshan", "tang aa", "bakwas",
              "bekaar", "gussa", "परेशान", "बार बार", "बकवास", "तंग", "गुस्सा", "बेकार", "ಬೇಸರ", "ಕೋಪ",
              "ಪದೇ ಪದೇ", "ತೊಂದರೆ"]
URGENT = ["urgent", "asap", "immediately", "right now", "jaldi", "turant", "legal action", "consumer court",
          "police", "जल्दी", "तुरंत", "तत्काल", "ಬೇಗ", "ತುರ್ತು", "ತಕ್ಷಣ"]
LOW = ["suggestion", "feedback", "just wanted to know", "enquiry", "inquiry", "sujhav", "सुझाव", "ಸಲಹೆ"]
TWICE = ["twice", "double", "do baar", "dobara", "दो बार", "दोबारा", "ಎರಡು ಬಾರಿ"]

NW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
      "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "saat": 7,
      "aath": 8, "nau": 9, "das": 10,
      "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8,
      "नौ": 9, "दस": 10,
      "ಒಂದು": 1, "ಎರಡು": 2, "ಮೂರು": 3, "ನಾಲ್ಕು": 4, "ಐದು": 5, "ಆರು": 6, "ಏಳು": 7, "ಎಂಟು": 8,
      "ಒಂಬತ್ತು": 9, "ಹತ್ತು": 10}

# ------------------------------------------------------------------ text helpers
_DIGITS = str.maketrans("०१२३४५६७८९೦೧೨೩೪೫೬೭೮೯౦౧౨౩౪౫౬౭౮౯",
                        "012345678901234567890123456789")


def norm(s):
    s = unicodedata.normalize("NFC", s).lower()
    s = s.translate(_DIGITS)
    for ch in ("\u200c", "\u200d", "\u093c"):
        s = s.replace(ch, "")
    return re.sub(r"\s+", " ", s).strip()


def _compile(kw):
    if kw.startswith("re:"):
        return re.compile(kw[3:])
    return re.compile(r"(?<!\w)" + re.escape(norm(kw)))


_RX = {c: [(k, _compile(k)) for k in kws] for c, kws in KW.items()}


def _any(words, t):
    return [w for w in words if re.search(r"(?<!\w)" + re.escape(norm(w)), t)]


def script_lang(text):
    """Best guess of language from the writing system."""
    for lo, hi, code in ((0x0900, 0x097F, "hi"), (0x0C80, 0x0CFF, "kn"), (0x0B80, 0x0BFF, "ta"),
                         (0x0C00, 0x0C7F, "te"), (0x0980, 0x09FF, "bn"), (0x0D00, 0x0D7F, "ml"),
                         (0x0A80, 0x0AFF, "gu"), (0x0A00, 0x0A7F, "pa")):
        if any(lo <= ord(ch) <= hi for ch in text):
            return code
    return "en"


# ------------------------------------------------------------------ entity extraction + PII masking
_NUMW = "|".join(sorted((re.escape(norm(w)) for w in NW), key=len, reverse=True))
_DAYS = re.compile(r"(?<!\w)(\d+|" + _NUMW + r")\s*-?\s*(days?|din|दिन|ದಿನ|hafte|hafta|weeks?|हफ्ते|हफ्ता|ವಾರ)")
_AMT1 = re.compile(r"(?:₹|(?<!\w)rs\.?|inr|rupees?|rupaye|rupay|रुपये|रुपए|रुपया|ರೂಪಾಯಿ|ರೂ\.?)\s*([\d,]+(?:\.\d+)?)")
_AMT2 = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:₹|(?<!\w)rs(?!\w)|rupees?|rupaye|rupay|रुपये|रुपए|रुपया|ರೂಪಾಯಿ|ರೂ)")
_ORDER = re.compile(
    r"(?:order|ऑర్డర్|ಆರ್ಡರ್|ఆర్డర్|booking)\s*(?:no\.?|number|num|id|नंबर|संख्या|ಸಂಖ್ಯೆ)?"
    r"\s*(?:is\s+|[:#-]\s*)?([a-z]{0,3}\d{4,12})"
)
_CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)")


def extract_days(t):
    m = _DAYS.search(t)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else NW.get(m.group(1))
    if n is None:
        n = next((v for k, v in NW.items() if norm(k) == m.group(1)), None)
    if n is None:
        return None
    return n * 7 if m.group(2).startswith(("hafte", "hafta", "week", "हफ्त", "ವಾರ")) else n


def extract_amount(t):
    m = _AMT1.search(t) or _AMT2.search(t)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(v) if v == int(v) else v


def extract_order(t):
    t = norm(t)
    m = _ORDER.search(t)
    if m:
        return m.group(1).upper()
    context = re.search(
        r"(?:order|ऑर्डर|ಆರ್ಡರ್|ఆర్డర్|booking)\s*(?:no\.?|number|num|id|नंबर|संख्या|ಸಂಖ್ಯೆ)?"
        r"\s*(?:is\s+|[:#-]\s*)?(.{1,80})",
        t,
    )
    if context:
        numeric_id = re.search(r"(?<!\d)([a-z]{0,3}\d{4,12})(?!\d)", context.group(1))
        if numeric_id:
            return numeric_id.group(1).upper()
        digits = words_to_digits(context.group(1))
        if digits:
            return digits
    delivery_context = re.search(
        r"\b(order|parcel|package|delivery|delivered|courier|shipment|tracking|"
        r"ऑर्डर|पार्सल|डिलीवरी|ಆರ್ಡರ್|ಪಾರ್ಸೆಲ್|ಡೆಲಿವರಿ|ఆర్డర్|పార్సెల్|డెలివరీ)\b",
        t,
    )
    if delivery_context:
        candidates = re.finditer(r"(?<!\d)([a-z]{0,3}\d{4,12})(?!\d)", t)
        for candidate in candidates:
            value = candidate.group(1).upper()
            if not _PHONE.fullmatch(value):
                return value
        spoken_digits = words_to_digits(t)
        if spoken_digits:
            return spoken_digits
    return None


def mask_pii(text, keep=()):
    """Mask card and phone numbers (keep digits of IDs we deliberately extracted)."""
    def card(m):
        digits = re.sub(r"\D", "", m.group(0))
        return m.group(0) if digits in keep else "XXXX-XXXX-XXXX-" + digits[-4:]

    def phone(m):
        digits = re.sub(r"\D", "", m.group(0))
        return m.group(0) if digits in keep else "XXXXXX" + digits[-4:]
    return _PHONE.sub(phone, _CARD.sub(card, text))


# ------------------------------------------------------------------ classification
def classify(t):
    scores, hits = defaultdict(int), defaultdict(list)
    for cat, rx in _RX.items():
        for kw, r in rx:
            if r.search(t):
                w = WEIGHT_OVERRIDE.get(cat, HEAVY_WORDS.get(kw, 1))
                scores[cat] += w
                hits[cat].append(kw.replace("re:", "").replace("\\b", "").replace("(?<!\\w)", "").replace("(?!\\w)", ""))
    if not scores:
        return CATS[-1], []
    best = sorted(scores, key=lambda c: (-scores[c], TIE_ORDER[c]))[0]
    return best, hits[best]


LEVELS = ["Low", "Medium", "High", "Critical"]
SLA_HOURS = {"Critical": 1, "High": 4, "Medium": 24, "Low": 72}  # example targets, configurable


def triage(cat, t, days, amount, frustrated):
    reasons = []
    if cat in CRITICAL_CATS:
        return "Critical", ["Fraud/safety issue: escalate to a human agent immediately"]
    level = 1
    if _any(LOW, t):
        level = 0
        reasons.append("feedback or suggestion")
    if days and days >= 3:
        level = max(level, 2)
        reasons.append(f"unresolved for {days} days")
    if _any(URGENT, t):
        level = max(level, 2)
        reasons.append("customer asked for urgency")
    if amount and amount >= 5000:
        level = max(level, 2)
        reasons.append(f"high amount (Rs {amount})")
    if cat == CATS[2] and _any(TWICE, t):
        level = max(level, 2)
        reasons.append("possible duplicate charge")
    if frustrated and level < 2:
        level += 1
        reasons.append("customer sounds frustrated")
    return LEVELS[level], reasons


# ------------------------------------------------------------------ spoken confirmation (templates)
CAT_NAMES = {
    "hi": ["धोखाधड़ी / अनधिकृत लेन-देन", "सुरक्षा खतरा", "बिलिंग / भुगतान", "रिफंड / वापसी", "उत्पाद में खराबी",
           "डिलीवरी / ऑर्डर", "नेटवर्क / सेवा", "अकाउंट / लॉगिन", "स्टाफ का व्यवहार", "अन्य"],
    "kn": ["ವಂಚನೆ / ಅನಧಿಕೃತ ವಹಿವಾಟು", "ಸುರಕ್ಷತಾ ಅಪಾಯ", "ಬಿಲ್ಲಿಂಗ್ / ಪಾವತಿ", "ರಿಫಂಡ್ / ಹಿಂತಿರುಗಿಸುವಿಕೆ",
           "ಉತ್ಪನ್ನ ದೋಷ", "ಡೆಲಿವರಿ / ಆರ್ಡರ್", "ನೆಟ್ವರ್ಕ್ / ಸೇವೆ", "ಖಾತೆ / ಲಾಗಿನ್", "ಸಿಬ್ಬಂದಿ ವರ್ತನೆ", "ಇತರೆ"],
    "en": CATS,
}
URG_NAMES = {
    "hi": {"Critical": "अत्यंत ज़रूरी", "High": "ऊँची", "Medium": "मध्यम", "Low": "कम"},
    "kn": {"Critical": "ಅತ್ಯಂತ ತುರ್ತು", "High": "ಹೆಚ್ಚು", "Medium": "ಮಧ್ಯಮ", "Low": "ಕಡಿಮೆ"},
    "en": {"Critical": "Critical", "High": "High", "Medium": "Medium", "Low": "Low"},
}
TEMPLATES = {
    "hi": ("आपकी शिकायत दर्ज हो गई है। शिकायत संख्या {num}। श्रेणी, {cat}। प्राथमिकता, {urg}। {esc}"
           "हमारी टीम {sla} घंटे के भीतर आपसे संपर्क करेगी। धन्यवाद।",
           "यह मामला बहुत ज़रूरी है, इसलिए इसे तुरंत हमारे अधिकारी को भेजा जा रहा है। "),
    "kn": ("ನಿಮ್ಮ ದೂರು ದಾಖಲಾಗಿದೆ. ದೂರು ಸಂಖ್ಯೆ {num}. ವರ್ಗ, {cat}. ಆದ್ಯತೆ, {urg}. {esc}"
           "ನಮ್ಮ ತಂಡ {sla} ಗಂಟೆಗಳ ಒಳಗೆ ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸುತ್ತದೆ. ಧನ್ಯವಾದಗಳು.",
           "ಇದು ತುರ್ತು ವಿಷಯವಾದ್ದರಿಂದ ತಕ್ಷಣ ನಮ್ಮ ಅಧಿಕಾರಿಗೆ ರವಾನಿಸಲಾಗಿದೆ. "),
    "en": ("Your complaint has been registered. Ticket number {num}. Category: {cat}. Priority: {urg}. {esc}"
           "Our team will contact you within {sla} hours. Thank you.",
           "This is urgent, so it is being sent to a human officer right away. "),
}
REPLY_LANGS = tuple(TEMPLATES)


def reply_language(lang_code, transcript):
    base = (lang_code or "").split("-")[0].lower()
    script = script_lang(transcript)
    if script in ("hi", "kn"):
        return script
    if script == "en" and base not in ("hi", "kn"):
        return "en"
    if base in ("hi", "kn", "en"):
        return base
    return "en"  # other detected languages: English reply (templates exist for hi/kn/en)


def confirmation(ticket_no, cat, urgency, lang):
    tpl, esc = TEMPLATES[lang]
    ci = CATS.index(cat)
    return tpl.format(num=" ".join(str(ticket_no)), cat=CAT_NAMES[lang][ci], urg=URG_NAMES[lang][urgency],
                      esc=esc if urgency == "Critical" else "", sla=SLA_HOURS[urgency])


# ------------------------------------------------------------------ dialogue: missing details, next steps
REQUIRED = {CATS[2]: "amount", CATS[3]: "order_id", CATS[5]: "order_id"}  # category -> detail we must have
QUESTIONS = {
    "order_id": {"en": "Please tell me your order number, digit by digit.",
                 "hi": "कृपया अपना ऑर्डर नंबर एक-एक अंक करके बताइए।",
                 "kn": "ದಯವಿಟ್ಟು ನಿಮ್ಮ ಆರ್ಡರ್ ಸಂಖ್ಯೆಯನ್ನು ಒಂದೊಂದೇ ಅಂಕೆಯಾಗಿ ಹೇಳಿ."},
    "amount": {"en": "How much money is involved? Please say the amount in rupees.",
               "hi": "यह कितने रुपये का मामला है? कृपया राशि बताइए।",
               "kn": "ಇದು ಎಷ್ಟು ರೂಪಾಯಿಯ ವಿಷಯ? ದಯವಿಟ್ಟು ಮೊತ್ತವನ್ನು ಹೇಳಿ."},
}
NEXT_STEP = {
    CATS[0]: "Freeze the card/account, verify the customer's identity and call back within the hour.",
    CATS[1]: "Tell the customer to stop using the product, log a safety incident and alert the safety team.",
    CATS[2]: "Pull the invoice and payment log, check for a duplicate charge and offer a correction or refund.",
    CATS[3]: "Verify the order and return eligibility, then start the refund or replacement.",
    CATS[4]: "Offer repair or replacement and ask for photos or the serial number.",
    CATS[5]: "Check courier tracking for the order and offer a re-ship or refund if it is lost or late.",
    CATS[6]: "Check for an outage in the customer's area; book a technician visit if it is only their line.",
    CATS[7]: "Verify identity, then reset access or unblock the account.",
    CATS[8]: "Log a service-quality note for the team lead and call the customer back to apologise.",
    CATS[9]: "Route to the general support queue for manual review.",
}
_DIGIT_WORDS = {k: v for k, v in NW.items() if v <= 9}
_DIGIT_WORDS.update({"zero": 0, "shunya": 0, "sifar": 0, "जीरो": 0, "शून्य": 0, "ಸೊನ್ನೆ": 0, "ziro": 0})
_DIGIT_WORDS.update({"సున్నా": 0, "ఒకటి": 1, "రెండు": 2, "మూడు": 3, "నాలుగు": 4,
                     "ఐదు": 5, "ఆరు": 6, "ఏడు": 7, "ఎనిమిది": 8, "తొమ్మిది": 9})
_DIGIT_WORDS = {norm(k): v for k, v in _DIGIT_WORDS.items()}


def words_to_digits(t):
    """'four eight two one three' / 'चार आठ दो एक तीन' -> '48213' (needs a run of 4+ digit words)."""
    best, run = "", ""
    for tok in re.split(r"[\s,.;:!?।|-]+", norm(t)):
        d = str(_DIGIT_WORDS[tok]) if tok in _DIGIT_WORDS else (tok if tok.isdigit() and len(tok) == 1 else None)
        if d is None:
            best, run = (run if len(run) > len(best) else best), ""
        else:
            run += d
    best = run if len(run) > len(best) else best
    return best if len(best) >= 4 else None


def fill_slot(slot, text):
    """Pull the missing detail out of the customer's short answer. Returns a value or None."""
    t = norm(text)
    if slot == "order_id":
        m = re.search(r"([a-z]{0,3}\d{4,12})", t.replace(" ", "") if re.fullmatch(r"[a-z0-9 -]+", t) and any(c.isdigit() for c in t) else t)
        if m:
            return m.group(1).upper()
        return words_to_digits(t)
    if slot == "amount":
        v = extract_amount(t)
        if v:
            return v
        m = re.search(r"(\d[\d,]*)", t)
        return int(m.group(1).replace(",", "")) if m and m.group(1).replace(",", "") else None
    return None


def missing_slot(ticket):
    """Which key detail is still missing? Critical cases are never delayed with questions."""
    if ticket["escalate"]:
        return None
    slot = REQUIRED.get(ticket["category"])
    if slot == "order_id" and not ticket["order_id"]:
        return slot
    if slot == "amount" and not ticket["amount"]:
        return slot
    return None


def followup_question(slot, lang):
    return QUESTIONS[slot][lang if lang in REPLY_LANGS else "en"]


# ------------------------------------------------------------------ the ticket
def make_ticket(transcript, lang_code, number, history=None, overrides=None):
    t = norm(transcript)
    cat, matched = classify(t)
    days, amount, order = extract_days(t), extract_amount(t), extract_order(t)
    if overrides:
        order = overrides.get("order_id", order)
        amount = overrides.get("amount", amount)
    frustrated = bool(_any(FRUSTRATED, t))
    urgency, reasons = triage(cat, t, days, amount, frustrated)
    # repeat complaint: same order reported again -> at least High
    repeat_of = None
    if order:
        prior = [h for h in (history or []) if h.get("order_id") == order]
        if prior:
            repeat_of = prior[-1]["id"]
            reasons.append(f"repeat complaint (earlier ticket {repeat_of})")
            if urgency in ("Low", "Medium"):
                urgency = "High"
    masked = mask_pii(transcript, keep=({re.sub(r"\D", "", order)} if order else set()))
    lang = reply_language(lang_code, transcript)
    facts = [f"Rs {amount}" if amount else None, f"order {order}" if order else None,
             f"{days} day(s)" if days else None, f"REPEAT of {repeat_of}" if repeat_of else None]
    facts = ", ".join(f for f in facts if f)
    snippet = masked if len(masked) <= 140 else masked[:137] + "..."
    summary = f"{cat} | {urgency} priority" + (f" | {facts}" if facts else "") + f" | \"{snippet}\""
    return {
        "id": f"VD-{1000 + number}", "number": 1000 + number, "created": datetime.now().strftime("%H:%M:%S"),
        "created_ts": time.time(), "status": "Open",
        "language": lang_code or script_lang(transcript), "reply_lang": lang,
        "transcript": masked, "category": cat, "urgency": urgency,
        "emotion": "Frustrated" if frustrated else "Neutral",
        "amount": amount, "order_id": order, "days": days, "sla_hours": SLA_HOURS[urgency],
        "escalate": urgency == "Critical", "repeat_of": repeat_of, "matched": matched, "reasons": reasons,
        "summary": summary, "next_step": NEXT_STEP[cat],
        "confirmation": confirmation(1000 + number, cat, urgency, lang),
    }


def to_record(t):
    """Integration-ready record (e.g. to push to a CRM or helpdesk)."""
    keys = ("id", "created", "status", "language", "category", "urgency", "emotion", "escalate", "sla_hours",
            "order_id", "amount", "days", "repeat_of", "next_step", "summary", "transcript")
    return {k: t.get(k) for k in keys}


SAMPLES = [
    ("English - fraud", "My account was hacked and money was transferred without my permission"),
    ("Hinglish - delivery", "Mera order teen din se nahi aaya, order number 48213, bahut deri ho gayi"),
    ("Hindi - billing", "बिल में ज्यादा चार्ज लगा है, 300 रुपये, कृपया ठीक करें"),
    ("Kannada - delivery", "ನನ್ನ ಆರ್ಡರ್ ಮೂರು ದಿನಗಳಿಂದ ಬಂದಿಲ್ಲ"),
    ("English - safety", "The mixer grinder is giving sparks and smoke, I got an electric shock"),
    ("Hinglish - frustrated", "Net bahut slow chal raha hai, main bahut pareshan ho gaya hoon"),
]


# ------------------------------------------------------------------ evaluation on a labelled CSV
def eval_rows(path, audio=False):
    """Returns (stats, fails). stats[group] = [category_ok, urgency_ok, both_ok, n]."""
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    stats = defaultdict(lambda: [0, 0, 0, 0])
    fails = []
    if audio:
        import os
        import syst
        key = os.environ.get("GNANI_API_KEY")
    for r in rows:
        text, lang = r.get("text", ""), None
        if audio and r.get("wav"):
            res = syst.transcribe(open(r["wav"], "rb").read(), "indic-auto", "prisma-v3.0", key)
            text, lang = res["text"], res["lang"]
        tk = make_ticket(text, lang, 0)
        c_ok, u_ok = tk["category"] == r["category"], tk["urgency"] == r["urgency"]
        for g in ("ALL", r["language"]):
            s_ = stats[g]
            s_[0] += c_ok
            s_[1] += u_ok
            s_[2] += c_ok and u_ok
            s_[3] += 1
        if not (c_ok and u_ok):
            fails.append((r["language"], text, f"{tk['category']}/{tk['urgency']}", f"{r['category']}/{r['urgency']}"))
    return stats, fails


def evaluate(path, audio=False):
    stats, fails = eval_rows(path, audio)
    print(f"\n{'Group':<12}{'Category':>10}{'Urgency':>10}{'Both':>8}{'N':>5}")
    for g in sorted(stats, key=lambda x: (x != "ALL", x)):
        c, u, b, n = stats[g]
        print(f"{g:<12}{c / n:>10.0%}{u / n:>10.0%}{b / n:>8.0%}{n:>5}")
    for f in fails:
        print("MISS", f)
    return stats["ALL"][2] / max(stats["ALL"][3], 1)


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    for f in ("test_complaints.csv", "holdout_complaints.csv"):
        check(f"rules >= 90% on {f}", evaluate(f) >= 0.9)
    check("slot: order id digits", fill_slot("order_id", "48213") == "48213")
    check("slot: order id spoken Hindi digits", fill_slot("order_id", "चार आठ दो एक तीन") == "48213")
    check("slot: order id spoken English digits", fill_slot("order_id", "four eight two one three") == "48213")
    check("slot: order id too short -> None", fill_slot("order_id", "12") is None)
    check("order id after natural-language 'is' connector", extract_order("my order number is 48213") == "48213")
    check("order id after intervening complaint details",
          extract_order("my order is delayed for three days, please check 48213") == "48213")
    check("order id after Telugu complaint details",
          extract_order("నా ఆర్డర్ రాలేదు మూడు రోజులు 48213") == "48213")
    check("order id before delivery description",
          extract_order("48213 has not arrived, my package is delayed") == "48213")
    check("order ID extracted from package wording",
          extract_order("Package delayed for three days, tracking number 48213") == "48213")
    check("order id spoken as English digits in complaint",
          extract_order("my order number is four eight two one three") == "48213")
    check("order id spoken as Telugu digits in complaint",
          extract_order("నా ఆర్డర్ మూడు నాలుగు ఐదు ఆరు ఏడు ఎనిమిది") == "345678")
    check("Telugu numeric order id digits", extract_order("ఆర్డర్ ౪౮౨౧౩") == "48213")
    initial_with_order = make_ticket("My order has not arrived, order number is 48213", "en-IN", 5)
    check("complaint with order ID does not request it again",
          initial_with_order["order_id"] == "48213" and missing_slot(initial_with_order) is None)
    delayed_with_order = make_ticket("My order is delayed for three days, please check 48213", "en-IN", 6)
    check("delayed complaint with later order ID does not request it again",
          delayed_with_order["order_id"] == "48213" and missing_slot(delayed_with_order) is None)
    check("slot: amount", fill_slot("amount", "1200 rupees") == 1200)
    check("slot: bare amount", fill_slot("amount", "500") == 500)
    d = make_ticket("Mera order nahi aaya, bahut deri ho gayi", "hi-IN", 1)
    check("delivery without order id asks for it", missing_slot(d) == "order_id")
    d2 = make_ticket("Mera order nahi aaya", "hi-IN", 1, overrides={"order_id": "48213"})
    check("override fills order id", missing_slot(d2) is None and d2["order_id"] == "48213")
    f = make_ticket("My account was hacked, money stolen", "en-IN", 2)
    check("fraud is never delayed by questions", missing_slot(f) is None and f["escalate"])
    first = make_ticket("My parcel has not arrived. Order number 48213", "en-IN", 3)
    again = make_ticket("My parcel still has not arrived. Order number 48213", "en-IN", 4, history=[first])
    check("repeat complaint detected and raised", again["repeat_of"] == first["id"] and again["urgency"] in ("High", "Critical"))
    check("English transcript overrides unsupported auto-detected language",
          reply_language("te-IN", "My order has not arrived") == "en")
    check("Hindi script overrides conflicting detected language",
          reply_language("en-IN", "मेरा ऑर्डर नहीं आया") == "hi")
    check("Kannada script overrides conflicting detected language",
          reply_language("te-IN", "ನನ್ನ ಆರ್ಡರ್ ಬಂದಿಲ್ಲ") == "kn")
    check("Romanized Hindi honors Hindi auto-detection",
          reply_language("hi-IN", "Mera order nahi aaya") == "hi")
    check("questions exist in hi/kn/en", all(followup_question(s_, l) for s_ in QUESTIONS for l in ("hi", "kn", "en")))
    check("card masked, spacing kept", mask_pii("card 4111 1111 1111 1234 used") == "card XXXX-XXXX-XXXX-1234 used")
    check("phone masked", mask_pii("call 9876543210").endswith("3210") and "98765" not in mask_pii("call 9876543210"))
    check("json record has next step", "next_step" in to_record(d))
    print("\nALL OK" if ok else "\nSOME FAILED")
    return ok


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        sys.exit(0 if selftest() else 1)
    if not args or args[0] != "--eval":
        sys.exit(__doc__)
    acc = evaluate(args[1] if len(args) > 1 else "test_complaints.csv", audio="--audio" in args)
    sys.exit(0 if acc >= 0.9 else 1)
