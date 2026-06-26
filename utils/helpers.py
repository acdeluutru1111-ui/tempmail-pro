# utils/helpers.py
import hashlib
import secrets
from datetime import datetime


def generate_token(length: int = 32) -> str:
    """Generate random token"""
    return secrets.token_urlsafe(length)


def hash_user_id(user_id: int) -> str:
    """Hash user ID for external tracking"""
    return hashlib.md5(str(user_id).encode()).hexdigest()


def format_timestamp(timestamp: float = None) -> str:
    """Format timestamp to readable string"""
    if timestamp is None:
        timestamp = datetime.now().timestamp()
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def escape_markdown(text: str) -> str:
    """Escape markdown special characters for Telegram"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>',
                     '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text
