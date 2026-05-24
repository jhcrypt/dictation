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
import glob as _glob
import subprocess as _subprocess
from urllib.parse import quote as _urlquote

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
SETTINGS_FILE         = os.path.expanduser("~/.dictation_settings.json")
VOCAB_FILE            = os.path.expanduser("~/.dictation_vocabulary.json")
SNIPPETS_FILE         = os.path.expanduser("~/.dictation_snippets.json")
CUSTOM_COMMANDS_FILE  = os.path.expanduser("~/.dictation_custom_commands.json")

# ── App keyword map ───────────────────────────────────────────────────────────
# Maps spoken keywords → correct macOS app name.
# Port of Python reference _fast_jarvis_match app_keywords dict.
# Built once at startup so glob calls for Adobe apps run only once.

def _find_adobe(name: str) -> str:
    """Return the exact name of the installed Adobe app (version-agnostic)."""
    matches = sorted(_glob.glob(f"/Applications/Adobe {name}*.app"), reverse=True)
    if matches:
        return matches[0].split("/")[-1].replace(".app", "")
    return f"Adobe {name}"

_APP_KEYWORDS: dict = {
    # macOS built-ins & common apps
    "notes":           "Notes",
    "messages":        "Messages",
    "slack":           "Slack",
    "finder":          "Finder",
    "terminal":        "Terminal",
    "system settings": "System Settings",
    "music":           "Music",
    "photos":          "Photos",
    "facetime":        "FaceTime",
    "maps":            "Maps",
    "reminders":       "Reminders",
    "calculator":      "Calculator",
    "safari":          "Safari",
    "chrome":          "Google Chrome",
    "firefox":         "Firefox",
    "vs code":         "Visual Studio Code",
    "vscode":          "Visual Studio Code",
    "xcode":           "Xcode",
    "textedit":        "TextEdit",
    "zoom":            "Zoom",
    "teams":           "Microsoft Teams",
    "word":            "Microsoft Word",
    "excel":           "Microsoft Excel",
    "powerpoint":      "Microsoft PowerPoint",
    "outlook":         "Microsoft Outlook",
    "notion":          "Notion",
    "obsidian":        "Obsidian",
    "discord":         "Discord",
    "whatsapp":        "WhatsApp",
    "telegram":        "Telegram",
    "1password":       "1Password 7",
    "screenflow":      "ScreenFlow",
    "quicktime":       "QuickTime Player",
    "vlc":             "VLC",
    "iterm":           "iTerm",
    "app store":       "App Store",
    "figma":           "Figma",
    "sketch":          "Sketch",
}
# Adobe — detect installed year-versioned apps at startup
_APP_KEYWORDS.update({
    "photoshop":    _find_adobe("Photoshop"),
    "illustrator":  _find_adobe("Illustrator"),
    "premiere":     _find_adobe("Premiere Pro"),
    "after effects":_find_adobe("After Effects"),
    "lightroom":    _find_adobe("Lightroom Classic"),
    "acrobat":      _find_adobe("Acrobat"),
    "media encoder":_find_adobe("Media Encoder"),
    "encoder":      _find_adobe("Media Encoder"),
    "indesign":     _find_adobe("InDesign"),
})

