# Provenance Guard Planning

## Project Goal

Provenance Guard is a backend attribution-transparency system for creative writing platforms. It accepts a text submission, analyzes the text using multiple detection signals, returns an attribution result with a confidence score, generates a plain-language transparency label, and supports appeals from creators who believe their work was misclassified.

The system is not designed to prove authorship. Instead, it provides a confidence-scored signal that communicates uncertainty honestly and gives creators a path to contest classifications.

## Design Principle

A false positive, meaning a human-written work labeled as AI-generated, is more harmful than a false negative on a creative platform. The scoring thresholds and transparency labels are therefore designed to avoid overconfident AI accusations. Borderline cases should be labeled as uncertain rather than likely AI.

## Architecture

The submission flow starts when the client sends `POST /submit` with only `{ text }` in the request body. The backend validates and cleans the text, builds an internal submission object, runs the stylometric and Groq-based signals in parallel, combines their outputs into an AI-likeness score and confidence score, generates a transparency label, writes a structured audit record, and returns the result to the client.

The appeal flow starts when the creator sends `POST /appeal` with a `submission_id` and `appeal_reason`. The backend validates the appeal, looks up the original decision, updates the submission status to `under_review`, logs the appeal alongside the original classification, and returns the updated status.

```mermaid
flowchart TD

  %% =========================
  %% Submission Flow
  %% =========================

  A[Client / Creative Platform UI]
  B[POST /submit]
  C[Input Validator]
  D[Submission Builder]
  E[Signal 1: Stylometric Heuristics]
  F[Signal 2: Groq Semantic Genericness]
  G[Signal 3: Groq Pragmatic Genericness]
  H[Confidence Scoring Engine]
  I[Transparency Label Generator]
  J[Structured Audit Log]
  K[Response to Client]

  A -->|Request body: { text }| B

  B -->|Raw input: { text }| C

  C -->|Validated input: { clean_text }| D

  D -->|Submission object: { submission_id, clean_text, created_at }| E
  D -->|Submission object: { submission_id, clean_text, created_at }| F
  D -->|Submission object: { submission_id, clean_text, created_at }| G

  E -->|StylometricResult: { submission_id, em_dash_ratio, sentence_cv, sentence_regularity_score, discourse_marker_density, stylometric_score }| H

  F -->|SemanticResult: { submission_id, semantic_genericness_score, semantic_ai_probability, semantic_rationale }| H

  G -->|PragmaticResult: { submission_id, pragmatic_genericness_score, pragmatic_ai_probability, pragmatic_rationale }| H

  H -->|ScoringResult: { submission_id, combined_ai_score, confidence_score, attribution_result, score_breakdown }| I

  I -->|TransparencyLabel: { submission_id, label_variant, label_text, plain_language_explanation }| J

  E -->|StylometricResult| J
  F -->|SemanticResult| J
  G -->|PragmaticResult| J
  H -->|ScoringResult| J

  J -->|AuditRecord: { submission_id, text_hash, signals_used, signal_scores, combined_ai_score, confidence_score, attribution_result, label_text, status, created_at }| K

  K -->|Response JSON: { submission_id, attribution_result, confidence_score, transparency_label, score_breakdown, status }| A


  %% =========================
  %% Appeal Flow
  %% =========================

  L[Client / Creator UI]
  M[POST /appeal]
  N[Appeal Validator]
  O[Submission Lookup]
  P[Status Update]
  Q[Structured Audit Log]
  R[Appeal Response]

  L -->|Request body: { submission_id, appeal_reason }| M

  M -->|Raw appeal input: { submission_id, appeal_reason }| N

  N -->|Validated appeal: { submission_id, appeal_reason }| O

  O -->|Original decision: { submission_id, attribution_result, confidence_score, label_text, current_status }| P

  P -->|Updated status: { submission_id, status: under_review, appeal_reason, appealed_at }| Q

  Q -->|AppealAuditRecord: { submission_id, appeal_reason, previous_status, new_status, original_decision, appealed_at }| R

  R -->|Response JSON: { submission_id, status: under_review, message }| L
```

