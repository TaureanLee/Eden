# Shipping Eden

Eden is **two separate things**, and they ship in two different ways. Getting this
split right is the whole deployment story.

| Part | What it is | Where it runs |
|------|------------|---------------|
| **The analyzer** (`server.py` + `static/`) | The live EEG reader | **Locally, on the user's own machine** |
| **The website** (`site/`) | Marketing + guide | **Vercel** (or any static host) |

## Why the analyzer can't run on Vercel (or any cloud)

The live app is inherently local — this is not a limitation to "fix," it's the nature
of the product:

1. **The headset is paired to the user's own computer** (Bluetooth / USB / WiFi).
   A cloud server has no path to that physical device.
2. **It is stateful and long-running** — a background acquisition thread plus a
   persistent Server-Sent-Events stream. Vercel's serverless functions are stateless
   and time-limited; they can hold neither.
3. **BrainFlow needs native OS-level device access**, which serverless sandboxes
   don't provide.

So the analyzer is distributed as code the user runs locally (see the one-step
launchers in the [README](README.md)); the browser UI is simply served from
`http://127.0.0.1:5000`. No data ever leaves the user's machine.

---

## Deploying the website (`site/`) to Vercel

The `site/` folder is a plain static site (HTML/CSS/SVG + one screenshot) — no build
step, no framework, no environment variables.

### Option A — Vercel dashboard (recommended)

1. Push this repo to GitHub/GitLab/Bitbucket.
2. In Vercel: **Add New → Project**, import the repo.
3. Set **Root Directory** to `site`. Leave the framework preset as **Other**
   (no build command, no install command).
4. **Deploy.** That's it — `vercel.json` in `site/` handles caching + headers.

### Option B — Vercel CLI

```bash
npm i -g vercel
cd site
vercel            # preview deploy
vercel --prod     # production deploy
```

Running from **inside** `site/` keeps the Python app out of the deployment.

### Custom domain

Add a domain (e.g. `eden.exergis.com` or `eden.exergis.io`) in
**Project → Settings → Domains** and point the DNS record Vercel shows you.

---

## Any other static host

`site/` also deploys unchanged to **Netlify**, **Cloudflare Pages**, or
**GitHub Pages** — set the publish/root directory to `site` and there is no build
command. `vercel.json` is simply ignored by those hosts (headers can be reconfigured
per-host if desired).

---

## The logo

The site uses the real EDEN mark at
[`site/assets/eden-logo.png`](site/assets/eden-logo.png) — the original artwork with
its slate background keyed to transparent and margins trimmed, so it drops cleanly
onto any background. The compact [`favicon.svg`](site/assets/favicon.svg) is used for
the browser tab.

To refresh the logo later, replace `site/assets/eden-logo.png` with a new
transparent-background PNG (or any format) and keep the same filename — no HTML
changes needed.