def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _load_custom_commands() -> list:
    """Load user-defined custom commands from disk.
    Called from _cmd_detect to check custom commands BEFORE built-ins,
    matching the Python reference's priority order.
    Returns [] on any error so callers never crash.
    """
    try:
        with open(CUSTOM_COMMANDS_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


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
        # Default structure — updated below from file so partial files don't lose keys.
        vocab: dict = {"word_counts": {}, "total_dictations": 0, "phrases": {}}
        try:
            with open(VOCAB_FILE) as f:
                loaded = json.load(f)
            # Merge file content into defaults so missing keys don't cause KeyErrors.
            if isinstance(loaded, dict):
                vocab.update(loaded)
                # Ensure required sub-dicts exist even if the file predates them.
                if not isinstance(vocab.get("word_counts"), dict):
                    vocab["word_counts"] = {}
                if not isinstance(vocab.get("phrases"), dict):
                    vocab["phrases"] = {}
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


# ── Disfluency cleanup ────────────────────────────────────────────────────────

# Safe contractions: only unambiguous forms (cant/its/lets/were/id excluded).
_SAFE_CONTRACTIONS: dict[str, str] = {
    "hows":     "how's",    "whats":    "what's",   "thats":    "that's",
    "whos":     "who's",    "wheres":   "where's",  "heres":    "here's",
    "theres":   "there's",  "dont":     "don't",    "doesnt":   "doesn't",
    "didnt":    "didn't",   "wont":     "won't",    "wasnt":    "wasn't",
    "isnt":     "isn't",    "arent":    "aren't",   "havent":   "haven't",
    "hadnt":    "hadn't",   "hasnt":    "hasn't",   "wouldnt":  "wouldn't",
    "couldnt":  "couldn't", "shouldnt": "shouldn't",
    "youre":    "you're",   "theyre":   "they're",  "youve":    "you've",
    "weve":     "we've",    "theyve":   "they've",  "ive":      "I've",
}

_CONTRACTION_RE = re.compile(
    r'\b(' + '|'.join(sorted(_SAFE_CONTRACTIONS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)

# Code/URL/path/shell detector — skip disfluency cleanup on these.
_CODE_RE = re.compile(
    r"""
    https?://                                                  |  # URL
    www\.                                                      |  # web address
    (?:^|(?<=\s))[./~][\w/\\]                                 |  # path: ./foo /bar ~/baz
    \b(?:npm|git|pip|sudo|brew|cargo|docker|kubectl)\s+\w     |  # shell cmds
    \b(?:import|function|const|let|var|def|class|return|async|await)\b |
    [{}()\[\];&|<>]                                           |
    ===|!==|=>|::|->|\|\|                                     |
    \.\b(?:py|js|ts|rs|json|yaml|yml|sh|cpp|java|swift|go|rb)\b |
    \b\w{2,}_\w{2,}_\w{2,}\b                                     # snake_case_identifiers
    """,
    re.VERBOSE | re.IGNORECASE,
)


def remove_disfluencies(text: str, profile: str = "General") -> str:
    """
    Light local pass to clean common speech transcription artefacts.
    Runs in the correction pipeline regardless of whether Ollama ran.

    Operations:
      1. Removes standalone filler words (um, uh, ah, er, hmm).
      2. Collapses adjacent duplicate words ("the the" → "the").
      3. Removes clearly-parenthetical filler phrases ("you know", "I mean").
      4. Fixes time-spacing ("10PM" → "10 PM").
      5. Restores missing apostrophes in safe contractions (English-only).

    Guardrails — returns text unchanged when:
      - profile is "Developer" or "Verbatim"
      - text contains code, paths, URLs, or shell-command patterns
    """
    if not text or not text.strip():
        return text
    if profile in ("Developer", "Verbatim"):
        return text
    if _CODE_RE.search(text):
        return text

    # 1. Remove filler words (with optional adjacent comma)
    text = re.sub(
        r'(?:,\s*)?\b(?:um|uh|ah|er|hmm|hm)\b(?:\s*,)?',
        '', text, flags=re.IGNORECASE,
    )

    # 2. Collapse adjacent duplicates (loop handles triple+)
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'\b(\w+)\s+\1\b', r'\1', text, flags=re.IGNORECASE)

    # 3. Remove parenthetical filler phrases
    text = re.sub(r',?\s*\byou know\b,?\s*', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:^|(?<=,)\s*)\bI mean\b,?\s*', '', text, flags=re.IGNORECASE)

    # 4. Time spacing: "10PM" / "10:30am" → "10 PM" / "10:30 AM"
    text = re.sub(
        r'\b(\d{1,2}(?::\d{2})?)\s*(AM|PM|am|pm)\b',
        lambda m: f"{m.group(1)} {m.group(2).upper()}",
        text,
    )

    # 5. Contraction repair (English ASCII text only)
    if text.isascii():
        def _fix_contraction(m: re.Match) -> str:
            word = m.group(0)
            contracted = _SAFE_CONTRACTIONS.get(word.lower())
            if contracted is None:
                return word
            if word[0].isupper():
                return contracted[0].upper() + contracted[1:]
            return contracted
        text = _CONTRACTION_RE.sub(_fix_contraction, text)

    # Normalize whitespace and re-capitalize first letter
    text = re.sub(r'  +', ' ', text).strip()
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    if text and text[0].islower():
        text = text[0].upper() + text[1:]

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


# ── Whisper deduplication ─────────────────────────────────────────────────────

def _deduplicate_whisper(text: str) -> str:
    """Remove Whisper hallucination: exact duplicate adjacent sentences/phrases.

    Whisper sometimes repeats the same sentence or phrase consecutively when
    audio is quiet or the model is uncertain.  This function removes those
    exact duplicates at sentence and word-chunk level.
    """
    if not text:
        return text
    # Sentence-level: split on ". " / "! " / "? " boundaries
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    deduped: list[str] = []
    for p in parts:
        norm = p.strip().lower().rstrip('.!?')
        prev = deduped[-1].strip().lower().rstrip('.!?') if deduped else ""
        if not deduped or norm != prev:
            deduped.append(p)
    result = ' '.join(deduped)
    # Word-chunk level: catch "hello world hello world" (no punctuation boundary)
    words = result.split()
    n = len(words)
    for half in range(n // 2, 3, -1):
        first_h  = ' '.join(words[:half]).lower().rstrip(' .,!?')
        second_h = ' '.join(words[half:half * 2]).lower().rstrip(' .,!?')
        if first_h == second_h:
            result = ' '.join(words[:half] + words[half * 2:])
            break
    return result


# ── Snippet helpers ───────────────────────────────────────────────────────────

def _save_snippet(trigger: str, content: str) -> None:
    """Persist a new snippet to ~/.dictation_snippets.json."""
    try:
        snippets: dict = {}
        try:
            with open(SNIPPETS_FILE) as f:
                snippets = json.load(f)
        except Exception:
            pass
        snippets[trigger.lower().strip()] = content
        with open(SNIPPETS_FILE, "w") as f:
            json.dump(snippets, f, indent=2)
        _log(f"Snippet saved: {trigger!r} → {content[:40]!r}")
    except Exception as e:
        _log(f"save_snippet error: {e}")


# ── Contacts email lookup ─────────────────────────────────────────────────────

def _lookup_contact_email(name: str) -> "str | None":
    """Return the email address for a contact by name/alias from contacts file."""
    name_lower = name.lower().strip()
    try:
        path = os.path.expanduser("~/.dictation_contacts.json")
        with open(path) as f:
            contacts = json.load(f)
        for c in contacts:
            if not isinstance(c, dict):
                continue
            cname = c.get("name", "").lower()
            email = c.get("email", "")
            if not email:
                continue
            if name_lower in cname or cname.startswith(name_lower):
                return email
            aliases = c.get("aliases", "")
            if aliases:
                for alias in str(aliases).split(","):
                    if alias.strip().lower() == name_lower:
                        return email
    except Exception:
        pass
    return None


def _email_contact_split(rest_lower: str, raw_rest: str) -> "tuple[str, str, str]":
    """Split 'email <rest>' into (ename_lower, body_lower, raw_body) by trying to
    match a known contact at the start of rest_lower.

    Tries 1, 2, then 3-word prefixes via EXACT contact/alias match.  Returns the
    longest prefix that matches a known contact and the remaining text as the body.

    Falls back to (rest_lower, "", "") if no contact is found — the caller keeps
    the original no-body logic (full rest = recipient attempt, no body).

    Why this matters: users say "email Bob hey Bob everything is fine" without a
    body marker.  Without this, _ename becomes the whole sentence and the body is
    lost (or the full sentence lands in the To field when Bob isn't in contacts).
    """
    words = rest_lower.split()
    raw_words = raw_rest.split() if raw_rest else []

    for n in (3, 2, 1):
        if len(words) <= n:
            continue  # need at least one word of body after the name
        candidate = " ".join(words[:n])
        if _lookup_contact_email(candidate):
            body_lower = " ".join(words[n:]).strip()
            raw_body   = " ".join(raw_words[n:]).strip() if len(raw_words) > n else body_lower
            return candidate, body_lower, raw_body

    return rest_lower, "", ""


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
    Called from cmd_stop_recording and cmd_cancel_recording (via background thread).
    Guard: returns immediately if recording restarted before this fires."""
    global _wake_stream
    if not _wake_listening:
        return
    if _recording:
        # A new recording started before this deferred resume could run.
        # cmd_start_recording already closed the wake stream, so nothing to do.
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
    if _recording and _stream is not None:
        # Sidecar is already recording — the Tauri/TS side previously timed out or
        # errored while the Python stream stayed open.  Reset the audio buffer so
        # this recording starts from *now* (discarding any stale audio captured
        # before this call), then return success.  No need to close/reopen the
        # hardware stream — the callback is still running and will fill _audio_frames
        # from this point forward.
        with _audio_lock:
            _audio_frames = []
        _log("start_recording: stream already open — buffer cleared, returning ok")
        return {"ok": True, "status": "recording"}
    if _recording and _stream is None:
        # Inconsistent state — _recording True but no stream. Reset and fall
        # through to open a fresh stream.
        _recording = False
        _log("start_recording: _recording=True but no stream — resetting")

    # Close wake stream so the mic is free for recording.
    # _wake_listening stays True — the stream is re-opened by _resume_wake_stream()
    # after recording ends.
    wake_was_open = False
    if _wake_stream is not None:
        wake_was_open = True
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
        # On macOS, CoreAudio can take a moment to fully release the audio device
        # after a stream is closed.  Opening a new stream immediately (especially
        # at a different sample rate) can fail with a PortAudio device-busy error.
        # A brief pause lets CoreAudio complete the teardown.
        import time as _time
        _time.sleep(0.08)

    with _audio_lock:
        _audio_frames = []
    # Reset VAD state so a stale high noise floor from a previous session
    # (e.g. recorded in a noisy room) doesn't prevent voice detection in this one.
    global _noise_floor, _voice_active, _live_audio_rms
    _noise_floor    = 0.01
    _voice_active   = False
    _live_audio_rms = 0.0
    _recording = True

    settings    = load_settings()
    mic_device  = settings.get("mic_device", None)
    sample_rate = settings.get("sample_rate", 48000)

    try:
        import sounddevice as sd
        import numpy as _np  # captured in closure — avoids per-call import overhead
        import time as _time
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
                    # Noise-floor adaptation:
                    #   Silent frames → fast adapt DOWN so transients don't raise the floor.
                    #   Voice frames  → very slow adapt UP to handle the catch-22 where
                    #     _noise_floor starts at 0.01 but ambient is 0.03+: without upward
                    #     adaptation the floor stays at 0.01, threshold stays at 0.025, and
                    #     ambient 0.03 pins va=True forever so silence is never detected.
                    #     The slow rate (0.5 %) ensures real speech (>>0.03) barely moves
                    #     the floor while steady room noise pulls it up within ~5–10 s.
                    if not va:
                        _noise_floor = _noise_floor * 0.98 + rms * 0.02
                    elif _noise_floor < rms * 0.8:
                        # Only creep upward when floor is well below ambient (not during
                        # genuine loud speech where the gap is intentional).
                        _noise_floor = _noise_floor * 0.995 + rms * 0.005
                except Exception:
                    pass  # never let a frame error kill the audio stream

        # Open the recording stream — retry once on failure.
        # On macOS, opening a new InputStream immediately after closing the wake
        # stream can fail with a PortAudio device-busy error even with the 80 ms
        # settle above (device-release latency varies with system load).
        last_err = None
        for attempt in range(2):
            try:
                _stream = sd.InputStream(
                    samplerate=sample_rate,
                    channels=channels,
                    dtype="float32",
                    device=device,
                    blocksize=CHUNK,
                    callback=_callback,
                )
                _stream.start()
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt == 0 and wake_was_open:
                    _log(f"start_recording attempt {attempt+1} failed ({e}), retrying…")
                    _time.sleep(0.12)  # extra settle before retry
                else:
                    break

        if last_err is not None:
            _recording = False
            _log(f"start_recording error: {last_err}")
            return {"ok": False, "error": str(last_err)}

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
    # Defer wake-stream resume to a background thread so this command returns
    # immediately and sidecar_transcribe_last can start without waiting for
    # CoreAudio to open the wake-word stream (~200–300 ms on macOS).
    if _wake_listening:
        threading.Thread(target=_resume_wake_stream, daemon=True).start()
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


# ── Dictation command detection (ported from jarvis_dictation.py) ─────────────
# Mirrors the Python app's deterministic command routing that runs on raw Whisper
# text BEFORE the correction pipeline.  Returns a command action dict or None.

# Email body-marker pattern — ported from jarvis_dictation.py _MARKER.
# Matches speech patterns that separate the recipient from the body:
#   "email Val tell her the meeting is cancelled"
#   "email Val let him know I'll be late"
#   "email Val saying see you tomorrow"
#   "email Val ask them about the invoice"
# Operates on the punctuation-stripped lowercase input (lower) so no punct handling needed.
_EMAIL_BODY_MARKER = re.compile(
    # Optional punct/space BEFORE marker — matches Python reference exactly.
    r"\s*(?:[.,:;-]\s*)?"
    r"(?:tell\s+(?:him|her|them|me|it)"
    r"|let\s+(?:him|her|them)\s+know"
    r"|say(?:ing)?"
    r"|telling\s+(?:him|her|them)?"
    r"|letting\s+(?:him|her|them)\s+know"
    r"|ask(?:ing)?(?:\s+(?:him|her|them))?)"
    # Optional punct/space AFTER marker — consumes ", " in "Tell him, the meeting..."
    r"[.,:;-]?\s*",
    re.IGNORECASE,
)

# Prefix regex for extracting raw-text email body (preserves capitalization).
_EMAIL_PREFIX_RE = re.compile(
    r"^(?:email|compose email to|write (?:an )?email to|send email to|"
    r"new email to|draft email to|email to|send email)\s+(.+)$",
    re.IGNORECASE,
)

_cmd_last_text:     str       = ""
_cmd_history:       list[str] = []
_cmd_history_index: int       = -1
_cmd_redo_stack:    list[str] = []      # populated by scratch; cleared by new dictation
_snippet_state:     str       = "idle"  # "idle" | "waiting_trigger" | "waiting_content"
_snippet_trigger:   str       = ""

PUNCT_COMMANDS: dict[str, str] = {
    "period": ".",   "full stop": ".",
    "comma": ",",
    "exclamation point": "!", "exclamation mark": "!",
    "question mark": "?",
    "colon": ":",    "semicolon": ";",
    "ellipsis": "...",
    "open paren": "(", "close paren": ")",
    "dash": " — ",   "hyphen": "-",
}

def _fmt_bullet(t: str) -> str:
    return "\n".join(f"• {s.strip()}" for s in t.split('.') if s.strip())

# (triggers, format_fn, hud_label)
FORMAT_COMMANDS: list[tuple] = [
    (("make bold",      "bold that"),                             lambda t: f"**{t}**",   "Bolded!"),
    (("make italic",    "italic that"),                           lambda t: f"*{t}*",     "Italicized!"),
    (("format as code", "code that", "make code"),                lambda t: f"`{t}`",     "Code formatted!"),
    (("make heading",   "heading that", "make title"),            lambda t: f"# {t}",     "Heading!"),
    (("all caps",       "make caps", "capitalize that"),          str.upper,              "ALL CAPS!"),
    (("make bullet",    "bullet that", "create list", "make list"), _fmt_bullet,          "Bulleted!"),
    (("make quote",     "quote that", "block quote"),             lambda t: f"> {t}",     "Quoted!"),
    (("strikethrough that", "strike that"),                       lambda t: f"~~{t}~~",   "Strikethrough!"),
]

def _cmd_add_to_history(text: str) -> None:
    global _cmd_history, _cmd_history_index, _cmd_redo_stack
    if _cmd_history_index < len(_cmd_history) - 1:
        _cmd_history = _cmd_history[:_cmd_history_index + 1]
    _cmd_history.append(text)
    _cmd_history_index = len(_cmd_history) - 1
    _cmd_redo_stack.clear()  # new dictation invalidates the redo stack
    if len(_cmd_history) > 50:
        _cmd_history = _cmd_history[-50:]
        _cmd_history_index = 49

# Chat apps where Shift+Enter inserts a newline rather than sending the message.
_CHAT_APPS: frozenset = frozenset({
    "slack", "messages", "discord", "teams", "whatsapp", "telegram",
    "signal", "zoom", "imessage", "texts", "mattermost",
})


def _cmd_detect(
    lower: str,
    raw_text: str,
    jarvis_enabled: bool = True,
    active_app: str = "",
) -> "dict | None":
    """Detect a dictation command from the normalized Whisper output.

    Called on the raw (pre-pipeline) transcript so command routing is
    unaffected by spelling correction or Ollama rewrites.

    jarvis_enabled gates the Jarvis system-command block (open app, search,
    volume, reminders, etc.) but never gates voice-editing commands (scratch,
    formatting, navigation) — those always run.

    active_app  (optional) app name string used for context-sensitive routing
                (e.g. Shift+Enter in chat apps).

    Returns an action dict consumed by useGlobalHotkey.ts, or None.
    """
    global _cmd_last_text, _cmd_history, _cmd_history_index, _cmd_redo_stack, _snippet_state, _snippet_trigger

    # ── Scratch / undo ────────────────────────────────────────────────────────
    sc = 0
    if lower in ("scratch that", "undo that", "delete that",
                 "scratch", "undo", "scratch last",
                 "scratch again", "undo again", "scratch more"):
        sc = 1
    elif any(p in lower for p in ("scratch last 2", "scratch two", "scratch last two",
                                   "undo last 2", "undo two", "undo last two",
                                   "delete last 2", "delete two")):
        sc = 2
    elif any(p in lower for p in ("scratch last 3", "scratch three", "scratch last three",
                                   "undo last 3", "undo three", "undo last three",
                                   "delete last 3", "delete three")):
        sc = 3
    elif any(p in lower for p in ("scratch all", "undo all", "delete all", "clear all")):
        sc = max(len(_cmd_history), 1 if _cmd_last_text else 0)

    if sc > 0:
        bc = 0
        scratched_texts: list[str] = []
        for i in range(sc):
            if 0 <= _cmd_history_index < len(_cmd_history):
                scratched_texts.append(_cmd_history[_cmd_history_index])
                bc += len(_cmd_history[_cmd_history_index]) + 1  # +1 for trailing space paste adds
                _cmd_history.pop(_cmd_history_index)
                _cmd_history_index = len(_cmd_history) - 1
            elif i == 0 and _cmd_last_text:
                scratched_texts.append(_cmd_last_text)
                bc += len(_cmd_last_text) + 1
        _cmd_last_text = _cmd_history[_cmd_history_index] if (0 <= _cmd_history_index < len(_cmd_history)) else ""
        # Push scratched items to redo stack (most recent on top)
        for t in reversed(scratched_texts):
            if t:
                _cmd_redo_stack.append(t)
        msg = (f"Scratched {sc}!" if sc > 1 else "Scratched!") if bc > 0 else "Nothing to scratch"
        return {"action": "scratch", "backspace_count": bc, "hud": msg, "hud_color": "#ff9f0a"}

    # ── Redo ──────────────────────────────────────────────────────────────────
    if lower in ("redo", "redo that", "redo dictation", "redo last"):
        if _cmd_redo_stack:
            redo_text = _cmd_redo_stack.pop()
            _cmd_last_text = redo_text
            _cmd_add_to_history(redo_text)
            return {"action": "paste_text", "text": redo_text,
                    "hud": "Redone!", "hud_color": "#30d158"}
        return {"action": "noop", "hud": "Nothing to redo", "hud_color": "#ff9f0a"}

    # ── Punctuation ───────────────────────────────────────────────────────────
    if lower in PUNCT_COMMANDS:
        return {"action": "paste_text", "text": PUNCT_COMMANDS[lower],
                "hud": lower.capitalize(), "hud_color": "#0a84ff"}

    # ── Navigation / whitespace keys ──────────────────────────────────────────
    if lower in ("new line", "newline", "next line"):
        # Chat apps: Shift+Enter inserts a line break without sending the message
        _app_lower = active_app.lower() if active_app else ""
        _use_shift = any(ca in _app_lower for ca in _CHAT_APPS)
        return {"action": "keypress", "key": "return", "with_shift": _use_shift, "repeat": 1,
                "hud": "New line", "hud_color": "#0a84ff"}
    if lower in ("new paragraph", "next paragraph"):
        return {"action": "keypress", "key": "return", "with_shift": False, "repeat": 2,
                "hud": "Next paragraph", "hud_color": "#0a84ff"}
    if lower in ("tab", "indent"):
        return {"action": "keypress", "key": "tab", "with_shift": False, "repeat": 1,
                "hud": "Tab", "hud_color": "#0a84ff"}
    if lower == "select all":
        return {"action": "key_combo", "modifier": "cmd", "key": "a",
                "hud": "Select all", "hud_color": "#0a84ff"}

    # ── Copy / paste ──────────────────────────────────────────────────────────
    if lower in ("copy that", "copy last"):
        if _cmd_last_text:
            return {"action": "copy_text", "text": _cmd_last_text,
                    "hud": "Copied!", "hud_color": "#0a84ff"}
        return {"action": "noop", "hud": "Nothing to copy", "hud_color": "#ff9f0a"}
    if lower == "copy all":
        return {"action": "copy_all", "hud": "Copied all!", "hud_color": "#0a84ff"}
    if lower in ("paste", "paste that"):
        return {"action": "key_combo", "modifier": "cmd", "key": "v",
                "hud": "Pasted!", "hud_color": "#0a84ff"}
    if lower in ("reinsert last", "re insert last", "insert last", "paste last"):
        if _cmd_last_text:
            return {"action": "paste_text", "text": _cmd_last_text,
                    "hud": "Re-inserted!", "hud_color": "#30d158"}
        return {"action": "noop", "hud": "Nothing to re-insert", "hud_color": "#ff9f0a"}

    # ── Navigate ──────────────────────────────────────────────────────────────
    if lower in ("show history", "dictation history", "view history"):
        return {"action": "navigate", "nav_target": "history",
                "hud": None, "hud_color": None}
    if lower in ("correct that", "correct last", "add correction", "fix that"):
        return {"action": "navigate", "nav_target": "vocabulary",
                "hud": None, "hud_color": None}

    # ── Formatting ────────────────────────────────────────────────────────────
    for triggers, fmt_fn, label in FORMAT_COMMANDS:
        hit = next((p for p in triggers if p in lower), None)
        if hit is None:
            continue
        hit_idx = raw_text.lower().find(hit)
        before  = raw_text[:hit_idx].strip(" .,!? ") if hit_idx > 0 else ""
        if before:
            # Inline: format the text before the trigger phrase
            return {"action": "paste_text", "text": fmt_fn(before),
                    "hud": label, "hud_color": "#0a84ff"}
        # Standalone: format the previous dictation
        if not _cmd_last_text:
            return {"action": "noop", "hud": "Nothing to format", "hud_color": "#ff9f0a"}
        return {"action": "format_paste",
                "text":            fmt_fn(_cmd_last_text),
                "backspace_count": len(_cmd_last_text) + 1,
                "hud":             label, "hud_color": "#0a84ff"}

    # ── Jarvis system commands ────────────────────────────────────────────────
    # Gated by jarvis_enabled. Safe Mode already blocks at the call site.
    if jarvis_enabled:
        # ── Custom user commands — checked FIRST, before all built-ins ────────
        # Matches Python reference priority: custom commands win over built-ins.
        # Without this, "open photoshop" is intercepted by the generic open_app
        # handler before the JS can match the custom trigger "open photoshop"
        # (which has target "Adobe Photoshop 2024" — the correct full app name).
        for _cc in _load_custom_commands():
            _cc_trigger = str(_cc.get("trigger", "")).lower().strip()
            # Skip single-word triggers (too ambiguous) — matches Python reference.
            if not _cc_trigger or len(_cc_trigger.split()) < 2:
                continue
            if lower == _cc_trigger:
                _cc_action = str(_cc.get("action", ""))
                _cc_target = str(_cc.get("target", ""))
                _cc_hud    = _cc_trigger.title()
                if _cc_action == "open_url" and _cc_target:
                    return {"action": "open_url", "url": _cc_target,
                            "hud": _cc_hud, "hud_color": "#0a84ff"}
                if _cc_action == "open_app" and _cc_target:
                    return {"action": "open_app", "app_name": _cc_target,
                            "hud": _cc_hud, "hud_color": "#0a84ff"}
                if _cc_action == "type_text":
                    return {"action": "paste_text", "text": _cc_target,
                            "hud": _cc_hud[:55], "hud_color": "#0a84ff"}

        # Website → URL map (checked before generic open-app)
        _WEBSITE_MAP = {
            "youtube":    "https://www.youtube.com",
            "google":     "https://www.google.com",
            "gmail":      "https://mail.google.com",
            "github":     "https://github.com",
            "netflix":    "https://www.netflix.com",
            "spotify":    "spotify:",
            "twitter":    "https://www.twitter.com",
            "x":          "https://www.x.com",
            "instagram":  "https://www.instagram.com",
            "facebook":   "https://www.facebook.com",
            "linkedin":   "https://www.linkedin.com",
            "reddit":     "https://www.reddit.com",
            "claude":     "https://claude.ai",
            "chatgpt":    "https://chat.openai.com",
            "amazon":     "https://www.amazon.com",
        }

        # Named Spotify playlists
        _PLAYLIST_MAP = {
            "coding playlist":  "spotify:playlist:37i9dQZF1DX4UtSsGT1Sbe",
            "workout playlist": "spotify:playlist:37i9dQZF1DX70RN3TfR07f",
            "playlist 4":       "spotify:playlist:37i9dQZF1DX4UtSsGT1Sbe",
            "playlist 5":       "spotify:playlist:37i9dQZF1DX70RN3TfR07f",
            "playlist 6":       "spotify:playlist:7JZxrxQtbmAGcXf9b4BibQ",
        }

        # ── open [target] ─────────────────────────────────────────────────────
        _open_m = re.match(r"^open (.+)$", lower)
        if _open_m:
            target = _open_m.group(1).strip()
            if target in ("calendar", "my calendar"):
                return {"action": "open_app", "app_name": "Calendar",
                        "hud": "Opening Calendar…", "hud_color": "#30d158"}
            if target in _WEBSITE_MAP:
                return {"action": "open_url", "url": _WEBSITE_MAP[target],
                        "hud": f"Opening {target.capitalize()}…", "hud_color": "#30d158"}
            # Keyword normalisation: "chrome" → "Google Chrome", etc.
            # Port of Python reference app_keywords map — exact match first,
            # then partial (e.g. "photoshop 2024" still matches "photoshop").
            _resolved_app = _APP_KEYWORDS.get(target)
            if not _resolved_app:
                for _kw, _kname in _APP_KEYWORDS.items():
                    if _kw in target:
                        _resolved_app = _kname
                        break
            _final_app = _resolved_app or target.title()
            return {"action": "open_app", "app_name": _final_app,
                    "hud": f"Opening {_final_app}…", "hud_color": "#30d158"}

        # ── Direct app name (no "open" prefix) ───────────────────────────────
        # "photoshop", "safari", "chrome" etc. without saying "open".
        # Port of Python reference direct app name match.
        if lower in _APP_KEYWORDS:
            _dapp = _APP_KEYWORDS[lower]
            return {"action": "open_app", "app_name": _dapp,
                    "hud": f"Opening {_dapp}…", "hud_color": "#30d158"}
        # Partial match for multi-word keyword said without "open"
        for _kw, _kapp in _APP_KEYWORDS.items():
            if lower == _kw:
                return {"action": "open_app", "app_name": _kapp,
                        "hud": f"Opening {_kapp}…", "hud_color": "#30d158"}

        # ── Web search ────────────────────────────────────────────────────────
        for _pfx in ("search for ", "search ", "google ", "look up ", "find "):
            if lower.startswith(_pfx):
                _query = lower[len(_pfx):].strip()
                if _query:
                    _url = f"https://duckduckgo.com/?q={_query.replace(' ', '+')}"
                    return {"action": "open_url", "url": _url,
                            "hud": f"Searching: {_query[:30]}…", "hud_color": "#0a84ff"}

        # ── Spotify / playlists / YouTube ────────────────────────────────────
        if lower.startswith("play "):
            _tail = lower[5:].strip()
            for _kw, _uri in _PLAYLIST_MAP.items():
                if _kw in _tail:
                    return {"action": "open_url", "url": _uri,
                            "hud": f"Playing {_kw}…", "hud_color": "#30d158"}
            if _tail.endswith(" on spotify"):
                _song = _tail[:-11].strip()
                _uri = f"spotify:search:{_song.replace(' ', '%20')}"
                return {"action": "open_url", "url": _uri,
                        "hud": f"Spotify: {_song[:25]}…", "hud_color": "#30d158"}
            if _tail.endswith(" on apple music"):
                _song = _tail[:-15].strip()
                return {"action": "open_url",
                        "url": f"https://music.apple.com/search?term={_song.replace(' ', '+')}",
                        "hud": f"Apple Music: {_song[:25]}…", "hud_color": "#fa2d55"}
            if _tail:
                # Default: search YouTube (matches Python reference behaviour)
                return {"action": "open_url",
                        "url": f"https://www.youtube.com/results?search_query={_tail.replace(' ', '+')}",
                        "hud": f"YouTube: {_tail[:25]}…", "hud_color": "#ff0000"}

        # ── Watch X → YouTube ─────────────────────────────────────────────────
        if lower.startswith("watch "):
            _wtail = lower[6:].strip()
            if _wtail:
                return {"action": "open_url",
                        "url": f"https://www.youtube.com/results?search_query={_wtail.replace(' ', '+')}",
                        "hud": f"YouTube: {_wtail[:25]}…", "hud_color": "#ff0000"}

        # ── System volume ─────────────────────────────────────────────────────
        if lower in ("volume up", "turn volume up", "increase volume",
                     "raise volume", "louder"):
            return {"action": "set_volume", "direction": "up",
                    "hud": "Volume up", "hud_color": "#30d158"}
        if lower in ("volume down", "turn volume down", "decrease volume",
                     "lower volume", "quieter"):
            return {"action": "set_volume", "direction": "down",
                    "hud": "Volume down", "hud_color": "#30d158"}
        if lower in ("mute", "mute volume", "turn off sound"):
            return {"action": "set_volume", "direction": "mute",
                    "hud": "Muted", "hud_color": "#30d158"}
        if lower == "unmute":
            return {"action": "set_volume", "direction": "unmute",
                    "hud": "Unmuted", "hud_color": "#30d158"}
        _vol_m = re.match(r"^(?:set volume to|volume to)\s+(\d+)", lower)
        if _vol_m:
            _lvl = min(100, max(0, int(_vol_m.group(1))))
            return {"action": "set_volume", "direction": "set", "level": _lvl,
                    "hud": f"Volume: {_lvl}%", "hud_color": "#30d158"}

        # ── Screenshots ───────────────────────────────────────────────────────
        if any(p in lower for p in ("capture area", "area capture", "area screenshot")):
            return {"action": "take_screenshot", "screenshot_type": "area",
                    "hud": "Area capture…", "hud_color": "#0a84ff"}
        if any(p in lower for p in ("scrolling capture", "scrolling screenshot",
                                     "capture scrolling", "capture scroll")):
            return {"action": "take_screenshot", "screenshot_type": "scrolling",
                    "hud": "Scrolling capture…", "hud_color": "#0a84ff"}
        if any(p in lower for p in ("text recognition", "extract text",
                                     "capture text", "recognize text")):
            return {"action": "take_screenshot", "screenshot_type": "text",
                    "hud": "Text recognition…", "hud_color": "#0a84ff"}
        if any(p in lower for p in ("screenshot", "take a screenshot", "capture screen",
                                     "take screenshot", "capture window", "window screenshot")):
            return {"action": "take_screenshot", "screenshot_type": "screen",
                    "hud": "Screenshot…", "hud_color": "#0a84ff"}

        # ── Brightness ────────────────────────────────────────────────────────
        # Port of Python reference set_brightness handler.
        # Uses osascript key codes: 144=brightness up, 145=brightness down.
        # Handled directly in sidecar (no Rust command needed).
        if lower in ("brightness up", "increase brightness", "brighter"):
            try:
                _subprocess.Popen(
                    ["osascript", "-e",
                     'tell application "System Events" to key code 144']
                )
            except Exception:
                pass
            return {"action": "noop", "hud": "Brightness up", "hud_color": "#30d158"}
        if lower in ("brightness down", "decrease brightness", "dimmer", "dim screen"):
            try:
                _subprocess.Popen(
                    ["osascript", "-e",
                     'tell application "System Events" to key code 145']
                )
            except Exception:
                pass
            return {"action": "noop", "hud": "Brightness down", "hud_color": "#30d158"}
        _bright_m = re.match(r"^set brightness to (\d+)$", lower)
        if _bright_m:
            _bval = min(100, max(0, int(_bright_m.group(1))))
            _steps = max(0, min(16, round(_bval / 100 * 16)))
            _bscript = (
                'tell application "System Events"\n'
                '    repeat 16 times\n'
                '        key code 145\n'
                '    end repeat\n'
                f'    repeat {_steps} times\n'
                '        key code 144\n'
                '    end repeat\n'
                'end tell'
            )
            try:
                _subprocess.Popen(["osascript", "-e", _bscript])
            except Exception:
                pass
            return {"action": "noop", "hud": f"Brightness: {_bval}%",
                    "hud_color": "#30d158"}

        # ── Weather ───────────────────────────────────────────────────────────
        if any(p in lower for p in ("check weather", "whats the weather",
                                     "weather today", "what is the weather")):
            return {"action": "open_url",
                    "url": "https://duckduckgo.com/?q=weather+today",
                    "hud": "Checking weather…", "hud_color": "#0a84ff"}
        _weather_m = re.match(r"^weather (?:in |for )?(.+)$", lower)
        if _weather_m:
            _loc = _weather_m.group(1).strip()
            return {"action": "open_url",
                    "url": f"https://duckduckgo.com/?q=weather+in+{_loc.replace(' ', '+')}",
                    "hud": f"Weather: {_loc[:20]}…", "hud_color": "#0a84ff"}

        # ── Calendar ──────────────────────────────────────────────────────────
        if any(p in lower for p in ("open calendar", "check calendar",
                                     "whats on my calendar", "what is on my calendar")):
            return {"action": "open_app", "app_name": "Calendar",
                    "hud": "Opening Calendar…", "hud_color": "#30d158"}

        # ── Reminders ─────────────────────────────────────────────────────────
        # Port of Python reference reminder trigger — matches same set of phrases.
        _remind_m = re.match(
            r"^(?:"
            r"remind me (?:to )?"
            r"|set (?:a )?reminder (?:to )?"
            r"|create (?:a )?(?:task|reminder) (?:to )?"
            r"|add (?:a )?(?:task|reminder) (?:to )?"
            r")(.+)",
            lower,
        )
        if _remind_m:
            # Use raw Whisper text for proper capitalisation
            _raw_remind = re.match(
                r"(?i)^(?:"
                r"remind me (?:to )?"
                r"|set (?:a )?reminder (?:to )?"
                r"|create (?:a )?(?:task|reminder) (?:to )?"
                r"|add (?:a )?(?:task|reminder) (?:to )?"
                r")(.+)",
                raw_text.strip(),
            )
            _task = (_raw_remind.group(1).strip().rstrip(".") if _raw_remind
                     else _remind_m.group(1).strip())
            return {"action": "create_reminder", "text": _task,
                    "hud": f"Reminder: {_task[:30]}…", "hud_color": "#30d158"}

        # ── Close / kill app ──────────────────────────────────────────────────
        _close_m = re.match(r"^close (.+)$", lower)
        if _close_m:
            _aname = _close_m.group(1).strip().title()
            return {"action": "close_app", "app_name": _aname, "force": False,
                    "hud": f"Closing {_aname}…", "hud_color": "#30d158"}
        _kill_m = re.match(r"^(?:kill|force quit|force close) (.+)$", lower)
        if _kill_m:
            _aname = _kill_m.group(1).strip().title()
            return {"action": "close_app", "app_name": _aname, "force": True,
                    "hud": f"Force-quitting {_aname}…", "hud_color": "#ff3b30"}

        # ── Translate on-demand ───────────────────────────────────────────────
        if any(p in lower for p in ("translate that", "translate selected", "translate last")):
            return {"action": "translate_last", "language": None,
                    "hud": "Translating…", "hud_color": "#0a84ff"}
        _translate_m = re.match(r"^translate (?:to |into )?(.+)$", lower)
        if _translate_m:
            _lang = _translate_m.group(1).strip()
            if _lang not in ("that", "last", "selected", "text"):
                return {"action": "translate_last", "language": _lang,
                        "hud": f"Translating to {_lang.title()}…", "hud_color": "#0a84ff"}

        # ── Email contact ─────────────────────────────────────────────────────
        # Supported: "email Jack", "compose email to Jack",
        #   "write an email to Jack", "new email to Jack",
        #   "email Jack about Monday meeting",
        #   "email Jack saying I will call you tomorrow",
        #   "email Jack let her know the meeting is cancelled",
        #   "email Jack tell him I will be late",
        #   "email Jack about Monday meeting saying I will call you tomorrow"
        _email_m = re.match(
            r"^(?:email|compose email to|write (?:an )?email to|send email to|"
            r"new email to|draft email to|email to|send email)\s+(.+)$",
            lower,
        )
        if _email_m:
            _rest = _email_m.group(1).strip()

            # Extract raw_rest for capitalization-preserving body extraction.
            _raw_rest_email = ""
            if raw_text:
                _rp = _EMAIL_PREFIX_RE.match(raw_text.strip())
                if _rp:
                    _raw_rest_email = _rp.group(1).strip()

            # Step 1: Extract body using the full Python-ported marker set.
            # Handles: tell him/her/them, let him/her/them know, say/saying,
            #   telling him/her/them, letting him/her/them know, ask/asking.
            _marker_m = _EMAIL_BODY_MARKER.search(_rest)
            if _marker_m:
                _rest_no_body = _rest[: _marker_m.start()].strip()
                _body_lower   = _rest[_marker_m.end():].strip()

                # Prefer body from raw text (preserves Whisper's capitalization).
                _body = ""
                if _raw_rest_email:
                    _raw_marker_m = _EMAIL_BODY_MARKER.search(_raw_rest_email)
                    if _raw_marker_m:
                        _body = _raw_rest_email[_raw_marker_m.end():].strip()
                        # Strip any residual leading punctuation (e.g. Whisper adds comma
                        # after "tell him" → "Tell him, the meeting..." → body=", the meeting...")
                        _body = re.sub(r'^[\s,\.!\?;:-]+', '', _body).strip()
                if not _body and _body_lower:
                    _body = _body_lower[0].upper() + _body_lower[1:]
            else:
                # No explicit body marker (e.g. "email Bob hey Bob everything is good").
                # Try to recover body by splitting on a known contact name prefix.
                # This handles the natural "email <name> <body>" pattern without a marker.
                _split_ename, _split_body_lower, _split_raw_body = _email_contact_split(
                    _rest, _raw_rest_email
                )
                if _split_body_lower:
                    # Contact prefix found — split succeeded.
                    _rest_no_body = _split_ename
                    _body_lower   = _split_body_lower
                    _body = (
                        _split_raw_body[0].upper() + _split_raw_body[1:]
                        if _split_raw_body
                        else _body_lower[0].upper() + _body_lower[1:]
                    )
                else:
                    # No contact prefix found — full rest is the recipient, no body.
                    _rest_no_body = _rest
                    _body = ""

            # Step 3: Polish body — capitalize first letter, ensure ends with period.
            # Port of Python reference _polish_email_body() basic fallback.
            if _body:
                _body = _body[0].upper() + _body[1:]
                if _body and _body[-1] not in ".!?":
                    _body += "."

            # Step 2: Extract subject from "about …" keyword.
            _subj_kw_m = re.search(r"\s+about\s+(.+)$", _rest_no_body)
            _subject = _subj_kw_m.group(1).strip() if _subj_kw_m else ""
            _ename = (
                _rest_no_body[: _subj_kw_m.start()].strip()
                if _subj_kw_m
                else _rest_no_body
            ).rstrip(".")

            # Step 4: Auto-generate subject from first sentence if not set.
            # Port of Python reference _generate_email_subject() fallback.
            if not _subject and _body:
                _subj_first = re.split(r"[.!?]", _body)[0].strip()
                _subj_first = re.sub(
                    r"(?i)^(that|which|how|just|so|and|but|or)\s+", "", _subj_first
                ).strip()
                if _subj_first:
                    _subject = _subj_first[0].upper() + _subj_first[1:]
                    if len(_subject) > 60:
                        _subject = _subject[:57].rsplit(" ", 1)[0] + "..."
                else:
                    _subject = "Following up"

            if not _ename:
                # Malformed — fall through to plain dictation
                pass
            else:
                _contact_email = _lookup_contact_email(_ename)
                _found = bool(_contact_email)
                _to = _contact_email if _found else _ename.replace(" ", "%20")

                # Build mailto: URL — always include subject (fallback "Following up").
                # Port of Python reference _open_email_draft() URL construction.
                # Use safe="" for body/subject so all special chars are encoded.
                _params: list[str] = []
                _final_subject = _subject or "Following up"
                _params.append(
                    f"subject={_urlquote(_final_subject[0].upper() + _final_subject[1:], safe='')}"
                )
                if _body:
                    _params.append(f"body={_urlquote(_body, safe='')}")
                _mailto = "mailto:" + _to + ("?" + "&".join(_params) if _params else "")

                # HUD message — always surface what was parsed; annotate contact-not-found
                _disp = _ename.title()
                if _body:
                    _hud_suffix = "body filled"
                elif _subject:
                    _hud_suffix = "subject filled"
                else:
                    _hud_suffix = "click body to dictate"
                if not _found:
                    _hud_suffix = f"contact not found — {_hud_suffix}"
                _hud = f"Draft to {_disp} — {_hud_suffix}"

                return {"action": "open_url", "url": _mailto,
                        "hud": _hud, "hud_color": "#0a84ff"}

        # ── Create snippet ────────────────────────────────────────────────────
        if lower in ("create snippet", "new snippet", "add snippet", "make snippet"):
            _snippet_state = "waiting_trigger"
            return {"action": "snippet_waiting_trigger",
                    "hud": "Say the trigger phrase…", "hud_color": "#0a84ff"}

    return None


def cmd_transcribe_last(cmd: dict) -> dict:
    global _last_result, _cmd_last_text, _snippet_state, _snippet_trigger
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
            # vad_filter removes silent/noise-only segments before transcription.
            # Without it, Whisper processes leading silence and hallucinates
            # continuation punctuation (leading commas/periods) — matches the
            # stable Python app which passes these same three params.
            vad_filter=True,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            **transcribe_kwargs,
        )
        raw_text = " ".join(seg.text.strip() for seg in segments).strip()
        # Strip hallucinated leading punctuation (safety net even with vad_filter).
        # Whisper occasionally starts output with ", " or ". " when it treats the
        # audio as a continuation; this never represents real speech.
        raw_text = re.sub(r'^[\s,\.!\?]+', '', raw_text).strip()
        t_whisper = int((time.time() - t_whisper_start) * 1000)
        _log(f"Whisper: {raw_text!r} ({t_whisper}ms)")

        # Remove Whisper repetition hallucinations
        raw_text = _deduplicate_whisper(raw_text)

        # ── Snippet capture state machine ─────────────────────────────────────
        # Intercept dictation BEFORE command detection when we are mid-snippet
        # so that the trigger phrase or content is captured verbatim.
        if _snippet_state == "waiting_trigger":
            _snippet_trigger = raw_text.strip()
            _snippet_state = "waiting_content"
            t_total = int((time.time() - t_total_start) * 1000)
            return {
                "ok":              True,
                "text":            None,
                "action":          "snippet_trigger_received",
                "backspace_count": 0,
                "key":             None,
                "with_shift":      False,
                "repeat":          1,
                "modifier":        None,
                "nav_target":      None,
                "app_name":        None,
                "url":             None,
                "direction":       None,
                "level":           None,
                "screenshot_type": None,
                "force":           False,
                "hud":     f"Trigger: \"{_snippet_trigger[:30]}\" — now say the content",
                "hud_color": "#0a84ff",
                "timing":  {"whisper": t_whisper, "ollama": 0, "total": t_total},
            }
        elif _snippet_state == "waiting_content":
            _content     = raw_text.strip()
            _trigger_key = _snippet_trigger.lower().strip()
            _save_snippet(_trigger_key, _content)
            _snippet_state   = "idle"
            _snippet_trigger = ""
            t_total = int((time.time() - t_total_start) * 1000)
            return {
                "ok":              True,
                "text":            None,
                "action":          "snippet_saved",
                "backspace_count": 0,
                "key":             None,
                "with_shift":      False,
                "repeat":          1,
                "modifier":        None,
                "nav_target":      None,
                "app_name":        None,
                "url":             None,
                "direction":       None,
                "level":           None,
                "screenshot_type": None,
                "force":           False,
                "hud":     f"Snippet \"{_trigger_key[:25]}\" saved!",
                "hud_color": "#30d158",
                "timing":  {"whisper": t_whisper, "ollama": 0, "total": t_total},
            }

        # ── Command detection (before Ollama / corrections) ───────────────────
        # Normalize: lowercase, strip non-alpha/digit/space — same as Python app.
        lower_cmd = re.sub(r"[^a-z0-9 ]", "", raw_text.lower()).strip()
        safe_mode_on = settings.get("safe_mode", False)

        jarvis_on = settings.get("jarvis_enabled", True)
        if not safe_mode_on and lower_cmd:
            cmd_result = _cmd_detect(lower_cmd, raw_text, jarvis_enabled=jarvis_on, active_app=active_app)
            if cmd_result is not None:
                _log(f"Command detected: action={cmd_result['action']} lower={lower_cmd!r}")

                # ── translate_last: run Ollama inline before returning ─────────
                if cmd_result["action"] == "translate_last":
                    _src = _cmd_last_text
                    if not _src:
                        t_total = int((time.time() - t_total_start) * 1000)
                        return {
                            "ok": True, "text": None, "action": "noop",
                            "backspace_count": 0, "key": None, "with_shift": False,
                            "repeat": 1, "modifier": None, "nav_target": None,
                            "app_name": None, "url": None, "direction": None,
                            "level": None, "screenshot_type": None, "force": False,
                            "hud": "Nothing to translate", "hud_color": "#ff9f0a",
                            "timing": {"whisper": t_whisper, "ollama": 0, "total": t_total},
                        }
                    _lang = (cmd_result.get("language")
                             or settings.get("translate_target_language", "English"))
                    if not _lang or _lang in ("Off", "off"):
                        _lang = "English"
                    try:
                        import requests as _req
                        _prompt = (f"Translate the following text to {_lang}. "
                                   f"Return only the translation:\n\n{_src}")
                        _resp = _req.post(
                            "http://localhost:11434/api/generate",
                            json={"model": "qwen2.5:3b", "prompt": _prompt, "stream": False},
                            timeout=20,
                        )
                        if _resp.ok:
                            _translated = _resp.json().get("response", "").strip()
                            if _translated:
                                _bc = len(_src) + 1
                                _cmd_last_text = _translated
                                _cmd_add_to_history(_translated)
                                t_total  = int((time.time() - t_total_start) * 1000)
                                t_ol_ms  = max(0, t_total - t_whisper)
                                return {
                                    "ok": True, "text": _translated,
                                    "action": "format_paste",
                                    "backspace_count": _bc,
                                    "key": None, "with_shift": False, "repeat": 1,
                                    "modifier": None, "nav_target": None,
                                    "app_name": None, "url": None, "direction": None,
                                    "level": None, "screenshot_type": None, "force": False,
                                    "hud": f"Translated to {_lang.title()}!",
                                    "hud_color": "#0a84ff",
                                    "timing": {"whisper": t_whisper, "ollama": t_ol_ms, "total": t_total},
                                }
                    except Exception as _te:
                        _log(f"translate_last error: {_te}")
                    # Translation failed — fall through to error noop
                    t_total = int((time.time() - t_total_start) * 1000)
                    return {
                        "ok": True, "text": None, "action": "noop",
                        "backspace_count": 0, "key": None, "with_shift": False,
                        "repeat": 1, "modifier": None, "nav_target": None,
                        "app_name": None, "url": None, "direction": None,
                        "level": None, "screenshot_type": None, "force": False,
                        "hud": "Translation failed", "hud_color": "#ff3b30",
                        "timing": {"whisper": t_whisper, "ollama": 0, "total": t_total},
                    }

                # ── snippet_waiting_trigger: update state and return ──────────
                if cmd_result["action"] == "snippet_waiting_trigger":
                    # _snippet_state was already set to "waiting_trigger" in _cmd_detect
                    t_total = int((time.time() - t_total_start) * 1000)
                    return {
                        "ok": True, "text": None, "action": "snippet_waiting_trigger",
                        "backspace_count": 0, "key": None, "with_shift": False,
                        "repeat": 1, "modifier": None, "nav_target": None,
                        "app_name": None, "url": None, "direction": None,
                        "level": None, "screenshot_type": None, "force": False,
                        "hud": cmd_result.get("hud"), "hud_color": "#0a84ff",
                        "timing": {"whisper": t_whisper, "ollama": 0, "total": t_total},
                    }

                t_total = int((time.time() - t_total_start) * 1000)
                return {
                    "ok":     True,
                    "text":   cmd_result.get("text"),
                    "action": cmd_result["action"],
                    "backspace_count": cmd_result.get("backspace_count", 0),
                    "key":    cmd_result.get("key"),
                    "with_shift": cmd_result.get("with_shift", False),
                    "repeat": cmd_result.get("repeat", 1),
                    "modifier": cmd_result.get("modifier"),
                    "nav_target": cmd_result.get("nav_target"),
                    # Jarvis command fields
                    "app_name":        cmd_result.get("app_name"),
                    "url":             cmd_result.get("url"),
                    "direction":       cmd_result.get("direction"),
                    "level":           cmd_result.get("level"),
                    "screenshot_type": cmd_result.get("screenshot_type"),
                    "force":           cmd_result.get("force", False),
                    "hud":    cmd_result.get("hud"),
                    "hud_color": cmd_result.get("hud_color", "#0a84ff"),
                    "timing": {"whisper": t_whisper, "ollama": 0, "total": t_total},
                }

        text = raw_text

        # ── Snippets (applied before Ollama — exact phrase triggers) ──────────
        text = apply_snippets(text)
        if text != raw_text:
            _log(f"Snippet expanded: {text!r}")

        # ── Ollama cleanup ─────────────────────────────────────────────────────
        t_ollama = 0
        ollama_text_raw: "str | None" = None   # raw Ollama output (before safety filter)
        ollama_accepted: "bool | None" = None  # True/False after safety filter; None if skipped
        ollama_reject_reason: "str | None" = None
        use_ollama   = settings.get("use_ollama", True)
        ai_mode      = settings.get("ai_cleanup_mode", "auto")
        strength     = settings.get("correction_strength", "Standard")
        safe_mode    = settings.get("safe_mode", False)
        ollama_model = "qwen2.5:3b"

        # Determine profile (auto-detect or manual)
        profile = get_active_writing_profile(settings, active_app if active_app else None)
        _log(f"Profile: {profile} (app={active_app!r})")

        word_count = len(_dictation_words(text)) if text else 0

        # Determine skip reason before deciding
        skip_reason_cleanup: "str | None" = None
        if safe_mode:
            skip_reason_cleanup = "safe_mode"
        elif not use_ollama:
            skip_reason_cleanup = "use_ollama=false"
        elif ai_mode == "off":
            skip_reason_cleanup = "ai_cleanup=off"
        elif strength == "Off":
            skip_reason_cleanup = "strength=Off"
        elif not text:
            skip_reason_cleanup = "empty_text"
        elif word_count <= 4:
            skip_reason_cleanup = f"too_short ({word_count} words ≤ 4)"
        elif ai_mode == "auto" and word_count < 10:
            skip_reason_cleanup = f"auto_short ({word_count} words < 10)"

        skip_ollama = skip_reason_cleanup is not None

        _log(
            f"[cleanup] mode={ai_mode} strength={strength} model={ollama_model} "
            f"words={word_count} skip={skip_ollama} reason={skip_reason_cleanup!r}"
        )

        t_request_ms: int = 0  # Ollama HTTP round-trip only (0 if skipped)
        if not skip_ollama:
            t_ollama_start = time.time()
            try:
                import requests
                system_prompt = build_ollama_system_prompt(profile, strength)
                t_request_start = time.time()
                resp = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": ollama_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user",   "content": text},
                        ],
                        "stream": False,
                        "keep_alive": "30m",
                        "options": {
                            "repeat_penalty": 1.15,
                            "num_predict":    180,
                            "temperature":    0.35,
                            "top_p":          0.85,
                        },
                    },
                    timeout=12,
                )
                t_request_ms = int((time.time() - t_request_start) * 1000)
                if resp.ok:
                    raw_ollama = resp.json().get("message", {}).get("content", "").strip()
                    if raw_ollama:
                        cleaned = strip_ollama_preamble(raw_ollama)
                        ollama_text_raw = cleaned  # capture before safety filter
                        ok, reason = ollama_result_is_safe(text, cleaned)
                        ollama_accepted = ok
                        if ok:
                            text = cleaned
                            ollama_reject_reason = None
                            _log(f"[cleanup] accepted  request={t_request_ms}ms  result={text!r}")
                        else:
                            ollama_accepted = False
                            ollama_reject_reason = reason
                            _log(f"[cleanup] REJECTED ({reason})  request={t_request_ms}ms  result={cleaned!r}")
                    else:
                        _log(f"[cleanup] empty response from Ollama  request={t_request_ms}ms")
                else:
                    _log(f"[cleanup] HTTP {resp.status_code}  request={t_request_ms}ms")
                t_ollama = int((time.time() - t_ollama_start) * 1000)
                _log(
                    f"[cleanup] total={t_ollama}ms request={t_request_ms}ms "
                    f"model={ollama_model} words={word_count} "
                    f"accepted={ollama_accepted}"
                )
            except Exception as e:
                t_ollama = int((time.time() - t_ollama_start) * 1000)
                skip_reason_cleanup = f"error: {e}"
                _log(f"[cleanup] exception after {t_ollama}ms: {e}")

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

        # ── Disfluency cleanup (runs whether or not Ollama ran) ──────────────
        text = remove_disfluencies(text, profile)

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

        # ── Update command history for scratch/format commands ────────────────
        if text:
            _cmd_last_text = text
            _cmd_add_to_history(text)

        t_total = int((time.time() - t_total_start) * 1000)
        result = {
            "ok":          True,
            "text":        text,
            "action":      None,
            "timing":      {"whisper": t_whisper, "ollama": t_ollama, "total": t_total},
            "profile":     profile,
            # Cleanup metadata — used by HUD skipped badge and timing card
            "skipped_cleanup":    skip_ollama,
            "skip_reason":        skip_reason_cleanup,
            "ollama_accepted":    ollama_accepted,
            "ollama_reject_reason": ollama_reject_reason,
            "ollama_request_ms":  t_request_ms,
            "ollama_model":       ollama_model if not skip_ollama else None,
            "word_count":         word_count,
            # History enrichment — only include when they differ from final text
            "whisper_text": raw_text if raw_text != text else None,
            "ollama_text":  ollama_text_raw,
            "active_app":  active_app or None,
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
    if _wake_listening:
        threading.Thread(target=_resume_wake_stream, daemon=True).start()
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
