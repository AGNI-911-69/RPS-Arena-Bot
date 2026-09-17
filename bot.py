"""Rock Paper Scissors 1v1 Telegram bot.

Run with BOT_TOKEN=... python bot.py.  The bot uses SQLite, so stats and
in-progress games survive restarts.
"""
import asyncio
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

TOKEN = os.environ.get("BOT_TOKEN")
DB_PATH = Path(os.environ.get("RPS_DB", "rps.sqlite3"))
MOVES = {"rock": "🪨 Rock", "paper": "📄 Paper", "scissors": "✂️ Scissors"}
BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def setup_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS players (
          user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT,
          wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
          draws INTEGER NOT NULL DEFAULT 0, matches INTEGER NOT NULL DEFAULT 0,
          rounds INTEGER NOT NULL DEFAULT 0, same_weapon INTEGER NOT NULL DEFAULT 0,
          current_streak INTEGER NOT NULL DEFAULT 0, best_streak INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS weapon_stats (
          user_id INTEGER NOT NULL, weapon TEXT NOT NULL,
          wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
          draws INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (user_id, weapon)
        );
        CREATE TABLE IF NOT EXISTS games (
          id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, message_id INTEGER,
          player1 INTEGER NOT NULL, player2 INTEGER NOT NULL, p1_name TEXT NOT NULL,
          p2_name TEXT NOT NULL, p1_score INTEGER NOT NULL DEFAULT 0,
          p2_score INTEGER NOT NULL DEFAULT 0, target INTEGER NOT NULL DEFAULT 3,
          p1_move TEXT, p2_move TEXT, status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE INDEX IF NOT EXISTS active_games ON games(status, player1, player2);
        """)


def display(user) -> str:
    return user.full_name.replace("<", "&lt;").replace(">", "&gt;")


def register_user(user):
    if not user:
        return
    with db() as con:
        con.execute("""INSERT INTO players(user_id,name,username) VALUES(?,?,?)
          ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, username=excluded.username""",
          (user.id, display(user), user.username))
        for weapon in MOVES:
            con.execute("INSERT OR IGNORE INTO weapon_stats(user_id,weapon) VALUES(?,?)", (user.id, weapon))


def game_link(bot_username: str, game_id: str) -> str:
    return f"https://t.me/{bot_username}?start=g_{game_id}"


def choices_keyboard(game_id: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🪨 Rock", callback_data=f"move:{game_id}:rock"),
        InlineKeyboardButton("📄 Paper", callback_data=f"move:{game_id}:paper"),
        InlineKeyboardButton("✂️ Scissors", callback_data=f"move:{game_id}:scissors"),
    ]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    args = context.args
    if not args or not args[0].startswith("g_"):
        await update.message.reply_text("🥊 I run private Rock Paper Scissors battles. Reply to someone in a group with /challenge to begin.")
        return
    game_id = args[0][2:]
    with db() as con:
        game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game or game["status"] != "active":
        await update.message.reply_text("That match is no longer active.")
        return
    if update.effective_user.id not in (game["player1"], game["player2"]):
        await update.message.reply_text("This private link belongs to the two players in that match.")
        return
    await update.message.reply_text(
        f"🥊 <b>Match ready</b>\n{game['p1_name']} vs {game['p2_name']}\n\nChoose your weapon secretly:",
        parse_mode=ParseMode.HTML, reply_markup=choices_keyboard(game_id),
    )


async def challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    message = update.effective_message
    if update.effective_chat.type == "private":
        await message.reply_text("Use /challenge by replying to a friend’s message in a group.")
        return
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        await message.reply_text("Reply to the person you want to challenge, then use /challenge.")
        return
    opponent = reply.from_user
    if opponent.is_bot or opponent.id == update.effective_user.id:
        await message.reply_text("Choose another human player.")
        return
    register_user(opponent)
    with db() as con:
        existing = con.execute("SELECT id FROM games WHERE status='active' AND (player1=? OR player2=? OR player1=? OR player2=?)",
                               (update.effective_user.id, update.effective_user.id, opponent.id, opponent.id)).fetchone()
        if existing:
            await message.reply_text("One of those players already has an active match. Finish or cancel it first.")
            return
        game_id = uuid.uuid4().hex[:16]
        con.execute("INSERT INTO games(id,chat_id,player1,player2,p1_name,p2_name,target) VALUES(?,?,?,?,?,?,?)",
                    (game_id, update.effective_chat.id, update.effective_user.id, opponent.id, display(update.effective_user), display(opponent), 3))
    me = await context.bot.get_me()
    link = game_link(me.username, game_id)
    text = (f"🥊 <b>Rock Paper Scissors — 1v1</b>\n\n"
            f"{display(update.effective_user)} has challenged {display(opponent)}!\n"
            f"Best of <b>5</b> — first to <b>3</b> wins. Draws raise the target.\n\n"
            "Both players: open the private panel below and lock in a secret weapon.")
    sent = await message.reply_text(text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Choose secretly", url=link)]]))
    with db() as con:
        con.execute("UPDATE games SET message_id=? WHERE id=?", (sent.message_id, game_id))


def round_result(a, b):
    if a == b: return 0
    return 1 if BEATS[a] == b else 2


def update_weapon(con, user_id, weapon, outcome):
    field = {"win": "wins", "loss": "losses", "draw": "draws"}[outcome]
    con.execute(f"UPDATE weapon_stats SET {field}={field}+1 WHERE user_id=? AND weapon=?", (user_id, weapon))


def finish_match(con, game, winner):
    p1, p2 = game["player1"], game["player2"]
    con.execute("UPDATE games SET status='finished' WHERE id=?", (game["id"],))
    if winner == 0:
        con.execute("UPDATE players SET draws=draws+1,matches=matches+1,current_streak=0 WHERE user_id IN (?,?)", (p1,p2))
    else:
        win, lose = (p1,p2) if winner == 1 else (p2,p1)
        con.execute("UPDATE players SET wins=wins+1,matches=matches+1,current_streak=current_streak+1 WHERE user_id=?", (win,))
        con.execute("UPDATE players SET best_streak=MAX(best_streak,current_streak) WHERE user_id=?", (win,))
        con.execute("UPDATE players SET losses=losses+1,matches=matches+1,current_streak=0 WHERE user_id=?", (lose,))


async def move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    register_user(query.from_user)
    _, game_id, weapon = query.data.split(":")
    with db() as con:
        game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if not game or game["status"] != "active":
            await query.edit_message_text("This match is no longer active.")
            return
        slot = "p1_move" if query.from_user.id == game["player1"] else "p2_move" if query.from_user.id == game["player2"] else None
        if not slot:
            await query.answer("This is not your match.", show_alert=True)
            return
        if game[slot]:
            await query.answer("Your choice is already locked.", show_alert=True)
            return
        con.execute(f"UPDATE games SET {slot}=? WHERE id=?", (weapon, game_id))
        game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    await query.edit_message_text("🔒 Weapon locked. Waiting for your opponent…")
    if not (game["p1_move"] and game["p2_move"]):
        return
    await resolve_round(context, game_id)


async def resolve_round(context, game_id):
    with db() as con:
        game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if not game or game["status"] != "active" or not game["p1_move"] or not game["p2_move"]:
            return
        move1, move2 = game["p1_move"], game["p2_move"]
        result = round_result(move1, move2)
        p1, p2 = game["player1"], game["player2"]
        con.execute("UPDATE players SET rounds=rounds+1 WHERE user_id IN (?,?)", (p1,p2))
        if result == 0:
            con.execute("UPDATE players SET same_weapon=same_weapon+1 WHERE user_id IN (?,?)", (p1,p2))
            update_weapon(con,p1,move1,"draw"); update_weapon(con,p2,move2,"draw")
            con.execute("UPDATE games SET p1_score=p1_score+1,p2_score=p2_score+1,target=target+1,p1_move=NULL,p2_move=NULL WHERE id=?", (game_id,))
            outcome = "🤝 <b>Draw!</b> Both players gain a point and the target increases by 1."
        else:
            winner, loser = (p1,p2) if result == 1 else (p2,p1)
            win_move, lose_move = (move1,move2) if result == 1 else (move2,move1)
            update_weapon(con,winner,win_move,"win"); update_weapon(con,loser,lose_move,"loss")
            score_col = "p1_score" if result == 1 else "p2_score"
            con.execute(f"UPDATE games SET {score_col}={score_col}+1,p1_move=NULL,p2_move=NULL WHERE id=?", (game_id,))
            outcome = f"🏆 <b>{game['p1_name'] if result == 1 else game['p2_name']} wins the round!</b>"
        game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        match_winner = 1 if game["p1_score"] >= game["target"] else 2 if game["p2_score"] >= game["target"] else 0
        if match_winner:
            finish_match(con, game, match_winner)
    reveal = f"{game['p1_name']}: {MOVES[move1]}\n{game['p2_name']}: {MOVES[move2]}"
    score = f"Score: <b>{game['p1_score']}–{game['p2_score']}</b> · Target: <b>{game['target']}</b>"
    if match_winner:
        champion = game['p1_name'] if match_winner == 1 else game['p2_name']
        text = f"🥊 <b>Round reveal</b>\n{reveal}\n\n{outcome}\n{score}\n\n🎉 <b>{champion} wins the match!</b> +1 point"
        await context.bot.send_message(game["chat_id"], text, parse_mode=ParseMode.HTML)
    else:
        me = await context.bot.get_me()
        text = f"🥊 <b>Round reveal</b>\n{reveal}\n\n{outcome}\n{score}\n\nChoose secretly for the next round."
        await context.bot.send_message(game["chat_id"], text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Next round", url=game_link(me.username, game_id))]]))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; register_user(user)
    with db() as con:
        player = con.execute("SELECT * FROM players WHERE user_id=?", (user.id,)).fetchone()
        weapons = {r["weapon"]: r for r in con.execute("SELECT * FROM weapon_stats WHERE user_id=?", (user.id,))}
    def line(w):
        s = weapons[w]; return f"{MOVES[w]}: <b>{s['wins']}W</b> • {s['losses']}L • {s['draws']}D"
    text = (f"📊 <b>{display(user)}’s Stats</b>\n\n🏆 {player['wins']} wins · 💀 {player['losses']} losses · 🤝 {player['draws']} draws\n"
            f"🎮 {player['matches']} matches · {player['rounds']} rounds\n🪞 Same weapon: {player['same_weapon']}\n"
            f"🔥 Streak: {player['current_streak']} current · {player['best_streak']} best\n\n{line('rock')}\n\n{line('paper')}\n\n{line('scissors')}")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as con:
        rows = con.execute("SELECT name,wins,losses,draws FROM players ORDER BY wins DESC, draws DESC, losses ASC LIMIT 10").fetchall()
    if not rows:
        await update.effective_message.reply_text("No battles yet. Be the first to /challenge someone!"); return
    lines = [f"{i}. <b>{r['name']}</b> — 🏆 {r['wins']} · 💀 {r['losses']} · 🤝 {r['draws']}" for i,r in enumerate(rows,1)]
    await update.effective_message.reply_text("🏅 <b>Leaderboard</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with db() as con:
        game = con.execute("SELECT * FROM games WHERE status='active' AND chat_id=? AND (player1=? OR player2=?) ORDER BY rowid DESC LIMIT 1", (update.effective_chat.id,user.id,user.id)).fetchone()
        if game: con.execute("UPDATE games SET status='cancelled' WHERE id=?", (game['id'],))
    await update.effective_message.reply_text("Match cancelled." if game else "You have no active match here.")


async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)


def main():
    if not TOKEN:
        raise RuntimeError("Set BOT_TOKEN to the token from @BotFather.")
    setup_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("challenge", challenge))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(move, pattern=r"^move:"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, remember))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
