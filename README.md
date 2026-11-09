# VoiceDesk - Voice Complaint Taker

Customers **speak** a complaint in their own language. VoiceDesk turns it into a **structured, triaged ticket** and **speaks a confirmation back** in the customer's language. Built for the Gnani.ai Great Indian AI Internship Challenge 2026.

## The problem
In India, customers complain in Hindi, Kannada, Hinglish and many other languages, often mixed in one sentence. Support teams then listen and type tickets by hand. That is slow, inconsistent, and urgent cases (fraud, safety) can sit in the same queue as small queries. Typing-based forms also shut out people who find speaking easier.

## What it does
1. **Listens:** Gnani **Prisma** speech-to-text, with automatic language detection.
2. **Understands:** category (billing, delivery, fraud, safety...), urgency, customer mood, and facts such as amount, order ID and days pending.
3. **Asks when something is missing (multi-turn voice dialogue):** a delivery complaint without an order number gets a spoken follow-up question in the customer's language; the customer answers by voice and the ticket is completed. Fraud and safety cases are never delayed with questions.
4. **Triages:** fraud and safety issues are always *Critical* and flagged for a human agent. Long pending time, duplicate charges, large amounts, urgent words, an upset customer or a **repeat complaint about the same order** raise the priority.
5. **Supports the human agent:** every ticket has a suggested next step and an integration-ready JSON record (CSV and JSON export).
6. **Runs like a queue:** most-urgent-first list, live "time left / OVERDUE" against the response target, resolve button, and charts by category, urgency and language.
7. **Protects privacy:** phone and card numbers are masked before the transcript is shown or stored.
8. **Replies out loud:** Gnani **Timbre** text-to-speech asks the question and confirms the ticket number, category, priority and response time in Hindi, Kannada or English.

## Gnani AI models used
- **Prisma v3.0** (auto language detection) with **Prisma v2.5** as fallback - speech-to-text
- **Timbre v2.5** - text-to-speech

## Run it
```bash
pip install -r requirements.txt
python -m streamlit run app.py
```
Add your Gnani API key to `.env` beside `app.py` as `GNANI_API_KEY=your_key_here`.
The app loads the key from this file and does not display it in the UI. `.env` is ignored by Git; never commit or share it.

## Evaluation (rules only, text input)
`python core.py --selftest` runs all logic tests (rules accuracy, follow-up slot filling, repeat detection, PII masking). `python core.py --eval test_complaints.csv` and `python core.py --eval holdout_complaints.csv` print the accuracy tables. The same report is inside the app (Quality report).

| Set | Examples | Category correct | Urgency correct |
|---|---|---|---|
| Development set (used while writing the rules) | 29 | 29 | 29 |
| Holdout set (written afterwards, no tuning) | 18 | 18 | 18 |

Both sets were written by the developer, so treat them as a sanity check, not an independent benchmark. They cover English, Hinglish, Hindi and Kannada.

**Speech accuracy:** add recorded clips with a `wav` column (see `audio_samples_template.csv`) and run
`python core.py --eval your_file.csv --audio` to measure the full voice-to-ticket pipeline.
_Fill in your own audio results here:_ ___

## Limitations
- Category and urgency use keyword rules, so unusual phrasings can be misclassified.
- Rules cover English, Hinglish, Hindi and Kannada. Other languages are transcribed but filed as "Other"; spoken replies exist for Hindi, Kannada and English only.
- Response targets (1 h / 4 h / 24 h / 72 h) are example values.
- Follow-up answers work best when numbers are spoken digit by digit ("four eight two one three").
- Prototype tested on made-up complaints, not real customer data.

## Contribution
Solo project: design, implementation, testing and demo by _your name_.
