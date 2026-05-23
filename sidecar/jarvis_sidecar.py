#!/usr/bin/env python3
"""
Jarvis Dictation Sidecar — JSON stdin/stdout bridge.

Reads one JSON command per line from stdin.
Writes one JSON response per line to stdout.

Supported commands:
  {"action": "ping"}
  {"action": "start_recording"}
  {"action": "stop_recording"}
  {"action": "cancel_recording"}
  {"action": "get_status"}
  {"action": "transcribe_last", "active_app": "Notion"}
  {"action": "list_microphones"}
  {"action": "test_microphone"}

FUTURE SIDECAR FEATURE GAP — wake-word / continuous listening:
  The Tauri JarvisPage saves wake_enabled, jarvis_enabled, and timing values to
  ~/.dictation_settings.json, but this sidecar does NOT implement continuous
  wake-word detection.  The Python Quill app handles "hey Jarvis" in its own
  event loop.  To support this in Tauri, add start_wake_listen /
  stop_wake_listen actions that run VAD + keyword matching on a background
  thread and push results back over stdout.
"""

import sys
import os
import json
import re
import time
import threading
import wave
import tempfile

# ── Environment guards (must be set BEFORE importing faster_whisper / onnxruntime)
# These match the stable Python app exactly.
# Without them, onnxruntime spawns multi-threaded C++ inference workers that
# trigger a GIL abort ("illegal hardware instruction") on macOS / Python 3.11.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["CT2_USE_EXPERIMENTAL_PACKED_GEMM"] = "0"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"
os.environ["MKL_DEBUG_CPU_TYPE"] = "5"        # prevents illegal-hardware-instruction crash
os.environ["ORT_DISABLE_ALL_OPTIMIZATIONS"] = "0"  # keep optimizations but force single-thread below

# ── Logging ───────────────────────────────────────────────────────────────────
def _log(msg: str):
    try:
        log_path = os.path.expanduser("~/jarvis_sidecar.log")
        with open(log_path, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass

# ── Settings ──────────────────────────────────────────────────────────────────
SETTINGS_FILE  = os.path.expanduser("~/.dictation_settings.json")
VOCAB_FILE     = os.path.expanduser("~/.dictation_vocabulary.json")
SNIPPETS_FILE  = os.path.expanduser("~/.dictation_snippets.json")

def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

# ── Writing profiles (ported from jarvis_dictation.py) ───────────────────────
WRITING_PROFILES = {
    "General": (
        "Use balanced everyday dictation cleanup. Preserve the speaker's wording and intent."
    ),
    "Professional": (
        "Make the text clear, polished, and professional without sounding stiff. Do not add content."
    ),
    "Email": (
        "Use complete sentences and a polite professional tone. Do not add greetings, sign-offs, subjects, or recipients unless dictated."
    ),
    "Developer": (
        "Preserve technical terms, commands, package names, filenames, paths, variables, acronyms, casing, and symbols. Do not convert commands into prose."
    ),
    "Medical": (
        "Preserve clinical terminology, medication names, measurements, acronyms, and dictated structure. Do not infer diagnoses, findings, or clinical facts."
    ),
    "Legal": (
        "Use precise formal language. Preserve names, dates, clauses, citations, and quoted language. Do not invent facts or legal conclusions."
    ),
    "Sales": (
        "Make the text concise, client-friendly, persuasive, and clear while preserving factual meaning."
    ),
    "Notes": (
        "Format as clean notes when appropriate. Keep wording concise. Use bullets only if the speaker clearly dictated a list."
    ),
    "Creative": (
        "Improve flow and readability while preserving the speaker's voice, style, and meaning."
    ),
    "Verbatim": (
        "Use minimal cleanup only. Preserve the original wording. Fix only punctuation, spacing, capitalization, and obvious recognition errors."
    ),
}

# ── App → profile auto-detection rules ───────────────────────────────────────
APP_PROFILE_RULES = {
    "mail":               "Email",
    "spark":              "Email",
    "spark desktop":      "Email",
    "readdle":            "Email",
    "outlook":            "Email",
    "gmail":              "Email",
    "terminal":           "Developer",
    "iterm":              "Developer",
    "visual studio code": "Developer",
    "code":               "Developer",
    "xcode":              "Developer",
    "notes":              "Notes",
    "notion":             "Notes",
    "obsidian":           "Notes",
    "word":               "Professional",
    "pages":              "Professional",
    "slack":              "General",
    "messages":           "General",
    "teams":              "General",
}

# ── App → format rules (rule-based, no LLM) ──────────────────────────────────
APP_FORMAT_RULES = {
    "mail":               "email",
    "spark":              "email",
    "spark desktop":      "email",
    "readdle":            "email",
    "outlook":            "email",
    "notes":              "notes",
    "iterm":              "terminal",
    "terminal":           "terminal",
    "code":               "terminal",
    "visual studio code": "terminal",
    "messages":           "casual",
    "slack":              "casual",
}

# ── Ollama base system prompt ─────────────────────────────────────────────────
_OLLAMA_SYSTEM_PROMPT = (
    "You are a dictation cleanup engine. "
    "Correct only the text the user dictated. "
    "Preserve the user's exact meaning, wording, and intent. "
    "Do not answer questions. "
    "Do not continue the conversation. "
    "Do not add new information. "
    "Do not expand short phrases into longer responses. "
    "Do not rewrite the text unless it is clearly needed. "
    "Fix obvious speech-to-text errors, punctuation, capitalization, grammar, and spacing. "
    "If the input is already clear, return it unchanged. "
    "Return only the corrected dictation text."
)

# ── Word-to-digit map ─────────────────────────────────────────────────────────
WORD_TO_NUM = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "it", "i", "you", "we", "he", "she", "they",
    "this", "that", "was", "are", "be", "been", "have", "has", "had",
    "do", "did", "will", "would", "could", "should", "not", "no", "so",
    "if", "as", "by", "up", "out", "about", "just", "like", "from",
    "what", "when", "where", "how", "why", "who", "my", "your", "its",
    "our", "their", "testing", "one", "two", "three", "four", "five",
    "okay", "yes", "no",
}

# ── Profile / prompt helpers ──────────────────────────────────────────────────

def get_active_writing_profile(settings: dict, active_app: str | None = None) -> str:
    """Return the writing profile, optionally auto-detected from the active app name."""
    default = settings.get("writing_profile", "General")
    if default not in WRITING_PROFILES:
        default = "General"

    if settings.get("auto_profile_detection", True) and active_app:
        app_lower = active_app.lower()
        for key, profile in APP_PROFILE_RULES.items():
            if key in app_lower and profile in WRITING_PROFILES:
                return profile

    return default


