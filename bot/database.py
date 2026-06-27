# bot/database.py
import json
import hashlib
import time
from typing import Dict
from threading import Lock
from datetime import datetime


class UserDatabase:
    """Simple JSON-based user database with optimized writes"""

    def __init__(self, filepath: str = "users.json"):
        self.filepath = filepath
        self.users = {}
        self.lock = Lock()
        self._dirty = False
        self.load()

    def load(self):
        """Load users from file"""
        try:
            with open(self.filepath, 'r') as f:
                self.users = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.users = {}

    def save(self):
        """Save users to file (only if dirty)"""
        if not self._dirty:
            return
        with self.lock:
            try:
                with open(self.filepath, 'w') as f:
                    json.dump(self.users, f, indent=2)
                self._dirty = False
            except Exception as e:
                print(f"Error saving database: {e}")

    def _mark_dirty(self):
        self._dirty = True

    def get_user(self, user_id: int) -> Dict:
        """Get user data, create if not exists"""
        user_id_str = str(user_id)

        if user_id_str not in self.users:
            self.users[user_id_str] = {
                "user_id": user_id,
                "tokens": 3,
                "total_earned": 3,
                "emails_created": 0,
                "tasks_completed": [],
                "premium_until": None,
                "referral_code": self._generate_ref_code(user_id),
                "referred_by": None,
                "referral_count": 0,
                "seen_welcome": False,
                "emails": [],
                "created_at": time.time(),
                "last_active": time.time(),
            }
            self._mark_dirty()
            self.save()  # Save immediately for new users only

        # Update last active
        self.users[user_id_str]["last_active"] = time.time()
        return self.users[user_id_str]

    def update_user(self, user_id: int, **kwargs):
        """Update user fields"""
        user_id_str = str(user_id)
        if user_id_str in self.users:
            self.users[user_id_str].update(kwargs)
            self._mark_dirty()

    def add_tokens(self, user_id: int, amount: int, reason: str = ""):
        """Add tokens to user"""
        user = self.get_user(user_id)
        user["tokens"] += amount
        user["total_earned"] += amount
        self._mark_dirty()
        print(f"[TOKENS] User {user_id} +{amount} ({reason})")

    def use_tokens(self, user_id: int, amount: int = 1) -> bool:
        """Use tokens, return success. Premium users bypass."""
        user = self.get_user(user_id)

        # Premium users don't consume tokens
        if user.get("premium_until"):
            try:
                premium_time = datetime.fromisoformat(user["premium_until"])
                if premium_time > datetime.now():
                    return True
            except (ValueError, TypeError):
                pass

        if user["tokens"] >= amount:
            user["tokens"] -= amount
            self._mark_dirty()
            return True
        return False

    def is_premium(self, user_id: int) -> bool:
        """Check if user has active premium"""
        user = self.get_user(user_id)
        if user.get("premium_until"):
            try:
                premium_time = datetime.fromisoformat(user["premium_until"])
                return premium_time > datetime.now()
            except (ValueError, TypeError):
                pass
        return False

    def _generate_ref_code(self, user_id: int) -> str:
        """Generate unique referral code"""
        return hashlib.md5(f"{user_id}".encode()).hexdigest()[:8]

    def get_all_users(self) -> Dict:
        """Get all users"""
        return self.users

    def add_email(self, user_id: int, address: str, timestamp: str, key: str):
        """Add email to user's history"""
        user = self.get_user(user_id)
        if "emails" not in user:
            user["emails"] = []
        # Remove duplicate if exists
        user["emails"] = [e for e in user["emails"] if e["address"] != address]
        user["emails"].insert(0, {
            "address": address,
            "timestamp": timestamp,
            "key": key,
            "created_at": time.time(),
        })
        # Keep only last 20 emails
        user["emails"] = user["emails"][:20]
        self._mark_dirty()

    def get_emails(self, user_id: int) -> list:
        """Get user's email list"""
        user = self.get_user(user_id)
        return user.get("emails", [])

    def get_email_by_addr(self, user_id: int, address: str) -> dict:
        """Get specific email from user's history"""
        for e in self.get_emails(user_id):
            if e["address"] == address:
                return e
        return None


# Global database instance
db = UserDatabase()
