import os
import logging
import asyncio
import time
import shutil
import psutil
import platform
import sys
import datetime
import re
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv
from processor import process_url
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

# New Imports
from config import *
from database import file_store
from utils import ProgressTracker, check_force_sub, process_and_post_to_channel

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_START_TIME = time.time()
BOT_USERNAME = None

if not all([TOKEN, API_ID, API_HASH, MONGO_URI]):
    logging.error("Missing configuration. Please check your .env file or environment variables.")
    exit(1)

# Initialize Pyrogram Client with Plugins
app = Client(
    "codelist_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TOKEN,
    plugins=dict(root="plugins")
)

# --- RSS / Monitor Logic ---
async def monitor_codelist(client):
    """
    Background task to monitor codelist.cc for new posts.
    """
    # URLs to monitor
    urls_to_monitor = [
        "https://codelist.cc/v3/",
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
            RSS_STATS["last_check"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
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
                    RSS_STATS["total_found"] += len(new_posts)
                    
                    # Process from oldest to newest
                    for post_url in reversed(new_posts):
                        logging.info(f"Auto-processing: {post_url}")
                        try:
                            await process_and_post_to_channel(client, post_url, BOT_USERNAME)
                            # Mark as processed ONLY after success (or attempt)
                            await file_store.add_processed_url(post_url)
                            RSS_STATS["total_processed"] += 1
                        except Exception as e:
                            logging.error(f"Failed to auto-process {post_url}: {e}")
                            # Mark as processed to prevent infinite retry loop on bad posts
                            await file_store.add_processed_url(post_url)
                            
                        await asyncio.sleep(10)
        
            await asyncio.sleep(600) # 10 minutes
            
        except Exception as e:
            logging.error(f"Monitor loop error: {e}")
            await asyncio.sleep(600)


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
            is_joined, missing_channels = await check_force_sub(client, message.from_user.id, FORCE_SUB_CHANNELS)
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
        "📊 **System Stats**:\n"
        f"• Uptime: `{uptime}`\n"
        f"• RAM: `{ram_usage}`\n"
        f"• Users: `{total_users}`\n"
        f"• Channel: {channel_text}\n\n"
        "📰 **RSS Stats**:\n"
        f"• Last Check: `{RSS_STATS['last_check']}`\n"
        f"• Total Found: `{RSS_STATS['total_found']}`\n"
        f"• Processed: `{RSS_STATS['total_processed']}`\n\n"
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
            InlineKeyboardButton("🔄 Restart", callback_data="restart_bot")
        ]
    ])
    
    await message.reply_text(text, reply_markup=buttons)

# Callbacks for settings
@app.on_callback_query(filters.regex("toggle_monitor") & filters.user(ADMIN_ID))
async def toggle_monitor(client, callback_query: CallbackQuery):
    global MONITOR_ACTIVE
    MONITOR_ACTIVE = not MONITOR_ACTIVE
    await settings_command(client, callback_query.message)

@app.on_callback_query(filters.regex("toggle_maintenance") & filters.user(ADMIN_ID))
async def toggle_maintenance(client, callback_query: CallbackQuery):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    await settings_command(client, callback_query.message)

@app.on_callback_query(filters.regex("toggle_force_sub") & filters.user(ADMIN_ID))
async def toggle_force_sub(client, callback_query: CallbackQuery):
    global FORCE_SUB_ACTIVE
    FORCE_SUB_ACTIVE = not FORCE_SUB_ACTIVE
    await settings_command(client, callback_query.message)

# State management for setting channel (simple in-memory)
user_states = {}
user_data = {}

# Constants for States
STATE_WAIT_CHANNEL = "waiting_for_channel"
STATE_POST_TITLE = "post_wait_title"
STATE_POST_DESC = "post_wait_desc"
STATE_POST_DEMO = "post_wait_demo"
STATE_POST_FILE = "post_wait_file"

@app.on_message(filters.command("cancel") & filters.user(ADMIN_ID))
async def cancel_command(client, message):
    user_states.pop(message.from_user.id, None)
    user_data.pop(message.from_user.id, None)
    await message.reply_text("❌ Operation cancelled.")

@app.on_message(filters.command("post") & filters.user(ADMIN_ID))
async def post_command(client, message):
    user_states[message.from_user.id] = STATE_POST_TITLE
    user_data[message.from_user.id] = {}
    await message.reply_text(
        "📝 **Create New Post**\n\n"
        "Please enter the **Title** of the content:\n"
        "(/cancel to stop)"
    )

@app.on_callback_query(filters.regex("set_channel") & filters.user(ADMIN_ID))
async def set_channel_callback(client, callback_query: CallbackQuery):
    user_states[callback_query.from_user.id] = STATE_WAIT_CHANNEL
    await callback_query.message.edit_text(
        "Please forward a message from the target channel or send the Channel ID (starts with -100)."
    )