## Detection Signals

The detection pipeline uses three signal groups. The first signal group is a set of stylometric heuristics. The second and third signal groups use Groq-based LLM classification to measure meaning-level features that simple stylometric counts cannot capture.

### Signal 1: Stylometric Heuristics

This signal measures surface-level writing patterns that can be computed directly from the submitted text.

The stylometric signal contains three features:

1. Sentence-length regularity
2. Em-dash density
3. Discourse-marker density

#### Feature 1: Sentence-Length Regularity

This feature measures whether the text has unusually even sentence rhythm.

Raw calculation:

```text
sentence_cv = standard_deviation(sentence_lengths) / mean(sentence_lengths)
```

Lower `sentence_cv` means more regular sentence lengths. Because highly regular sentence rhythm can be associated with AI-generated explanatory writing, the system converts this into an AI-likeness score:

```text
sentence_regularity_score = clamp((0.80 - sentence_cv) / 0.80, 0, 1)
```

Output:

```json
{
  "sentence_cv": 0.42,
  "sentence_regularity_score": 0.475
}
```

#### Feature 2: Em-Dash Density

This feature measures whether the text relies heavily on em-dashes for polished interruption or emphasis.

Raw calculation:

```text
em_dash_ratio = number_of_em_dashes / number_of_sentences
```

Normalized score:

```text
em_dash_score = clamp(em_dash_ratio / 0.30, 0, 1)
```

Output:

```json
{
  "em_dash_ratio": 0.15,
  "em_dash_score": 0.50
}
```

#### Feature 3: Discourse-Marker Density

This feature measures formulaic rhetorical structure by counting transition phrases such as `moreover`, `furthermore`, `additionally`, `overall`, `in conclusion`, `it is important to note`, and `as a result`.

Raw calculation:

```text
discourse_marker_density = number_of_discourse_markers / number_of_sentences
```

Normalized score:

```text
discourse_marker_score = clamp(discourse_marker_density / 0.30, 0, 1)
```

Output:

```json
{
  "discourse_marker_density": 0.20,
  "discourse_marker_score": 0.67
}
```

#### Stylometric Signal Output

The three stylometric feature scores are combined into one stylometric score:

```text
stylometric_score =
  0.40 * sentence_regularity_score
+ 0.25 * em_dash_score
+ 0.35 * discourse_marker_score
```

Example output:

```json
{
  "submission_id": "sub_001",
  "em_dash_ratio": 0.15,
  "sentence_cv": 0.42,
  "sentence_regularity_score": 0.475,
  "discourse_marker_density": 0.20,
  "stylometric_score": 0.55
}
```

### Signal 2: Groq Semantic Genericness

This signal measures whether the content is concrete and situated or generic and interchangeable. Stylometric features can count punctuation and sentence patterns, but they cannot reliably tell whether the text contains specific meaning, lived details, or context-dependent claims.

The Groq prompt asks the model to score semantic genericness from 0 to 5:

```text
0 = highly specific, situated, and human-like
5 = highly generic, interchangeable, and AI-like
```

The system converts this to a 0-1 score:

```text
semantic_genericness_score = groq_semantic_score / 5
```

Example output:

```json
{
  "submission_id": "sub_001",
  "semantic_genericness_score": 0.60,
  "semantic_ai_probability": 0.62,
  "semantic_rationale": "The text uses broad claims and examples that could apply to many prompts."
}
```

### Signal 3: Groq Pragmatic Genericness

This signal measures whether the text appears to have a specific communicative purpose. It asks whether the writing seems directed from a real creator to a real audience, or whether it sounds like a generalized answer produced to satisfy a prompt.

The Groq prompt asks the model to score pragmatic genericness from 0 to 5:

```text
0 = strong human communicative intent
5 = weak or generic communicative intent, more AI-like
```

The system converts this to a 0-1 score:

```text
pragmatic_genericness_score = groq_pragmatic_score / 5
```

Example output:

