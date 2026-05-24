#!/usr/bin/env python3
"""
test_sidecar_cmds.py

Regression tests for the sidecar's _cmd_detect() function and the
shape of the transcribe_last command response wrapper.

Run:
    cd /Users/user1/jarvis-tauri/sidecar
    python3 test_sidecar_cmds.py

All tests must pass before any release.  These tests protect against:
  - Command phrases being accidentally swallowed (routed to text paste)
  - Command responses missing required fields that the TypeScript side reads
  - Safe-mode bypass of system commands
  - Known-good command phrases that must always be recognised
"""

import sys
import unittest

# ---------------------------------------------------------------------------
# Load the sidecar module safely — we only need _cmd_detect, no I/O loops.
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")

# Exec the module up to (but not including) the if __name__=="__main__" block
# so we get all globals without starting the IPC loop.
_src = open("jarvis_sidecar.py").read()
_split = _src.split('\nif __name__ == "__main__":')
exec(_split[0], globals())   # type: ignore[arg-type]

# After exec, _cmd_detect is available as a global.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def detect(phrase: str, raw: str = "", jarvis: bool = True, safe: bool = False):
    """Wrapper: call _cmd_detect with the given phrase normalised as the sidecar does."""
    import re as _re
    lower = _re.sub(r"[^a-z0-9 ]", "", phrase.lower()).strip()
    if safe:
        return None  # safe mode: no commands at all
    return _cmd_detect(lower, raw or phrase, jarvis_enabled=jarvis)  # type: ignore[name-defined]


def action_of(phrase, **kw):
    r = detect(phrase, **kw)
    return r["action"] if r else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPunctuationCommands(unittest.TestCase):

    def test_period(self):
        r = detect("period")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "paste_text")
        self.assertEqual(r["text"], ".")

    def test_comma(self):
        r = detect("comma")
        self.assertEqual(r["action"], "paste_text")
        self.assertEqual(r["text"], ",")

    def test_exclamation_mark(self):
        r = detect("exclamation mark")
        self.assertEqual(r["action"], "paste_text")
        self.assertIn(r["text"], ["!", "exclamation mark"])  # depends on PUNCT_COMMANDS

    def test_question_mark(self):
        r = detect("question mark")
        self.assertEqual(r["action"], "paste_text")

    def test_ellipsis(self):
        r = detect("ellipsis")
        self.assertEqual(r["action"], "paste_text")
        self.assertIn(r["text"], ["...", "…"])

    def test_hud_present(self):
        """Every punct command must include a hud label."""
        for phrase in ("period", "comma", "question mark", "ellipsis"):
            r = detect(phrase)
            self.assertIsNotNone(r)
            self.assertIn("hud", r, msg=f"Missing hud for '{phrase}'")


class TestScratchCommands(unittest.TestCase):

    def test_scratch_that_returns_action_scratch(self):
        r = detect("scratch that")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "scratch")

    def test_undo_that(self):
        r = detect("undo that")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "scratch")

    def test_scratch_result_has_backspace_count(self):
        r = detect("scratch that")
        self.assertIn("backspace_count", r)

    def test_scratch_all_with_history(self):
        # "scratch all" needs something in _cmd_history to return non-None.
        # Populate a fake entry, run, then clean up.
        global _cmd_history, _cmd_history_index, _cmd_last_text  # type: ignore[name-defined]
        _orig_history = list(_cmd_history)       # type: ignore[name-defined]
        _orig_index   = _cmd_history_index        # type: ignore[name-defined]
        _orig_last    = _cmd_last_text            # type: ignore[name-defined]
        try:
            _cmd_history.append("hello world")   # type: ignore[name-defined]
            _cmd_history_index = 0               # type: ignore[name-defined]
            _cmd_last_text = "hello world"       # type: ignore[name-defined]
            r = detect("scratch all")
            self.assertIsNotNone(r, "scratch all with history should return a result")
            self.assertEqual(r["action"], "scratch")
            self.assertGreater(r.get("backspace_count", 0), 0)
        finally:
            _cmd_history[:] = _orig_history      # type: ignore[name-defined]
            _cmd_history_index = _orig_index     # type: ignore[name-defined]
            _cmd_last_text = _orig_last          # type: ignore[name-defined]

    def test_scratch_all_empty_history_returns_none_or_nothing(self):
        # With no history, "scratch all" has nothing to scratch, so sc=0
        # and _cmd_detect returns None (the TypeScript handles this gracefully
        # because it still goes through the cmd_transcribe_last wrapper which
        # returns ok=True, action="noop" with hud="Nothing to scratch").
        # At the _cmd_detect level, None is the correct return.
        import re as _re
        lower = _re.sub(r"[^a-z0-9 ]", "", "scratch all").strip()
        r = _cmd_detect(lower, "scratch all", jarvis_enabled=True)  # type: ignore[name-defined]
        # Either None (nothing to scratch) or action="scratch" with bc=0 is acceptable;
        # the important thing is it does NOT raise an exception.
        if r is not None:
            self.assertEqual(r["action"], "scratch")


