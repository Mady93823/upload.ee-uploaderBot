import os
import logging
import asyncio
import time
import shutil
import secrets
import psutil
import platform
import sys
import datetime
import re
import motor.motor_asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv
from processor import process_url
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_START_TIME = time.time()

# Configuration from env
TOKEN = os.getenv("TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
ADMIN_ID = os.getenv("ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
MONGO_URI = os.getenv("MONGO_URI")
JOIN_CHANNELS = os.getenv("JOIN_CHANNELS", "")
FORCE_SUB_CHANNELS = [int(x) for x in JOIN_CHANNELS.split() if x.strip().lstrip('-').isdigit()]

# Global Toggles
MONITOR_ACTIVE = True
MAINTENANCE_MODE = False
FORCE_SUB_ACTIVE = True

BOT_USERNAME = None

if not all([TOKEN, API_ID, API_HASH, MONGO_URI]):
    logging.error("Missing configuration. Please check your .env file or environment variables.")
    exit(1)

try:
    API_ID = int(API_ID)
    if ADMIN_ID:
        ADMIN_ID = int(ADMIN_ID)
    if CHANNEL_ID:
        CHANNEL_ID = int(CHANNEL_ID)
except ValueError:
    logging.error("API_ID, ADMIN_ID and CHANNEL_ID must be integers.")
    exit(1)

# --- Database Helper ---
class MongoFileStore:
    def __init__(self, uri):
        # Optimized connection pooling
        self.client = motor.motor_asyncio.AsyncIOMotorClient(
            uri,
            maxPoolSize=100,
            minPoolSize=10,
            serverSelectionTimeoutMS=5000
        )
        self.db = self.client.codelist_bot
        self.collection = self.db.CODELIST
        self.users = self.db.USERS
        self.processed = self.db.PROCESSED_POSTS

    async def add_user(self, user_id, first_name):
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "first_name": first_name, "last_active": datetime.datetime.now()}},
            upsert=True
        )

    async def is_url_processed(self, url):
        return await self.processed.find_one({"url": url})

    async def add_processed_url(self, url):
        await self.processed.update_one(
            {"url": url},
            {"$set": {"url": url, "processed_at": datetime.datetime.now()}},
            upsert=True
        )

    async def get_total_users(self):
        return await self.users.count_documents({})

    async def get_all_users(self):
        return self.users.find({})

    async def save_file(self, file_id, caption=None):
        # Generate a unique 8-char code
        while True:
            code = secrets.token_urlsafe(6)
            existing = await self.collection.find_one({"code": code})
            if not existing:
                break
        
        await self.collection.insert_one({
            "code": code,
            "file_id": file_id,
            "caption": caption,
            "created_at": time.time()
        })
        return code

    async def get_file(self, code):
        return await self.collection.find_one({"code": code})

file_store = MongoFileStore(MONGO_URI)

# Initialize Pyrogram Client
app = Client(
    "codelist_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TOKEN
)

# Progress tracking helper
class ProgressTracker:
    def __init__(self, message: Message, operation: str):
        self.message = message
        self.operation = operation
        self.last_update_time = 0
        self.start_time = time.time()

    async def update(self, current, total):
        now = time.time()
        if now - self.last_update_time < 3 and current != total:
            return

        self.last_update_time = now
        percentage = (current / total) * 100
        
        # Simple progress bar
        filled = int(percentage / 10)
        bar = "█" * filled + "░" * (10 - filled)
        
        # Calculate speed
        elapsed = now - self.start_time
        if elapsed > 0:
            speed = current / elapsed
            speed_str = f"{speed / 1024 / 1024:.2f} MB/s"
        else:
            speed_str = "0 MB/s"

        text = (
            f"**{self.operation}**\n"
            f"[{bar}] {percentage:.1f}%\n"
            f"🚀 **Speed**: {speed_str}\n"
            f"📦 **Size**: {current / 1024 / 1024:.2f} / {total / 1024 / 1024:.2f} MB"
        )
        
        try:
            await self.message.edit_text(text)
        except Exception as e:
            logging.error(f"Error updating progress: {e}")

