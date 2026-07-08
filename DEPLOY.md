# 🚀 Deploy Crypto Signal Bot to Render (FREE)

Render lets you run a **free background worker** — perfect for this bot since it doesn't need a website, just a 24/7 Python process.

---

## Prerequisites

Before deploying, make sure you have:

1. ✅ A **GitHub account** — [github.com](https://github.com)
2. ✅ A **Render account** — [render.com](https://render.com) (sign up with GitHub)
3. ✅ Your **API keys** ready:
   - `ALPHAVANTAGE_API_KEY` — from [alphavantage.co](https://www.alphavantage.co/support/#api-key)
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `TELEGRAM_CHAT_ID` — your Telegram chat ID

---

## Step-by-Step Deployment

### Step 1: Push Code to GitHub

Open a terminal in the project folder and run:

```bash
git init
git add .
git commit -m "Initial commit - Crypto Signal Bot"
```

Then create a repo on GitHub and push:

```bash
git remote add origin https://github.com/YOUR_USERNAME/crypto-signal-bot.git
git branch -M main
git push -u origin main
```

### Step 2: Create a Render Account

1. Go to [render.com](https://render.com)
2. Click **"Get Started for Free"**
3. Sign up with your **GitHub account** (easiest)

### Step 3: Deploy as Background Worker

#### Option A: Using the Blueprint (Easiest)

1. Go to [render.com/dashboard](https://dashboard.render.com)
2. Click **"New"** → **"Blueprint"**
3. Connect your GitHub repo
4. Render will detect the `render.yaml` file automatically
5. Fill in the **secret environment variables** when prompted:
   - `ALPHAVANTAGE_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
6. Click **"Apply"** — done! 🎉

#### Option B: Manual Setup

1. Go to [render.com/dashboard](https://dashboard.render.com)
2. Click **"New"** → **"Background Worker"**
3. Connect your GitHub repo
4. Configure:
   - **Name:** `crypto-signal-bot`
   - **Region:** Singapore (or closest to you)
   - **Runtime:** Docker
   - **Plan:** Free
5. Add **Environment Variables:**

   | Key | Value |
   |-----|-------|
   | `ALPHAVANTAGE_API_KEY` | your_key_here |
   | `TELEGRAM_BOT_TOKEN` | your_bot_token |
   | `TELEGRAM_CHAT_ID` | your_chat_id |
   | `POLL_INTERVAL` | 60 |
   | `TRADE_UPDATE_INTERVAL` | 300 |
   | `CONFIDENCE_THRESHOLD` | 0.70 |

6. Click **"Create Background Worker"**

### Step 4: Verify It's Working

1. In the Render dashboard, click on your service
2. Go to the **"Logs"** tab
3. You should see output like:
   ```
   CRYPTO SIGNAL GENERATOR
   Symbols  : BTC/USDT, ETH/USDT
   Interval : 60s
   ── Cycle 1 ──
   Scanning BTC/USDT
   ```
4. Check your **Telegram** — you should receive signals when conditions are met!

---

## ⚙️ Configuration

You can change any setting via **Environment Variables** in the Render dashboard (no redeployment needed — just restart the service):

| Variable | Default | Description |
|----------|---------|-------------|
| `SYMBOLS` | `BTC/USDT,ETH/USDT` | Comma-separated trading pairs |
| `POLL_INTERVAL` | `60` | Seconds between scan cycles |
| `TRADE_UPDATE_INTERVAL` | `300` | Seconds between trade updates |
| `CONFIDENCE_THRESHOLD` | `0.70` | Min confidence to trigger signal (0-1) |
| `TECHNICAL_WEIGHT` | `0.6` | Weight for technical analysis |
| `SENTIMENT_WEIGHT` | `0.4` | Weight for sentiment analysis |
| `SL_ATR_MULT` | `1.5` | Stop-loss ATR multiplier |
| `RISK_REWARD` | `2.0` | Risk-reward ratio for targets |

---

## 🔄 Auto-Deploy on Git Push

Render automatically redeploys when you push to `main`:

```bash
git add .
git commit -m "Update config"
git push
```

The bot will restart with the new code within ~2 minutes.

---

## 📝 Important Notes

- **Free tier**: The worker may spin down after 15 minutes of inactivity. However, since your bot polls continuously, it stays alive.
- **Render free tier limits**: 750 hours/month of free usage (enough for 24/7 for one service).
- **Logs**: Available in the Render dashboard under your service → "Logs" tab.
- **Restart**: You can manually restart from the dashboard if needed.
- **.env file**: Never commit your `.env` file! Use Render's environment variables instead.