```json
{
  "submission_id": "sub_001",
  "pragmatic_genericness_score": 0.70,
  "pragmatic_ai_probability": 0.68,
  "pragmatic_rationale": "The text is polished and complete but does not reveal a specific audience, stake, or local reason for being written."
}
```

## Combining Signals Into One Score

The combined AI-likeness score is a weighted average of all five underlying features:

```text
combined_ai_score =
  0.20 * sentence_regularity_score
+ 0.15 * em_dash_score
+ 0.20 * discourse_marker_score
+ 0.25 * semantic_genericness_score
+ 0.20 * pragmatic_genericness_score
```

All feature scores use the same interpretation:

```text
0 = more human-like signal
1 = more AI-like signal
```

The LLM-based features receive 45% of the total weight because they capture meaning-level and intent-level patterns that surface stylometry cannot measure.

Example:

```json
{
  "sentence_regularity_score": 0.70,
  "em_dash_score": 0.40,
  "discourse_marker_score": 0.65,
  "semantic_genericness_score": 0.80,
  "pragmatic_genericness_score": 0.75,
  "combined_ai_score": 0.68
}
```

## Uncertainty Representation

The system separates two ideas:

1. `combined_ai_score`: how AI-like the text appears on a 0-1 scale.
2. `confidence_score`: how far the result is from the ambiguous middle.

A combined AI score near 0.5 means the system sees mixed signals. A confidence score of 0.6 means the result is moderately far from the ambiguous midpoint, but still not definitive.

Confidence is calculated as:

```text
confidence_score = abs(combined_ai_score - 0.5) * 2
```

Examples:

```text
combined_ai_score = 0.50 -> confidence_score = 0.00
combined_ai_score = 0.60 -> confidence_score = 0.20
combined_ai_score = 0.80 -> confidence_score = 0.60
combined_ai_score = 0.95 -> confidence_score = 0.90
combined_ai_score = 0.20 -> confidence_score = 0.60
```

In this system, a confidence score of 0.6 means the classifier is meaningfully away from uncertainty, but it should still be communicated as a probability-based signal rather than proof.

### Attribution Thresholds

The system uses conservative thresholds because false positives are especially harmful on creative platforms.

```text
combined_ai_score <= 0.30 -> likely_human
0.30 < combined_ai_score < 0.75 -> uncertain
combined_ai_score >= 0.75 -> likely_ai
```

The AI threshold is intentionally higher than the human threshold. This makes the system more cautious before showing a high-confidence AI label.

### Label Variant Logic

```text
likely_human + confidence_score >= 0.60 -> high-confidence human label
likely_ai + confidence_score >= 0.60 -> high-confidence AI label
all other cases -> uncertain label
```

This means that a raw AI-likeness score of 0.60 is not labeled as likely AI. It remains uncertain because it is too close to the middle and false positives are costly.

## Transparency Label Design

The transparency label is displayed to readers on the creative platform. It should be understandable to a non-technical reader and should avoid treating the classification as proof.

### High-Confidence AI Label

```text
This piece shows strong signals commonly associated with AI-generated writing. This does not prove how it was created, but readers should know the system found high AI-likeness across multiple detection signals.
```

### High-Confidence Human Label

```text
This piece shows strong signals commonly associated with human-written work. This does not prove authorship, but the system found low AI-likeness across multiple detection signals.
```

### Uncertain Label

```text
This piece has mixed authorship signals. Some patterns resemble AI-assisted writing, while others resemble human writing. This label is not a final judgment, and the creator may appeal the classification.
```

## Appeals Workflow

### Who Can Submit an Appeal?

The creator who submitted the text can submit an appeal. In this project version, user authentication is not implemented, so the appeal endpoint accepts a `submission_id` and an `appeal_reason`. In a production version, the system would verify that the appeal is being submitted by the creator associated with the submission.

### Appeal Input

Endpoint:

```text
POST /appeal
```

Request body:

```json
{
  "submission_id": "sub_001",
  "appeal_reason": "I wrote this myself and used a formal style because it was for a contest submission."
}
```

### What Happens When an Appeal Is Received?

When an appeal is received, the system will:

1. Validate that `submission_id` exists.
2. Validate that `appeal_reason` is non-empty.
3. Look up the original classification decision.
4. Update the submission status from `classified` to `under_review`.
5. Add an appeal event to the structured audit log.
6. Return a response confirming that the appeal was received.

Appeal response:

```json
{
  "submission_id": "sub_001",
  "status": "under_review",
  "message": "Your appeal has been received. The original classification is now marked as under review."
}
```

### What Gets Logged?

The appeal audit log includes:

```json
{
  "event_type": "appeal",
  "submission_id": "sub_001",
  "appeal_reason": "I wrote this myself and used a formal style because it was for a contest submission.",
  "previous_status": "classified",
  "new_status": "under_review",
  "original_decision": {
    "attribution_result": "likely_ai",
    "confidence_score": 0.82,
    "combined_ai_score": 0.91,
    "label_text": "This piece shows strong signals commonly associated with AI-generated writing. This does not prove how it was created, but readers should know the system found high AI-likeness across multiple detection signals."
  },
  "appealed_at": "2026-06-30T12:10:00Z"
}
```

### What Would a Human Reviewer See?

A human reviewer opening the appeal queue would see:

```json
{
  "submission_id": "sub_001",
  "status": "under_review",
  "appeal_reason": "I wrote this myself and used a formal style because it was for a contest submission.",
  "original_label": "likely_ai",
  "original_confidence_score": 0.82,
  "combined_ai_score": 0.91,
  "score_breakdown": {
    "sentence_regularity_score": 0.80,
    "em_dash_score": 0.40,
    "discourse_marker_score": 0.75,
    "semantic_genericness_score": 0.90,
    "pragmatic_genericness_score": 0.85
  },
  "label_text": "This piece shows strong signals commonly associated with AI-generated writing. This does not prove how it was created, but readers should know the system found high AI-likeness across multiple detection signals."
}
```

The reviewer would not see the decision as final proof. They would see the original classification, feature breakdown, creator explanation, and status.

## API Plan

### POST /submit

Request body:

```json
{
  "text": "The submitted creative work goes here."
}
```

Response body:

```json
{
  "submission_id": "sub_001",
  "attribution_result": "uncertain",
  "confidence_score": 0.32,
  "transparency_label": "This piece has mixed authorship signals. Some patterns resemble AI-assisted writing, while others resemble human writing. This label is not a final judgment, and the creator may appeal the classification.",
  "score_breakdown": {
    "sentence_regularity_score": 0.55,
    "em_dash_score": 0.10,
    "discourse_marker_score": 0.40,
    "semantic_genericness_score": 0.62,
    "pragmatic_genericness_score": 0.50,
    "combined_ai_score": 0.58
  },
  "status": "classified"
}
```

### POST /appeal

Request body:

```json
{
  "submission_id": "sub_001",
  "appeal_reason": "I wrote this myself and can explain my drafting process."
}
```

Response body:

```json
{
  "submission_id": "sub_001",
  "status": "under_review",
  "message": "Your appeal has been received. The original classification is now marked as under review."
}
```

### GET /log

This endpoint returns structured audit log entries for grading and debugging.

Response body:

```json
[
  {
    "event_type": "classification",
    "submission_id": "sub_001",
    "text_hash": "abc123",
    "signals_used": ["stylometric", "semantic_llm", "pragmatic_llm"],
    "signal_scores": {
      "sentence_regularity_score": 0.55,
      "em_dash_score": 0.10,
      "discourse_marker_score": 0.40,
      "semantic_genericness_score": 0.62,
      "pragmatic_genericness_score": 0.50
    },
    "combined_ai_score": 0.58,
    "confidence_score": 0.16,
    "attribution_result": "uncertain",
    "status": "classified",
    "created_at": "2026-06-30T12:00:00Z"
  }
]
```

## Rate Limiting

The system will use IP-based rate limiting.

Chosen limits:

```text
POST /submit: 10 requests per minute per IP
POST /appeal: 5 requests per minute per IP
GET /log: 30 requests per minute per IP
```

