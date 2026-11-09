"""VoiceDesk - a voice complaint agent: listens, asks for missing details, files a triaged ticket, replies out loud.
Powered by Gnani Prisma (speech-to-text) and Timbre (text-to-speech)."""
import hashlib
import json
import os
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import core
import syst

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
api_key = os.environ.get("GNANI_API_KEY", "").strip()
st.set_page_config(page_title="VoiceDesk", page_icon="🎙️", layout="wide")
S = st.session_state
S.setdefault("tickets", [])
S.setdefault("seen", set())
S.setdefault("last", None)
S.setdefault("pending", None)
S.setdefault("turn", 0)
S.setdefault("capture_turn", 0)

COLORS = {"Critical": "#d93025", "High": "#f29900", "Medium": "#1a73e8", "Low": "#188038"}
RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def badge(text, color):
    return (f'<span style="background:{color};color:#fff;padding:3px 12px;border-radius:12px;'
            f'font-weight:600;font-size:0.85rem;margin-right:6px">{text}</span>')


def load_sample():
    label = S.get("sample")
    if label and label != "-":
        S["typed"] = dict(core.SAMPLES)[label]


def due_text(t):
    if t["status"] == "Resolved":
        return "resolved"
    left = t["created_ts"] + t["sla_hours"] * 3600 - time.time()
    m = int(abs(left) // 60)
    h, m = divmod(m, 60)
    span = f"{h}h {m}m" if h else f"{m}m"
    return f"OVERDUE by {span}" if left < 0 else f"{span} left"


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    lang_label = st.selectbox("Customer's language", list(syst.LANGS), index=0,
                              help="Auto-detect lets the customer speak any supported Indian language.")
    speak = st.toggle("Speak replies aloud (Timbre)", value=True)
    follow = st.toggle("Ask a follow-up question when a key detail is missing", value=True)
    st.caption("Demo uses made-up complaints only. Never enter real personal data.")
    if st.button("Clear all tickets"):
        S.tickets, S.seen, S.last, S.pending = [], set(), None, None
        st.rerun()

st.title("🎙️ VoiceDesk")
st.caption("A voice complaint agent for Indian languages. The customer speaks; VoiceDesk asks for any missing "
           "detail, files a triaged ticket with a suggested next step, and speaks a confirmation back. "
           "Powered by Gnani Prisma (speech-to-text) and Timbre (text-to-speech).")


# ---------------------------------------------------------------- processing
def synth(text, reply_lang, warn):
    if not (speak and api_key):
        return None
    try:
        return syst.synthesize(text, reply_lang, api_key)
    except Exception as e:  # noqa
        warn.append(f"Voice reply unavailable: {e}")
        return None


def stt(audio_bytes, filename="audio.wav"):
    """Speech to text. Returns (result, notes) or (None, notes) after recording the error."""
    notes = []
    if not api_key:
        S.last = {"ticket": None, "audio": None,
                  "warn": ["Gnani API key not configured. Add GNANI_API_KEY to the .env file beside app.py."],
                  "played": True}
        return None, notes
    code, model = syst.LANGS[lang_label]
    try:
        try:
            return syst.transcribe(audio_bytes, code, model, api_key, filename), notes
        except Exception as e:  # noqa
            if code != "indic-auto":
                raise
            notes.append(f"Auto-detect failed ({e}); retried as Hindi. Pick the language in the sidebar if needed.")
            return syst.transcribe(audio_bytes, "hi-IN", None, api_key, filename), notes
    except Exception as e:  # noqa
        S.last = {"ticket": None, "audio": None, "warn": [str(e)], "played": True}
        return None, notes


def finalize(transcript, lang_code, stt_ms, t0, notes, overrides=None, prev_s=0.0):
    ticket = core.make_ticket(transcript, lang_code, len(S.tickets) + 1, history=S.tickets, overrides=overrides)
    ticket["stt_ms"] = stt_ms
    warn = list(notes)
    audio = synth(ticket["confirmation"], ticket["reply_lang"], warn)
    ticket["total_s"] = round(prev_s + (time.time() - t0), 2)
    S.tickets.append(ticket)
    S.last = {"ticket": ticket, "audio": audio, "warn": warn, "played": False}


def first_turn(transcript, lang_code, stt_ms, t0, notes):
    S.pending = None
    if not transcript.strip():
        S.last = {"ticket": None, "audio": None, "warn": notes + ["No speech was recognised. Please try again."], "played": True}
        return
    draft = core.make_ticket(transcript, lang_code, len(S.tickets) + 1, history=S.tickets)
    slot = core.missing_slot(draft) if follow else None
    if slot:
        q = core.followup_question(slot, draft["reply_lang"])
        warn = list(notes)
        S.pending = {"text": transcript, "lang": lang_code, "slot": slot, "question": q,
                     "audio": synth(q, draft["reply_lang"], warn), "played": False, "stt_ms": stt_ms,
                     "prev_s": time.time() - t0, "notes": warn}
        S.last = None
        return
    finalize(transcript, lang_code, stt_ms, t0, notes)


def answer_turn(answer_text, stt_ms, skip=False):
    p = S.pending
    t0 = time.time()
    notes = list(p["notes"])
    value = core.fill_slot(p["slot"], answer_text) if answer_text.strip() else None
    if not value and not skip:
        p["answer_error"] = "I couldn't identify that detail. Please try again or skip the question."
        return
    overrides = {p["slot"]: value} if value else {}
    combined = p["text"] + (" | " + answer_text if answer_text.strip() else "")
    S.pending, S.turn = None, S.turn + 1
    finalize(combined, p["lang"], p["stt_ms"] if p["stt_ms"] is not None else stt_ms, t0, notes, overrides, p["prev_s"])


tab1, tab2, tab3 = st.tabs(["🎙️ Speak", "📁 Upload audio", "⌨️ Type / sample"])
with tab1:
    st.write("Press the microphone, speak the complaint, then press stop.")
    rec = (st.audio_input("Record the complaint", sample_rate=16000, key=f"mic_{S.capture_turn}")
           if hasattr(st, "audio_input") and not S.pending else None)
    if rec is not None:
        data = rec.getvalue()
        h = hashlib.md5(data).hexdigest()
        if h not in S.seen:
            S.seen.add(h)
            with st.spinner("Listening and understanding..."):
                t0 = time.time()
                res, notes = stt(data)
                if res:
                    first_turn(res["text"], res["lang"], res["stt_ms"], t0, notes)
                S.capture_turn += 1
            st.rerun()
with tab2:
    up = st.file_uploader("Upload a recording (wav, mp3, m4a, ogg, flac; max 30 s)",
                          type=["wav", "mp3", "m4a", "ogg", "flac", "aac"])
    if up is not None and st.button("Create ticket from this file"):
        with st.spinner("Processing..."):
            t0 = time.time()
            res, notes = stt(up.getvalue(), up.name)
            if res:
                first_turn(res["text"], res["lang"], res["stt_ms"], t0, notes)
        st.rerun()
with tab3:
    st.selectbox("Sample complaints", ["-"] + [x[0] for x in core.SAMPLES], key="sample", on_change=load_sample)
    typed = st.text_area("Complaint text", key="typed", height=100,
                         placeholder="Type or pick a sample. This skips speech-to-text.")
    if st.button("Create ticket from text"):
        first_turn(typed, None, None, time.time(), [])
        st.rerun()

# ---------------------------------------------------------------- follow-up question (multi-turn)
p = S.pending
if p:
    st.divider()
    st.subheader("🤖 One more detail needed")
    st.info(f"**Assistant asks:** {p['question']}")
    if p.get("answer_error"):
        st.info(p["answer_error"])
    for w in p["notes"]:
        st.warning(w)
    if p["audio"]:
        st.audio(p["audio"], format="audio/wav", autoplay=not p["played"])
        p["played"] = True
    c1, c2 = st.columns(2)
    with c1:
        ans = (st.audio_input("Answer by voice", sample_rate=16000, key=f"ans_{S.capture_turn}")
               if hasattr(st, "audio_input") else None)
        if ans is not None:
            data = ans.getvalue()
            h = hashlib.md5(data).hexdigest()
            if h not in S.seen:
                S.seen.add(h)
                with st.spinner("Listening..."):
                    res, notes = stt(data)
                if res:
                    answer_turn(res["text"], res["stt_ms"])
                else:
                    p["answer_error"] = "; ".join(notes or S.last.get("warn", [])) or \
                        "I couldn't transcribe that recording. Please try recording again or type the answer."
                S.capture_turn += 1
                st.rerun()
    with c2:
        txt = st.text_input("...or type the answer", key=f"anstxt_{S.turn}")
        b1, b2 = st.columns(2)
        if b1.button("Submit answer"):
            answer_turn(txt, None)
            st.rerun()
        if b2.button("Skip and create ticket"):
            answer_turn("", None, skip=True)
            st.rerun()

# ---------------------------------------------------------------- latest ticket
last = S.last
if last is None and not p:
    st.divider()
    st.info("No tickets yet. Record a complaint, or pick a sample in the last tab.")
elif last is not None:
    st.divider()
    for w in last["warn"]:
        st.warning(w)
    t = last["ticket"]
    if t:
        left, right = st.columns([3, 2])
        with left:
            st.subheader(f"Ticket {t['id']}")
            st.markdown(badge(t["urgency"], COLORS[t["urgency"]]) + badge(t["category"], "#5f6368")
                        + badge(t["emotion"], "#9334e6" if t["emotion"] == "Frustrated" else "#80868b"),
                        unsafe_allow_html=True)
            if t["escalate"]:
                st.error("Escalate to a human agent immediately.")
            if t["repeat_of"]:
                st.warning(f"Repeat complaint: this order was already reported in ticket {t['repeat_of']}.")
            st.markdown(f"**What the customer said** (language: `{t['language']}`; phone and card numbers masked)")
            st.write(t["transcript"])
            facts = {"Amount": f"Rs {t['amount']}" if t["amount"] else "-", "Order ID": t["order_id"] or "-",
                     "Pending for": f"{t['days']} day(s)" if t["days"] else "-",
                     "Respond within": f"{t['sla_hours']} h"}
            st.table(pd.DataFrame([facts]))
            st.markdown(f"**Suggested next step for the agent:** {t['next_step']}")
            if t["reasons"]:
                st.caption("Why this priority: " + "; ".join(t["reasons"]))
            if t["matched"]:
                st.caption("Category matched on: " + ", ".join(t["matched"]))
        with right:
            st.subheader("Spoken confirmation")
            st.write(t["confirmation"])
            if last["audio"]:
                st.audio(last["audio"], format="audio/wav", autoplay=not last["played"])
                last["played"] = True
            elif speak and not api_key:
                st.caption("Configure GNANI_API_KEY in the .env file to hear the reply.")
            if t.get("stt_ms") is not None:
                st.caption(f"Speech-to-text took {t['stt_ms']} ms. Processing time for this ticket: {t['total_s']} s.")
            with st.expander("Integration-ready JSON"):
                st.json(core.to_record(t))

# ---------------------------------------------------------------- queue, analytics
if S.tickets:
    st.divider()
    st.subheader("Ticket queue (most urgent first)")
    stt_ms = [x["stt_ms"] for x in S.tickets if x.get("stt_ms") is not None]
    tot = [x["total_s"] for x in S.tickets if x.get("stt_ms") is not None]
    open_n = sum(x["status"] == "Open" for x in S.tickets)
    overdue = sum(x["status"] == "Open" and due_text(x).startswith("OVERDUE") for x in S.tickets)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Tickets", len(S.tickets))
    m2.metric("Open / overdue", f"{open_n} / {overdue}")
    m3.metric("Escalated", sum(x["escalate"] for x in S.tickets))
    m4.metric("Avg speech-to-text", f"{sum(stt_ms) / len(stt_ms):.0f} ms" if stt_ms else "-")
    m5.metric("Avg time per ticket", f"{sum(tot) / len(tot):.1f} s" if tot else "-")
    rows = sorted(S.tickets, key=lambda x: (x["status"] == "Resolved", RANK[x["urgency"]], x["number"]))
    df = pd.DataFrame([{"ID": x["id"], "Status": x["status"], "Urgency": x["urgency"], "Category": x["category"],
                        "Language": x["language"], "Due": due_text(x), "Escalate": "YES" if x["escalate"] else "",
                        "Repeat": x["repeat_of"] or "", "Summary": x["summary"]} for x in rows])
    st.dataframe(df, hide_index=True)

    open_ids = [x["id"] for x in S.tickets if x["status"] == "Open"]
    r1, r2 = st.columns([3, 1])
    sel = r1.multiselect("Mark tickets as resolved", open_ids, key="resolve_sel")
    if r2.button("Resolve selected") and sel:
        for x in S.tickets:
            if x["id"] in sel:
                x["status"] = "Resolved"
        st.rerun()

    a1, a2, a3 = st.columns(3)
    a1.caption("Tickets by category")
    a1.bar_chart(df["Category"].value_counts())
    a2.caption("Tickets by urgency")
    a2.bar_chart(df["Urgency"].value_counts().reindex(core.LEVELS[::-1]).fillna(0))
    a3.caption("Tickets by language")
    a3.bar_chart(df["Language"].value_counts())

    d1, d2 = st.columns(2)
    d1.download_button("Download tickets (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                       "voicedesk_tickets.csv", "text/csv")
    d2.download_button("Download tickets (JSON, for integrations)",
                       json.dumps([core.to_record(x) for x in S.tickets], ensure_ascii=False, indent=2).encode("utf-8"),
                       "voicedesk_tickets.json", "application/json")

# ---------------------------------------------------------------- quality report + honest limits
with st.expander("Quality report (rule engine on labelled test sets)"):
    for label, fname in (("Development set", "test_complaints.csv"), ("Holdout set", "holdout_complaints.csv")):
        path = os.path.join(HERE, fname)
        if os.path.exists(path):
            stats, fails = core.eval_rows(path)
            tab = pd.DataFrame([{"Group": g, "Examples": v[3], "Category correct": f"{v[0] / v[3]:.0%}",
                                 "Urgency correct": f"{v[1] / v[3]:.0%}"}
                                for g, v in sorted(stats.items(), key=lambda kv: (kv[0] != "ALL", kv[0]))])
            st.markdown(f"**{label}** ({fname})")
            st.dataframe(tab, hide_index=True)
            for f in fails:
                st.caption(f"Miss: {f}")
    st.caption("Both sets were written by the developer, so this is a sanity check, not an independent benchmark. "
               "It tests the ticket rules on text. Speech accuracy is measured separately with recorded clips.")

with st.expander("How it works and honest limits"):
    st.markdown(
        "- **Pipeline:** voice → Gnani Prisma → transcript → rules → category, urgency, entities → "
        "(follow-up question if a key detail is missing) → ticket → Gnani Timbre speaks the confirmation.\n"
        "- **Triage:** fraud and safety issues are always *Critical* and go to a human at once. Long pending time, "
        "duplicate charges, large amounts, urgent words, an upset customer or a repeat complaint raise the priority.\n"
        "- **Agent support:** each ticket carries a suggested next step and an integration-ready JSON record.\n"
        "- **Privacy:** phone and card numbers are masked before the transcript is shown or stored.\n"
        "- **Limits:** categories and urgency use keyword rules (English, Hinglish, Hindi, Kannada). Other languages "
        "are transcribed but filed as *Other*; spoken replies exist for Hindi, Kannada and English. Follow-up "
        "answers work best when numbers are spoken digit by digit. Response targets are example values. "
        "This is a prototype tested on made-up complaints.")