# Force Sub Check Helper
async def check_force_sub(client, user_id):
    if not FORCE_SUB_CHANNELS:
        return True, []
        
    missing_channels = []
    for channel_id in FORCE_SUB_CHANNELS:
        try:
            member = await client.get_chat_member(channel_id, user_id)
            if member.status in ["left", "kicked", "banned"]:
                missing_channels.append(channel_id)
        except Exception:
            # If bot can't check (not admin or channel invalid), assume user is not in it or skip
            # Better to assume missing if we want to be strict, or skip if we want to be safe.
            # Let's add it to missing so they see the button and try.
            missing_channels.append(channel_id)
            
    return len(missing_channels) == 0, missing_channels

# --- RSS / Monitor Logic ---
async def monitor_codelist(client):
    """
    Background task to monitor codelist.cc for new posts.
    """
    # URLs to monitor
    urls_to_monitor = [
        "https://codelist.cc/scripts3/",
        "https://codelist.cc/plugins3/",
        "https://codelist.cc/mobile/",
        "https://codelist.cc/templates/"
    ]
    
    print(f"Starting Monitor for {urls_to_monitor}")
    
    # Initialize DB-based tracking
    processed_count = await file_store.processed.count_documents({})
    first_run_db_init = processed_count == 0
    
    while True:
        try:
            if not MONITOR_ACTIVE:
                await asyncio.sleep(60)
                continue

            logging.info("Checking for new posts...")
            loop = asyncio.get_running_loop()
            
            def fetch_feed(u):
                try:
                    r = cffi_requests.get(u, impersonate="chrome120", timeout=30, allow_redirects=True)
                    return r.text
                except Exception as e:
                    logging.error(f"Monitor fetch error for {u}: {e}")
                    return None

            current_batch = []
            
            for url in urls_to_monitor:
                html = await loop.run_in_executor(None, fetch_feed, url)
                
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    # Find all post links
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        
                        # Clean URL (remove anchor/query)
                        href = href.split('#')[0].split('?')[0]
                        
                        # Filter for valid content posts
                        is_content = False
                        if '.html' in href:
                             if any(cat in href for cat in ['/scripts3/', '/plugins3/', '/apps3/', '/mobile/', '/templates/']):
                                 is_content = True
                             # Fallback: if it's from main site and looks like a post (has numeric ID)
                             elif 'codelist.cc' in href and re.search(r'/\d+-', href):
                                 is_content = True
                        
                        if is_content:
                             if href not in current_batch:
                                 current_batch.append(href)
            
            if first_run_db_init:
                # If this is the very first run (DB empty), mark all current posts as processed
                # so we don't spam 50+ messages.
                logging.info(f"Initializing DB with {len(current_batch)} existing posts...")
                for url in current_batch:
                    await file_store.add_processed_url(url)
                first_run_db_init = False
                logging.info("DB Initialization Complete.")
            else:
                # Normal check against DB
                new_posts = []
                for url in current_batch:
                    if not await file_store.is_url_processed(url):
                        new_posts.append(url)
                
                if new_posts:
                    logging.info(f"Found {len(new_posts)} new posts!")
                    
                    # Process from oldest to newest
                    for post_url in reversed(new_posts):
                        logging.info(f"Auto-processing: {post_url}")
                        try:
                            await process_and_post_to_channel(client, post_url)
                            # Mark as processed ONLY after success (or attempt)
                            await file_store.add_processed_url(post_url)
                        except Exception as e:
                            logging.error(f"Failed to auto-process {post_url}: {e}")
                            # Mark as processed to prevent infinite retry loop on bad posts
                            await file_store.add_processed_url(post_url)
                            
                        await asyncio.sleep(10)
        
            await asyncio.sleep(600) # 10 minutes
            
        except Exception as e:
            logging.error(f"Monitor loop error: {e}")
            await asyncio.sleep(600)

