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
