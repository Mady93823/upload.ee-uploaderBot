import os
import logging
import asyncio
import time
import shutil
import secrets
import motor.motor_asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv
from processor import process_url

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Configuration from env
TOKEN = os.getenv("TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
ADMIN_ID = os.getenv("ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
MONGO_URI = os.getenv("MONGO_URI")
JOIN_CHANNELS = os.getenv("JOIN_CHANNELS", "")
FORCE_SUB_CHANNELS = [int(x) for x in JOIN_CHANNELS.split() if x.strip().lstrip('-').isdigit()]

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

@app.on_message(filters.command("start"))
async def start(client, message):
    # Check for deep link arguments
    if len(message.command) > 1:
        code = message.command[1]
        
        # Force Subscribe Check
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

# --- Admin Settings ---

@app.on_message(filters.command("settings") & filters.user(ADMIN_ID))
async def settings_command(client, message):
    global CHANNEL_ID
    
    channel_text = f"`{CHANNEL_ID}`" if CHANNEL_ID else "Not Set"
    
    text = (
        "**Admin Settings**\n\n"
        f"Current Channel ID: {channel_text}\n"
        "Use the button below to set the channel.\n"
        "Use /check_channel to verify bot permissions."
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Channel ID", callback_data="set_channel")]
    ])
    
    await message.reply_text(text, reply_markup=buttons)

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

# --- Main Logic ---

@app.on_message(filters.text & ~filters.command(["start", "settings"]))
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
        # Requirement: "and delete those files and add this files inside ... in root of cleaned zip"
        # Implies we should do it for this flow.
        
        add_copyright = should_autopost
        
        # Run processing in thread pool
        zip_path, metadata = await loop.run_in_executor(
            executor, 
            lambda: process_url(url, work_dir, progress_callback=download_progress_callback, add_copyright=add_copyright)
        )
        
        if os.path.exists(zip_path):
            await status_msg.edit_text("Processing complete. Uploading...")
            
            # 2. Upload with progress
            upload_tracker = ProgressTracker(status_msg, "Uploading...")
            
            async def upload_progress(current, total):
                await upload_tracker.update(current, total)

            # Send to User first
            sent_msg = await client.send_document(
                chat_id=message.chat.id,
                document=zip_path,
                caption="Here is your cleaned file!",
                progress=upload_progress
            )
            
            # 3. Auto-Post to Channel
            if should_autopost:
                if metadata and metadata.get('title'):
                    title = metadata['title']
                    image_url = metadata.get('image_url')
                    image_path = metadata.get('image_path')
                    demo_url = metadata.get('demo_url')
                    
                    # Cool caption with emojis and demo link
                    caption = f"✨ **{title}** ✨\n\n"
                    if demo_url:
                        caption += f"🌐 **Demo**: [Live Preview]({demo_url})\n"
                    caption += "━━━━━━━━━━━━━━━━━━━\n"
                    caption += "👨‍💻 **By**: @freephplaravel"

                    await status_msg.edit_text("Posting to channel...")
                    
                    try:
                        # Save file to store and generate link
                        global BOT_USERNAME
                        if not BOT_USERNAME:
                            me = await client.get_me()
                            BOT_USERNAME = me.username
                            
                        file_code = await file_store.save_file(sent_msg.document.file_id, caption)
                        deep_link = f"https://t.me/{BOT_USERNAME}?start={file_code}"
                        
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("Download 📥", url=deep_link)]
                        ])

                        # Send Image with Caption and Button
                        if image_path and os.path.exists(image_path):
                            await client.send_photo(
                                chat_id=CHANNEL_ID,
                                photo=image_path,
                                caption=caption,
                                reply_markup=keyboard
                            )
                        elif image_url:
                            # If we failed to process the local image (image_path is None),
                            # check if the fallback URL is from codelist.cc.
                            # If so, it likely has a watermark we wanted to hide.
                            # In this case, it's better to send NO image than a watermarked one.
                            if "codelist.cc" in image_url or "codelist.cc" in (metadata.get('original_url') or ""):
                                # Send text only
                                await client.send_message(
                                    chat_id=CHANNEL_ID,
                                    text=caption,
                                    reply_markup=keyboard,
                                    disable_web_page_preview=True
                                )
                            else:
                                await client.send_photo(
                                    chat_id=CHANNEL_ID,
                                    photo=image_url,
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
                            
                        # Removed: await client.send_document(...) - No longer sending file directly
                        
                        await status_msg.edit_text("Successfully posted to channel!")
                        
                    except Exception as e:
                        logging.error(f"Failed to post to channel: {e}")
                        await status_msg.edit_text(f"File sent, but failed to post to channel: {e}")
                else:
                     await status_msg.edit_text("File sent, but could not extract metadata for channel post.")
            
            else:
                await status_msg.delete()
                
        else:
            await status_msg.edit_text("Error: Output file not found.")
            
    except Exception as e:
        logging.error(f"Error processing URL: {e}")
        await status_msg.edit_text(f"An error occurred: {str(e)}")
        
    finally:
        # Cleanup
        if os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir)
            except Exception as e:
                logging.error(f"Cleanup failed: {e}")

if __name__ == '__main__':
    print("Bot is running...")
    app.run()