async def process_and_post_to_channel(client, url):
    """
    Headless version of the processing logic for automation.
    """
    work_dir = f"work_auto_{int(time.time())}_{secrets.token_hex(3)}"
    os.makedirs(work_dir, exist_ok=True)
    
    try:
        logging.info(f"Auto-processing URL: {url}")
        
        # 1. Download & Process
        loop = asyncio.get_running_loop()
        executor = None # Use default
        
        # We don't have a progress callback for auto-mode, or we log it
        zip_path, metadata = await loop.run_in_executor(
            executor, 
            lambda: process_url(url, work_dir, add_copyright=True)
        )
        
        if zip_path and os.path.exists(zip_path):
            logging.info(f"Processing complete. Uploading {zip_path}...")
            
            # 2. Upload to Telegram
            # We need to send it to the channel directly?
            # Or store it in DB and post a link? 
            # The original bot sends a photo to CHANNEL_ID with a button.
            # The button links to the bot with a start param.
            # So we need to:
            # a) Upload document to Telegram (to get file_id) - but we can't "just upload" without sending message?
            #    Actually we can send to a dump channel or to the admin.
            #    Or just send to the main channel directly?
            #    The user's flow is: Channel Post -> Button "Download" -> Bot PM -> File.
            
            # So we must upload the file somewhere to get file_id.
            # We can send it to ADMIN_ID first.
            
            caption_file = f"{metadata.get('title', 'File')}\n\nUploaded by Bot"
            
            # Upload to Admin to get File ID
            msg = await client.send_document(
                chat_id=ADMIN_ID,
                document=zip_path,
                caption=caption_file
            )
            
            file_id = msg.document.file_id
            
            # 3. Create Store Entry
            code = await file_store.save_file(file_id, caption=caption_file)
            bot_link = f"https://t.me/{BOT_USERNAME}?start={code}"
            
            # 4. Post to Channel
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Download File 📥", url=bot_link)]
            ])
            
            title = metadata.get('title', 'New Script')
            image_url = metadata.get('image_url')
            demo_url = metadata.get('demo_url')
            description = metadata.get('description')
            
            # Construct Caption
            caption = f"✨ **{title}** ✨\n\n"
            if description:
                caption += f"{description}\n\n"
            if demo_url:
                caption += f"🌐 **Demo**: [Live Preview]({demo_url})\n"
            caption += "━━━━━━━━━━━━━━━━━━━\n"
            caption += "👨‍💻 **By**: @freephplaravel"
            
            # Truncate caption if needed (1024 char limit)
            if len(caption) > 1024:
                caption = caption[:1021] + "..."

            logging.info(f"Posting to channel {CHANNEL_ID}")
            
            if image_url and "codelist.cc" not in image_url:
                 await client.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=image_url,
                    caption=caption,
                    reply_markup=keyboard
                )
            elif image_url:
                # Codelist image (potentially watermarked) - user wanted to hide logo?
                # We can try to upload the processed local image if available
                local_img = metadata.get('image_path')
                if local_img and os.path.exists(local_img):
                     await client.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=local_img,
                        caption=caption,
                        reply_markup=keyboard
                    )
                else:
                    # Fallback to text
                     await client.send_message(
                        chat_id=CHANNEL_ID,
                        text=caption,
                        reply_markup=keyboard,
                        disable_web_page_preview=True
                    )
            else:
                 await client.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            
            logging.info("Auto-post successful!")
            
        else:
            logging.error("Processing failed (no zip path returned).")

    except Exception as e:
        logging.error(f"Auto-process error: {e}")
    finally:
        # Cleanup
        if os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir)
            except:
                pass

# --- End RSS Logic ---

