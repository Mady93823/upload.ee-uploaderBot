import time
import logging
import asyncio
import os
import shutil
import secrets
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from processor import process_url
from config import ADMIN_ID, CHANNEL_ID
from database import file_store

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

async def check_force_sub(client, user_id, force_sub_channels):
    if not force_sub_channels:
        return True, []
        
    missing_channels = []
    for channel_id in force_sub_channels:
        try:
            member = await client.get_chat_member(channel_id, user_id)
            if member.status in ["left", "kicked", "banned"]:
                missing_channels.append(channel_id)
        except Exception:
            # If bot can't check (not admin or channel invalid), assume user is not in it or skip
            missing_channels.append(channel_id)
            
    return len(missing_channels) == 0, missing_channels

async def process_and_post_to_channel(client, url, bot_username=None):
    """
    Headless version of the processing logic for automation.
    """
    if not bot_username:
         try:
             me = await client.get_me()
             bot_username = me.username
         except:
             bot_username = "Bot"

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
            # We send it to ADMIN_ID first to get file_id and store it.
            # If ADMIN_ID is not set, we might fail or need a dump channel.
            target_chat = ADMIN_ID if ADMIN_ID else CHANNEL_ID
            
            caption_file = f"{metadata.get('title', 'File')}\n\nUploaded by Bot"
            
            # Upload to Admin to get File ID
            msg = await client.send_document(
                chat_id=target_chat,
                document=zip_path,
                caption=caption_file
            )
            
            file_id = msg.document.file_id
            
            # 3. Create Store Entry
            code = await file_store.save_file(file_id, caption=caption_file)
            bot_link = f"https://t.me/{bot_username}?start={code}"
            
            # 4. Post to Channel
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Download File 📥", url=bot_link)]
            ])
            
            title = metadata.get('title', 'New Script')
            image_url = metadata.get('image_url')
            demo_url = metadata.get('demo_url')
            description = metadata.get('description')
            
            # Stylish Caption
            caption = f"🔥 **{title}**\n\n"
            
            if description:
                # Limit description length to avoid clutter
                desc_preview = description[:300] + "..." if len(description) > 300 else description
                caption += f"📝 **Description**:\n{desc_preview}\n\n"
            
            if demo_url:
                caption += f"🌐 **Demo**: [Live Preview]({demo_url})\n"
                
            caption += "\n━━━━━━━━━━━━━━━━━━━━━\n"
            caption += "🚀 **Join Channel**: @freephplaravel\n"
            caption += "━━━━━━━━━━━━━━━━━━━━━"
            
            # Truncate caption if needed (1024 char limit)
            if len(caption) > 1024:
                caption = caption[:1021] + "..."

            logging.info(f"Posting to channel {CHANNEL_ID}")
            
            sent_msg = None
            local_img = metadata.get('image_path')
            use_local_img = local_img and os.path.exists(local_img)
            
            if image_url and "codelist.cc" not in image_url:
                 sent_msg = await client.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=image_url,
                    caption=caption,
                    reply_markup=keyboard
                )
            elif use_local_img:
                # Fallback to local processed image
                 sent_msg = await client.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=local_img,
                    caption=caption,
                    reply_markup=keyboard
                )
            else:
                 sent_msg = await client.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            
            logging.info("Auto-post successful!")
            return sent_msg
            
        else:
            logging.error("Processing failed (no zip path returned).")
            return None

    except Exception as e:
        logging.error(f"Auto-process error: {e}")
        return None
    finally:
        # Cleanup
        if os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir)
            except:
                pass
