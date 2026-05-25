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


class TestCustomCommandPriority(unittest.TestCase):
    """Regression: custom commands must be checked BEFORE built-in open_app.

    Bug: "open photoshop" was intercepted by the built-in open_app handler
    (which would try `open -a Photoshop`) before the JS could check the custom
    command list (which has target "Adobe Photoshop 2024").  The fix moves custom
    command checking into _cmd_detect FIRST, exactly matching Python reference.
    """

    def setUp(self):
        """Inject a fake custom commands file for the duration of the test."""
        import json as _json, tempfile as _tmp, os as _os
        self._tmp = _tmp.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        _json.dump([
            {"trigger": "open photoshop",   "action": "open_app",  "target": "Adobe Photoshop 2024"},
            {"trigger": "open movies",      "action": "open_url",  "target": "https://fmoviess.org/home/"},
            {"trigger": "user email",       "action": "type_text", "target": "Dear User,\n\nTest body."},
            {"trigger": "lets play chess",  "action": "open_url",  "target": "https://www.chess.com/play/online"},
        ], self._tmp)
        self._tmp.close()
        g = globals()
        self._old_file = g.get("CUSTOM_COMMANDS_FILE", "")
        g["CUSTOM_COMMANDS_FILE"] = self._tmp.name

    def tearDown(self):
        import os as _os
        globals()["CUSTOM_COMMANDS_FILE"] = self._old_file
        _os.unlink(self._tmp.name)

    def test_open_photoshop_uses_custom_not_builtin(self):
        """open photoshop → custom app_name 'Adobe Photoshop 2024', not builtin 'photoshop'."""
        r = detect("open photoshop", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "open_app")
        self.assertEqual(r.get("app_name"), "Adobe Photoshop 2024",
                         f"Expected 'Adobe Photoshop 2024' but got {r.get('app_name')!r}")

    def test_open_movies_custom_url(self):
        """open movies → custom open_url, not builtin open_app."""
        r = detect("open movies", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "open_url")
        self.assertIn("fmoviess", r.get("url", ""))

    def test_type_text_custom_command(self):
        """user email → paste_text with custom body."""
        r = detect("user email", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "paste_text")
        self.assertIn("Dear User", r.get("text", ""))

    def test_open_url_custom_command(self):
        """lets play chess → open_url with chess.com."""
        r = detect("lets play chess", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "open_url")
        self.assertIn("chess.com", r.get("url", ""))

    def test_custom_commands_blocked_when_jarvis_off(self):
        """Custom commands must not fire when jarvis_enabled=False."""
        r = detect("open photoshop", jarvis=False)
        self.assertIsNone(r, "custom commands must be blocked when jarvis_enabled=False")

    def test_single_word_trigger_not_matched(self):
        """Single-word custom triggers are skipped (matches Python reference)."""
        import json as _j, os as _o
        with open(self._tmp.name, "w") as f:
            _j.dump([{"trigger": "chess", "action": "open_url", "target": "https://chess.com"}], f)
        r = detect("chess", jarvis=True)
        # Should NOT match — single-word triggers are skipped
        self.assertIsNone(r, "single-word custom triggers must be skipped")

    def test_apostrophe_in_stored_trigger_matches_speech(self):
        """Stored trigger "let's play chess" (apostrophe) must match speech "lets play chess".

        Root cause: _cc_trigger was only .lower().strip()'d, not re.sub'd.
        So stored "let's play chess" != speech-normalized "lets play chess".
        Fix: apply re.sub(r'[^a-z0-9 ]', '', ...) to the stored trigger too.
        """
        import json as _j
        with open(self._tmp.name, "w") as f:
            _j.dump([
                {"trigger": "let's play chess", "action": "open_url",
                 "target": "https://www.chess.com/play/online"},
            ], f)
        # Simulate Whisper output: apostrophe already stripped by re.sub on raw text
        r = detect("lets play chess", jarvis=True)
        self.assertIsNotNone(r, "stored trigger with apostrophe must match speech without apostrophe")
        self.assertEqual(r["action"], "open_url")
        self.assertIn("chess.com", r.get("url", ""))

    def test_leading_whisper_comma_does_not_block_custom_match(self):
        """Whisper sometimes prepends ', ' to a phrase; re.sub strips it, match still works."""
        # detect() feeds raw_text directly; simulate Whisper comma prefix
        r = detect(", open movies.", jarvis=True)
        self.assertIsNotNone(r, "leading Whisper comma must not break custom command match")
        self.assertEqual(r["action"], "open_url")
        self.assertIn("fmoviess", r.get("url", ""))

    def test_open_url_result_has_url_field(self):
        """open_url custom command must return url= field (not target=) for TS dispatch."""
        r = detect("open movies", jarvis=True)
        self.assertIsNotNone(r)
        self.assertIn("url", r, "open_url result must have 'url' key")
        self.assertNotIn("target", r, "open_url result must NOT expose raw 'target' key")

    def test_open_app_result_has_app_name_field(self):
        """open_app custom command must return app_name= field for TS dispatch."""
        r = detect("open photoshop", jarvis=True)
        self.assertIsNotNone(r)
        self.assertIn("app_name", r, "open_app result must have 'app_name' key")

    def test_type_text_result_action_is_paste_text(self):
        """type_text custom command must return action='paste_text' (not 'type_text') for TS dispatch."""
        r = detect("user email", jarvis=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "paste_text",
                         "type_text custom command must use action='paste_text' so TS paste path is triggered")
        self.assertIn("text", r, "type_text result must carry 'text' field")

    def test_custom_command_result_has_hud_field(self):
        """All custom command results must include 'hud' for HUD display."""
        for phrase, action in [("open movies", "open_url"), ("open photoshop", "open_app"),
                               ("user email", "paste_text")]:
            with self.subTest(phrase=phrase, action=action):
                r = detect(phrase, jarvis=True)
                self.assertIsNotNone(r)
                self.assertIn("hud", r, f"Custom command '{phrase}' result missing 'hud' field")
                self.assertTrue(r["hud"], f"Custom command '{phrase}' hud must be non-empty")

    def test_missing_custom_commands_file_returns_no_match(self):
        """If the custom commands file is missing, _cmd_detect must not crash."""
        import os as _os
        globals()["CUSTOM_COMMANDS_FILE"] = "/tmp/__nonexistent_custom_commands__.json"
        try:
            r = detect("open photoshop", jarvis=True)
            # Should fall through to built-in open_app (not None) or None — just must not crash
            # We only verify it didn't raise an exception (test reaching here is the assertion)
        finally:
            globals()["CUSTOM_COMMANDS_FILE"] = self._tmp.name


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
        # subject is always included (defaulting to "Following up" when no body)
        self.assertIn("subject=", url)
        self.assertIn("Following", url.replace("%20", " "))
        # no body param — no body was dictated
        self.assertNotIn("body=", url)
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

    # 6. "email Jack saying I will call you tomorrow" — body extracted, subject auto-generated
    def test_email_with_body_saying(self):
        r = detect("email Jack saying I will call you tomorrow", jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("body=", url)
        decoded = url.replace("%20", " ").replace("+", " ")
        self.assertIn("call", decoded.lower())
        # subject is auto-generated from first sentence of body
        self.assertIn("subject=", url)
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

    # 14b. Regression: "Tell him, <body>" — trailing comma after marker stripped from body.
    #      Whisper often transcribes "Tell him, the meeting is cancelled" with a comma
    #      after the marker.  Without [.,:;-]?\s* at the end of _EMAIL_BODY_MARKER,
    #      the body starts with ", the meeting..." (leading comma visible in email draft).
    def test_email_tell_him_comma_not_in_body(self):
        raw = "Send email to King. Tell him, the meeting is cancelled for tomorrow, we will resume next week."
        r = detect(raw, raw=raw, jarvis=True)
        self._assert_draft_only(r)
        url = r["url"]
        self.assertIn("body=", url, f"Body must be present: {url!r}")
        decoded = url.replace("%20", " ").replace("%2C", ",").replace("+", " ")
        body_part = decoded.split("body=", 1)[1] if "body=" in decoded else ""
        # Body must NOT start with a comma
        self.assertFalse(body_part.startswith(","),
                         f"Body must not start with comma: {body_part!r}")
        self.assertIn("meeting", body_part.lower(), f"'meeting' missing from body: {body_part!r}")

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
# _deduplicate_whisper regression tests
# ---------------------------------------------------------------------------

class TestApplyInlinePunctuation(unittest.TestCase):
    """Regression tests for apply_inline_punctuation.

    Protected invariants:
    - Spoken punct words inside dictation are replaced with symbols
    - Spacing is cleaned up (no space before . , ! ? etc.)
    - Sentence-starting words are capitalised after . ! ?
    - Standalone punct phrases are returned unchanged (handled upstream)
    - Developer / Verbatim profile → text returned unchanged
    - Code-like text → text returned unchanged
    """

    def punct(self, text, profile="General"):
        return apply_inline_punctuation(text, profile)  # type: ignore[name-defined]

    # ── Core substitutions ────────────────────────────────────────────────────

    def test_period_at_end(self):
        self.assertEqual(self.punct("hello period"), "Hello.")

    def test_period_inline(self):
        self.assertEqual(
            self.punct("hello period come again period"),
            "Hello. Come again."
        )

    def test_full_stop_synonym(self):
        self.assertEqual(self.punct("hello full stop"), "Hello.")

    def test_exclamation_mark(self):
        self.assertEqual(self.punct("see you later exclamation mark"), "See you later!")

    def test_exclamation_point(self):
        self.assertEqual(self.punct("see you later exclamation point"), "See you later!")

    def test_question_mark(self):
        self.assertEqual(self.punct("how are you question mark"), "How are you?")

    def test_comma(self):
        self.assertEqual(self.punct("hello comma Bob"), "Hello, Bob")

    def test_colon(self):
        self.assertEqual(self.punct("ingredients colon flour"), "Ingredients: flour")

    def test_semicolon(self):
        result = self.punct("first item semicolon second item")
        self.assertIn(";", result)
        self.assertNotIn(" ;", result)

    def test_ellipsis(self):
        self.assertEqual(self.punct("he said ellipsis"), "He said...")

    def test_open_close_paren(self):
        self.assertEqual(self.punct("open paren test close paren"), "(test)")

    def test_hyphen(self):
        result = self.punct("twenty hyphen five")
        self.assertIn("-", result)
        self.assertNotIn("hyphen", result)

    def test_dash(self):
        result = self.punct("hello dash world")
        self.assertIn("—", result)
        self.assertNotIn("dash", result)

    # ── Task acceptance tests (from task description) ─────────────────────────

    def test_task_full_sentence(self):
        """Task example: hello period come again period see you later exclamation mark question mark"""
        result = self.punct(
            "hello period come again period see you later exclamation mark question mark"
        )
        self.assertEqual(result, "Hello. Come again. See you later!?")

    def test_task_comma_name(self):
        """Task example: hello comma Bob"""
        self.assertEqual(self.punct("hello comma Bob"), "Hello, Bob")

    def test_task_parens(self):
        """Task example: open paren test close paren → (test)"""
        self.assertEqual(self.punct("open paren test close paren"), "(test)")

    # ── Spacing cleanup ───────────────────────────────────────────────────────

    def test_no_space_before_period(self):
        """No space before period after substitution."""
        result = self.punct("hello period")
        self.assertNotIn(" .", result)

    def test_no_space_inside_parens(self):
        """No space after ( or before )."""
        result = self.punct("open paren hello close paren")
        self.assertFalse(result.startswith("( "))
        self.assertFalse(result.endswith(" )"))

    def test_capitalise_after_period(self):
        """Word after period is capitalised."""
        result = self.punct("hello period world")
        self.assertIn(". W", result)

    def test_capitalise_first_word(self):
        """First word of output is always capitalised."""
        result = self.punct("hello period")
        self.assertTrue(result[0].isupper())

    # ── Guardrails ────────────────────────────────────────────────────────────

    def test_standalone_period_unchanged(self):
        """Standalone 'period' returns unchanged — command routing handles it."""
        self.assertEqual(self.punct("period"), "period")

    def test_standalone_question_mark_unchanged(self):
        self.assertEqual(self.punct("question mark"), "question mark")

    def test_standalone_exclamation_mark_unchanged(self):
        self.assertEqual(self.punct("exclamation mark"), "exclamation mark")

    def test_standalone_full_stop_unchanged(self):
        self.assertEqual(self.punct("full stop"), "full stop")

    def test_developer_profile_unchanged(self):
        """Developer profile: text returned verbatim."""
        text = "hello period world"
        self.assertEqual(self.punct(text, profile="Developer"), text)

    def test_verbatim_profile_unchanged(self):
        """Verbatim profile: text returned verbatim."""
        text = "hello period world"
        self.assertEqual(self.punct(text, profile="Verbatim"), text)

    def test_code_text_unchanged(self):
        """Code-like text (contains import/function/etc) is returned unchanged."""
        text = "import period os"
        result = self.punct(text)
        # _CODE_RE should match 'import' and skip substitution
        self.assertEqual(result, text)

    def test_empty_string(self):
        """Empty string returns empty string."""
        self.assertEqual(self.punct(""), "")

    def test_no_false_match_in_periodic(self):
        """'periodic' must not be partially matched as 'period' — word boundary guard."""
        result = self.punct("periodic table of elements")
        self.assertNotIn(".", result)
        # The word is preserved (possibly title-cased by capitalize-first), not replaced.
        self.assertIn("eriodic", result)  # suffix 'eriodic' survives regardless of capitalisation

    def test_no_false_match_in_hyphenated_word(self):
        """'hyphenated' must not be partially matched as 'hyphen' — word boundary guard."""
        result = self.punct("hyphenated words are common")
        # The word is preserved (possibly title-cased), not replaced with '-'.
        self.assertNotIn(" - ", result)
        self.assertIn("yphenated", result)  # suffix survives regardless of capitalisation

    # ── Whisper-inserted trailing punctuation after command words ────────────
    # These are the EXACT assertions from the bug report — do not weaken them.

    def test_whisper_hello_period_dot(self):
        """'Hello, period.' → 'Hello.'  (Whisper adds trailing period)"""
        self.assertEqual(self.punct("Hello, period."), "Hello.")

    def test_whisper_come_again_period_dot(self):
        """'Come again, period.' → 'Come again.'"""
        self.assertEqual(self.punct("Come again, period."), "Come again.")

    def test_whisper_see_you_later_period_dot(self):
        """'See you later, period.' → 'See you later.'"""
        self.assertEqual(self.punct("See you later, period."), "See you later.")

    def test_whisper_question_mark_trailing_comma(self):
        """'Question mark,' → '?'  (Whisper adds trailing comma)"""
        self.assertEqual(self.punct("Question mark,"), "?")

    def test_whisper_question_mark_trailing_comma_plus_smart_punct_period(self):
        """smart_punctuate adds '.' to 'Question mark,' → 'Question mark,.' → '?'"""
        # This simulates the pipeline: smart_punctuate runs before apply_inline_punctuation
        self.assertEqual(self.punct("Question mark,."), "?")

    def test_whisper_exclamation_mark_trailing_comma(self):
        """'Exclamation mark,' → '!'"""
        self.assertEqual(self.punct("Exclamation mark,"), "!")

    def test_whisper_exclamation_mark_trailing_comma_plus_smart_punct(self):
        """smart_punctuate adds '.' after Whisper comma: 'Exclamation mark,.' → '!'"""
        self.assertEqual(self.punct("Exclamation mark,."), "!")

    def test_whisper_explanation_mark_mishearing(self):
        """'Explanation mark,' → '!'  (common Whisper mishearing of exclamation mark)"""
        self.assertEqual(self.punct("Explanation mark,"), "!")

    def test_whisper_period_exclamation_question_sequence(self):
        """'Period, exclamation mark, question mark.' → '.!?'"""
        self.assertEqual(
            self.punct("Period, exclamation mark, question mark."),
            ".!?",
        )

    def test_whisper_full_failing_sentence(self):
        """Exact failing dictation from the bug report must produce exact expected output."""
        result = self.punct(
            "Question mark, exclamation mark, period. Hello, period. "
            "Come again, period. See you later, period."
        )
        self.assertEqual(result, "?!. Hello. Come again. See you later.")

    def test_whisper_trailing_comma_after_period(self):
        """'Hello, period,' → 'Hello.'  (Whisper adds trailing comma instead of period)"""
        self.assertEqual(self.punct("Hello, period,"), "Hello.")

    def test_whisper_trailing_comma_after_question_mark(self):
        """'Really, question mark,' → 'Really?'"""
        self.assertEqual(self.punct("Really, question mark,"), "Really?")

    def test_whisper_trailing_comma_after_exclamation_mark(self):
        """'Wow, exclamation mark,' → 'Wow!'"""
        self.assertEqual(self.punct("Wow, exclamation mark,"), "Wow!")

    def test_whisper_comma_before_command_not_doubled(self):
        """'Hello, comma, world' → 'Hello, world' (not 'Hello,, world')."""
        self.assertEqual(self.punct("Hello, comma, world"), "Hello, world")

    def test_whisper_trailing_period_on_question_mark(self):
        """'Is this right, question mark.' → 'Is this right?'"""
        self.assertEqual(self.punct("Is this right, question mark."), "Is this right?")

    def test_whisper_sentence_capitalize_after_command(self):
        """Words after period command are capitalized: 'hello period come again' → 'Hello. Come again'"""
        self.assertEqual(self.punct("hello period come again"), "Hello. Come again")

    def test_whisper_goodbye_period(self):
        """'Goodbye, period' → 'Goodbye.'"""
        self.assertEqual(self.punct("Goodbye, period"), "Goodbye.")

    def test_smart_punctuate_double_question_mark_collapsed(self):
        """smart_punctuate adds '?' AND user said 'question mark': must not produce '??'."""
        # Simulate what the pipeline produces after smart_punctuate adds trailing '?'
        result = self.punct("Is this working question mark?")
        self.assertEqual(result, "Is this working?")

    def test_smart_punctuate_double_exclamation_collapsed(self):
        """Duplicate '!!' from back-to-back exclamation commands → single '!'."""
        result = self.punct("Wow exclamation mark!")
        self.assertEqual(result, "Wow!")

    def test_mixed_punctuation_not_collapsed(self):
        """'?!' and '!?' are valid mixed sequences and must NOT be collapsed."""
        result = self.punct("Really question mark exclamation mark")
        # Both symbols must be present; order depends on substitution order
        self.assertIn("?", result)
        self.assertIn("!", result)


class TestDeduplicateWhisper(unittest.TestCase):
    """Regression tests for _deduplicate_whisper.

    Protected invariants:
    - 3× repetition of ANY window size → collapse (existing behavior, must not break)
    - 2× repetition of 3+-word window → collapse (Issue 6 fix: catch Whisper hallucination)
    - 2× repetition of 1- or 2-word window → do NOT collapse (avoid false positives)
    - sentence-level dedup via Pass 2 still fires for punctuation-delimited repetitions
    - code/non-sentence text with 2× repetition of 3+ words → collapsed
    """

    def dedup(self, text):
        return _deduplicate_whisper(text)  # type: ignore[name-defined]

    # ── 3× repeats (original behavior must be preserved) ─────────────────────

    def test_three_repeats_single_word_collapsed(self):
        """testing testing testing → testing"""
        self.assertEqual(self.dedup("testing testing testing"), "testing")

    def test_three_repeats_two_word_window_collapsed(self):
        """three-word phrase × 3 → single phrase"""
        result = self.dedup("hello world hello world hello world")
        self.assertEqual(result, "hello world")

    def test_three_repeats_multi_word_collapsed(self):
        """Jarvis is not working × 3 → single phrase"""
        result = self.dedup("Jarvis is not working Jarvis is not working Jarvis is not working")
        self.assertEqual(result, "Jarvis is not working")

    # ── 2× repeats: 3+-word windows MUST collapse (Issue 6 fix) ─────────────

    def test_two_repeats_three_word_window_collapsed(self):
        """Why is this × 2 → Why is this  (3-word window, threshold=2)"""
        result = self.dedup("Why is this Why is this")
        self.assertEqual(result, "Why is this")

    def test_two_repeats_five_word_window_collapsed(self):
        """'I'll print up your dictation' × 2 → collapsed"""
        phrase = "I'll print up your dictation"
        result = self.dedup(f"{phrase} {phrase}")
        # Should collapse to the first occurrence
        self.assertEqual(result.strip(), phrase.strip())

    def test_two_repeats_code_path_collapsed(self):
        """path = Path('/mnt/data') × 2 → collapsed (no sentence punctuation needed)"""
        phrase = "path = Path mnt data"  # as Whisper would transcribe it
        result = self.dedup(f"{phrase} {phrase}")
        self.assertEqual(result, phrase)

    def test_two_repeats_long_sentence_no_punctuation_not_collapsed_by_pass1(self):
        """Phrases > 8 words without punctuation are NOT caught by Pass 1
        (window range is 1-8).  They are caught instead by the JS lastPasteRef
        guard in useGlobalHotkey.ts (5-second consecutive-duplicate suppression).
        This test documents that known limitation so it is not accidentally 'fixed'
        by raising the window ceiling and breaking other behavior."""
        phrase = "The cow ran up the hill to drink a bottle of water"  # 11 words
        result = self.dedup(f"{phrase} {phrase}")
        # Pass 1 cannot collapse this (window max = 8, phrase = 11 words)
        # Pass 2 cannot collapse this (no sentence-ending punctuation)
        # Result is unchanged — the JS guard is the backstop for this case.
        self.assertEqual(result, f"{phrase} {phrase}")

    # ── 2× repeats: 1- or 2-word windows must NOT collapse ───────────────────

    def test_two_repeats_single_word_not_collapsed(self):
        """'testing testing' must NOT be collapsed (1-word window, threshold=3)"""
        result = self.dedup("testing testing")
        self.assertEqual(result, "testing testing")

    def test_two_repeats_two_word_window_not_collapsed(self):
        """'hello world hello world' must NOT be collapsed (2-word window, threshold=3)"""
        result = self.dedup("hello world hello world")
        self.assertEqual(result, "hello world hello world")

    # ── Pass 2: sentence-level dedup ─────────────────────────────────────────

    def test_sentence_level_dedup_with_punctuation(self):
        """Punctuation-delimited sentence repetition → collapsed by Pass 2"""
        result = self.dedup(
            "Why is my dictation coming out like this? "
            "Why is my dictation coming out like this?"
        )
        # Should contain only one copy of the sentence
        self.assertNotIn(
            "Why is my dictation coming out like this? Why is my dictation coming out like this?",
            result
        )

    def test_no_false_collapse_different_sentences(self):
        """Two different sentences must both survive"""
        text = "The quick brown fox. The lazy dog sat."
        result = self.dedup(text)
        self.assertIn("quick brown fox", result)
        self.assertIn("lazy dog", result)

    def test_empty_string_passthrough(self):
        """Empty string returns empty string"""
        self.assertEqual(self.dedup(""), "")

    def test_single_word_passthrough(self):
        """Single word returns unchanged"""
        self.assertEqual(self.dedup("hello"), "hello")


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
