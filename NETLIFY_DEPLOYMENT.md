# WhisperFlow — Netlify Deployment Guide

## Quick Deploy

1. **Push to GitHub**
   ```bash
   git add index.html
   git commit -m "Production-ready for Netlify"
   git push
   ```

2. **Connect to Netlify**
   - Go to [netlify.com](https://netlify.com)
   - Click "Add new site" → "Import an existing project"
   - Select your GitHub repo
   - Deploy settings:
     - **Base directory**: (leave empty)
     - **Build command**: (leave empty)
     - **Publish directory**: (leave empty)
   - Click **Deploy site**

3. **Your site is live!**
   The app will be available at `https://wisperflow.netlify.app/` (or your custom domain)

---

## How to Use on Netlify

### Getting Your Groq API Key

1. Sign up at [console.groq.com](https://console.groq.com)
2. Create an API key
3. Copy your key (starts with `gsk_...`)

### Using the App

1. Open your Netlify site
2. Click the **⚙️ settings icon** in the top-right
3. Paste your Groq API key into the field
4. Click **Save** — it's stored in your browser's session
5. Start speaking into the mic! 🎙️

---

## What Changed for Production

✅ **Local development** (`http://127.0.0.1:5500`) — Still tries to auto-load from `groq.key` file  
✅ **Netlify production** — Users must manually enter API key via settings popup  
✅ **All features work** — Grammar fix, transcription, export, history, copy all functional  
✅ **No build required** — Single HTML file, zero dependencies

---

## Important Notes

- **API Key is stored in browser session only** — Refreshing the page won't delete it, but closing the browser tab will. Users can always re-enter it.
- **Free tier** — Groq API has generous free limits (~1000 requests/month)
- **Privacy** — No transcript data is sent anywhere except to Groq's API for processing
- **Web Speech API** — Works in Chrome, Edge, Safari, Opera. Firefox support is limited.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No API key found" message | Click ⚙️ and paste your Groq API key |
| Mic not working | Check browser permissions (Chrome/Edge > Settings > Privacy > Microphone) |
| "Invalid API key" error | Make sure the key starts with `gsk_` and is copied completely |
| Rate limit hit | Wait ~1 hour. Groq free tier has usage limits. |
| Can't select language | Only EN, HI, NP languages supported in Web Speech API for these regions |

---

## Custom Domain

To use a custom domain:
1. In Netlify dashboard → **Domain settings** → **Custom domain**
2. Add your domain and follow DNS setup instructions
3. App will work identically at your custom domain

---

## Redeploy Updates

If you update `index.html`:
```bash
git add index.html
git commit -m "Update: [your change]"
git push
```
Netlify auto-deploys on push to main branch.