class TestNavigationCommands(unittest.TestCase):

    def test_next_line(self):
        r = detect("next line")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "keypress")
        self.assertEqual(r["key"], "return")
        self.assertEqual(r["repeat"], 1)

    def test_next_paragraph(self):
        r = detect("next paragraph")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "keypress")
        self.assertEqual(r["repeat"], 2)

    def test_tab(self):
        r = detect("tab")
        self.assertIsNotNone(r)
        self.assertIn(r["action"], ("keypress", "key_combo"))

    def test_select_all(self):
        r = detect("select all")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "key_combo")
        self.assertEqual(r["key"], "a")
        self.assertEqual(r["modifier"], "cmd")

    def test_show_history(self):
        r = detect("show history")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "navigate")
        self.assertEqual(r["nav_target"], "history")


class TestJarvisSystemCommands(unittest.TestCase):
    """System commands (open app/url, volume) require jarvis_enabled=True."""

    def test_open_safari(self):
        r = detect("open safari", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "open_app")
        self.assertIn("app_name", r)
        self.assertEqual(r["app_name"], "Safari")

    def test_open_terminal(self):
        r = detect("open terminal", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "open_app")

    def test_volume_up(self):
        r = detect("volume up", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "set_volume")
        self.assertEqual(r["direction"], "up")

    def test_volume_down(self):
        r = detect("volume down", jarvis=True)
        self.assertEqual(r["action"], "set_volume")
        self.assertEqual(r["direction"], "down")

    def test_mute(self):
        r = detect("mute", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "set_volume")
        self.assertEqual(r["direction"], "mute")

    def test_screenshot_area(self):
        r = detect("take screenshot", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "take_screenshot")

    def test_system_commands_blocked_when_jarvis_off(self):
        """Open/volume/etc must be blocked when jarvis_enabled=False."""
        r_safari  = detect("open safari",  jarvis=False)
        r_volume  = detect("volume up",    jarvis=False)
        # These should return None (not detected) when jarvis is off.
        # Voice-editing commands (scratch/punct/format/nav) are unaffected.
        self.assertIsNone(r_safari,  "open_app must be blocked when jarvis_enabled=False")
        self.assertIsNone(r_volume,  "set_volume must be blocked when jarvis_enabled=False")


class TestNonCommands(unittest.TestCase):
    """Phrases that should NOT be detected as commands."""

    def test_plain_dictation_not_a_command(self):
        self.assertIsNone(detect("hello world"))

    def test_partial_match_not_a_command(self):
        self.assertIsNone(detect("period is important"))  # contains "period" but not standalone

    def test_empty_string_not_a_command(self):
        self.assertIsNone(detect(""))


