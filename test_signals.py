"""Calibration test set for the detection pipeline.

Runs every signal on a set of deliberately chosen inputs and prints each
signal score alongside the combined score, confidence, and attribution.
Use this to sanity-check calibration after changing a signal or a weight.

    python test_signals.py
"""

from dotenv import load_dotenv

load_dotenv()

from signals import (  # noqa: E402  (import after load_dotenv)
    run_stylometric_signal,
    run_semantic_signal,
    run_pragmatic_signal,
)
from scoring import (  # noqa: E402
    combine_scores,
    confidence_score,
    attribution_result,
)

# (label, expected-ballpark, text)
CASES = [
    (
        "Clearly AI (uniform + generic)",
        "likely_ai",
        "Technology continues to shape the modern world in profound ways. "
        "Moreover, innovation drives progress across nearly every industry today. "
        "Furthermore, businesses must adapt quickly to remain competitive and relevant. "
        "Additionally, collaboration between teams enhances productivity and overall success. "
        "Consequently, organizations should invest in continuous learning and development. "
        "In conclusion, embracing change remains essential for long-term growth.",
    ),
    (
        "Clearly AI (essay tone)",
        "high",
        "Artificial intelligence represents a transformative paradigm shift in modern "
        "society. It is important to note that while the benefits of AI are numerous, it "
        "is equally essential to consider the ethical implications. Furthermore, "
        "stakeholders across various sectors must collaborate to ensure responsible "
        "deployment.",
    ),
    (
        "Clearly human (casual)",
        "likely_human",
        "ok so i finally tried that new ramen place downtown and honestly? underwhelming. "
        "the broth was fine but they put WAY too much sodium in it and i was thirsty for "
        "like three hours after. my friend got the spicy version and said it was better. "
        "probably won't go back unless someone drags me there",
    ),
    (
        "Borderline: formal human",
        "uncertain",
        "The relationship between monetary policy and asset price inflation has been "
        "extensively studied in the literature. Central banks face a fundamental tension "
        "between their mandate for price stability and the unintended consequences of "
        "prolonged low interest rates on equity and real estate valuations.",
    ),
    (
        "Borderline: lightly edited AI",
        "uncertain",
        "I've been thinking a lot about remote work lately. There are genuine tradeoffs — "
        "flexibility and no commute on one side, isolation and blurred work-life boundaries "
        "on the other. Studies show productivity varies widely by individual and role type.",
    ),
]


def run_case(text):
    stylo = run_stylometric_signal(text)
    semantic = run_semantic_signal(text)
    pragmatic = run_pragmatic_signal(text)
    combined = combine_scores(
        stylo["sentence_regularity_score"],
        stylo["em_dash_score"],
        stylo["discourse_marker_score"],
        semantic["semantic_genericness_score"],
        pragmatic["pragmatic_genericness_score"],
    )
    return {
        "reg": stylo["sentence_regularity_score"],
        "dash": stylo["em_dash_score"],
        "disc": stylo["discourse_marker_score"],
        "sem": semantic["semantic_genericness_score"],
        "prag": pragmatic["pragmatic_genericness_score"],
        "combined": combined,
        "confidence": confidence_score(combined),
        "attribution": attribution_result(combined),
    }


if __name__ == "__main__":
    print(f"{'case':<34}{'combined':>9}{'conf':>7}{'attribution':>15}   stylo(reg/dash/disc) sem prag")
    print("-" * 108)
    for label, expected, text in CASES:
        r = run_case(text)
        print(
            f"{label:<34}{r['combined']:>9}{r['confidence']:>7}{r['attribution']:>15}"
            f"   {r['reg']}/{r['dash']}/{r['disc']}  {r['sem']} {r['prag']}"
            f"   (expected ~{expected})"
        )
