import re
import statistics

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