@app.on_message(filters.command("start"))
async def start(client, message):
    # Save User
    try:
        await file_store.add_user(message.from_user.id, message.from_user.first_name)
    except Exception as e:
        logging.error(f"Error saving user: {e}")

    # Maintenance Mode Check
    if MAINTENANCE_MODE and message.from_user.id != ADMIN_ID:
        await message.reply_text("🚧 **Bot is currently under maintenance.**\nPlease try again later.")
        return

    # Check for deep link arguments
    if len(message.command) > 1:
        code = message.command[1]
        
        # Force Subscribe Check
        if FORCE_SUB_ACTIVE:
            is_joined, missing_channels = await check_force_sub(client, message.from_user.id)
            if not is_joined:
                buttons = []
                for channel_id in missing_channels:
                    try:
                        chat = await client.get_chat(channel_id)
                        invite_link = chat.invite_link or f"https://t.me/{chat.username}" if chat.username else None
                        if not invite_link:
                             # Try to generate one if bot is admin
                             try:
                                 invite_link = await client.export_chat_invite_link(channel_id)
                             except:
                                 pass
                        
                        if invite_link:
                            buttons.append([InlineKeyboardButton(f"Join {chat.title}", url=invite_link)])
                    except Exception:
                        pass
                
                # Add Try Again button with the same deep link
                global BOT_USERNAME
                if not BOT_USERNAME:
                    me = await client.get_me()
                    BOT_USERNAME = me.username
                    
                deep_link = f"https://t.me/{BOT_USERNAME}?start={code}"
                buttons.append([InlineKeyboardButton("Try Again 🔄", url=deep_link)])
                
                await message.reply_text(
                    "🔒 **Access Denied**\n\nPlease join our channels to download this file.",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                return

        try:
            file_info = await file_store.get_file(code)
            
            if file_info:
                await message.reply_document(
                    document=file_info['file_id'],
                    caption=file_info.get('caption', "Here is your file!")
                )
            else:
                await message.reply_text("❌ File not found or link expired.")
        except Exception as e:
            logging.error(f"Error fetching file: {e}")
            await message.reply_text("❌ An error occurred while fetching the file.")
        return

    await message.reply_text(
        "**👋 Hello! I am your File Downloader Bot.**\n\n"
        "Send me a supported link and I will process it for you.\n"
        "⚡ Supports large files up to 2GB!"
    )

# --- Admin Settings & Tools ---
@app.on_message(filters.command("settings") & filters.user(ADMIN_ID))
async def settings_command(client, message):
    global CHANNEL_ID
    
    # Stats
    uptime = time.strftime("%Hh %Mm", time.gmtime(time.time() - BOT_START_TIME))
    process = psutil.Process(os.getpid())
    ram_usage = f"{process.memory_info().rss / 1024 / 1024:.2f} MB"
    total_users = await file_store.get_total_users()
    channel_text = f"`{CHANNEL_ID}`" if CHANNEL_ID else "Not Set"
    
    text = (
        "⚙️ **Admin Control Panel**\n\n"
        "📊 **Stats**:\n"
        f"• Uptime: `{uptime}`\n"
        f"• RAM: `{ram_usage}`\n"
        f"• Users: `{total_users}`\n"
        f"• Channel: {channel_text}\n\n"
        "🔘 **Toggles**:"
    )
    
    # Toggle Buttons
    mon_icon = "✅" if MONITOR_ACTIVE else "❌"
    maint_icon = "✅" if MAINTENANCE_MODE else "❌"
    force_icon = "✅" if FORCE_SUB_ACTIVE else "❌"
    
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{mon_icon} Monitor", callback_data="toggle_monitor"),
            InlineKeyboardButton(f"{maint_icon} Maintenance", callback_data="toggle_maintenance")
        ],
        [
            InlineKeyboardButton(f"{force_icon} Force Sub", callback_data="toggle_force_sub"),
            InlineKeyboardButton("Set Channel ID", callback_data="set_channel")
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="broadcast_info"),
            InlineKeyboardButton("📄 Get Logs", callback_data="get_logs")
        ],
        [
            InlineKeyboardButton("🔄 Restart Bot", callback_data="restart_bot")
        ]
    ])
    
    await message.reply_text(text, reply_markup=buttons)

