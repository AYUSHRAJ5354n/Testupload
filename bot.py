import os
import re
import asyncio
import glob
import requests
import yt_dlp
from bs4 import BeautifulSoup
from pymongo import MongoClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MONGO_URL = os.getenv("MONGO_URL")

client = MongoClient(MONGO_URL)
db = client["donghua"]
col = db["uploaded"]

queue = []
running = False

# ========= PROGRESS BAR =========
def progress_bar(percent):
    try:
        percent = float(percent.replace('%', '').strip())
    except:
        percent = 0
    filled = int(percent // 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"{bar} {percent:.1f}%"

# ========= CLEANUP =========
def cleanup():
    files = glob.glob("*.mp4") + glob.glob("*.mkv") + glob.glob("*.webm") + glob.glob("*.part")
    for f in files:
        try:
            os.remove(f)
        except:
            pass

# ========= SCRAPER =========
def get_animexin():
    url = "https://animexin.dev/"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    posts = []

    for card in soup.select("article"):
        try:
            a = card.find("a")
            title = a.get("title", "").strip()
            link = a.get("href")

            if not title or not link:
                continue

            if "episode" in title.lower() and "?" not in title:
                posts.append((title, link))

        except:
            continue

    return posts

# ========= EXTRACT =========
def get_dm(page):
    r = requests.get(page, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    iframe = soup.find("iframe")
    if iframe:
        src = iframe.get("src")
        if "dailymotion" in src:
            return src.replace("embed/video", "video")

    return None

# ========= DOWNLOAD =========
async def download_video(url, msg, loop):
    def hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0%')
            speed = d.get('_speed_str', '')
            eta = d.get('_eta_str', '')

            bar = progress_bar(percent)

            text = f"⬇️ Downloading\n{bar}\n⚡ {speed}\n⏳ ETA {eta}"

            asyncio.run_coroutine_threadsafe(
                msg.edit_text(text),
                loop
            )

    ydl_opts = {
        "format": "best[height<=480]",
        "outtmpl": "video.%(ext)s",
        "progress_hooks": [hook],
        "quiet": True,
        "noplaylist": True,
        "nopart": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    file = [f for f in os.listdir() if f.endswith((".mp4", ".mkv", ".webm"))][0]
    return file

# ========= UPLOAD =========
async def upload(bot, file, msg):
    await msg.edit_text("📤 Uploading...\n████░░░░░░")

    with open(file, "rb") as f:
        await bot.send_video(
            chat_id=CHAT_ID,
            video=f,
            supports_streaming=True
        )

    await msg.edit_text("✅ Done!")

# ========= WORKER =========
async def worker(app):
    global running

    while True:
        if queue and not running:
            running = True
            title, link = queue.pop(0)

            msg = await app.bot.send_message(
                chat_id=CHAT_ID,
                text=f"⏳ Processing:\n{title}"
            )

            try:
                dm = get_dm(link)

                if not dm:
                    await msg.edit_text("❌ No video found")
                    running = False
                    continue

                file = await download_video(dm, msg, asyncio.get_event_loop())

                await upload(app.bot, file, msg)

                col.insert_one({"url": link})

            except Exception as e:
                await msg.edit_text(f"❌ Error\n{e}")

            finally:
                cleanup()

            running = False

        await asyncio.sleep(5)

# ========= AUTO LOOP =========
async def auto_loop():
    while True:
        print("🔄 Checking new episodes...")
        posts = get_animexin()

        for title, link in posts:
            if not col.find_one({"url": link}):
                queue.append((title, link))

        await asyncio.sleep(300)

# ========= COMMANDS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔥 Auto Donghua Bot Running")

async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    posts = get_animexin()

    added = 0
    for p in posts:
        if not col.find_one({"url": p[1]}):
            queue.append(p)
            added += 1

    await update.message.reply_text(f"🔄 Added {added} new episodes")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = col.count_documents({})
    await update.message.reply_text(f"📊 Total Uploaded: {count}")

async def clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    col.delete_many({})
    await update.message.reply_text("🧹 Database cleaned")

# ========= MAIN =========
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("clean", clean))

    print("🔥 Bot Running...")

    async def post_init(app):
        asyncio.create_task(worker(app))
        asyncio.create_task(auto_loop())

    app.post_init = post_init

    app.run_polling()

# ========= RUN =========
if __name__ == "__main__":
    main()
