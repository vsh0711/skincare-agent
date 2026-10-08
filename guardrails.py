"""
Guardrails — Input/output validation and prompt injection prevention.
Applied before every agent.run() call and after every response.
"""

import re
import unicodedata
from dataclasses import dataclass, field

# ── Config ────────────────────────────────────────────────────────────────────
MAX_INPUT_CHARS = 400
MIN_INPUT_CHARS = 1

# ── Prompt injection patterns ─────────────────────────────────────────────────
# Covers unicode-normalised lowercase input after NFKC normalisation.
_INJECTION = [
    r"ignore\s+(previous|all|above|prior|system)\s+(instruction|prompt|rule|directive)",
    r"forget\s+(your\s+)?(instruction|prompt|rule|training|previous)",
    r"(you\s+are\s+now|act\s+as|roleplay\s+as|pretend\s+to\s+be|behave\s+as)\s+\w",
    r"new\s+(system\s+)?(prompt|instruction|rule)",
    r"(override|bypass|disregard|discard)\s+(your\s+)?(instruction|rule|guideline|training)",
    r"\bjailbreak\b",
    r"\bdan\b",                          # "Do Anything Now"
    r"developer\s*mode",
    r"\[system\]|\[assistant\]|\[inst\]",# role injection brackets
    r"<\s*(system|instruction|prompt)\s*>",  # XML/HTML role tags
    r"(reveal|show|tell\s+me|what\s+are)\s+[\w\s]{0,15}?(instruction|system\s+prompt|rule|training)",
    r"your\s+(real|true|actual)\s+(instruction|purpose|goal|mission)",
    r"(what\s+(are|were)\s+)?(your|the)\s+system\s+instruction",
    r"(sudo|admin|root)\s*:",
    r"\bbase64\s*[=:\[]",
    r"eval\s*\(|exec\s*\(|__import__",   # code injection
    r"os\.(system|popen|exec|spawn)",
    r"\\x[0-9a-f]{2}",                  # hex-escaped bypass
    r"\\u[0-9a-f]{4}",                  # unicode-escaped bypass
]

# ── Off-topic / sensitive data patterns ───────────────────────────────────────
_OFF_TOPIC = [
    r"(password|passphrase|credit\s*card|cvv|ssn|social\s+security|bank\s+account|pin\s+number|otp)",
    r"(hack|exploit|vulnerabilit|malware|virus|phishing|ransomware|sql\s+injection|xss)",
    r"(write\s+(me\s+)?(a\s+)?(poem|story|essay|novel|lyrics|rap|song))",
    r"(write\s+[\w\s]{0,20}?(function|script|code|program|class|module)(?!\s+for\s+skin))",
    r"(political|religion|election|war|weapon|drug\s+deal)",
]

# ── Safe output leak patterns (warn, don't block) ─────────────────────────────
_OUTPUT_LEAK = [
    r"my (system |)instructions? (are|say|state|include|tell me)",
    r"i was (told|instructed|programmed|trained) to",
    r"the instructions (say|state|include|tell)",
]

_INJECTION_RE  = [re.compile(p, re.IGNORECASE) for p in _INJECTION]
_OFF_TOPIC_RE  = [re.compile(p, re.IGNORECASE) for p in _OFF_TOPIC]
_OUTPUT_LEAK_RE = [re.compile(p, re.IGNORECASE) for p in _OUTPUT_LEAK]


@dataclass
class GuardrailResult:
    allowed: bool
    text: str            # sanitized input or cleaned output
    reason: str = ""


# ── Public API ────────────────────────────────────────────────────────────────

def check_input(raw: str) -> GuardrailResult:
    """
    Validate and sanitize user input before sending to the agent.
    Returns GuardrailResult(allowed=False) if the input should be blocked.
    """
    # 1. Empty / whitespace
    stripped = raw.strip()
    if len(stripped) < MIN_INPUT_CHARS:
        return GuardrailResult(False, "", "empty_input")

    # 2. Length cap (prevents token flooding)
    if len(stripped) > MAX_INPUT_CHARS:
        return GuardrailResult(
            False, "",
            f"Input too long — please keep it under {MAX_INPUT_CHARS} characters."
        )

    # 3. Unicode normalise (catches homoglyph / invisible-char bypass tricks)
    normalised = unicodedata.normalize("NFKC", stripped)
    lower = normalised.lower()

    # 4. Prompt injection check
    for rx in _INJECTION_RE:
        if rx.search(lower):
            return GuardrailResult(False, "", "prompt_injection")

    # 5. Off-topic / sensitive data
    for rx in _OFF_TOPIC_RE:
        if rx.search(lower):
            return GuardrailResult(False, "", "off_topic")

    # 6. Collapse whitespace
    sanitised = " ".join(normalised.split())
    return GuardrailResult(True, sanitised)


def check_output(raw: str) -> GuardrailResult:
    """
    Scan agent output for accidental instruction leaks.
    Rewrites the output if a leak is detected.
    """
    for rx in _OUTPUT_LEAK_RE:
        if rx.search(raw):
            # Replace the offending sentence rather than blocking the whole reply
            clean = rx.sub("[redacted]", raw)
            return GuardrailResult(True, clean, "output_leak_redacted")
    return GuardrailResult(True, raw)


# ── User-facing rejection messages ───────────────────────────────────────────
REJECTION_MESSAGES = {
    "empty_input":      "Please type something so I can help you!",
    "prompt_injection": (
        "I only help with Indian skincare advice. "
        "If you have a skin concern, I'm all ears! 🌿"
    ),
    "off_topic": (
        "That's outside my area — I'm a skincare specialist. "
        "Tell me about your skin type or concern and I'll suggest the right products!"
    ),
    "too_long": (
        f"Please keep your message under {MAX_INPUT_CHARS} characters."
    ),
}


def rejection_message(reason: str) -> str:
    return REJECTION_MESSAGES.get(reason, REJECTION_MESSAGES["off_topic"])