def build_ollama_system_prompt(profile: str, strength: str) -> str:
    """Build full Ollama system prompt from profile + correction strength."""
    if profile not in WRITING_PROFILES:
        profile = "General"

    prompt = (
        _OLLAMA_SYSTEM_PROMPT + " "
        f"Active writing profile: {profile}. "
        + WRITING_PROFILES[profile] + " "
    )

    if strength == "Light":
        return (
            prompt +
            "Use light correction only: punctuation, capitalization, spacing, and obvious word errors. "
            "Keep the original wording whenever possible."
        )
    if strength == "Strong":
        return (
            prompt +
            "You may smooth awkward dictated phrasing, but you must not add ideas, answer questions, or change the speaker's intent."
        )
    # Standard (default)
    return prompt


# ── Ollama safety filter (ported from jarvis_dictation.py) ───────────────────

def _dictation_words(text: str) -> list:
    return re.findall(r"[a-zA-Z0-9']+", text or "")


def _is_question_like(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    question_starters = (
        "what", "when", "where", "who", "why", "how", "which", "whose",
        "is", "are", "was", "were", "will", "would", "could", "should",
        "do", "does", "did", "have", "has", "had", "can", "may", "might",
        "am", "isn't", "aren't", "wasn't", "weren't", "don't", "doesn't",
    )
    first = _dictation_words(t)[:1]
    return t.endswith("?") or (first and first[0] in question_starters)


def _looks_like_assistant_answer(text: str) -> bool:
    t = (text or "").strip().lower()
    suspicious_starts = (
        "sure", "certainly", "here is", "here's", "i can", "i will",
        "you should", "the next", "next is", "to improve", "it sounds like",
        "based on", "as an ai", "let's", "we should", "you asked",
        "the answer", "this means",
    )
    return any(t.startswith(p) for p in suspicious_starts)


def ollama_result_is_safe(original: str, refined: str) -> tuple:
    """Return (ok: bool, reason: str). Reject expansions, replies, meaning changes."""
    if not refined or refined.lower().strip() == "nothing":
        return False, "empty result"

    orig = (original or "").strip()
    out  = (refined or "").strip()
    if not orig:
        return False, "empty original"

    orig_words = _dictation_words(orig.lower())
    out_words  = _dictation_words(out.lower())
    if not out_words:
        return False, "empty output"

    # Most dangerous: short prompt becomes a long assistant answer
    if len(orig_words) <= 6 and len(out_words) > max(10, len(orig_words) * 3):
        return False, "expanded short dictation"

    if _is_question_like(orig) and not _is_question_like(out):
        return False, "question became non-question"

    if _looks_like_assistant_answer(out):
        return False, "looks like assistant response"

    orig_set = set(orig_words)
    if len(orig_words) >= 3 and orig_set:
        new_words = [w for w in out_words if w not in orig_set]
        if len(new_words) > max(6, len(orig_words)):
            return False, "too many new words"

    if len(out) > max(len(orig) * 2.2, len(orig) + 80):
        return False, "output too long"

    return True, "accepted"


# ── Vocabulary helpers ────────────────────────────────────────────────────────

def get_personal_prompt(settings: dict) -> str:
    """Build Whisper initial_prompt from manual vocabulary + learned words."""
    try:
        manual_vocab = settings.get("manual_vocabulary", "").strip()

        top_words: list = []
        try:
            with open(VOCAB_FILE) as f:
                vocab = json.load(f)
            word_counts = vocab.get("word_counts", {})
            top_words = sorted(word_counts, key=word_counts.get, reverse=True)[:20]
        except Exception:
            pass

        prompt = "Transcribe accurately."
        if manual_vocab:
            prompt += f" Technical terms: {manual_vocab}."
        if top_words:
            prompt += f" Common words: {', '.join(top_words)}."
        return prompt
    except Exception:
        return "Transcribe spoken English accurately."


def learn_from_text(text: str):
    """Update vocabulary word counts after each dictation."""
    try:
        vocab = {"word_counts": {}, "total_dictations": 0, "phrases": {}}
        try:
            with open(VOCAB_FILE) as f:
                vocab = json.load(f)
        except Exception:
            pass

        vocab["total_dictations"] = vocab.get("total_dictations", 0) + 1
        words = re.findall(r"[a-zA-Z']+", text.lower())
        for word in words:
            if len(word) > 3 and word not in STOPWORDS:
                vocab["word_counts"][word] = vocab["word_counts"].get(word, 0) + 1
        for i in range(len(words) - 1):
            phrase = words[i] + " " + words[i + 1]
            if not any(w in STOPWORDS for w in [words[i], words[i + 1]]):
                vocab["phrases"][phrase] = vocab["phrases"].get(phrase, 0) + 1

        with open(VOCAB_FILE, "w") as f:
            json.dump(vocab, f, indent=2)
    except Exception as e:
        _log(f"learn_from_text error: {e}")


# ── Snippets ──────────────────────────────────────────────────────────────────

def apply_snippets(text: str) -> str:
    """Replace exact trigger phrases with their expanded snippets."""
    try:
        with open(SNIPPETS_FILE) as f:
            snippets = json.load(f)
        lower = text.strip().lower().rstrip(".,!?")
        for trigger, expansion in snippets.items():
            if lower == trigger.lower():
                return expansion
    except Exception:
        pass
    return text


# ── Mojibake repair ───────────────────────────────────────────────────────────

_MOJIBAKE_MAP = [
    ("¬¨‚Ä†",  " "),   # non-breaking space rendered via two-byte mojibake
    ("¬†",      " "),   # lone variant
    ("Â ",      " "),   # UTF-8 NBSP decoded as Latin-1
    (" ",  " "),   # actual Unicode non-breaking space
    ("‚Äô",    "'"),   # right single quotation mark
    ("‚Äú",    '"'),   # left double quotation mark
    ("‚Äù",    '"'),   # right double quotation mark
    ("‚Äì",    "-"),   # en dash
    ("‚Äî",    "-"),   # em dash
    ("‚Ä¶",    "..."), # horizontal ellipsis
    # MacRoman mojibake: UTF-8 bytes misread as Mac OS Roman
    ("√©", "é"),  ("√®", "è"),  ("√™", "ê"),  ("√´", "ë"),
    ("√†", "à"),  ("√¢", "â"),  ("√ß", "ç"),  ("√Æ", "î"),
    ("√Ø", "ï"),  ("√¥", "ô"),  ("√π", "ù"),  ("√ª", "û"),
    ("√º", "ü"),  ("≈ì", "œ"),  ("√¶", "æ"),
    ("√â", "É"),  ("√à", "È"),  ("√ä", "Ê"),  ("√ã", "Ë"),
    ("√Ä", "À"),  ("√Ç", "Â"),  ("√á", "Ç"),  ("√é", "Î"),
    ("√è", "Ï"),  ("√î", "Ô"),  ("√ô", "Ù"),  ("√õ", "Û"),
    ("√ú", "Ü"),  ("≈í", "Œ"),  ("√Ü", "Æ"),  ("√±", "ñ"),
    ("√ë", "Ñ"),
]

def repair_mojibake(text: str) -> str:
    """Replace mojibake sequences, collapse multiple spaces, fix space-before-punct."""
    if not text:
        return text
    for bad, good in _MOJIBAKE_MAP:
        text = text.replace(bad, good)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return text


# ── Profile aliases (multi-word phrase → abbreviation) ────────────────────────
# Only multi-word source phrases are allowed as keys — never single words —
# to prevent dangerous substitutions (e.g. "I" → "UI").
# Ported from jarvis_dictation.py PROFILE_ALIASES.

PROFILE_ALIASES: dict[str, dict[str, str]] = {
    "Developer": {
        # HUD mis-transcription fixes
        "the had":      "the HUD",
        "this had":     "this HUD",
        "that had":     "that HUD",
        "had window":   "HUD window",
        "had overlay":  "HUD overlay",
        "had card":     "HUD card",
        "had icon":     "HUD icon",
        "had position": "HUD position",
        "had setting":  "HUD setting",
        "had settings": "HUD settings",
        # Standard abbreviations
        "user interface":                    "UI",
        "user experience":                   "UX",
        "application programming interface": "API",
        "java script object notation":       "JSON",
        "type script":                       "TypeScript",
        "java script":                       "JavaScript",
        "local host":                        "localhost",
        "pull request":                      "PR",
        "command line interface":            "CLI",
        "continuous integration":            "CI",
        "continuous deployment":             "CD",
        "continuous delivery":               "CD",
    },
    "Medical": {
        "blood pressure":             "BP",
        "heart rate":                 "HR",
        "electrocardiogram":          "ECG",
        "magnetic resonance imaging": "MRI",
        "computed tomography":        "CT",
        "body mass index":            "BMI",
        "complete blood count":       "CBC",
        "beats per minute":           "BPM",
    },
    "Legal": {
        "limited liability company":     "LLC",
        "limited liability partnership": "LLP",
    },
    "Sales": {
        "customer relationship management": "CRM",
        "key performance indicator":        "KPI",
        "return on investment":             "ROI",
        "marketing qualified lead":         "MQL",
        "sales qualified lead":             "SQL",
    },
}

_URL_EMAIL_RE = re.compile(r'https?://\S+|www\.\S+|\S+@\S+\.\S+')

def apply_profile_aliases(text: str, profile: str) -> str:
    """Replace spoken multi-word phrases with profile-specific abbreviations.

    Only multi-word source phrases — never single-word keys — so "I" can never
    accidentally map to "UI".  Longest phrase matched first.
    URLs and email addresses are masked so they survive unchanged.
    """
    aliases = PROFILE_ALIASES.get(profile)
    if not aliases:
        return text

    masks: list[tuple[str, str]] = []
    def _mask(m: re.Match) -> str:
        token = f"\x00MASK{len(masks)}\x00"
        masks.append((token, m.group(0)))
        return token
    masked = _URL_EMAIL_RE.sub(_mask, text)

    for phrase in sorted(aliases, key=len, reverse=True):
        replacement = aliases[phrase]
        pat = re.compile(r'\b' + re.escape(phrase) + r'\b', re.IGNORECASE)
        masked = pat.sub(replacement, masked)

    for token, original in masks:
        masked = masked.replace(token, original)
    return masked


# ── Developer-profile contextual fixes ───────────────────────────────────────

_UI_CONTEXT_WORDS: frozenset = frozenset({
    "website", "app", "screen", "page", "layout", "design", "interface",
    "button", "menu", "card", "settings", "frontend", "component", "modal",
    "dashboard", "sidebar", "header", "footer", "navbar", "dropdown",
    "form", "dialog", "popup", "panel", "widget", "theme", "css", "html",
    "responsive", "mobile", "desktop", "viewport", "animation", "icon",
})
_UI_VERB_RE = re.compile(
    r'(must|should|needs|looks|renders|displays|shows|updates|loads|'
    r'crashes|breaks|feels|appears|handles|requires|supports|allows)',
    re.IGNORECASE,
)

def _apply_ui_context_fix(text: str, profile: str) -> str:
    """Correct Whisper's mis-transcription of 'UI' as 'I' in Developer profile."""
    if profile != "Developer":
        return text
    # Tier 1: determiner-anchored
    text = re.sub(r'\b(the|this|that|our|your|its)\s+I\b',
                  lambda m: m.group(1) + " UI", text, flags=re.IGNORECASE)
    # Tier 2: sentence-start + visual verb
    text = re.sub(r'(^|(?<=[.!?])\s+)I\s+(' + _UI_VERB_RE.pattern + r')\b',
                  lambda m: m.group(1) + "UI " + m.group(2),
                  text, flags=re.IGNORECASE | re.MULTILINE)
    # Tier 3: context-word triggered
    text_words = set(re.findall(r'\b\w+\b', text.lower()))
    if not (text_words & _UI_CONTEXT_WORDS):
        return text
    text = re.sub(r'\bI\s+on\b', 'UI on', text, flags=re.IGNORECASE)
    text = re.sub(r'(^|(?<=[.!?])\s+)I\s+(is|was|has|will|can|would|needs to|should be)\b',
                  lambda m: m.group(1) + "UI " + m.group(2),
                  text, flags=re.IGNORECASE | re.MULTILINE)
    return text

_HUD_CONTEXT_WORDS: frozenset = frozenset({
    "window", "overlay", "card", "settings", "setting", "icon",
    "position", "floating", "recording", "dictation", "interface",
    "screen", "transparent", "rounded", "corner", "resize", "drag",
    "visible", "hidden", "opacity", "titlebar", "menubar", "panel",
    "display", "layer", "mode", "state",
})

def _apply_hud_context_fix(text: str, profile: str) -> str:
    """Correct Whisper's mis-transcription of 'HUD' as 'had'/'hud' in Developer profile."""
    if profile != "Developer":
        return text
    # Tier 1: casing normalisation
    text = re.sub(r'\bh\s+u\s+d\b', 'HUD', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhud\b', 'HUD', text, flags=re.IGNORECASE)
    # Tier 2: contextual "had" → "HUD"
    text_words = set(re.findall(r'\b\w+\b', text.lower()))
    if not (text_words & _HUD_CONTEXT_WORDS):
        return text
    _noun = r'(window|overlay|card|icon|position|setting|settings|panel|display|bar|mode|state|view|layer|opacity|size)'
    text = re.sub(r'\bhad\s+' + _noun + r'\b',
                  lambda m: 'HUD ' + m.group(1), text, flags=re.IGNORECASE)
    text = re.sub(r'\b(the|this|that|our|your|its)\s+had\b',
                  lambda m: m.group(1) + ' HUD', text, flags=re.IGNORECASE)
    return text


# ── Inline linebreaks ─────────────────────────────────────────────────────────

def apply_inline_linebreaks(text: str) -> str:
    """Convert spoken 'next line' / 'next paragraph' markers to real line breaks."""
    text = re.sub(r'\s*\bnext paragraph\b\s*', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*\bnew paragraph\b\s*',  '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*\bnext line\b\s*',      '\n',   text, flags=re.IGNORECASE)
    return text.strip()


# ── Personal corrections (vocab["corrections"]) ───────────────────────────────

def apply_corrections(text: str) -> str:
    """Apply user-defined corrections (wrong → right) from vocabulary file.

    - Case-insensitive, word-boundary-anchored matching.
    - Longest phrase matched first so short keys can't shadow long ones.
    - Replacement is preserved exactly as the user entered it.
    - Safe for all languages — user controls the mappings.
    """
    try:
        with open(VOCAB_FILE) as f:
            vocab = json.load(f)
        corrections: dict[str, str] = vocab.get("corrections", {})
        if not corrections:
            return text
        for wrong in sorted(corrections, key=len, reverse=True):
            right = corrections[wrong]
            pattern = re.compile(r'\b' + re.escape(wrong) + r'\b', re.IGNORECASE)
            text = pattern.sub(lambda _m, r=right: r, text)
    except Exception:
        pass
    return text


# ── SymSpell typo correction ──────────────────────────────────────────────────
# Graceful degradation: if symspellpy is not installed, symspell_correct is a no-op.
# Install with: pip install symspellpy

try:
    from symspellpy import SymSpell, Verbosity as _Verbosity
    import symspellpy as _symspellpy_pkg
    _sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    _SYMSPELL_DICT = os.path.join(
        os.path.dirname(_symspellpy_pkg.__file__),
        "frequency_dictionary_en_82_765.txt",
    )
    _USE_SYMSPELL = os.path.exists(_SYMSPELL_DICT) and _sym.load_dictionary(
        _SYMSPELL_DICT, term_index=0, count_index=1
    )
except ImportError:
    _USE_SYMSPELL = False

def symspell_correct(text: str) -> str:
    """Apply SymSpell word-level typo correction.

    Safety rules (mirrors Python jarvis_dictation.py):
    - Only corrects pure alpha words with optional trailing punctuation.
    - Skips words containing digits, underscores, slashes, or dots
      (protects code, paths, URLs, snake_case, camelCase, acronyms).
    - Skips ALL-CAPS words (acronyms like API, HUD, PR).
    - Skips CamelCase words (TypeScript, iPhone, etc.).
    - English dictionary only — caller must skip for non-English.
    - Returns text unchanged if symspellpy is unavailable.
    """
    if not _USE_SYMSPELL:
        return text
    words = text.split()
    corrected = []
    for word in words:
        m = re.match(r"^([a-zA-Z']+)([.,!?;:]*)$", word)
        if not m:
            # Contains digit, underscore, slash, dot, etc. — skip
            corrected.append(word)
            continue
        core, punct = m.group(1), m.group(2)
        # Skip ALL-CAPS (acronyms) and CamelCase (product names)
        if core.isupper() or (core != core.lower() and core != core.capitalize()):
            corrected.append(word)
            continue
        suggestions = _sym.lookup(core.lower(), _Verbosity.CLOSEST, max_edit_distance=2)
        if suggestions:
            s = suggestions[0].term
            if core[0].isupper():
                s = s.capitalize()
            corrected.append(s + punct)
        else:
            corrected.append(word)
    return " ".join(corrected)


# ── Text post-processing ──────────────────────────────────────────────────────

def smart_punctuate(text: str) -> str:
    """Add terminal punctuation if missing."""
    if not text or text.rstrip()[-1] in ".!?":
        return text
    question_starters = (
        "what", "when", "where", "who", "why", "how", "which", "whose",
        "is ", "are ", "was ", "were ", "will ", "would ", "could ", "should ",
        "do ", "does ", "did ", "have ", "has ", "had ", "can ", "may ",
        "might ", "shall ", "am ", "isn't", "aren't", "wasn't", "weren't",
        "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't",
    )
    if any(text.lower().strip().startswith(q) for q in question_starters):
        return text.rstrip() + "?"
    return text.rstrip() + "."


def words_to_digits(text: str) -> str:
    """Convert spoken number words to digits."""
    def replace(m):
        return WORD_TO_NUM.get(m.group(0).lower(), m.group(0))
    pattern = r'\b(' + '|'.join(re.escape(k) for k in WORD_TO_NUM.keys()) + r')\b'
    return re.sub(pattern, replace, text, flags=re.IGNORECASE)


def format_for_app(text: str, app_name: str) -> str:
    """Rule-based formatting — no LLM required."""
    if not app_name:
        return text
    app_lower = app_name.lower()
    rule_key = next((k for k in APP_FORMAT_RULES if k in app_lower), None)
    if not rule_key:
        return text

    rule = APP_FORMAT_RULES[rule_key]
    text = text.strip()
    if not text:
        return text

    # Capitalize first letter for all rules
    text = text[0].upper() + text[1:]

    if rule == "email":
        if text[-1] not in ".!?":
            text += "."
        text = re.sub(r'(\.\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), text)

    elif rule == "casual":
        if text.endswith("."):
            text = text[:-1]

    elif rule == "terminal":
        text = text.lower().strip()
        if text.endswith("."):
            text = text[:-1]

    _log(f"format_for_app: '{app_name}' → rule='{rule}'")
    return text


# ── Strip common Ollama preamble patterns ─────────────────────────────────────

def strip_ollama_preamble(text: str) -> str:
    for prefix in (
        "Corrected transcription:", "Corrected:", "Here is the corrected",
        "Here's the corrected", "Output:", "Result:",
    ):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break
    # If model returned multiple lines, take only the last non-empty one
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) > 1:
        text = lines[-1]
    return text


# ── Audio state ───────────────────────────────────────────────────────────────
_recording     = False
_audio_frames: list = []
_audio_lock    = threading.Lock()
_stream        = None        # recording InputStream (user sample_rate)
_last_result: dict | None = None

CHUNK = 1024

# ── Live VAD state (updated by recording callback, read by get_status) ────────
# Updated every ~21 ms (1024 samples @ 48 kHz) from the sounddevice callback.
# Globals are read/written under Python's GIL so no explicit lock is needed for
# simple scalar assignments.  Worst case is reading one stale frame — acceptable.
_live_audio_rms: float = 0.0

# Rolling noise floor — adapts slowly to room ambience.
# Updated only when voice is NOT active, so speech cannot raise the floor.
# Formula: floor = floor*0.98 + rms*0.02  (τ ≈ 49 callbacks ≈ 1 s at 48 kHz/1024)
# Initial value 0.01 suits a typical quiet-to-moderate room.
_noise_floor: float = 0.01

# True when current RMS is clearly above the noise floor (speech, not fan/AC).
# Threshold: rms > max(floor * 2.5, 0.012) — the 0.012 floor ensures we always
# require a minimum absolute level even in very quiet rooms.
_voice_active: bool = False

# ── Wake-word state ───────────────────────────────────────────────────────────
# Architecture: one mic stream at a time.
#   _wake_stream  — 16 kHz InputStream, only open when wake listening AND not recording
#   _stream       — recording InputStream, only open during active recording
# cmd_start_recording closes _wake_stream; cmd_stop/cancel_recording re-opens it.
_wake_listening    = False        # True while wake listener is active
_wake_stream       = None         # 16 kHz sounddevice InputStream
_wake_frames: list = []
_wake_lock         = threading.Lock()
_wake_detected     = False        # set by wake thread, consumed atomically by get_wake_status
_wake_thread: threading.Thread | None = None
_wake_thread_stop  = threading.Event()

WAKE_SAMPLE_RATE   = 16000        # openwakeword requires 16 kHz input
WAKE_THRESHOLD     = 0.5          # detection score threshold (0–1)

# ── Whisper model (lazy loaded) ───────────────────────────────────────────────
_model      = None
_model_name = None

def _get_model(model_name: str):
    global _model, _model_name
    if _model is None or _model_name != model_name:
        _log(f"Loading Whisper model: {model_name}")
        from faster_whisper import WhisperModel
        _model = WhisperModel(model_name, device="cpu", compute_type="int8")
        _model_name = model_name
    return _model

# ── Wake-word helpers ─────────────────────────────────────────────────────────

def _wake_audio_callback(indata, frames, time_info, status):
    """Callback for the wake-word InputStream — feeds _wake_frames only."""
    if _wake_listening and not _recording:
        with _wake_lock:
            _wake_frames.append(indata.copy())


def _resume_wake_stream():
    """Re-open the wake stream after recording ends (if wake_listening is still active).
    Called from cmd_stop_recording and cmd_cancel_recording."""
    global _wake_stream
    if not _wake_listening:
        return
    # Flush any audio that built up while the stream was paused.
    # The wake loop processes _wake_frames in its next iteration — without this
    # clear, stale frames (including the original wake word utterance) could
    # cause an immediate spurious re-detection right after recording ends.
    with _wake_lock:
        _wake_frames.clear()
    settings   = load_settings()
    mic_device = settings.get("mic_device", None)
    try:
        import sounddevice as sd
        device, _ = _resolve_input_device(mic_device, WAKE_SAMPLE_RATE)
        _wake_stream = sd.InputStream(
            samplerate=WAKE_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=device,
            blocksize=CHUNK,
            callback=_wake_audio_callback,
        )
        _wake_stream.start()
        _log(f"Wake stream resumed: device={device}")
    except Exception as e:
        _log(f"Wake stream resume error (non-fatal): {e}")


def _load_wake_model():
    """Load the openwakeword model on the CALLING thread.

    MUST be called from the main thread (or any thread that is the only writer
    to sys.stdout at that moment).  We use contextlib.redirect_stdout to suppress
    openwakeword's startup chatter — if this ran in a background thread while the
    main thread was writing JSON responses, redirect_stdout would silently eat those
    responses and corrupt the protocol.

    Returns the loaded model, or None on failure.
    """
    import io, contextlib
    import numpy as np  # ensure numpy is imported before onnxruntime to avoid conflict

    _oww_buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_oww_buf):
            from openwakeword.model import Model as _WakeModel
            try:
                import onnxruntime as _ort
                _sess_opts = _ort.SessionOptions()
                _sess_opts.inter_op_num_threads = 1
                _sess_opts.intra_op_num_threads = 1
                _sess_opts.execution_mode = _ort.ExecutionMode.ORT_SEQUENTIAL
                oww = _WakeModel(
                    wakeword_models=["hey_jarvis"],
                    inference_framework="onnx",
                    openwakeword_models_kwargs={"sess_options": _sess_opts},
                )
                _log("Wake model loaded with ORT_SEQUENTIAL single-thread session")
            except Exception as _ort_e:
                # openwakeword_models_kwargs not accepted by this version — fall back
                _log(f"Wake model: ORT SessionOptions unavailable ({_ort_e}), using defaults")
                oww = _WakeModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")
                _log("Wake model loaded (fallback, no session options)")
        return oww
    except ImportError:
        _log("Wake model: openwakeword not available")
        return None
    except Exception as e:
        _log(f"Wake model load failed: {e}")
        return None


def _wake_loop(oww) -> None:
    """Background thread: feed 16 kHz audio to openwakeword, set _wake_detected on hit.
    Runs for the lifetime of the wake listener — stopped via _wake_thread_stop event.

    `oww` is the pre-loaded Model instance (loaded by cmd_start_wake_listen on the
    main thread so that the redirect_stdout suppression cannot race with the main
    thread's JSON protocol writes).

    Parity with stable Python app:
      - backlog cap to avoid runaway catch-up after a slow predict
      - oww.reset() after detection to clear stale model state
      - time.sleep(0) between chunks to yield GIL to the main command thread
    """
    global _wake_detected
    import numpy as np
    _log("Wake loop: starting")

    buf: list = []        # accumulates int16 samples between poll cycles
    CHUNK_SAMPLES = 1280  # 80 ms at 16 kHz — openwakeword's expected frame size
    # Backlog cap: ~3 seconds of 16 kHz audio = 3 × 16000 = 48000 int16 samples.
    # If predict() falls behind, drop the oldest half rather than running a long
    # catch-up loop that starves the main command thread.
    BACKLOG_CAP = 48000

    while not _wake_thread_stop.is_set():
        # Grab all pending frames
        with _wake_lock:
            frames = list(_wake_frames)
            _wake_frames.clear()

        if frames:
            audio = np.concatenate(frames, axis=0).flatten()
            # Convert float32 → int16 (openwakeword expects int16 PCM at 16 kHz)
            audio_i16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            buf.extend(audio_i16.tolist())

            # Backlog guard: if more than ~3 s has accumulated, drop the oldest half.
            if len(buf) > BACKLOG_CAP:
                drop = len(buf) - BACKLOG_CAP // 2
                buf = buf[drop:]
                _log(f"Wake backlog trimmed: dropped {drop} samples, kept {len(buf)}")

            # Process 80 ms chunks; yield GIL between each predict so the main
            # command thread can respond to get_wake_status / stop_wake_listen.
            triggered = False
            while len(buf) >= CHUNK_SAMPLES and not _wake_thread_stop.is_set():
                chunk = np.array(buf[:CHUNK_SAMPLES], dtype=np.int16)
                buf = buf[CHUNK_SAMPLES:]
                try:
                    import time as _time
                    _time.sleep(0)  # yield GIL to main thread between predictions
                    scores = oww.predict(chunk)
                    # Model key may be "hey_jarvis" or "hey_jarvis_v0.1" depending on version
                    score = max(
                        float(scores.get("hey_jarvis",      0)),
                        float(scores.get("hey_jarvis_v0.1", 0)),
                    )
                    if score >= WAKE_THRESHOLD:
                        _log(f"Wake word detected — score={score:.3f}")
                        _wake_detected = True
                        buf.clear()
                        triggered = True
                        # Reset model state to clear stale prediction buffer (matches stable Python)
                        try:
                            oww.reset()
                        except Exception:
                            pass
                        # 1.5 s cooldown so a single wake phrase doesn't trigger twice
                        _wake_thread_stop.wait(1.5)
                        break
                except Exception as e:
                    _log(f"Wake predict error: {e}")
                    buf.clear()
                    break
            if triggered:
                continue
        else:
            # No new audio — sleep briefly
            _wake_thread_stop.wait(0.05)

    _log("Wake loop: stopped")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_ping(_cmd: dict) -> dict:
    return {"ok": True, "pong": True}


def _resolve_input_device(mic_device, sample_rate):
    """Return (device, channels) — falls back to system default if needed."""
    import sounddevice as sd

    if mic_device is not None:
        try:
            info = sd.query_devices(int(mic_device))
            if info["max_input_channels"] < 1:
                _log(f"Device {mic_device} has no input channels, using system default")
                mic_device = None
        except Exception:
            _log(f"Device {mic_device} not found, using system default")
            mic_device = None

    try:
        if mic_device is not None:
            info = sd.query_devices(int(mic_device))
        else:
            info = sd.query_devices(kind="input")
        native_ch = int(info["max_input_channels"])
    except Exception:
        native_ch = 1

    channels = 1 if native_ch >= 1 else native_ch
    return mic_device, channels


def cmd_start_recording(_cmd: dict) -> dict:
    global _recording, _audio_frames, _stream, _wake_stream
    if _recording:
        return {"ok": False, "error": "already recording"}

    # Close wake stream so the mic is free for recording.
    # _wake_listening stays True — the stream is re-opened by _resume_wake_stream()
    # after recording ends.
    if _wake_stream is not None:
        try:
            _wake_stream.stop()
            _wake_stream.close()
        except Exception:
            pass
        _wake_stream = None
        # Discard any audio that accumulated in the wake buffer before the stream
        # closed.  The wake loop runs as a daemon thread and may still process
        # these frames after the stream is paused, potentially re-detecting the
        # wake word immediately when _resume_wake_stream() re-opens the stream.
        with _wake_lock:
            _wake_frames.clear()
        _log("Wake stream paused for recording")

    with _audio_lock:
        _audio_frames = []
    _recording = True

    settings    = load_settings()
    mic_device  = settings.get("mic_device", None)
    sample_rate = settings.get("sample_rate", 48000)

    try:
        import sounddevice as sd
        import numpy as _np  # captured in closure — avoids per-call import overhead
        device, channels = _resolve_input_device(mic_device, sample_rate)

        def _callback(indata, frames, time_info, status):
            """Called by sounddevice on every audio block (~21 ms at 48 kHz / 1024 blocksize).

            Responsibilities:
              1. Append frame to _audio_frames for transcription.
              2. Compute lightweight RMS and update the rolling noise floor + VAD flag.
                 These are read by cmd_get_status to drive the HUD waveform and
                 the wake auto-stop monitor in the frontend.

            VAD logic (matches stable Python _silence_stop_monitor approach):
              noise_floor adapts slowly to room ambience — only while NOT speaking.
              voice_active = rms clearly exceeds noise_floor, so fan/AC noise
              (steady, low-level) does not falsely trigger speech detection.
            """
            global _live_audio_rms, _noise_floor, _voice_active
            if _recording:
                with _audio_lock:
                    _audio_frames.append(indata.copy())
                try:
                    rms = float(_np.sqrt(_np.mean(indata.astype("float32") ** 2)))
                    _live_audio_rms = rms
                    # Voice active when RMS is clearly above the noise floor.
                    va = rms > max(_noise_floor * 2.5, 0.012)
                    _voice_active = va
                    # Only update floor when silent — speech must not raise the floor.
                    if not va:
                        _noise_floor = _noise_floor * 0.98 + rms * 0.02
                except Exception:
                    pass  # never let a frame error kill the audio stream

        _stream = sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            device=device,
            blocksize=CHUNK,
            callback=_callback,
        )
        _stream.start()
        _log(f"Recording started: device={device} channels={channels} rate={sample_rate}")
        return {"ok": True, "status": "recording"}
    except Exception as e:
        _recording = False
        _log(f"start_recording error: {e}")
        return {"ok": False, "error": str(e)}


def cmd_stop_recording(_cmd: dict) -> dict:
    global _recording, _stream
    _recording = False
    if _stream:
        try:
            _stream.stop()
            _stream.close()
        except Exception:
            pass
        _stream = None
    _log("Recording stopped")
    _resume_wake_stream()   # re-open wake stream if still enabled
    return {"ok": True, "status": "stopped"}


def cmd_get_status(_cmd: dict) -> dict:
    """Return sidecar recording state, live RMS, and voice-activity flag.

    Values are read from module-level globals updated by the sounddevice callback
    every ~21 ms — no lock or numpy computation needed here.

    recording_rms : float | None — raw RMS of the most recent audio frame.
                    Drives subtle waveform movement even during background noise.
    voice_active  : bool — True only when RMS is clearly above the rolling noise
                    floor (speech, not fan/AC).  Used by:
                      • HudApp.tsx  — scales waveform bars up only during speech
                      • useGlobalHotkey.ts wake monitor — resets silence window
    """
    return {
        "ok": True,
        "recording": _recording,
        "has_audio": len(_audio_frames) > 0,
        "recording_rms": _live_audio_rms if _recording else None,
        "voice_active":  _voice_active  if _recording else False,
    }


def cmd_transcribe_last(cmd: dict) -> dict:
    global _last_result
    t_total_start = time.time()

    settings    = load_settings()
    quality     = settings.get("dictation_quality", "Balanced")
    model_override = settings.get("model", "")
    language    = settings.get("language", "en") or None
    auto_detect = settings.get("auto_detect", False)
    translate_target = settings.get("translate_my_dictation", "Off")

    # Active app passed from Rust (for auto profile detection)
    active_app  = cmd.get("active_app") or ""

    quality_to_model = {"Fast": "tiny.en", "Balanced": "small.en", "Accurate": "medium.en"}
    if auto_detect or (language and language != "en"):
        quality_to_model = {"Fast": "tiny", "Balanced": "small", "Accurate": "medium"}

    model_name = model_override if model_override else quality_to_model.get(quality, "small.en")

    with _audio_lock:
        frames = list(_audio_frames)

    if not frames:
        return {"ok": False, "error": "no audio recorded"}

    # ── Write WAV ──────────────────────────────────────────────────────────────
    sample_rate = settings.get("sample_rate", 48000)
    import numpy as np
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        audio = np.concatenate(frames, axis=0)
        if audio.ndim > 1 and audio.shape[1] > 1:
            audio = audio.mean(axis=1)
        audio = audio.flatten()
        audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        # ── Transcribe with Whisper ────────────────────────────────────────────
        t_whisper_start = time.time()
        model = _get_model(model_name)
        transcribe_kwargs: dict = {}
        if language and not auto_detect:
            transcribe_kwargs["language"] = language

        # Build initial_prompt from vocabulary (manual + learned)
        if not model_name.startswith("distil-"):
            personal_prompt = get_personal_prompt(settings)
            if personal_prompt:
                transcribe_kwargs["initial_prompt"] = personal_prompt

        segments, _info = model.transcribe(
            tmp.name,
            beam_size=1,
            best_of=1,
            condition_on_previous_text=False,
            **transcribe_kwargs,
        )
        raw_text = " ".join(seg.text.strip() for seg in segments).strip()
        t_whisper = int((time.time() - t_whisper_start) * 1000)
        _log(f"Whisper: {raw_text!r} ({t_whisper}ms)")

        text = raw_text

        # ── Snippets (applied before Ollama — exact phrase triggers) ──────────
        text = apply_snippets(text)
        if text != raw_text:
            _log(f"Snippet expanded: {text!r}")

        # ── Ollama cleanup ─────────────────────────────────────────────────────
        t_ollama = 0
        use_ollama   = settings.get("use_ollama", True)
        ai_mode      = settings.get("ai_cleanup_mode", "auto")
        strength     = settings.get("correction_strength", "Standard")
        safe_mode    = settings.get("safe_mode", False)

        # Determine profile (auto-detect or manual)
        profile = get_active_writing_profile(settings, active_app if active_app else None)
        _log(f"Profile: {profile} (app={active_app!r})")

        skip_ollama = (
            safe_mode
            or not use_ollama
            or ai_mode == "off"
            or strength == "Off"
            or not text
            or len(_dictation_words(text)) <= 4
            or (ai_mode == "auto" and len(_dictation_words(text)) < 10)
        )

        if not skip_ollama:
            t_ollama_start = time.time()
            try:
                import requests
                system_prompt = build_ollama_system_prompt(profile, strength)
                resp = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "qwen2.5:3b",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user",   "content": text},
                        ],
                        "stream": False,
                        "options": {
                            "repeat_penalty": 1.15,
                            "num_predict":    180,
                            "temperature":    0.35,
                            "top_p":          0.85,
                        },
                    },
                    timeout=12,
                )
                if resp.ok:
                    raw_ollama = resp.json().get("message", {}).get("content", "").strip()
                    if raw_ollama:
                        cleaned = strip_ollama_preamble(raw_ollama)
                        ok, reason = ollama_result_is_safe(text, cleaned)
                        if ok:
                            text = cleaned
                            _log(f"Ollama accepted: {text!r}")
                        else:
                            _log(f"Ollama rejected ({reason}): {cleaned!r}")
                t_ollama = int((time.time() - t_ollama_start) * 1000)
            except Exception as e:
                _log(f"Ollama skipped: {e}")

        # ── Translation ────────────────────────────────────────────────────────
        if translate_target and translate_target != "Off" and text:
            try:
                import requests
                prompt = f"Translate to {translate_target}. Return only the translation:\n\n{text}"
                resp = requests.post(
                    "http://localhost:11434/api/generate",
                    json={"model": "qwen2.5:3b", "prompt": prompt, "stream": False},
                    timeout=12,
                )
                if resp.ok:
                    translated = resp.json().get("response", text).strip()
                    if translated:
                        text = translated
            except Exception as e:
                _log(f"Translation skipped: {e}")

        # ── Local correction pipeline (matches jarvis_dictation.py) ──────────
        # Determine whether the transcription is non-English so we can skip the
        # English-only SymSpell dictionary on French/Spanish/etc. text.
        _is_non_english = bool(
            language and language != "en" and not auto_detect
        )

        if _is_non_english:
            # Skip SymSpell for non-English — it uses an English dictionary and
            # would corrupt French/Spanish/etc. words.
            text = repair_mojibake(smart_punctuate(text))
        else:
            text = repair_mojibake(smart_punctuate(symspell_correct(text)))
            # Profile aliases: safe multi-word phrase → abbreviation
            text = apply_profile_aliases(text, profile)
            # Developer-profile contextual fixes (UI/HUD mis-transcription)
            text = _apply_ui_context_fix(text, profile)
            text = _apply_hud_context_fix(text, profile)

        # Inline linebreaks: "next line" / "next paragraph" → real newlines.
        # Runs for all languages.
        text = apply_inline_linebreaks(text)

        # Personal corrections from vocab["corrections"]: user-defined wrong→right.
        # Runs for all languages — user controls the mappings.
        text = apply_corrections(text)

        # Number words → digits (e.g. "twenty three" → "23")
        text = words_to_digits(text)

        # App-context formatting (email → period, terminal → lowercase, etc.)
        if active_app:
            text = format_for_app(text, active_app)

        _log(f"Final text: {text!r}")

        # ── Learn vocabulary from this dictation ───────────────────────────────
        if text:
            learn_from_text(text)

        t_total = int((time.time() - t_total_start) * 1000)
        result = {
            "ok":     True,
            "text":   text,
            "timing": {"whisper": t_whisper, "ollama": t_ollama, "total": t_total},
            "profile": profile,
        }
        _last_result = result
        return result

    except Exception as e:
        _log(f"transcribe_last error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def cmd_cancel_recording(_cmd: dict) -> dict:
    global _recording, _stream, _audio_frames
    _recording = False
    if _stream:
        try:
            _stream.stop()
            _stream.close()
        except Exception:
            pass
        _stream = None
    with _audio_lock:
        _audio_frames = []
    _log("Recording cancelled and buffer cleared")
    _resume_wake_stream()   # re-open wake stream if still enabled
    return {"ok": True, "status": "cancelled"}


def cmd_list_microphones(_cmd: dict) -> dict:
    try:
        import sounddevice as sd
        all_devices = sd.query_devices()
        devices = []
        for i, info in enumerate(all_devices):
            if info["max_input_channels"] > 0:
                devices.append({
                    "index":               i,
                    "name":                info["name"],
                    "default_sample_rate": int(info["default_samplerate"]),
                })
        settings = load_settings()
        mic_device = settings.get("mic_device", None)
        try:
            default_info = sd.query_devices(kind="input")
            default_idx  = int(default_info["index"]) if hasattr(default_info, "__getitem__") else None
        except Exception:
            default_idx = None
        selected_exists = any(d["index"] == int(mic_device) for d in devices) if mic_device is not None else True
        return {
            "ok":             True,
            "devices":        devices,
            "selected":       mic_device,
            "default_index":  default_idx,
            "selected_exists": selected_exists,
        }
    except Exception as e:
        _log(f"list_microphones error: {e}")
        return {"ok": False, "error": str(e)}


def cmd_test_microphone(_cmd: dict) -> dict:
    settings    = load_settings()
    mic_device  = settings.get("mic_device", None)
    sample_rate = settings.get("sample_rate", 48000)
    try:
        import sounddevice as sd
        import numpy as np
        data       = sd.rec(CHUNK, samplerate=sample_rate, channels=1, dtype="float32",
                            device=mic_device, blocking=True)
        bytes_read = data.nbytes
        _log(f"test_microphone ok: device={mic_device} rate={sample_rate} bytes={bytes_read}")
        return {"ok": True, "device": mic_device, "sample_rate": sample_rate, "bytes_read": bytes_read}
    except Exception as e:
        _log(f"test_microphone error: {e}")
        return {"ok": False, "error": str(e), "device": mic_device, "sample_rate": sample_rate}


# ── Wake-word commands ────────────────────────────────────────────────────────

def cmd_start_wake_listen(_cmd: dict) -> dict:
    global _wake_listening, _wake_frames, _wake_stream, _wake_thread, _wake_thread_stop, _wake_detected

    # Idempotent — no-op if already listening
    if _wake_listening and _wake_thread and _wake_thread.is_alive():
        return {"ok": True, "status": "already_listening"}

    # Load the openwakeword model HERE, on the main thread, BEFORE opening the
    # stream or writing the response.  _load_wake_model() uses redirect_stdout
    # to suppress chatter — doing this on the main thread is safe because no
    # other thread is writing to sys.stdout at this point.  If we loaded the
    # model inside _wake_loop (a daemon thread), redirect_stdout would replace
    # sys.stdout globally and silently eat JSON responses written by the main
    # thread concurrently, corrupting the protocol.
    try:
        import openwakeword  # noqa: F401
    except ImportError:
        msg = "openwakeword not installed — run: pip install openwakeword"
        _log(f"start_wake_listen: {msg}")
        return {"ok": False, "error": msg}

    oww = _load_wake_model()
    if oww is None:
        return {"ok": False, "error": "openwakeword model failed to load — check ~/jarvis_sidecar.log"}

    settings   = load_settings()
    mic_device = settings.get("mic_device", None)

    # Reset state
    with _wake_lock:
        _wake_frames = []
    _wake_detected  = False
    _wake_listening = True

    # Open wake stream only if not currently recording (else it opens after recording ends)
    if not _recording:
        try:
            import sounddevice as sd
            device, _ = _resolve_input_device(mic_device, WAKE_SAMPLE_RATE)
            _wake_stream = sd.InputStream(
                samplerate=WAKE_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=device,
                blocksize=CHUNK,
                callback=_wake_audio_callback,
            )
            _wake_stream.start()
            _log(f"Wake stream opened: device={device} rate={WAKE_SAMPLE_RATE}")
        except Exception as e:
            _wake_listening = False
            _log(f"Wake stream open error: {e}")
            return {"ok": False, "error": str(e)}

    # Start wake detection thread with the pre-loaded model
    _wake_thread_stop.clear()
    _wake_thread = threading.Thread(target=_wake_loop, args=(oww,), daemon=True, name="wake-loop")
    _wake_thread.start()
    _log("Wake listener started")
    return {"ok": True, "status": "listening"}


def cmd_stop_wake_listen(_cmd: dict) -> dict:
    global _wake_listening, _wake_stream, _wake_detected

    _wake_listening = False
    _wake_detected  = False

    # Close wake stream
    if _wake_stream is not None:
        try:
            _wake_stream.stop()
            _wake_stream.close()
        except Exception:
            pass
        _wake_stream = None

    # Signal wake thread to exit cleanly (daemon, so process exit cleans up anyway)
    _wake_thread_stop.set()

    with _wake_lock:
        _wake_frames.clear()

    _log("Wake listener stopped")
    return {"ok": True, "status": "stopped"}


def cmd_get_wake_status(_cmd: dict) -> dict:
    global _wake_detected
    # Atomically consume the detected flag (one-shot per detection)
    detected       = _wake_detected
    _wake_detected = False
    return {
        "ok":        True,
        "listening": _wake_listening,
        "detected":  detected,
    }


# ── Dispatch ──────────────────────────────────────────────────────────────────
HANDLERS = {
    "ping":              cmd_ping,
    "start_recording":   cmd_start_recording,
    "stop_recording":    cmd_stop_recording,
    "cancel_recording":  cmd_cancel_recording,
    "get_status":        cmd_get_status,
    "transcribe_last":   cmd_transcribe_last,
    "list_microphones":  cmd_list_microphones,
    "test_microphone":   cmd_test_microphone,
    # Wake-word
    "start_wake_listen": cmd_start_wake_listen,
    "stop_wake_listen":  cmd_stop_wake_listen,
    "get_wake_status":   cmd_get_wake_status,
}

def main():
    _log("Sidecar started")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd     = json.loads(line)
            action  = cmd.get("action", "")
            handler = HANDLERS.get(action)
            if handler:
                resp = handler(cmd)
            else:
                resp = {"ok": False, "error": f"unknown action: {action}"}
        except Exception as e:
            resp = {"ok": False, "error": str(e)}

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

    _log("Sidecar stdin closed, exiting")

if __name__ == "__main__":
    main()
