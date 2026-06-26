# bot/database.py
import json
import hashlib
import time
from typing import Dict
from threading import Lock
from datetime import datetime


class UserDatabase:
    """Simple JSON-based user database"""

    def __init__(self, filepath: str = "users.json"):
        self.filepath = filepath
        self.users = {}
        self.lock = Lock()
        self.load()

    def load(self):
        """Load users from file"""
        try:
            with open(self.filepath, 'r') as f:
                self.users = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.users = {}

    def save(self):
        """Save users to file"""
        with self.lock:
            try:
                with open(self.filepath, 'w') as f:
                    json.dump(self.users, f, indent=2)
            except Exception as e:
                print(f"Error saving database: {e}")

    def get_user(self, user_id: int) -> Dict:
        """Get user data, create if not exists"""
        user_id_str = str(user_id)

        if user_id_str not in self.users:
            self.users[user_id_str] = {
                "user_id": user_id,
                "tokens": 3,           # Welcome tokens
                "total_earned": 3,
                "emails_created": 0,
                "tasks_completed": [],
                "premium_until": None,
                "referral_code": self._generate_ref_code(user_id),
                "referred_by": None,
                "referral_count": 0,
                "created_at": time.time(),
                "last_active": time.time(),
            }
            self.save()

        # Update last active
        self.users[user_id_str]["last_active"] = time.time()
        return self.users[user_id_str]

    def update_user(self, user_id: int, **kwargs):
        """Update user fields"""
        user_id_str = str(user_id)
        if user_id_str in self.users:
            self.users[user_id_str].update(kwargs)
            self.save()

    def add_tokens(self, user_id: int, amount: int, reason: str = ""):
        """Add tokens to user"""
        user = self.get_user(user_id)
        user["tokens"] += amount
        user["total_earned"] += amount
        self.save()
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
            self.save()
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


# Global database instance
db = UserDatabase()
