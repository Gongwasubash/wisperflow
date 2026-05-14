# WhisperFlow Netlify Troubleshooting

## Language Translation & Auto-Fix Not Working?

### ✅ Quick Checklist

1. **API Key is SET** (Required!)
   - Click the **⚙️ settings icon** in top-right
   - Paste your Groq API key (starts with `gsk_`)
   - Click **Save**
   - Check if status shows "Key is set" ✓

2. **Browser Console for Debugging**
   - Press `F12` to open Developer Tools
   - Go to **Console** tab
   - Look for messages like:
     - `WhisperFlow loaded`
     - `API Key loaded: true` ✓ (or `false` ✗)
     - `Speech Recognition supported: true` ✓

---

## What Should Happen on Netlify

### 🎙️ **Recording** (Works without API key)
1. Click mic button
2. Speak into microphone
3. Text appears in real-time (interim)
4. When you pause ~1.5 sec, text becomes final

### 🌐 **Language Translation** (Requires API key)
1. Click **EN** / **HI** / **NP** button to change language
2. If you have existing text + API key → Auto-translates
3. If no API key → Warning toast appears: "Add your API key in settings ⚙️ to translate text"
4. Console shows: `Cannot translate: No API key set`

### ✏️ **Grammar Fix** (Requires API key)
- Auto-fixes 4 seconds after you stop speaking (if API key set)
- Click **Fix Grammar** button manually
- Without API key:
  - Button stays disabled while recording
  - No console warnings (silent skip)
  - Auto-fix timer doesn't trigger

---

## Debugging Steps

### Problem: Language buttons don't change
**Expected behavior:** Button should highlight immediately ✓
**Actual:** Nothing happens

**Solution:**
```
1. Open F12 Console
2. Click a language button
3. You should see a log message
4. If no logs appear = JavaScript error somewhere
```

### Problem: Auto-fix doesn't trigger
**Expected behavior:** 4 seconds after you stop speaking, text auto-corrects

**Solution:**
```
1. Speak some text with grammar errors: "i am going to the store"
2. Wait 4-5 seconds after you stop talking
3. Check Console (F12) for: "Auto-fixing grammar..." log
4. If no log = API key is missing
```

### Problem: Translation doesn't work
**Expected behavior:** Click EN→HI and existing text translates to Hindi

**Solution:**
1. Make sure you have text in the transcript
2. Click settings ⚙️ and paste API key
3. Click a different language button
4. Should see toast: "Translated to Hindi"
5. Check Console for API errors

---

## Common Error Messages

| Console Message | Meaning | Fix |
|---|---|---|
| `API Key loaded: false` | No API key in sessionStorage | Click ⚙️ → Paste key → Save |
| `Cannot translate: No API key set` | Tried to translate without key | Enter API key first |
| `Auto-fix skipped: No API key` | Auto-grammar was about to run but no key | Enter API key first |
| `Invalid Groq API key` | Key rejected by Groq | Check key starts with `gsk_`, copy completely |
| `Rate limit hit` | Used too many requests | Wait 1 hour, Groq free tier has limits |

---

## API Key Storage Behavior

- **Stored in:** Browser's sessionStorage (per-tab, per-session)
- **Lasts until:** Browser tab is closed OR you clear browser data
- **Reappears when:** You reload page (same tab)
- **Lost when:** Close browser/tab, clear cache, different browser
- **Never sent to:** Our servers — only to Groq's API

---

## If Still Not Working

1. **Check Groq Console** https://console.groq.com
   - Is your API key active? ✓
   - Do you have usage quota remaining? ✓
   - Any rate limit warnings?

2. **Test on localhost first**
   - Go to `http://127.0.0.1:5500/`
   - Does it work there? 
   - If yes: Netlify deployment issue
   - If no: Code issue (report bug)

3. **Check Browser Support**
   - Chrome, Edge, Safari, Opera = ✅ Full support
   - Firefox = ⚠️ Limited support
   - Other browsers = ❌ No Web Speech API

4. **Reset Browser**
   ```
   F12 → Application → Clear site data
   Reload page
   Re-enter API key
   ```

---

## Key Differences: Localhost vs Netlify

| Feature | Localhost | Netlify |
|---------|-----------|---------|
| groq.key auto-load | ✅ Yes | ❌ No (file doesn't exist on server) |
| Manual API key entry | ✅ Optional | ✅ Required |
| sessionStorage | ✅ Works | ✅ Works |
| Recording | ✅ Works | ✅ Works |
| Grammar fix | ✅ Works | ✅ Works (needs key) |
| Language translation | ✅ Works | ✅ Works (needs key) |

