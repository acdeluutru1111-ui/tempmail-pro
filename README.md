---
title: TempMail Pro
emoji: 📧
colorFrom: indigo
colorTo: purple
sdk: docker
pinned: false
---

# 📧 TempMail Pro

Temporary email service with IP rotation via Cloudflare Workers.

## 🏗️ Architecture

```
User → Render.com (Flask server) → Cloudflare Worker (IP rotation) → SmailPro API
```

- **Render.com** — Server chính: logic, cache, rate limit, UI
- **Cloudflare Worker** — Middleware đổi IP mỗi request (~100K IPs)
- **Chi phí:** $0/tháng

## 📦 Project Structure

```
tempmail-pro/
├── app.py                  # Flask server (backend + frontend)
├── requirements.txt        # Python dependencies
├── render.yaml             # Render deployment config
├── Procfile                # Process file
├── .env.example            # Environment variables template
├── .gitignore
└── worker/
    ├── index.js            # Cloudflare Worker (IP rotation proxy)
    └── wrangler.toml       # Worker config
```

## 🚀 Deployment

### 1. Deploy Cloudflare Worker

```bash
# Install wrangler
npm install -g wrangler

# Login
wrangler login

# Navigate to worker directory
cd worker

# Set secrets (paste your cookie values)
wrangler secret put XSRF_TOKEN
wrangler secret put SONJJ_SESSION
wrangler secret put API_KEY        # Set a strong password

# Deploy
wrangler deploy
# → Copy the worker URL (e.g., https://tempmail-worker.xxx.workers.dev)
```

### 2. Deploy to Render.com

```bash
# Init git and push to GitHub
git init
git add .
git commit -m "Deploy TempMail Pro"
gh repo create tempmail-pro --public --source=. --push
```

Then on [Render Dashboard](https://dashboard.render.com):
1. **New** → **Web Service**
2. Connect GitHub repo `tempmail-pro`
3. Render auto-detects `render.yaml`
4. Set environment variables:
   - `CLOUDFLARE_WORKER_URL` = your Worker URL
   - `WORKER_API_KEY` = same key you set in Worker
5. **Deploy**

### 3. Update Cookies

Cookies expire periodically. Update via:

**Option A:** POST to `/api/cookies`
```bash
curl -X POST https://your-app.onrender.com/api/cookies \
  -H "Content-Type: application/json" \
  -d '{"xsrf_token": "NEW_VALUE", "sonjj_session": "NEW_VALUE"}'
```

**Option B:** Update Worker secrets
```bash
cd worker
wrangler secret put XSRF_TOKEN
wrangler secret put SONJJ_SESSION
```

## 💻 Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run (direct connection, no Worker needed)
python app.py

# Open http://localhost:5000
```

To test with Worker locally:
```bash
# Set env vars
set CLOUDFLARE_WORKER_URL=https://tempmail-worker.xxx.workers.dev
set WORKER_API_KEY=your-key

python app.py
```

## 📊 Capacity

| Resource | Limit | Status |
|----------|-------|--------|
| Render Free Tier | 750 hrs/month | ✅ |
| Cloudflare Workers | 100K req/day | ✅ |
| IP Pool | ~100,000 IPs | ✅ |
| Max Users | ~500 concurrent | ✅ |

## ⚠️ Notes

- **Render cold start:** ~30s after 15min idle (free tier)
- **Cookie expiry:** SmailPro cookies expire → update via `/api/cookies` or Worker secrets
- **Rate limit:** Client-side 10 req/min/IP (server-side protection)
