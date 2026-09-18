# RPS Arena Telegram Bot

A private, head-to-head Rock Paper Scissors Telegram bot. Players issue a challenge in a group, then choose their weapons privately through the bot so neither player can see the other choice early.

## Features

- Group challenges with secret one-on-one move selection
- Best-of-five matches (first to three); a drawn round awards both players a point and raises the target
- Persistent SQLite game state and player statistics
- Per-weapon results, streaks, personal stats, leaderboard, and match cancellation

## Requirements

- Python 3.10 or newer
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="your_telegram_bot_token"
python bot.py
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and set the token with `$env:BOT_TOKEN="your_telegram_bot_token"`.

The bot creates `rps.sqlite3` in the current directory by default. To use a different location, set `RPS_DB` before starting it:

```bash
export RPS_DB="/path/to/rps.sqlite3"
```

## Bot commands

| Command | Use |
| --- | --- |
| `/start` | Open the bot or enter a match from its private link |
| `/challenge` | Reply to someone in a group, then run this command to start a match |
| `/stats` | Show your overall and weapon-specific performance |
| `/leaderboard` | Show the top 10 players |
| `/cancel` | Cancel your latest active match in the current group |

## Add to GitHub

Keep `BOT_TOKEN` private. This repository's `.gitignore` excludes `.env` files and local SQLite databases. Copy `.env.example` to `.env` only if you use a tool that loads environment files; the bot itself reads `BOT_TOKEN` and `RPS_DB` from its environment.