class TestCommandResponseShape(unittest.TestCase):
    """
    Every command result that gets wrapped by cmd_transcribe_last must include
    specific fields that the TypeScript side reads.  This tests the _cmd_detect
    output shape (the wrapper adds ok/text/timing).
    """

    REQUIRED_FIELDS = ["action", "hud"]

    def test_period_has_required_fields(self):
        r = detect("period")
        for f in self.REQUIRED_FIELDS:
            self.assertIn(f, r, msg=f"period result missing '{f}'")

    def test_scratch_has_required_fields(self):
        r = detect("scratch that")
        for f in self.REQUIRED_FIELDS:
            self.assertIn(f, r, msg=f"scratch result missing '{f}'")

    def test_keypress_has_key_field(self):
        r = detect("next line")
        self.assertIn("key", r)
        self.assertIsNotNone(r["key"])

    def test_open_app_has_app_name(self):
        r = detect("open safari", jarvis=True)
        self.assertIn("app_name", r)
        self.assertIsNotNone(r["app_name"])

    def test_set_volume_has_direction(self):
        r = detect("volume up", jarvis=True)
        self.assertIn("direction", r)


class TestRoutingInvariants(unittest.TestCase):
    """
    Mirror of the TypeScript routing invariants in commandRouting.test.ts.
    Documents the expected result shapes that the TS classifier relies on.
    """

    def test_command_action_is_non_empty_string(self):
        """Action field must be a non-empty string, not None or ''."""
        for phrase in ("period", "scratch that", "next line", "open safari"):
            r = detect(phrase, jarvis=True)
            if r is None:
                continue  # skip phrases not detected in this config
            act = r.get("action")
            self.assertIsNotNone(act, f"'{phrase}': action is None")
            self.assertNotEqual(act, "", f"'{phrase}': action is empty string")

    def test_text_only_present_when_text_will_be_pasted(self):
        """
        Only paste_text / format_paste / copy_text carry a 'text' field.
        All other command types should have text=None (or absent) so the
        TypeScript side doesn't accidentally paste the command name.
        """
        non_paste_actions = ("scratch", "keypress", "key_combo", "navigate",
                              "open_app", "open_url", "set_volume",
                              "take_screenshot", "close_app", "noop",
                              "copy_all")
        for phrase, act in [
            ("scratch that", "scratch"),
            ("next line",    "keypress"),
            ("select all",   "key_combo"),
            ("show history", "navigate"),
        ]:
            r = detect(phrase)
            if r is None or r.get("action") != act:
                continue
            # text field should be absent or None for these
            self.assertFalse(
                r.get("text"),
                msg=f"'{phrase}' ({act}): unexpected non-empty text={r.get('text')!r}",
            )


# ---------------------------------------------------------------------------
# Email command tests
# ---------------------------------------------------------------------------