Reasoning:

A normal creator is unlikely to submit more than a few pieces of writing in one minute, so 10 submissions per minute is enough for regular use while still limiting spam or adversarial flooding. Appeals should be less frequent because each appeal requires a reason and creates a review event, so the appeal endpoint has a stricter limit of 5 requests per minute. The audit log endpoint has a higher limit to support debugging and grading without leaving it unrestricted.

## Audit Logging

Every classification event and appeal event is written to the structured audit log.

### Classification Audit Record

```json
{
  "event_type": "classification",
  "submission_id": "sub_001",
  "text_hash": "abc123",
  "signals_used": ["stylometric", "semantic_llm", "pragmatic_llm"],
  "signal_scores": {
    "sentence_regularity_score": 0.55,
    "em_dash_score": 0.10,
    "discourse_marker_score": 0.40,
    "semantic_genericness_score": 0.62,
    "pragmatic_genericness_score": 0.50
  },
  "combined_ai_score": 0.58,
  "confidence_score": 0.16,
  "attribution_result": "uncertain",
  "transparency_label": "This piece has mixed authorship signals. Some patterns resemble AI-assisted writing, while others resemble human writing. This label is not a final judgment, and the creator may appeal the classification.",
  "status": "classified",
  "created_at": "2026-06-30T12:00:00Z"
}
```

### Appeal Audit Record

```json
{
  "event_type": "appeal",
  "submission_id": "sub_001",
  "appeal_reason": "I wrote this myself and can explain my drafting process.",
  "previous_status": "classified",
  "new_status": "under_review",
  "appealed_at": "2026-06-30T12:10:00Z"
}
```

## Anticipated Edge Cases

### Edge Case 1: Minimalist Poems

A short poem with simple vocabulary, short lines, and repeated structure may be scored as AI-like by sentence regularity and lexical simplicity even if it is human-written. For example, a poem that repeats the same phrase at the end of each stanza could have low variation and high structural regularity.

Mitigation:

The system should avoid high-confidence AI labels unless the LLM semantic and pragmatic scores also indicate genericness. If the stylometric score is high but the LLM detects strong situated imagery or personal stakes, the final score should remain uncertain.

### Edge Case 2: Formal Academic or Contest Writing

A human-written contest essay, grant statement, or formal blog post may use polished transitions, balanced paragraphs, and few personal details. This could increase discourse-marker density and pragmatic genericness.

Mitigation:

The transparency label must avoid accusing the creator. The appeal workflow allows the creator to explain that the formal style was intentional and to provide context for human review.

### Edge Case 3: Human Writing Edited by AI

A creator may write an original piece and then use AI for grammar polishing. The final text may contain human ideas but AI-smoothed style. Stylometric features may detect AI-like regularity, while semantic specificity may remain human-like.

Mitigation:

The system should often classify these cases as uncertain rather than likely AI. The label should mention mixed authorship signals rather than claiming the piece was generated by AI.

### Edge Case 4: Prompted AI with Specific Personal Details

An AI-generated piece can include highly specific details if the prompt contains them. This could lower the semantic genericness score even though the piece is AI-generated.

Mitigation:

The system uses multiple signals rather than relying only on specificity. If semantic specificity is low-AI but sentence regularity, discourse markers, and pragmatic genericness are high-AI, the result may still be uncertain or likely AI depending on the combined score.

## Testing Plan

The system will be tested with at least three categories of examples:

1. A human-like creative piece with irregular rhythm and specific personal details.
2. An AI-like explanatory or creative piece with polished structure and generic claims.
3. A mixed case, such as human-written text that has been heavily polished or a formal essay with generic transitions.

For each test case, I will check:

```text
- Whether each signal returns a 0-1 score
- Whether the combined score matches the intended threshold behavior
- Whether the label is cautious and understandable
- Whether the audit log records all signal scores and the final decision
- Whether appeals update the status to under_review and create an appeal log entry
```

## Implementation Notes

Recommended backend stack:

```text
Python + Flask
```

Planned files:

