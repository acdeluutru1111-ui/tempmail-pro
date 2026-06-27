---
title: TempMail Telegram Bot
emoji: 📧
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# 📧 TempMail Telegram Bot

Telegram bot for temporary email with token system, CPA offers, and premium subscriptions.

## Features

- 📧 Temporary Gmail generation
- 🎯 Token system (earn & spend)
- 📺 Rewarded video ads
- 🎮 Mini games (spin wheel)
- 📋 CPA offers integration
- 👥 Referral program
- 👑 Premium subscriptions
- 🌐 IP rotation via Cloudflare Worker

## Architecture

```
Telegram User → Telegram Bot (polling) → Flask API → Cloudflare Worker → SmailPro API
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token from @BotFather |
| `CLOUDFLARE_WORKER_URL` | ❌ | Worker URL for IP rotation |
| `WORKER_API_KEY` | ❌ | Worker authentication key |
| `XSRF_TOKEN` | ❌ | SmailPro XSRF cookie |
| `SONJJ_SESSION` | ❌ | SmailPro session cookie |
| `CPAGRIP_USER_ID` | ❌ | CPAGrip user ID for offers |
| `PORT` | ❌ | Server port (default: 7860) |

## Quick Start

### 1. Create Telegram Bot
1. Open Telegram → search @BotFather
2. Send `/newbot` → follow instructions
3. Copy the bot token

### 2. Deploy to HF Spaces
```bash
# Clone or create Space
huggingface-cli repo create tempmail-bot --type space --space_sdk docker

# Push code
git add .
git commit -m "Initial bot"
git push
```

### 3. Set Secrets
Go to Space Settings → Variables and secrets:
- `BOT_TOKEN` = your bot token
- `CLOUDFLARE_WORKER_URL` = (optional) worker URL
- `WORKER_API_KEY` = (optional) worker key

### 4. Test
Open Telegram → find your bot → send `/start`

## Project Structure

```
├── app.py                  # Main: Flask + Bot dual-mode
├── bot/
│   ├── handlers.py         # Command & callback handlers
│   ├── tasks.py            # Tasks: video, game, offers, referral
│   ├── database.py         # JSON-based user database
│   └── messages.py         # Text templates
├── services/
│   ├── email_service.py    # SmailPro + Worker email logic
│   └── cpa_service.py      # CPA offers
├── utils/
│   ├── cache.py            # In-memory cache
│   └── helpers.py          # Utility functions
├── worker/
│   ├── index.js            # Cloudflare Worker proxy
│   └── wrangler.toml       # Worker config
├── requirements.txt
├── Dockerfile
└── .env.example
```