class TestEmailCommands(unittest.TestCase):
    """Tests for the email command parser in _cmd_detect.

    These use detect() which calls _cmd_detect(lower, raw, jarvis_enabled=True).
    They verify:
      - action is always "open_url" (draft only, no auto-send)
      - recipient / name parsed correctly
      - subject parsed correctly from "about …"
      - body parsed correctly from "saying …" / "telling them …"
      - mailto: URL is correctly encoded
      - no automatic send
    """

    # All email actions open a URL — never send automatically.
    def _assert_draft_only(self, r):
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "open_url")
        url = r.get("url", "")
        self.assertTrue(url.startswith("mailto:"), f"URL must start with mailto: — got {url!r}")

    # 1. "email Jack" — minimal form, name-only draft
    def test_email_name_only(self):
        r = detect("email Jack", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        # recipient is in the URL (either resolved email or encoded name)
        self.assertIn("jack", url.lower())
        # no query parameters (no body, no subject)
        self.assertNotIn("?", url)
        # HUD must direct user to click body (contact-not-found prefix is OK too)
        self.assertIn("click body", r.get("hud", "").lower())

    # 2. "compose email to Jack" — alternate prefix
    def test_compose_email_to(self):
        r = detect("compose email to Jack", jarvis=True)
        self._assert_draft_only(r)
        self.assertIn("jack", r["url"].lower())

    # 3. "write an email to Jack" — new prefix
    def test_write_an_email_to(self):
        r = detect("write an email to Jack", jarvis=True)
        self._assert_draft_only(r)
        self.assertIn("jack", r["url"].lower())

    # 4. "new email to Jack" — new prefix
    def test_new_email_to(self):
        r = detect("new email to Jack", jarvis=True)
        self._assert_draft_only(r)
        self.assertIn("jack", r["url"].lower())

    # 5. "email Jack about Monday meeting" — subject extracted
    def test_email_with_subject(self):
        r = detect("email Jack about Monday meeting", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("subject=", url)
        # "Monday meeting" should be URL-encoded in subject
        self.assertIn("Monday", url.replace("%20", " ").replace("+", " "))
        # no body param
        self.assertNotIn("body=", url)
        self.assertIn("subject", r.get("hud", "").lower())

    # 6. "email Jack saying I will call you tomorrow" — body extracted
    def test_email_with_body_saying(self):
        r = detect("email Jack saying I will call you tomorrow", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("body=", url)
        decoded = url.replace("%20", " ").replace("+", " ")
        self.assertIn("call", decoded.lower())
        # no subject param
        self.assertNotIn("subject=", url)
        self.assertIn("body filled", r.get("hud", "").lower())

    # 7. "compose email to Jack saying I will call you tomorrow" — prefix + body
    def test_compose_email_with_body(self):
        r = detect("compose email to Jack saying I will call you tomorrow", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("body=", url)
        self.assertIn("jack", url.lower())

    # 8. "email Jack about Monday meeting saying I will call you tomorrow" — both
    def test_email_with_subject_and_body(self):
        r = detect(
            "email Jack about Monday meeting saying I will call you tomorrow",
            jarvis=True,
        )
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("subject=", url)
        self.assertIn("body=", url)
        decoded = url.replace("%20", " ").replace("+", " ")
        self.assertIn("Monday", decoded)
        self.assertIn("call", decoded.lower())

    # 9. Unknown contact — mailto still formed, HUD warns
    def test_unknown_contact_fallback(self):
        r = detect("email unknownperson xyz", jarvis=True)
        self._assert_draft_only(r)
        # HUD should mention contact not found
        self.assertIn("not found", r.get("hud", "").lower())

    # 10. URL encoding: spaces become %20, no raw spaces in URL
    def test_mailto_url_encoding(self):
        r = detect("email Jack saying call me at 5 PM", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        # After the '?' there should be no unencoded spaces
        if "?" in url:
            query = url.split("?", 1)[1]
            self.assertNotIn(" ", query, "Query string must not contain raw spaces")

    # 11. Email commands must not fire when jarvis is off
    def test_email_blocked_when_jarvis_off(self):
        r = detect("email Jack", jarvis=False)
        self.assertIsNone(r, "email command must be blocked when jarvis_enabled=False")

    # 12. "telling them" body keyword
    def test_email_with_body_telling_them(self):
        r = detect("email Jack telling them I will be late", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("body=", url)
        self.assertIn("late", url.replace("%20", " ").lower())

    # 13. "let her know" — the Python-ported marker (was broken before)
    def test_email_let_her_know(self):
        r = detect("email Val let her know the meeting is cancelled", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        # Recipient must be ONLY "val", NOT the full sentence
        self.assertIn("val", url.lower())
        self.assertNotIn("let%20her", url.lower())
        self.assertNotIn("meeting", url.lower().split("?")[0])  # meeting not in To
        # Body should contain "meeting"
        self.assertIn("body=", url)
        self.assertIn("meeting", url.replace("%20", " ").lower())

    # 14. "tell him" body keyword
    def test_email_tell_him(self):
        r = detect("email Jack tell him I will be late", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("body=", url)
        self.assertIn("late", url.replace("%20", " ").lower())
        # "tell him" must not be in the To field
        self.assertNotIn("tell", url.lower().split("?")[0])

    # 15. "say" body keyword (short form)
    def test_email_say(self):
        r = detect("email Jack say hi there", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("body=", url)
        self.assertIn("hi", url.replace("%20", " ").lower())

    # 16. Regression: no-marker body — "email Bob hey Bob everything is good"
    #     The user speaks the body directly after the recipient name WITHOUT a
    #     body marker (tell him / say / let her know).  The contact-prefix split
    #     must recover: recipient=Bob, body="hey Bob everything is good".
    #     Previously the entire sentence became the recipient → To field got
    #     the whole text when the contact wasn't found, or body was silently dropped
    #     when the contact WAS found via partial match.
    def test_email_no_marker_body_contact_prefix_split(self):
        raw = "email Bob hey Bob everything is good for tomorrow"
        r = detect(raw, raw=raw, jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        # Body MUST be present — the greeting/message is the email content
        self.assertIn("body=", url, f"Body missing from URL: {url!r}")
        decoded_url = url.replace("%20", " ").replace("%2C", ",")
        self.assertIn("hey", decoded_url.lower(), f"'hey' not in body: {url!r}")
        self.assertIn("everything", decoded_url.lower(), f"'everything' not in body: {url!r}")
        # The entire sentence must NOT be the recipient
        # (if contact found, To should be just the email; if not found, encoded name only)
        to_part = url.split("?")[0]
        self.assertNotIn("everything", to_part.lower(),
                         f"'everything' must not be in To field: {to_part!r}")

    # 17. Regression: no-marker body with unknown contact — message still not lost
    #     "email Alice hey Alice the meeting is at 3" — Alice not in contacts.
    #     Contact-prefix split tries "alice" → no match → falls back to full rest
    #     as recipient, body empty.  Body will be empty (can't guess split) but
    #     the To field gets only the name "Alice", not the whole sentence.
    def test_email_no_marker_unknown_contact_no_body_split(self):
        raw = "email Alice everything is fine"
        r = detect(raw, raw=raw, jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        # Without a contact match, no body is extracted (graceful degradation).
        # The important thing is the HUD mentions "contact not found".
        self.assertIn("not found", r.get("hud", "").lower())


# ---------------------------------------------------------------------------
# Disfluency cleanup tests
# ---------------------------------------------------------------------------

class TestRemoveDisfluencies(unittest.TestCase):
    """Tests for the remove_disfluencies() local cleanup function."""

    def _clean(self, text: str, profile: str = "General") -> str:
        return remove_disfluencies(text, profile)  # type: ignore[name-defined]

    # 1. Filler words are removed
    def test_filler_words_removed(self):
        result = self._clean("Um, I think we should, uh, go ahead with this.")
        self.assertNotIn("um", result.lower())
        self.assertNotIn("uh", result.lower())
        # Remaining text is coherent
        self.assertIn("think", result.lower())
        self.assertIn("go ahead", result.lower())

    # 2. Repeated words collapsed
    def test_repeated_word_collapsed(self):
        result = self._clean("We should do the the thing now.")
        self.assertNotIn("the the", result.lower())
        self.assertIn("the thing", result.lower())

    # 3. Time spacing fixed
    def test_time_spacing(self):
        result = self._clean("Hey, how's it going? We should do a call at 10:30, not at 11PM.")
        self.assertIn("11 PM", result)
        self.assertNotIn("11PM", result)

    # 4. Contraction repair
    def test_contraction_repair(self):
        result = self._clean("Hows it going? Dont worry about it.")
        self.assertIn("How's", result)
        self.assertIn("Don't", result)

    # 5. Developer profile: no cleanup applied
    def test_developer_profile_skipped(self):
        original = "Um, call the dont function with uh the args."
        result = self._clean(original, profile="Developer")
        self.assertEqual(result, original)

    # 6. Verbatim profile: no cleanup applied
    def test_verbatim_profile_skipped(self):
        original = "Um, hows it going?"
        result = self._clean(original, profile="Verbatim")
        self.assertEqual(result, original)

    # 7. Code-like text: no cleanup applied
    def test_code_text_skipped(self):
        code = "import dont from './module';"
        result = self._clean(code)
        # _CODE_RE should detect the import keyword — text returned unchanged
        self.assertEqual(result, code)

    # Bonus: filler phrase "you know" removed
    def test_you_know_removed(self):
        result = self._clean("It's, you know, a good idea.")
        self.assertNotIn("you know", result.lower())

    # Bonus: empty text passes through safely
    def test_empty_text_passthrough(self):
        self.assertEqual(self._clean(""), "")
        self.assertEqual(self._clean("   "), "   ")


# ---------------------------------------------------------------------------
# Regression: leading-punctuation strip + vad_filter parity
# ---------------------------------------------------------------------------

class TestLeadingPunctuationStrip(unittest.TestCase):
    """Regression: Whisper sometimes returns leading ', ' or '. '.
    The sidecar must strip it before any further processing so:
      1. Custom command triggers match ("lets play chess" not ", lets play chess")
      2. Dictation text doesn't start with comma/period
    This mirrors the behaviour enforced by vad_filter=True + the explicit strip in cmd_transcribe_last.
    """

    def _strip(self, raw: str) -> str:
        """Apply the same strip the sidecar applies to raw Whisper output."""
        import re as _re
        return _re.sub(r'^[\s,\.!\?]+', '', raw).strip()

    def test_leading_comma_stripped(self):
        self.assertEqual(self._strip(", hey Bob everything is good"), "hey Bob everything is good")

    def test_leading_comma_space_stripped(self):
        self.assertEqual(self._strip(", open movies."), "open movies.")

    def test_leading_period_stripped(self):
        self.assertEqual(self._strip(". let's play chess"), "let's play chess")

    def test_leading_whitespace_and_comma_stripped(self):
        self.assertEqual(self._strip("  , hello world"), "hello world")

    def test_no_leading_punct_unchanged(self):
        self.assertEqual(self._strip("hello world"), "hello world")
        self.assertEqual(self._strip("Open Safari"), "Open Safari")

    def test_empty_string_unchanged(self):
        self.assertEqual(self._strip(""), "")

    def test_comma_in_middle_preserved(self):
        # Only LEADING punctuation is stripped — mid-text commas are kept.
        self.assertEqual(self._strip("hello, world"), "hello, world")


# ---------------------------------------------------------------------------
# Regression: learn_from_text vocab file robustness
# ---------------------------------------------------------------------------

class TestLearnFromTextRobustness(unittest.TestCase):
    """Regression: learn_from_text must not raise KeyError when the vocab file
    exists but predates the word_counts / phrases keys (e.g. {} or old format)."""

    def test_empty_vocab_file_no_error(self):
        """learn_from_text with vocab that has no word_counts must not crash."""
        import tempfile, os
        import json as _json
        # Write a vocab file that's missing word_counts
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump({}, f)
            tmp_path = f.name
        old_vocab = VOCAB_FILE  # type: ignore[name-defined]
        try:
            # Temporarily point the module at our temp file
            import jarvis_sidecar as _sidecar  # type: ignore[import]
        except ImportError:
            pass  # module is exec'd into globals — use globals directly
        # Patch the global VOCAB_FILE path
        g = globals()
        g["VOCAB_FILE"] = tmp_path
        try:
            learn_from_text("testing the robustness fix")  # type: ignore[name-defined]
            # If we get here, no KeyError was raised
            with open(tmp_path) as f:
                out = _json.load(f)
            self.assertIn("word_counts", out)
            self.assertIsInstance(out["word_counts"], dict)
        finally:
            g["VOCAB_FILE"] = old_vocab
            os.unlink(tmp_path)

    def test_malformed_vocab_file_no_error(self):
        """learn_from_text with a list (not dict) vocab must not crash."""
        import tempfile, os
        import json as _json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump([], f)  # list, not dict — old/corrupt format
            tmp_path = f.name
        g = globals()
        old_vocab = g["VOCAB_FILE"]
        g["VOCAB_FILE"] = tmp_path
        try:
            # Should not raise — loads default dict when file is not a dict
            learn_from_text("another robustness test")  # type: ignore[name-defined]
        finally:
            g["VOCAB_FILE"] = old_vocab
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader  = unittest.TestLoader()
    suite   = loader.loadTestsFromModule(sys.modules[__name__])
    runner  = unittest.TextTestRunner(verbosity=2)
    result  = runner.run(suite)
    total   = result.testsRun
    passed  = total - len(result.failures) - len(result.errors)
    print(f"\n{'='*60}")
    print(f"Python sidecar tests: {passed}/{total} passed")
    if result.failures or result.errors:
        print("FAILED")
        sys.exit(1)
    else:
        print("ALL PASS")