```text
main.py          # API endpoints
signals.py       # stylometric and Groq-based signal functions
scoring.py       # weighted scoring and threshold logic
labels.py        # transparency label generation
audit_log.py     # structured audit log read/write helpers
rate_limit.py    # rate limiting configuration
planning.md      # architecture and system design
README.md        # setup, endpoints, labels, audit-log examples, limitations
```

The Groq API key will be stored in an environment variable and documented in `.env.example`, not committed directly to the repository.


## AI Tool Plan

This section describes how I will use AI tools during implementation. The planning document will be the main source of truth for prompts so that code generation follows the architecture, scoring logic, labels, and appeal workflow already designed here.

### M3: Submission Endpoint and First Signal

Spec sections to provide to the AI tool:

```text
- Architecture
- Detection Signals, especially Signal 1: Stylometric Heuristics
- API Plan: POST /submit
- Audit Logging: Classification Audit Record
```

What I will ask the AI tool to generate:
```text
- A Flask app skeleton
- A POST /submit endpoint that accepts only { text }
- Input validation for empty or missing text
- A stylometric signal function that calculates sentence-length regularity, em-dash density, discourse-marker density, and stylometric_score
- A basic in-memory submission store and audit log structure
```

How I will verify the output:
```text
- Test the stylometric function directly before connecting it to the endpoint
- Use one short poem, one formal paragraph, and one AI-like explanatory paragraph
- Confirm that all stylometric feature outputs are numeric scores between 0 and 1
- Confirm that POST /submit rejects empty text
- Confirm that POST /submit returns submission_id, score_breakdown, status, and an audit-log entry
```

### M4: Second Signal and Confidence Scoring
Spec sections to provide to the AI tool:
```text
- Architecture
- Detection Signals, especially Groq Semantic Genericness and Groq Pragmatic Genericness
- Combining Signals Into One Score
- Uncertainty Representation
- API Plan: POST /submit
```

What I will ask the AI tool to generate:
```text
- Groq-based LLM signal functions for semantic_genericness_score and pragmatic_genericness_score
- JSON-only Groq prompts that return scores from 0 to 5
- Conversion logic from Groq 0-5 scores to normalized 0-1 scores
- Combined AI-likeness scoring logic using the weighted formula
- Confidence scoring logic using confidence_score = abs(combined_ai_score - 0.5) * 2
- Attribution threshold logic for likely_human, uncertain, and likely_ai
```

What I will check:
```text
- Clearly AI-like text should generally produce a higher combined_ai_score than clearly human-like text
- Clearly human-like text should generally produce a lower combined_ai_score
- Borderline or mixed text should stay near the uncertain range
- A combined_ai_score around 0.50 should produce low confidence
- A combined_ai_score near 0.00 or 1.00 should produce high confidence
- The response should include score_breakdown so the decision is inspectable
```

### M5: Production Layer

Spec sections to provide to the AI tool:

```text
- Architecture
- Transparency Label Design
- Appeals Workflow
- API Plan: POST /appeal and GET /log
- Rate Limiting
- Audit Logging
```

What I will ask the AI tool to generate:
```text
- Label generation logic for the three required label variants
- The POST /appeal endpoint
- Appeal validation for missing submission_id or appeal_reason
- Status update logic that changes classified submissions to under_review
- Structured audit logging for appeal events
- GET /log endpoint for grading and debugging
- Rate limiting for POST /submit, POST /appeal, and GET /log
```

How I will verify:
```text
- Test that the high-confidence AI label, high-confidence human label, and uncertain label are all reachable with controlled score inputs
- Test that POST /appeal updates the submission status to under_review
- Test that an appeal log entry includes submission_id, appeal_reason, previous_status, new_status, and timestamp
- Test that GET /log shows at least three audit-log entries
- Test that rate limiting blocks requests after the configured limit
```

Stretch Feature Planning Rule

Before starting any stretch feature, I will update this planning.md file with a short design section for that feature. The update will describe what the stretch feature adds, what data it needs, how it affects the architecture, how it will be tested, and how it will be documented in the README.
