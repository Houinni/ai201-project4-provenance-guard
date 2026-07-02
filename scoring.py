"""Weighted scoring, confidence, and attribution thresholds.

All feature scores use the same interpretation:
    0 = more human-like signal
    1 = more AI-like signal
"""


def combine_scores(sentence_regularity_score, em_dash_score,
                   discourse_marker_score, semantic_genericness_score,
                   pragmatic_genericness_score):
    """Weighted average of the five underlying features (weights sum to 1.0)."""
    combined = (
        0.20 * sentence_regularity_score
        + 0.15 * em_dash_score
        + 0.20 * discourse_marker_score
        + 0.25 * semantic_genericness_score
        + 0.20 * pragmatic_genericness_score
    )
    return round(combined, 4)


def confidence_score(combined_ai_score):
    """How far the result is from the ambiguous midpoint (0.5)."""
    return round(abs(combined_ai_score - 0.5) * 2, 4)


def attribution_result(combined_ai_score):
    """Conservative thresholds: the AI threshold is higher than the human one
    because false positives are especially harmful on creative platforms."""
    if combined_ai_score <= 0.30:
        return "likely_human"
    if combined_ai_score >= 0.75:
        return "likely_ai"
    return "uncertain"


def label_variant(attribution, confidence):
    """Select which transparency label to show, gated on confidence.

    likely_human + confidence >= 0.60 -> high-confidence human label
    likely_ai    + confidence >= 0.60 -> high-confidence AI label
    all other cases                   -> uncertain label

    This means a borderline result (attribution near a threshold but low
    confidence) shows the cautious uncertain label rather than an
    overconfident accusation.
    """
    if attribution == "likely_human" and confidence >= 0.60:
        return "likely_human"
    if attribution == "likely_ai" and confidence >= 0.60:
        return "likely_ai"
    return "uncertain"
