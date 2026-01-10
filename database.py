import motor.motor_asyncio
import datetime
import time
import secrets
from config import MONGO_URI

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
