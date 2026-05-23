# Quill Tauri Preview — Feature Parity Audit

Last updated: 2026-05-23

---

## Local correction pipeline

| Feature | Python app | Tauri sidecar | Status |
|---|---|---|---|
| SymSpell English typo correction | ✓ | ✓ | Confirmed working |
| SymSpell skipped for non-English | ✓ | ✓ | Confirmed working |
| Personal corrections (vocab.corrections) | ✓ | ✓ | Confirmed working |
| Profile aliases (multi-word → abbreviation) | ✓ | ✓ | Confirmed working |
| Developer: UI/HUD contextual fixes | ✓ | ✓ | Confirmed working |
| Developer fixes off for other profiles | ✓ | ✓ | Confirmed working |
| Inline linebreaks ("next line" / "next paragraph") | ✓ | ✓ | Confirmed working |
| Linebreaks survive personal corrections | ✓ | ✓ | Confirmed working |
| Mojibake repair (smart-quotes, NBSP, accents) | ✓ | ✓ | Confirmed working |
| Smart punctuation (terminal period/question mark) | ✓ | ✓ | Confirmed working |
| Snippets (exact-phrase expansion, before Ollama) | ✓ | ✓ | Confirmed working |
| Whisper personal vocabulary prompt | ✓ | ✓ | Confirmed working |
| Ollama cleanup (with profile + strength) | ✓ | ✓ | Confirmed working |
| App-context formatting (email, terminal, casual) | ✓ | ✓ | Confirmed working |
| Clipboard preservation after paste | N/A (not in Python) | ✓ | Implemented (new) |

## Correction pipeline order (post-Ollama)

```
[English]
  symspell_correct(text)
  → repair_mojibake(smart_punctuate(...))
  → apply_profile_aliases (multi-word only, profile-gated)
  → _apply_ui_context_fix (Developer profile only)
  → _apply_hud_context_fix (Developer profile only)

[Non-English]
  repair_mojibake(smart_punctuate(text))
  [SymSpell and profile aliases skipped]

[All languages]
  → apply_inline_linebreaks ("next line" / "next paragraph" → \n)
  → apply_corrections (personal vocab["corrections"])
  → words_to_digits
  → format_for_app
  → paste
```

## Next parity buckets (priority order)

1. Voice commands: scratch / undo / redo / formatting commands
2. Privacy / temp WAV audit (ensure WAV files are deleted after transcription)
3. AI Cleanup / Ollama onboarding UX
4. Ollama installed-model selector
5. Small UI bugs
6. Packaging / app identity cleanup
