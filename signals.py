import json
import os
import re
import statistics

from groq import Groq

GROQ_MODEL = "llama-3.3-70b-versatile"

_groq_client = None


def _client():
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client


DISCOURSE_MARKERS = [
    "moreover", "furthermore", "additionally", "overall",
    "in conclusion", "it is important to note", "as a result",
    "however", "therefore", "consequently", "in addition",
    "on the other hand", "in summary", "to summarize",
    "in other words", "for example", "for instance",
    "in particular", "notably", "specifically",
]


def _split_sentences(text):
    # Split on sentence-ending punctuation or newlines (handles prose and poetry)
    parts = re.split(r'(?<=[.!?])\s+|\n+', text.strip())
    return [s for s in parts if s.strip()]


def run_stylometric_signal(text):
    sentences = _split_sentences(text)
    n = len(sentences)

    # Feature 1: Sentence-length regularity
    if n < 3:
        # Too few sentences for a meaningful regularity signal
        sentence_cv = 0.80
        sentence_regularity_score = 0.0
    else:
        lengths = [len(s.split()) for s in sentences]
        mean_len = statistics.mean(lengths)
        stdev_len = statistics.stdev(lengths)
        sentence_cv = stdev_len / mean_len if mean_len > 0 else 0.0
        sentence_regularity_score = max(0.0, min(1.0, (0.80 - sentence_cv) / 0.80))

    # Feature 2: Em-dash density
    em_dash_count = text.count("—") + text.count("--")
    em_dash_ratio = em_dash_count / max(n, 1)
    em_dash_score = min(1.0, em_dash_ratio / 0.30)

    # Feature 3: Discourse-marker density
    text_lower = text.lower()
    marker_count = sum(1 for m in DISCOURSE_MARKERS if m in text_lower)
    discourse_marker_density = marker_count / max(n, 1)
    discourse_marker_score = min(1.0, discourse_marker_density / 0.30)

    stylometric_score = (
        0.40 * sentence_regularity_score
        + 0.25 * em_dash_score
        + 0.35 * discourse_marker_score
    )

    return {
        "sentence_cv": round(sentence_cv, 4),
        "sentence_regularity_score": round(sentence_regularity_score, 4),
        "em_dash_ratio": round(em_dash_ratio, 4),
        "em_dash_score": round(em_dash_score, 4),
        "discourse_marker_density": round(discourse_marker_density, 4),
        "discourse_marker_score": round(discourse_marker_score, 4),
        "stylometric_score": round(stylometric_score, 4),
    }


# ---------------------------------------------------------------------------
# Groq LLM signals
# ---------------------------------------------------------------------------

_SEMANTIC_PROMPT = """You are a text-analysis component in an attribution-transparency system.

Rate the SEMANTIC GENERICNESS of the text on an integer scale from 0 to 5:
0 = highly specific, situated, and human-like (concrete lived detail, particular
    names/places/events, context-dependent claims that could not be swapped into
    another piece).
5 = highly generic, interchangeable, and AI-like (broad claims, filler examples,
    content that could satisfy many different prompts).

Judge only genericness of MEANING, not grammar, tone, or formality.

Respond with ONLY a JSON object in this exact shape:
{"score": <integer 0-5>, "rationale": "<one concise sentence>"}"""

_PRAGMATIC_PROMPT = """You are a text-analysis component in an attribution-transparency system.

Rate the PRAGMATIC GENERICNESS of the text on an integer scale from 0 to 5:
0 = strong human communicative intent (clearly directed from a real writer to a
    real audience, with a specific purpose, stake, or reason for being written).
5 = weak or generic communicative intent, more AI-like (a generalized answer
    produced to satisfy a prompt, with no discernible audience, stake, or occasion).

Judge only communicative intent, not grammar, tone, or formality.

Respond with ONLY a JSON object in this exact shape:
{"score": <integer 0-5>, "rationale": "<one concise sentence>"}"""


def _run_groq_genericness(text, system_prompt):
    """Call Groq and return (genericness_score_0_1, rationale). Raw score is 0-5."""
    resp = _client().chat.completions.create(
        model=GROQ_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
    )
    data = json.loads(resp.choices[0].message.content)
    raw = float(data.get("score", 0))
    raw = max(0.0, min(5.0, raw))
    rationale = str(data.get("rationale", "")).strip()
    return round(raw / 5.0, 4), rationale


def run_semantic_signal(text):
    score, rationale = _run_groq_genericness(text, _SEMANTIC_PROMPT)
    return {
        "semantic_genericness_score": score,
        "semantic_rationale": rationale,
    }


def run_pragmatic_signal(text):
    score, rationale = _run_groq_genericness(text, _PRAGMATIC_PROMPT)
    return {
        "pragmatic_genericness_score": score,
        "pragmatic_rationale": rationale,
    }