@app.on_callback_query(filters.regex("toggle_") & filters.user(ADMIN_ID))
async def handle_toggles(client, callback_query: CallbackQuery):
    global MONITOR_ACTIVE, MAINTENANCE_MODE, FORCE_SUB_ACTIVE
    data = callback_query.data
    
    if data == "toggle_monitor":
        MONITOR_ACTIVE = not MONITOR_ACTIVE
    elif data == "toggle_maintenance":
        MAINTENANCE_MODE = not MAINTENANCE_MODE
    elif data == "toggle_force_sub":
        FORCE_SUB_ACTIVE = not FORCE_SUB_ACTIVE
        
    # Refresh Panel
    await settings_command(client, callback_query.message)

@app.on_callback_query(filters.regex("broadcast_info") & filters.user(ADMIN_ID))
async def broadcast_info(client, callback_query: CallbackQuery):
    await callback_query.answer("Use /broadcast <message> to send to all users.", show_alert=True)

@app.on_callback_query(filters.regex("get_logs") & filters.user(ADMIN_ID))
async def get_logs_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Sending logs...")
    if os.path.exists("bot.log"):
        await client.send_document(
            chat_id=ADMIN_ID,
            document="bot.log",
            caption="📄 **Bot Logs**"
        )
    else:
        await client.send_message(ADMIN_ID, "❌ No log file found.")