@app.on_message(filters.user(ADMIN_ID) & filters.forwarded)
async def handle_forward_for_channel(client, message):
    global CHANNEL_ID
    state = user_states.get(message.from_user.id)
    
    if state == STATE_WAIT_CHANNEL:
        if message.forward_from_chat and message.forward_from_chat.type == "channel":
            CHANNEL_ID = message.forward_from_chat.id
            user_states.pop(message.from_user.id, None)
            await message.reply_text(f"Channel ID set to: `{CHANNEL_ID}`")
        else:
            await message.reply_text("Please forward a message from a CHANNEL.")

@app.on_message(filters.user(ADMIN_ID) & (filters.text | filters.document))
async def handle_admin_states(client, message):
    state = user_states.get(message.from_user.id)
    
    if not state:
        message.continue_propagation()
        return

    if state == STATE_WAIT_CHANNEL:
        # Handle text channel ID input
        if message.text and re.match(r"^-100\d+$", message.text):
            try:
                global CHANNEL_ID
                CHANNEL_ID = int(message.text)
                user_states.pop(message.from_user.id, None)
                await message.reply_text(f"Channel ID set to: `{CHANNEL_ID}`")
            except ValueError:
                await message.reply_text("Invalid ID format.")
        else:
             message.continue_propagation()
        return

    # /post Wizard Logic
    data = user_data.get(message.from_user.id, {})

    if state == STATE_POST_TITLE:
        if not message.text:
            await message.reply_text("Please send a valid text for Title.")
            return
        
        data['title'] = message.text
        user_states[message.from_user.id] = STATE_POST_DESC
        await message.reply_text(
            "✅ Title Set.\n\n"
            "Now send the **Description**:\n"
            "(Send 'skip' to leave empty)"
        )
    
    elif state == STATE_POST_DESC:
        if not message.text:
            await message.reply_text("Please send text.")
            return
        
        desc = message.text
        if desc.lower() == 'skip':
            desc = None
        
        data['description'] = desc
        user_states[message.from_user.id] = STATE_POST_DEMO
        await message.reply_text(
            "✅ Description Set.\n\n"
            "Now send the **Demo Link** (URL):\n"
            "(Send 'skip' to leave empty)"
        )
    
    elif state == STATE_POST_DEMO:
        if not message.text:
            await message.reply_text("Please send text.")
            return
        
        demo = message.text
        if demo.lower() == 'skip':
            demo = None
        
        data['demo_url'] = demo
        user_states[message.from_user.id] = STATE_POST_FILE
        await message.reply_text(
            "✅ Demo Link Set.\n\n"
            "Finally, send the **File** (Document) to upload:"
        )

    elif state == STATE_POST_FILE:
        if not message.document:
            await message.reply_text("Please send a **Document** file.")
            return
        
        status_msg = await message.reply_text("Processing upload...")
        
        try:
            # 1. Get File ID
            file_id = message.document.file_id
            
            # 2. Save to Store
            caption_file = f"{data.get('title')}\n\nUploaded by Bot"
            code = await file_store.save_file(file_id, caption=caption_file)
            
            # 3. Construct Post
            global BOT_USERNAME
            if not BOT_USERNAME:
                 me = await client.get_me()
                 BOT_USERNAME = me.username

            bot_link = f"https://t.me/{BOT_USERNAME}?start={code}"
            
            title = data.get('title')
            description = data.get('description')
            demo_url = data.get('demo_url')
            
            # Stylish Caption
            caption = f"🔥 **{title}**\n\n"
            if description:
                desc_preview = description[:300] + "..." if len(description) > 300 else description
                caption += f"📝 **Description**:\n{desc_preview}\n\n"
            if demo_url:
                caption += f"🌐 **Demo**: [Live Preview]({demo_url})\n"
            caption += "\n━━━━━━━━━━━━━━━━━━━━━\n"
            caption += "🚀 **Join Channel**: @freephplaravel\n"
            caption += "━━━━━━━━━━━━━━━━━━━━━"
            
            if len(caption) > 1024:
                caption = caption[:1021] + "..."
                
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Download File 📥", url=bot_link)]
            ])
            
            # 4. Post to Channel
            if CHANNEL_ID:
                try:
                    await client.send_message(
                        chat_id=CHANNEL_ID,
                        text=caption,
                        reply_markup=keyboard,
                        disable_web_page_preview=True
                    )
                    await status_msg.edit_text(f"✅ Posted to channel `{CHANNEL_ID}` successfully!")
                except Exception as e:
                    await status_msg.edit_text(f"⚠️ Saved file but failed to post to channel: {e}")
            else:
                 await status_msg.edit_text("⚠️ Channel ID not set. File saved but not posted.")
                 
            # Cleanup state
            user_states.pop(message.from_user.id, None)
            user_data.pop(message.from_user.id, None)
            
        except Exception as e:
            await status_msg.edit_text(f"Error: {e}")

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

