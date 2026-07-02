# Provenance Guard

A backend attribution-transparency system for creative-writing platforms. It accepts a
text submission, runs multiple detection signals, returns a **confidence-scored** AI-likeness
result with a **plain-language transparency label**, writes a structured audit record, and
lets creators **appeal** a classification.

Provenance Guard is **not** an authorship prover. It produces a probability-style signal that
communicates uncertainty honestly and gives creators a path to contest a result. Its central
design principle: on a creative platform, a **false positive** (a human writer labeled as AI)
is more harmful than a false negative, so the thresholds are deliberately cautious.

---

## Table of Contents

- [Setup](#setup)
- [Running the app](#running-the-app)
- [Architecture](#architecture)
- [API endpoints](#api-endpoints)
- [Detection signals — and why these](#detection-signals--and-why-these)
- [Confidence scoring — and why this approach](#confidence-scoring--and-why-this-approach)
- [Transparency label variants](#transparency-label-variants)
- [Appeals workflow](#appeals-workflow)
- [Rate limiting](#rate-limiting)
- [Audit log](#audit-log)
- [Known limitations](#known-limitations)
- [Spec reflection](#spec-reflection)
- [AI usage](#ai-usage)

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (see `.env.example`) with a Groq API key:

```
GROQ_API_KEY=your_groq_api_key_here
```

The two LLM signals call Groq's `llama-3.3-70b-versatile` model.

## Running the app

```bash
python main.py
# Serving on http://127.0.0.1:5001
```

> **Port note:** the app runs on **5001**, not 5000. On macOS, port 5000 is taken by the
> AirPlay Receiver, which silently returns `403` to every request. All curl examples below
> use `5001`.

Quick smoke test:

```bash
curl -s -X POST http://localhost:5001/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "The sun dipped below the horizon, painting the sky in hues of amber and rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet.", "creator_id": "test-user-1"}' | python -m json.tool
```

---

## Architecture

```
Client
  │  POST /submit { text, creator_id }
  ▼
Input validation ──► Submission builder (uuid content_id, text hash, timestamp)
  ▼
┌──────────────────────────────────────────────┐
│ Signal 1: Stylometric heuristics (local)      │
│ Signal 2: Groq semantic genericness (LLM)     │
│ Signal 3: Groq pragmatic genericness (LLM)    │
└──────────────────────────────────────────────┘
  ▼
Confidence scoring engine  (weighted combine → combined_ai_score → confidence → attribution)
  ▼
Transparency label generator (confidence-gated variant)
  ▼
Structured audit log (append-only JSONL)  ──►  Response to client
```

The appeal flow (`POST /appeal`) looks up the stored submission, flips its status to
`under_review`, and appends an appeal record that embeds the original decision.

Full design rationale, the mermaid diagram, and the scoring math live in
[`planning.md`](planning.md).

**Files**

| File | Responsibility |
|---|---|
| `main.py` | Flask app; `/submit`, `/appeal`, `/log` routes; rate limiting |
| `signals.py` | Stylometric heuristics + the two Groq genericness signals |
| `scoring.py` | Weighted combine, confidence, attribution thresholds, label variant |
| `audit_log.py` | Append/read helpers for the JSONL audit log |
| `test_signals.py` | Calibration harness that runs every signal on 5 chosen inputs |

---

## API endpoints

### `POST /submit`

Request:

```json
{ "text": "The submitted creative work goes here.", "creator_id": "test-user-1" }
```

Response (abridged):

```json
{
  "submission_id": "43d734aa-c03e-4d23-9431-99354d869554",
  "content_id": "43d734aa-c03e-4d23-9431-99354d869554",
  "attribution_result": "likely_ai",
  "confidence_score": 0.6724,
  "transparency_label": "This piece shows strong signals commonly associated with AI-generated writing. ...",
  "score_breakdown": {
    "sentence_regularity_score": 0.9308,
    "em_dash_score": 0.0,
    "discourse_marker_score": 1.0,
    "semantic_genericness_score": 1.0,
    "pragmatic_genericness_score": 1.0,
    "combined_ai_score": 0.8362
  },
  "signal_rationales": {
    "semantic_rationale": "The text consists of broad, general statements ...",
    "pragmatic_rationale": "The text conveys generic statements ... without a discernible audience ..."
  },
  "status": "classified"
}
```

`content_id` is an alias for `submission_id` — both are returned, and both endpoints accept
either name (see [Spec reflection](#spec-reflection)).

### `POST /appeal`

```bash
curl -s -X POST http://localhost:5001/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-CONTENT-ID", "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing may appear more formal than typical."}' | python -m json.tool
```

Accepts `{content_id, creator_reasoning}` or `{submission_id, appeal_reason}`. Returns:

```json
{
  "submission_id": "5a08788a-...",
  "content_id": "5a08788a-...",
  "status": "under_review",
  "message": "Your appeal has been received. The original classification is now marked as under review."
}
```

### `GET /log`

Returns the recent audit entries as `{"entries": [...]}` for grading and debugging. (In a
real system this would require auth.)

---

## Detection signals — and why these

The pipeline uses **three** feature groups across **two independent kinds of evidence**:
cheap local *surface* statistics, and LLM-based *meaning/intent* judgments. Combining kinds
matters — each covers the other's blind spot.

### Signal 1 — Stylometric heuristics (local, no API)

Three surface features computed directly from the text:

1. **Sentence-length regularity** — `sentence_cv = stdev/mean` of sentence lengths, converted
   so that *more uniform rhythm → more AI-like*. AI explanatory prose tends toward even cadence.
2. **Em-dash density** — em-dashes per sentence. Polished "interruption" punctuation shows up
   heavily in a lot of generated text.
3. **Discourse-marker density** — counts formulaic transitions (`moreover`, `furthermore`,
   `in conclusion`, `it is important to note`, ...).

**Why:** these are transparent, free, deterministic, and instantly explainable to a
non-technical creator. But on their own they are shallow — a human writing formally trips them,
and an AI told to write casually evades them. That's the motivation for signals 2 and 3.

### Signals 2 & 3 — Groq LLM genericness (semantic + pragmatic)

Surface counts can't tell whether text *means* something specific. Two LLM calls each return
an integer 0–5 (normalized to 0–1):

- **Semantic genericness** — is the content concrete and situated (specific names, lived
  detail, context-dependent claims) or generic and interchangeable (could satisfy any prompt)?
- **Pragmatic genericness** — does the writing have a real communicative purpose (a writer, an
  audience, a stake) or does it read like a generalized answer produced to satisfy a prompt?

**Why two LLM angles instead of one "is this AI?" call:** asking the model directly to detect
AI is unreliable and opaque. Asking it to judge *genericness of meaning* and *genericness of
intent* — two properties a human can also verify from the returned rationale — is more robust
and more honest. Each call returns a one-sentence rationale that is stored in the audit log.

The LLM features carry **45%** of the total weight because they capture meaning- and
intent-level patterns that surface stylometry structurally cannot.

---

## Confidence scoring — and why this approach

The system deliberately separates **two different questions**:

- **`combined_ai_score`** (0–1): *how AI-like* does the text look? A weighted average of the
  five features:

  ```
  combined_ai_score =
      0.20 * sentence_regularity_score
    + 0.15 * em_dash_score
    + 0.20 * discourse_marker_score
    + 0.25 * semantic_genericness_score
    + 0.20 * pragmatic_genericness_score
  ```

- **`confidence_score`** (0–1): *how far from the ambiguous middle* is that result?

  ```
  confidence_score = abs(combined_ai_score - 0.5) * 2
  ```

This split is the point. A `combined_ai_score` of 0.5 is not "50% likely AI" — it's *maximum
uncertainty*, and confidence is 0. A score near 0 or 1 is a confident human/AI read. Keeping
"how AI-like" and "how sure" as separate numbers stops the system from dressing up a coin-flip
as a verdict.

### Attribution thresholds (conservative on purpose)

```
combined_ai_score <= 0.30            -> likely_human
0.30 < combined_ai_score < 0.75      -> uncertain
combined_ai_score >= 0.75            -> likely_ai
```

The AI threshold (0.75) is intentionally **higher** than the human threshold (0.30). Because a
false AI accusation is the costly error on a creative platform, the "uncertain" band is wide
and asymmetric: text has to look *strongly* AI-like before it is ever called `likely_ai`.

### Two example submissions with different confidence

Both are real outputs from `test_signals.py`.

**High-confidence case — casual human review** (`confidence_score = 0.8416`)

> "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth
> was fine but they put WAY too much sodium in it ..."

| feature | score |
|---|---|
| sentence_regularity | 0.1458 |
| em_dash | 0.0 |
| discourse_marker | 0.0 |
| semantic_genericness | 0.2 |
| pragmatic_genericness | 0.0 |
| **combined_ai_score** | **0.0792** |
| **confidence_score** | **0.8416** → `likely_human` |

**Lower-confidence case — lightly edited AI** (`confidence_score = 0.026`)

> "I've been thinking a lot about remote work lately. There are genuine tradeoffs — flexibility
> and no commute on one side, isolation and blurred work-life boundaries on the other. Studies
> show productivity varies widely by individual and role type."

| feature | score |
|---|---|
| sentence_regularity | 0.4151 |
| em_dash | 1.0 |
| discourse_marker | 0.0 |
| semantic_genericness | 0.8 |
| pragmatic_genericness | 0.4 |
| **combined_ai_score** | **0.513** |
| **confidence_score** | **0.026** → `uncertain` |

The scores are meaningfully different (0.84 vs 0.03 confidence): the casual human review is far
from the ambiguous middle, while the lightly-edited-AI piece lands almost exactly on 0.5 — which
is the honest answer for genuinely mixed authorship.

---

## Transparency label variants

The label shown to readers is **gated on confidence**, not just attribution: a result that
leans one way but has low confidence still shows the cautious label
(`label_variant()` in `scoring.py`).

```
likely_human + confidence >= 0.60 -> high-confidence human label
likely_ai    + confidence >= 0.60 -> high-confidence AI label
all other cases                   -> uncertain label
```

**High-confidence AI label** (exact text):

> This piece shows strong signals commonly associated with AI-generated writing. This does not
> prove how it was created, but readers should know the system found high AI-likeness across
> multiple detection signals.

**High-confidence human label** (exact text):

> This piece shows strong signals commonly associated with human-written work. This does not
> prove authorship, but the system found low AI-likeness across multiple detection signals.

**Uncertain label** (exact text):

> This piece has mixed authorship signals. Some patterns resemble AI-assisted writing, while
> others resemble human writing. This label is not a final judgment, and the creator may appeal
> the classification.

All three are reachable (demonstrated in `test_signals.py`: casual human → human label,
uniform generic text → AI label, formal/edited text → uncertain label). No label claims proof.

---

## Appeals workflow

`POST /appeal` (no automated re-classification — appeals go to a human queue):

1. Validate the id and reasoning are present.
2. Look up the submission (404 if unknown).
3. Flip its status `classified → under_review`.
4. Append an appeal record embedding the **original decision** (attribution, confidence,
   combined score, full breakdown, label text).
5. Return a confirmation.

A human reviewer reading `/log` sees the original classification, the full feature breakdown,
the creator's explanation, and the `under_review` status — never a decision presented as final
proof.

---

## Rate limiting

IP-based, via Flask-Limiter with in-memory storage (`storage_uri="memory://"`).

| Endpoint | Limit | Reasoning |
|---|---|---|
| `POST /submit` | **10 / minute; 100 / day** | A real writer submits a handful of pieces at a time; 10/min is generous for human use while blocking a flooding script. The daily cap bounds sustained abuse and Groq cost. |
| `POST /appeal` | **5 / minute** | Appeals require a written reason and create a review event, so they are naturally rarer; a stricter cap discourages spamming the review queue. |
| `GET /log` | **30 / minute** | Read-only debugging/grading endpoint; higher limit for convenience without leaving it unbounded. |

**Evidence** — 12 rapid `POST /submit` requests (first 10 succeed, then `429`):

```
200
200
200
200
200
200
200
200
200
200
429
429
```

---

## Audit log

Every classification and appeal is appended as one JSON object per line to `audit_log.jsonl`
(structured, not `print()`). Each classification entry captures: timestamp, content id,
creator id, text hash, signals used, **each individual signal score**, the combined score,
confidence, attribution, the label shown, and status. Appeal entries capture the reasoning,
the status transition, and the embedded original decision.

**Sample — a classification entry:**

```json
{
  "event_type": "classification",
  "submission_id": "5a08788a-f19e-49e4-b931-80a77065a22c",
  "creator_id": "demo-human",
  "text_hash": "819676fbe89024f8",
  "signals_used": ["stylometric", "semantic_llm", "pragmatic_llm"],
  "signal_scores": {
    "sentence_regularity_score": 0.1458,
    "em_dash_score": 0.0,
    "discourse_marker_score": 0.0,
    "semantic_genericness_score": 0.2,
    "pragmatic_genericness_score": 0.0,
    "combined_ai_score": 0.0792
  },
  "signal_rationales": {
    "semantic_rationale": "The text contains specific details about a particular experience at a named location, making it highly specific and situated.",
    "pragmatic_rationale": "The text has a strong human communicative intent, sharing a personal experience and opinion about a specific restaurant."
  },
  "combined_ai_score": 0.0792,
  "confidence_score": 0.8416,
  "attribution_result": "likely_human",
  "transparency_label": "This piece shows strong signals commonly associated with human-written work. ...",
  "status": "classified",
  "created_at": "2026-07-02T00:07:54.307031+00:00"
}
```

**Sample — an appeal entry (status flipped to `under_review`, original decision embedded):**

```json
{
  "event_type": "appeal",
  "submission_id": "5a08788a-f19e-49e4-b931-80a77065a22c",
  "content_id": "5a08788a-f19e-49e4-b931-80a77065a22c",
  "creator_id": "demo-human",
  "appeal_reason": "I wrote this myself from personal experience about a restaurant I visited.",
  "creator_reasoning": "I wrote this myself from personal experience about a restaurant I visited.",
  "previous_status": "classified",
  "new_status": "under_review",
  "status": "under_review",
  "original_decision": {
    "attribution_result": "likely_human",
    "confidence_score": 0.8416,
    "combined_ai_score": 0.0792,
    "label_text": "This piece shows strong signals commonly associated with human-written work. ...",
    "score_breakdown": { "sentence_regularity_score": 0.1458, "em_dash_score": 0.0, "discourse_marker_score": 0.0, "semantic_genericness_score": 0.2, "pragmatic_genericness_score": 0.0, "combined_ai_score": 0.0792 }
  },
  "appealed_at": "2026-07-02T00:07:56.062941+00:00"
}
```

---

## Known limitations

**Formal human writing is the system's clearest failure mode** — contest essays, grant
statements, academic abstracts, and polished blog posts.

This is not a data problem; it's structural to the signals. On the borderline "formal human"
test input (a real paragraph about monetary policy), the pipeline returned
`semantic_genericness = 0.8` and `pragmatic_genericness = 0.8` — the LLM signals fired *hard*,
pushing `combined_ai_score` to 0.36, at the edge of the uncertain band. The reason: the LLM
signals measure **genericness of meaning and intent**, and genuinely formal human prose *is*
abstract, audience-neutral, and interchangeable-sounding. The signal cannot distinguish
"generic because a machine produced it" from "generic because a person chose a formal register."
Discourse-marker density compounds this, since formal writers legitimately use transitions.

The mitigations are deliberate rather than complete: the wide, asymmetric uncertain band keeps
these cases out of `likely_ai`, the confidence gate keeps the label cautious, and the appeal
workflow exists precisely so a formal-register human can contest the result. But the underlying
signal ambiguity remains, and no threshold fully removes it.

A second, symmetric limitation: **AI text seeded with specific personal details** (a prompt
that supplies real names/events) can lower semantic genericness enough to read human-like. The
multi-signal design softens this — regularity and discourse markers still fire — but a
well-prompted piece can land in `uncertain`.

**If deploying for real**, I would: calibrate thresholds against a labeled human/AI corpus
rather than hand-picked constants; run the two Groq calls concurrently (currently sequential)
to cut latency; add a length floor below which stylometry is untrustworthy; and persist
submissions to a real datastore instead of an in-memory dict (appeals are lost on restart).

---

## Spec reflection

**One way the spec guided the implementation.** `planning.md` fixed the exact scoring math —
the five weights, `confidence = abs(combined - 0.5) * 2`, and the `0.30 / 0.75` thresholds —
*before* any code existed. The milestone explicitly warned that AI-generated scoring functions
often look reasonable but silently diverge from the specified ranges. Having the weights written
down let me diff the generated `combine_scores` against the spec and confirm the 0.20/0.15/0.20/
0.25/0.20 split and the asymmetric thresholds were exactly right instead of "close enough."

**One way the implementation diverged.** The spec's API contract named the fields
`submission_id` and `appeal_reason`, but the assignment's own test commands (and likely the
grader) used `content_id` and `creator_reasoning`. Rather than pick one and risk a mismatch, I
diverged from the single-name contract: both endpoints now **accept either** name, and `/submit`
returns both. A smaller divergence: the app runs on port **5001** instead of the spec's 5000,
because macOS AirPlay occupies 5000 and returns a misleading `403`. I also added `signal_rationales`
to the response and log (not in the original contract) for inspectability.

---

## AI usage

**1. Flask skeleton + first signal (M3).** I gave the AI the architecture section, the Signal 1
spec, and the `POST /submit` contract from `planning.md`, and asked for a Flask skeleton plus the
stylometric function. I reviewed the output against my spec: the generated function was close but
I overrode the sentence-splitting to also break on newlines (so poems/short lines are handled),
added a `< 3 sentences` guard so short texts don't produce a bogus regularity score, and switched
the audit log from the suggested single-JSON-file approach to append-only JSONL so concurrent
writes don't corrupt it.

**2. Groq signals + scoring (M4).** I asked the AI to generate the two Groq genericness functions
and the combining logic, given the detection-signals and uncertainty sections. I verified the
generated scoring against the spec's weights and thresholds (per the milestone's warning) — they
matched, so I kept them. What I revised: I forced `temperature=0` and
`response_format={"type": "json_object"}` for deterministic, parseable output, clamped the raw
0–5 score before normalizing, and rewrote the prompts to demand a one-sentence rationale so every
LLM judgment is auditable rather than a bare number.

**3. Labels + appeal endpoint (M5).** I asked for the confidence-gated label function and the
`/appeal` endpoint. I confirmed the label function produced all three exact variant texts from my
spec. I overrode the appeal endpoint's field handling: the generated version used one field-name
convention, and I changed it to accept both `content_id`/`creator_reasoning` and
`submission_id`/`appeal_reason`, and to embed the full original decision in the appeal log entry
so a human reviewer has complete context.
