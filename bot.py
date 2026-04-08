import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# ========= ENV =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MONGO_URL = os.getenv("MONGO_URL")

client = MongoClient(MONGO_URL)
db = client["donghua"]
col = db["uploaded"]

queue = []
running = False

# ========= HEALTH SERVER =========
def run_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

    server = HTTPServer(("0.0.0.0", 8000), Handler)
    server.serve_forever()

threading.Thread(target=run_server).start()

# ========= SAFE FFMPEG SETUP =========
def setup_ffmpeg():
    if not os.path.exists("ffmpeg"):
        print("⬇️ Downloading ffmpeg (safe binary)...")

        url = "https://github.com/eugeneware/ffmpeg-static/releases/latest/download/ffmpeg-linux-x64"
        r = requests.get(url)

        with open("ffmpeg", "wb") as f:
            f.write(r.content)

        os.chmod("ffmpeg", 0o755)
        print("✅ ffmpeg ready")

setup_ffmpeg()

# ========= TELEGRAM =========
def send_msg(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text}
    )

def send_video(file, caption):
    with open(file, "rb") as v:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo",
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"video": v}
        )

# ========= SCRAPER =========
def get_animexin():
    url = "https://animexin.dev/"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    posts = []

    for a in soup.select("article a")[:10]:
        title = a.get_text().strip()
        link = a.get("href")

        if re.search(r'episode\s*\d+', title.lower()):
            posts.append((title, link))

    return posts

# ========= EXTRACT DM =========
def get_dm(page):
    r = requests.get(page)
    soup = BeautifulSoup(r.text, "html.parser")
    iframe = soup.find("iframe")

    if iframe:
        src = iframe.get("src")
        if "embed" in src:
            vid = src.split("/")[-1]
            return f"https://www.dailymotion.com/video/{vid}"

    return None

# ========= GET M3U8 =========
def get_m3u8(dm):
    vid = dm.split("/")[-1]
    api = f"https://www.dailymotion.com/player/metadata/video/{vid}"
    data = requests.get(api).json()
    return data["qualities"]["auto"][0]["url"]

# ========= DOWNLOAD =========
def download(m3u8):
    cmd = f'./ffmpeg -loglevel error -i "{m3u8}" -vf scale=-2:480 -c:v libx264 -preset veryfast -crf 28 video.mp4'
    os.system(cmd)
    return "video.mp4" if os.path.exists("video.mp4") else None

# ========= WORKER =========
async def worker():
    global running

    while True:
        if queue and not running:
            running = True
            title, link = queue.pop(0)

            send_msg(f"⏳ Processing:\n{title}")

            try:
                send_msg("📡 Extracting...")
                dm = get_dm(link)

                if not dm:
                    send_msg("❌ No video found")
                    running = False
                    continue

                send_msg("📡 Getting stream...")
                m3u8 = get_m3u8(dm)

                send_msg("📥 Downloading...")
                file = download(m3u8)

                if file:
                    send_msg("📤 Uploading...")
                    send_video(file, f"🔥 {title}")

                    os.remove(file)
                    col.insert_one({"url": link})

                    send_msg("✅ Done!")
                else:
                    send_msg("❌ Download failed")

            except Exception as e:
                send_msg(f"❌ Error:\n{e}")

            running = False

        await asyncio.sleep(5)

# ========= SCRAPER LOOP =========
async def scraper():
    while True:
        posts = get_animexin()

        for title, link in posts:
            if not col.find_one({"url": link}):
                queue.append((title, link))

        await asyncio.sleep(600)

# ========= COMMANDS =========
def handle_cmd(text):
    if text == "/update":
        posts = get_animexin()
        for p in posts:
            if not col.find_one({"url": p[1]}):
                queue.append(p)
        send_msg("🔄 Update triggered")

    elif text == "/stats":
        send_msg(f"📊 Total uploaded: {col.count_documents({})}")

    elif text == "/clean":
        col.delete_many({})
        send_msg("🧹 Database cleared")

    elif text == "/start":
        send_msg("🔥 Animexin Auto Bot Ready")

# ========= TELEGRAM LISTENER =========
async def telegram_listener():
    last_id = 0

    while True:
        res = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_id}"
        ).json()

        for upd in res.get("result", []):
            last_id = upd["update_id"] + 1
            msg = upd.get("message", {}).get("text")

            if msg:
                handle_cmd(msg)

        await asyncio.sleep(3)

# ========= MAIN =========
async def main():
    send_msg("🔥 Bot Started")

    await asyncio.gather(
        worker(),
        scraper(),
        telegram_listener()
    )

asyncio.run(main())