@app.on_message(filters.text & ~filters.command(["start", "settings", "stats", "post", "cancel"]))
async def handle_message(client, message):
    # Ignore group messages here, let plugins handle groups.
    # We only want to process PMs or specific commands unless explicitly handled.
    if message.chat.type != "private":
        message.continue_propagation()
        return

    url = message.text.strip()

    # Let plugins handle CodeCanyon links
    if "codecanyon.net" in url:
        message.continue_propagation()
        return

    if "upload.ee" not in url and "codelist.cc" not in url:
        # If it's a private chat and not a valid link, we might want to ignore or guide
        # But previously we replied "Please send a valid link".
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
        add_copyright = False # Default manual
        
        executor = None 
        zip_path, metadata = await loop.run_in_executor(
            executor, 
            lambda: process_url(url, work_dir, progress_callback=download_progress_callback, add_copyright=add_copyright)
        )
        
        if zip_path and os.path.exists(zip_path):
            await status_msg.edit_text("Processing complete. Uploading...")
            
            # 2. Upload
            caption_file = f"{metadata.get('title', 'File')}\n\nUploaded by Bot"
            
            msg = await client.send_document(
                chat_id=message.chat.id,
                document=zip_path,
                caption=caption_file
            )
            
            file_id = msg.document.file_id
            
            # 3. Store
            code = await file_store.save_file(file_id, caption=caption_file)
            global BOT_USERNAME
            if not BOT_USERNAME:
                 me = await client.get_me()
                 BOT_USERNAME = me.username
                 
            bot_link = f"https://t.me/{BOT_USERNAME}?start={code}"
            
            # 4. Reply with formatted post (Preview)
            title = metadata.get('title', 'New Script')
            image_url = metadata.get('image_url')
            demo_url = metadata.get('demo_url')
            description = metadata.get('description')
            
            # Stylish Caption
            caption = f"🔥 **{title}**\n\n"
            
            if description:
                desc_preview = description[:300] + "..." if len(description) > 300 else description
                caption += f"📝 **Description**:\n{desc_preview}\n\n"
            
            if demo_url:
                caption += f"🌐 **Demo**: [Live Preview]({demo_url})\n"
                
            caption += "\n━━━━━━━━━━━━━━━━━━━━━\n"
            caption += "🚀 **Join Channel**: @freephplaravel\n"
            caption += "━━━━━━━━━━━━━━━━━━━━━"
            
            if len(caption) > 1024:
                caption = caption[:1021] + "..."
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Download File 📥", url=bot_link)]
            ])
            
            await status_msg.delete()
            
            # Send to User (Preview)
            sent_msg = None
            
            local_img = metadata.get('image_path')
            use_local_img = local_img and os.path.exists(local_img)
            
            if image_url and "codelist.cc" not in image_url and "codelist.cc" not in (metadata.get('original_url') or ""):
                sent_msg = await message.reply_photo(
                    photo=image_url,
                    caption=caption,
                    reply_markup=keyboard
                )
            elif use_local_img:
                sent_msg = await message.reply_photo(
                    photo=local_img,
                    caption=caption,
                    reply_markup=keyboard
                )
            else:
                sent_msg = await message.reply_text(
                    text=caption,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
                
            # Auto-Post to Channel if Admin
            if should_autopost and sent_msg:
                logging.info(f"Auto-posting to channel {CHANNEL_ID}")
                try:
                    if image_url and "codelist.cc" not in image_url and "codelist.cc" not in (metadata.get('original_url') or ""):
                        await client.send_photo(
                            chat_id=CHANNEL_ID,
                            photo=image_url,
                            caption=caption,
                            reply_markup=keyboard
                        )
                    elif use_local_img:
                        await client.send_photo(
                            chat_id=CHANNEL_ID,
                            photo=local_img,
                            caption=caption,
                            reply_markup=keyboard
                        )
                    else:
                        await client.send_message(
                            chat_id=CHANNEL_ID,
                            text=caption,
                            reply_markup=keyboard,
                            disable_web_page_preview=True
                        )
                    
                    await message.reply_text(f"✅ Posted to channel `{CHANNEL_ID}`")
                except Exception as e:
                    await message.reply_text(f"⚠️ Failed to post to channel: {e}")
            
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

if __name__ == "__main__":
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
