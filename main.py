import hashlib
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit_log import append_entry, get_recent_entries
from signals import (
    run_stylometric_signal,
    run_semantic_signal,
    run_pragmatic_signal,
)
from scoring import (
    combine_scores,
    confidence_score,
    attribution_result,
    label_variant,
)

load_dotenv()

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# In-memory store for submissions (supports appeal lookup in M5)
submissions = {}

_LABELS = {
    "likely_human": (
        "This piece shows strong signals commonly associated with human-written work. "
        "This does not prove authorship, but the system found low AI-likeness across "
        "multiple detection signals."
    ),
    "likely_ai": (
        "This piece shows strong signals commonly associated with AI-generated writing. "
        "This does not prove how it was created, but readers should know the system found "
        "high AI-likeness across multiple detection signals."
    ),
    "uncertain": (
        "This piece has mixed authorship signals. Some patterns resemble AI-assisted "
        "writing, while others resemble human writing. This label is not a final "
        "judgment, and the creator may appeal the classification."
    ),
}


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON."}), 400

    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "The 'text' field is required and cannot be empty."}), 400

    creator_id = data.get("creator_id", "anonymous")

    submission_id = str(uuid.uuid4())
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    created_at = datetime.now(timezone.utc).isoformat()

    # Signal 1: Stylometric heuristics
    stylo = run_stylometric_signal(text)
    # Signal 2: Groq semantic genericness
    semantic = run_semantic_signal(text)
    # Signal 3: Groq pragmatic genericness
    pragmatic = run_pragmatic_signal(text)

    semantic_genericness_score = semantic["semantic_genericness_score"]
    pragmatic_genericness_score = pragmatic["pragmatic_genericness_score"]

    # Combine all five feature scores into one AI-likeness score
    combined_ai_score = combine_scores(
        stylo["sentence_regularity_score"],
        stylo["em_dash_score"],
        stylo["discourse_marker_score"],
        semantic_genericness_score,
        pragmatic_genericness_score,
    )
    confidence = confidence_score(combined_ai_score)
    attribution = attribution_result(combined_ai_score)
    # Label text is gated on confidence: a low-confidence result shows the
    # cautious uncertain label even when the attribution leans one way.
    transparency_label = _LABELS[label_variant(attribution, confidence)]

    score_breakdown = {
        "sentence_regularity_score": stylo["sentence_regularity_score"],
        "em_dash_score": stylo["em_dash_score"],
        "discourse_marker_score": stylo["discourse_marker_score"],
        "semantic_genericness_score": semantic_genericness_score,
        "pragmatic_genericness_score": pragmatic_genericness_score,
        "combined_ai_score": combined_ai_score,
    }

    submissions[submission_id] = {
        "submission_id": submission_id,
        "content_id": submission_id,   # alias
        "creator_id": creator_id,
        "text_hash": text_hash,
        "attribution_result": attribution,
        "confidence_score": confidence,
        "combined_ai_score": combined_ai_score,
        "transparency_label": transparency_label,
        "score_breakdown": score_breakdown,
        "status": "classified",
        "created_at": created_at,
        "appealed": False,
    }

    log_entry = {
        "event_type": "classification",
        "submission_id": submission_id,
        "creator_id": creator_id,
        "text_hash": text_hash,
        "signals_used": ["stylometric", "semantic_llm", "pragmatic_llm"],
        "signal_scores": score_breakdown,
        "signal_rationales": {
            "semantic_rationale": semantic["semantic_rationale"],
            "pragmatic_rationale": pragmatic["pragmatic_rationale"],
        },
        "combined_ai_score": combined_ai_score,
        "confidence_score": confidence,
        "attribution_result": attribution,
        "transparency_label": transparency_label,
        "status": "classified",
        "created_at": created_at,
    }
    append_entry(log_entry)

    return jsonify({
        "submission_id": submission_id,
        "content_id": submission_id,   # alias
        "attribution_result": attribution,
        "confidence_score": confidence,
        "transparency_label": transparency_label,
        "score_breakdown": score_breakdown,
        "signal_rationales": {
            "semantic_rationale": semantic["semantic_rationale"],
            "pragmatic_rationale": pragmatic["pragmatic_rationale"],
        },
        "status": "classified",
    }), 200


@app.route("/appeal", methods=["POST"])
@limiter.limit("5 per minute")
def appeal():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON."}), 400

    # Accept both the planning.md names and the generic milestone names.
    content_id = data.get("submission_id") or data.get("content_id")
    reason = (data.get("appeal_reason") or data.get("creator_reasoning") or "").strip()

    if not content_id:
        return jsonify({"error": "A 'submission_id' (or 'content_id') is required."}), 400
    if not reason:
        return jsonify({"error": "An 'appeal_reason' (or 'creator_reasoning') is required."}), 400

    submission = submissions.get(content_id)
    if submission is None:
        return jsonify({"error": f"No submission found for id '{content_id}'."}), 404

    previous_status = submission["status"]
    submission["status"] = "under_review"
    submission["appealed"] = True

    appealed_at = datetime.now(timezone.utc).isoformat()

    original_decision = {
        "attribution_result": submission["attribution_result"],
        "confidence_score": submission["confidence_score"],
        "combined_ai_score": submission["combined_ai_score"],
        "label_text": submission["transparency_label"],
        "score_breakdown": submission["score_breakdown"],
    }

    append_entry({
        "event_type": "appeal",
        "submission_id": content_id,
        "content_id": content_id,
        "creator_id": submission["creator_id"],
        "appeal_reason": reason,
        "creator_reasoning": reason,   # alias
        "previous_status": previous_status,
        "new_status": "under_review",
        "status": "under_review",
        "original_decision": original_decision,
        "appealed_at": appealed_at,
    })

    return jsonify({
        "submission_id": content_id,
        "content_id": content_id,
        "status": "under_review",
        "message": (
            "Your appeal has been received. The original classification is now "
            "marked as under review."
        ),
    }), 200


@app.route("/log", methods=["GET"])
@limiter.limit("30 per minute")
def get_log():
    return jsonify({"entries": get_recent_entries()}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5001)
