# WhisperFlow — CLAUDE.md

## Project Overview

WhisperFlow is a browser-based voice-to-text tool with AI grammar correction. Everything lives in a single `index.html` — no frameworks, no build tools, no bundlers. The browser's built-in Web Speech API handles real-time transcription for free (no API key needed for speech). Anthropic Claude API is used only for the optional grammar/punctuation correction step.

## Tech Stack

- **Vanilla HTML/CSS/JS** — single file, no dependencies
- **Web Speech API** (`SpeechRecognition`) — real-time transcription
- **Anthropic Claude API** (`claude-sonnet-4-20250514`) — grammar/post-processing, called via `fetch()`
- **sessionStorage** — ephemeral API key storage only; nothing persistent

## Feature List (build order)

1. Microphone start/stop button with recording state indicator
2. Real-time interim transcription display (updates as user speaks)
3. Final transcript accumulation with speaker pause detection
4. Grammar/punctuation fix button → calls Claude API
5. Diff view showing original vs. corrected text
6. Copy-to-clipboard button
7. Export-as-.txt download button
8. Session history sidebar (last 5 transcripts, stored in memory)
9. Live word/character count stats
10. Language selector: en-US, en-GB, en-IN, hi-IN, ne-NP

## Web Speech API Implementation Rules

### Configuration
```js
const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
recognition.continuous = true;    // keep listening until user stops
recognition.interimResults = true; // get partial words as they're spoken
recognition.lang = 'en-US';        // controlled by language selector
```

### Auto-restart
On `recognition.onend`, **always** restart via `recognition.start()` — **unless** the user has explicitly clicked the stop button. Use a boolean flag (e.g. `isStoppedByUser`) to distinguish intentional stops from natural timeouts.

### Error handling
- `recognition.onerror`: Log the error. If `error === 'no-speech'`, silently restart (this is common during silence). For other errors (`not-allowed`, `language-not-supported`, `service-not-allowed`), stop the loop and show a user-facing message in the UI. Do **not** show alerts for transient `no-speech` errors.
- Wrap `recognition.start()` in try-catch to handle `InvalidStateError` (recognition already started).

### Transcript accumulation
- `recognition.onresult` receives `SpeechRecognitionEvent`. Iterate `event.results` from `event.resultIndex` to the end.
- If `result.isFinal`, append `result[0].transcript` to the final transcript string with a trailing space.
- If not final, update the interim display line.
- Track a `silenceTimer`: reset on each new `result`. If no new results for ~1.5 seconds, treat as an utterance boundary (insert newline in final transcript).

### Cleanup
On page unload or explicit stop, call `recognition.abort()` (not `stop()`) to immediately halt without firing unnecessary `onend`/`onerror`.

## Claude API System Prompt for Grammar Fix

```
You are a grammar and punctuation correction assistant. Your task is to:
1. Fix grammar, spelling, and punctuation errors in the provided transcript
2. Add proper capitalization and line breaks where appropriate
3. Preserve the original meaning and wording as much as possible
4. Do NOT add, remove, or rephrase content beyond what is needed for correction
5. Do NOT add commentary, notes, or explanations — output only the corrected text
6. If the input appears to be in a language other than English and you can correct it, do so; otherwise return it as-is

Return ONLY the corrected transcript text, nothing else.
```

## UI Design Tokens

| Token | Value |
|---|---|
| Background | `#0D0D0D` (near-black) |
| Surface | `#1A1A1A` |
| Surface-hover | `#242424` |
| Border | `#2A2A2A` |
| Text primary | `#E8E8E8` |
| Text secondary | `#888888` |
| Text muted | `#555555` |
| Accent (recording) | `#0ECECE` |
| Accent dim | `#0A9A9A` |
| Error | `#FF4444` |
| Diff insert bg | `rgba(14, 206, 206, 0.1)` |
| Diff insert text | `#0ECECE` |
| Diff delete bg | `rgba(255, 68, 68, 0.1)` |
| Diff delete text | `#FF6666` |
| Font (transcript) | `'Geist Mono', 'JetBrains Mono', monospace` |
| Font (UI) | `'Inter', -apple-system, sans-serif` |
| Font size (base) | `14px` |
| Font size (transcript) | `16px` |
| Radius | `8px` |
| Radius (small) | `4px` |
| Transition | `150ms ease` |

## Code Quality & Naming Rules

- **No comments in production code** — let the code speak for itself
- **No external dependencies** — zero npm packages, no CDN scripts
- **CSS**: Use CSS custom properties (variables) for all design tokens. BEM-like naming for classes (e.g. `.transcript__display`, `.controls__btn--record`). No preprocessors.
- **JavaScript**: `camelCase` for variables and functions, `UPPER_SNAKE_CASE` for constants. Group code into labelled sections: `// DOM refs`, `// State`, `// Speech recognition`, `// Claude API`, `// UI helpers`, `// Event listeners`, `// Init`.
- **HTML**: Semantic elements (`<main>`, `<header>`, `<section>`, `<button>`, `<select>`). One `<h1>` for the title. ARIA labels on interactive controls.
- **Event listeners**: Use `addEventListener`, never inline `onclick` attributes. Attach all listeners in the `// Init` section.
- **Error handling**: Every async operation (Claude API call, clipboard write) must have try-catch with a user-facing fallback. No unhandled promise rejections.
- **No inline styles** — all styles in the embedded `<style>` block.
- **Formatting**: 2-space indentation. Single quotes for strings. Semicolons required.