@app.on_callback_query(filters.regex("restart_bot") & filters.user(ADMIN_ID))
async def restart_bot_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Restarting...", show_alert=True)
    os.execl(sys.executable, sys.executable, *sys.argv)

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast_command(client, message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ Usage: `/broadcast <message>`")
        return
        
    text = message.text.split(None, 1)[1]
    total_users = await file_store.get_total_users()
    
    status_msg = await message.reply_text(f"📢 Starting broadcast to {total_users} users...")
    
    success = 0
    failed = 0
    
    # Get all users (cursor)
    cursor = await file_store.get_all_users()
    
    async for user in cursor:
        try:
            await client.send_message(user['user_id'], text)
            success += 1
            await asyncio.sleep(0.1) # Flood wait prevention
        except Exception:
            failed += 1
            
    await status_msg.edit_text(
        f"✅ **Broadcast Complete**\n\n"
        f"✨ Success: `{success}`\n"
        f"❌ Failed: `{failed}`"
    )

@app.on_message(filters.command("logs") & filters.user(ADMIN_ID))
async def logs_command(client, message):
    if os.path.exists("bot.log"):
        await message.reply_document("bot.log", caption="📄 **Bot Logs**")
    else:
        await message.reply_text("❌ No log file found.")

@app.on_message(filters.command("users") & filters.user(ADMIN_ID))
async def users_command(client, message):
    total_users = await file_store.get_total_users()
    await message.reply_text(f"👥 **Total Users**: `{total_users}`")

@app.on_message(filters.command("restart") & filters.user(ADMIN_ID))
async def restart_command(client, message):
    await message.reply_text("🔄 Restarting bot...")
    os.execl(sys.executable, sys.executable, *sys.argv)

@app.on_message(filters.command("check_channel") & filters.user(ADMIN_ID))
async def check_channel_command(client, message):
    if not CHANNEL_ID:
        await message.reply_text("Channel ID is not set.")
        return
        
    status_msg = await message.reply_text(f"Checking channel `{CHANNEL_ID}`...")
    try:
        chat = await client.get_chat(CHANNEL_ID)
        text = f"✅ Channel found: **{chat.title}**\nType: `{chat.type}`\nID: `{chat.id}`\n\n"
        
        member = await client.get_chat_member(CHANNEL_ID, "me")
        text += f"Bot Status: `{member.status}`\n"
        
        if member.privileges:
             text += f"Can Post: `{member.privileges.can_post_messages}`\n"
             text += f"Can Edit: `{member.privileges.can_edit_messages}`\n"
        
        if str(member.status) not in ["ChatMemberStatus.ADMINISTRATOR", "administrator", "creator"]:
             text += "\n⚠️ **Warning**: Bot is NOT an admin. Auto-post will fail."
             
        await status_msg.edit_text(text)
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Error connecting to channel: {e}\n\nMake sure the bot is added to the channel.")


# State management for setting channel (simple in-memory)
user_states = {}

@app.on_callback_query(filters.regex("set_channel") & filters.user(ADMIN_ID))
async def set_channel_callback(client, callback_query: CallbackQuery):
    user_states[callback_query.from_user.id] = "waiting_for_channel"
    await callback_query.message.edit_text(
        "Please forward a message from the target channel or send the Channel ID (starts with -100)."
    )

@app.on_message(filters.user(ADMIN_ID) & filters.forwarded)
async def handle_forward_for_channel(client, message):
    global CHANNEL_ID
    state = user_states.get(message.from_user.id)
    
    if state == "waiting_for_channel":
        if message.forward_from_chat and message.forward_from_chat.type == "channel":
            CHANNEL_ID = message.forward_from_chat.id
            # Update .env (optional, but good for persistence in local dev)
            # For cloud (koyeb), this won't persist restarts usually unless using API
            user_states.pop(message.from_user.id, None)
            await message.reply_text(f"Channel ID set to: `{CHANNEL_ID}`")
        else:
            await message.reply_text("Please forward a message from a CHANNEL.")

@app.on_message(filters.user(ADMIN_ID) & filters.regex(r"^-100\d+$"))
async def handle_channel_id_text(client, message):
    global CHANNEL_ID
    state = user_states.get(message.from_user.id)
    
    if state == "waiting_for_channel":
        try:
            CHANNEL_ID = int(message.text)
            user_states.pop(message.from_user.id, None)
            await message.reply_text(f"Channel ID set to: `{CHANNEL_ID}`")
        except ValueError:
            await message.reply_text("Invalid ID format.")

import concurrent.futures

# Thread pool for blocking I/O
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# --- Stats Command ---
def get_size(bytes, suffix="B"):
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes < factor:
            return f"{bytes:.2f}{unit}{suffix}"
        bytes /= factor

@app.on_message(filters.command("stats"))
async def stats_command(client, message):
    # System Stats
    uname = platform.uname()
    os_info = f"{uname.system} {uname.release}"
    
    cpu_usage = psutil.cpu_percent(interval=0.1)
    
    # RAM
    svmem = psutil.virtual_memory()
    ram_total = get_size(svmem.total)
    ram_used = get_size(svmem.used)
    ram_percent = svmem.percent
    
    # Disk
    partition_usage = psutil.disk_usage('/')
    disk_total = get_size(partition_usage.total)
    disk_used = get_size(partition_usage.used)
    disk_percent = partition_usage.percent
    
    # Uptime
    current_time = time.time()
    uptime_seconds = int(current_time - BOT_START_TIME)
    uptime_str = time.strftime("%Hh %Mm %Ss", time.gmtime(uptime_seconds))
    
    # Process specific
    process = psutil.Process(os.getpid())
    memory_usage = process.memory_info().rss / 1024 / 1024  # MB
    
    stats_text = (
        f"📊 **System Status**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🖥 **OS**: `{os_info}`\n"
        f"⚙️ **CPU**: `{cpu_usage}%`\n"
        f"🧠 **RAM**: `{ram_used} / {ram_total} ({ram_percent}%)`\n"
        f"💾 **Disk**: `{disk_used} / {disk_total} ({disk_percent}%)`\n"
        f"🐍 **Python**: `{platform.python_version()}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **Bot Status**\n"
        f"⏱ **Uptime**: `{uptime_str}`\n"
        f"📦 **Memory**: `{memory_usage:.2f} MB`\n"
        f"🆔 **PID**: `{process.pid}`"
    )
    
    await message.reply_text(stats_text)

# --- Main Logic ---

@app.on_message(filters.text & ~filters.command(["start", "settings", "stats"]))
async def handle_message(client, message):
    url = message.text.strip()
    

    if "upload.ee" not in url and "codelist.cc" not in url:
        await message.reply_text("Please send a valid link.")
        return

    # Check if this is an Admin Auto-Post Trigger
    is_admin = message.from_user.id == ADMIN_ID
    is_codelist = "codelist.cc" in url
    should_autopost = is_admin and is_codelist and CHANNEL_ID
    
    status_msg = await message.reply_text("Initializing...")
    
    work_dir = f"work_{message.chat.id}_{message.id}"
    
    try:
        # 1. Download with progress
        download_tracker = ProgressTracker(status_msg, "Downloading...")
        
        def download_progress_callback(current, total):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(download_tracker.update(current, total))
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        
        # Determine if we should add copyright files (only for admin autopost?)
        # For now, let's say only add copyright if explicit command or always?
        # User requested to just upload, but in auto-mode we added copyright.
        # Let's keep manual mode clean unless specified.
        add_copyright = False # Default manual
        
        # We can add a flag logic if needed later
        
        # Run processing in executor to avoid blocking
        executor = None 
        zip_path, metadata = await loop.run_in_executor(
            executor, 
            lambda: process_url(url, work_dir, progress_callback=download_progress_callback, add_copyright=add_copyright)
        )
        
        if zip_path and os.path.exists(zip_path):
            await status_msg.edit_text("Processing complete. Uploading...")
            
            # 2. Upload
            caption_file = f"{metadata.get('title', 'File')}\n\nUploaded by Bot"
            
            # Upload to Telegram
            # We upload to the user who requested it
            msg = await client.send_document(
                chat_id=message.chat.id,
                document=zip_path,
                caption=caption_file
            )
            
            file_id = msg.document.file_id
            
            # 3. Store
            code = await file_store.save_file(file_id, caption=caption_file)
            bot_link = f"https://t.me/{BOT_USERNAME}?start={code}"
            
            # 4. Reply with formatted post (Preview)
            title = metadata.get('title', 'New Script')
            image_url = metadata.get('image_url')
            demo_url = metadata.get('demo_url')
            description = metadata.get('description')
            
            caption = f"✨ **{title}** ✨\n\n"
            if description:
                caption += f"{description}\n\n"
            if demo_url:
                caption += f"🌐 **Demo**: [Live Preview]({demo_url})\n"
            caption += "━━━━━━━━━━━━━━━━━━━\n"
            caption += "👨‍💻 **By**: @freephplaravel"
            
            if len(caption) > 1024:
                caption = caption[:1021] + "..."
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Download File 📥", url=bot_link)]
            ])
            
            await status_msg.delete()
            
            if image_url and "codelist.cc" not in image_url and "codelist.cc" not in (metadata.get('original_url') or ""):
                await message.reply_photo(
                    photo=image_url,
                    caption=caption,
                    reply_markup=keyboard
                )
            elif image_url and "codelist.cc" in image_url:
                 await message.reply_message(
                    text=caption,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            else:
                await message.reply_text(
                    text=caption,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            
        else:
            await status_msg.edit_text("Processing failed. Please check the logs.")

    except Exception as e:
        logging.error(f"Error: {e}")
        await status_msg.edit_text(f"An error occurred: {str(e)}")
    finally:
        if os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir)
            except:
                pass

# Clean up the if __name__ block mess I made
if __name__ == "__main__":
    # We need to run the bot and the monitor
    # Pyrogram app.run() is blocking.
    # We can use idle()
    from pyrogram import idle
    
    async def main():
        await app.start()
        
        me = await app.get_me()
        global BOT_USERNAME
        BOT_USERNAME = me.username
        logging.info(f"Bot started as @{BOT_USERNAME}")
        
        # Start Monitor
        asyncio.create_task(monitor_codelist(app))
        
        await idle()
        await app.stop()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
