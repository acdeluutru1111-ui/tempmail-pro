"""
═══════════════════════════════════════════════════════════════════════
    TEMP MAIL SERVICE - Single File Backend + Frontend
═══════════════════════════════════════════════════════════════════════

🎯 Features:
    ✅ Tạo email tạm thời (SmailPro)
    ✅ Đọc inbox realtime
    ✅ Xem chi tiết message
    ✅ Auto-refresh inbox
    ✅ Copy email 1 click
    ✅ UI đẹp, responsive
    ✅ Proxy rotation tự động
    ✅ Rate limiting
    ✅ Error handling

📦 Tech Stack:
    - Backend: Flask (lightweight)
    - Frontend: HTML/CSS/JS (no framework)
    - Cache: In-memory dict
    - Proxy: Rotation pool

🚀 Run:
    python app.py

📝 Requirements:
    pip install flask requests

🌐 Access:
    http://localhost:5000

Author: TempMail Pro
License: MIT
"""

import re
import time
import random
import hashlib
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from threading import Lock

import requests
from flask import Flask, request, jsonify, render_template_string
from werkzeug.exceptions import HTTPException

# ════════════════════════════════════════════════════════════════════
#                           CONFIGURATION
# ════════════════════════════════════════════════════════════════════

class Config:
    """Cấu hình toàn bộ app"""
    
    # Flask
    DEBUG = True
    HOST = "0.0.0.0"
    PORT = 5000
    SECRET_KEY = "temp-mail-secret-key-change-in-production"
    
    # SmailPro
    SMAILPRO_BASE = "https://smailpro.com"
    SMAILPRO_CREATE = f"{SMAILPRO_BASE}/app/create"
    SMAILPRO_INBOX = f"{SMAILPRO_BASE}/app/inbox"
    
    # Sonjj API
    SONJJ_BASE = "https://api.sonjj.com"
    SONJJ_INBOX = f"{SONJJ_BASE}/v1/temp_gmail/inbox"
    SONJJ_MESSAGE = f"{SONJJ_BASE}/v1/temp_gmail/message"
    SONJJ_TIMEOUT = 10  # Timeout riêng cho Sonjj API
    
    # Proxy Pool (thêm proxy của bạn vào đây)
    PROXIES = [
        # "http://user:pass@ip:port",
        # "http://ip:port",
    ]
    
    # Rate Limiting
    MAX_REQUESTS_PER_IP = 9      # requests/phút/proxy (cho proxy rotation)
    MAX_CREATE_PER_IP = 10       # requests/phút/IP (cho create email)
    MAX_INBOX_PER_IP = 10        # requests/phút/IP (cho inbox/messages)
    COOLDOWN_SECONDS = 60
    
    # Timeouts
    REQUEST_TIMEOUT = 15
    POLL_INTERVAL = 3  # giây
    MAX_POLL_ATTEMPTS = 20
    
    # Cache
    EMAIL_CACHE_TTL = 3600  # 1 giờ
    INBOX_CACHE_TTL = 10    # 10 giây
    PAYLOAD_CACHE_TTL = 300  # 5 phút - payload reuse được nhiều lần
    
    # Email limit per client
    MAX_EMAILS_PER_CLIENT = 10


# ════════════════════════════════════════════════════════════════════
#                           DATA MODELS
# ════════════════════════════════════════════════════════════════════

@dataclass
class TempEmail:
    """Email tạm thời"""
    address: str
    timestamp: str = ""
    key: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self):
        return {
            "address": self.address,
            "timestamp": self.timestamp,
            "key": self.key,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class InboxMessage:
    """Message trong inbox"""
    mid: str
    subject: str = ""
    sender: str = ""
    date: str = ""
    snippet: str = ""
    
    def to_dict(self):
        return {
            "mid": self.mid,
            "subject": self.subject,
            "sender": self.sender,
            "date": self.date,
            "snippet": self.snippet,
        }


@dataclass
class MessageDetail:
    """Chi tiết message"""
    mid: str
    subject: str = ""
    sender: str = ""
    to: str = ""
    date: str = ""
    body_html: str = ""
    body_text: str = ""
    
    def to_dict(self):
        return {
            "mid": self.mid,
            "subject": self.subject,
            "sender": self.sender,
            "to": self.to,
            "date": self.date,
            "body_html": self.body_html,
            "body_text": self.body_text,
        }


# ════════════════════════════════════════════════════════════════════
#                         PROXY MANAGER
# ════════════════════════════════════════════════════════════════════

class ProxyRotator:
    """Quản lý rotation proxy với rate limiting"""
    
    def __init__(self, proxies: List[str]):
        self.proxies = proxies if proxies else [None]  # None = no proxy
        self.usage_count = defaultdict(int)
        self.cooldown_until = {}
        self.lock = Lock()
    
    def get_proxy(self, count_usage: bool = True) -> Optional[Dict[str, str]]:
        """Lấy proxy khả dụng (không đệ quy, tránh treo)
        
        Args:
            count_usage: True = đếm usage (cho create_email), False = không đếm (cho inbox/message)
        """
        with self.lock:
            now = time.time()
            
            # Lọc proxy đã hết cooldown
            available = [
                p for p in self.proxies
                if self.cooldown_until.get(p, 0) < now
            ]
            
            if not available:
                # Không có proxy nào khả dụng → dùng trực tiếp (no proxy)
                return None
            
            # Chọn proxy ít dùng nhất
            proxy = min(available, key=lambda p: self.usage_count[p])
            
            # Chỉ tăng counter khi cần (create_email)
            if count_usage:
                self.usage_count[proxy] += 1
                
                # Nếu đạt limit, cho nghỉ
                if self.usage_count[proxy] >= Config.MAX_REQUESTS_PER_IP:
                    self.cooldown_until[proxy] = now + Config.COOLDOWN_SECONDS
                    self.usage_count[proxy] = 0
            
            # Format proxy
            if proxy:
                return {"http": proxy, "https": proxy}
            return None


# ════════════════════════════════════════════════════════════════════
#                         CACHE MANAGER
# ════════════════════════════════════════════════════════════════════

class SimpleCache:
    """In-memory cache đơn giản"""
    
    def __init__(self):
        self.data = {}
        self.lock = Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Lấy dữ liệu từ cache"""
        with self.lock:
            item = self.data.get(key)
            if item:
                if item["expires_at"] > datetime.now():
                    return item["value"]
                else:
                    del self.data[key]
            return None
    
    def set(self, key: str, value: Any, ttl: int):
        """Lưu vào cache với TTL"""
        with self.lock:
            self.data[key] = {
                "value": value,
                "expires_at": datetime.now() + timedelta(seconds=ttl)
            }
    
    def delete(self, key: str):
        """Xóa khỏi cache"""
        with self.lock:
            self.data.pop(key, None)
    
    def clear_expired(self):
        """Xóa items hết hạn"""
        with self.lock:
            now = datetime.now()
            expired = [
                k for k, v in self.data.items()
                if v["expires_at"] <= now
            ]
            for k in expired:
                del self.data[k]


# ════════════════════════════════════════════════════════════════════
#                       SMAILPRO CLIENT
# ════════════════════════════════════════════════════════════════════

class SmailProClient:
    """Client tương tác với SmailPro"""
    
    COOKIES = {
        "XSRF-TOKEN": "eyJpdiI6IlZJSVpvRHRZSkdsVXJuTHMydWE3b1E9PSIsInZhbHVlIjoidlhNdmhGQWZhazR6a1puMFNhQU5uSFRUNnRNa2VBeHVUVWdKanR1WjdxTG9CTTdTUTB2UCtBL1llMUlLUllCUnRWSVVIVERHUk10Vm1mczlBNE1SbHNTY3VuMmxYSWhUQ0dOL1R4bmg2Wlpqblc2bXJHQmhTSUFWYXdtVnRSTkgiLCJtYWMiOiJhOTNmMzk0N2Y3MGVhNTc4ODM0MWNiZWYxOGYyNTk0ZTAxYmJjOGNjOTZkOTFhZWQyMzUzYmI3MDc4Nzk4NWU2IiwidGFnIjoiIn0%3D",
        "sonjj_session": "eyJpdiI6Ikx4d2ZhRmcwZVBSWnZOK0x6djNMN2c9PSIsInZhbHVlIjoiTzZ0aGVjSXVJWS9PeWJYV1Axd2FYWUszVE8xWlA0L0Y3RVp2bXdxTVZiNFlFREQwWEZYcnRxS0F5YXgzL25DeTJBMnRRNHp0dlFZOC9KR1hWUXRwSnhiaGdqRXB0L2VoMUF1THh5SWMreXpXNkxlazRCMTVoRUJKVmo2T3ZrRHMiLCJtYWMiOiIzYTZhMDUyYjY1MjllYWU2ODg0OGQzNGJjZWYwODM3YmNkYjFiMzQzNTdjNzA4MGEyY2ZlNGEzNTlhZWM1YjRkIiwidGFnIjoiIn0%3D",
    }
    
    def __init__(self, proxy_rotator: ProxyRotator):
        self.proxy_rotator = proxy_rotator
        # Use instance variable to allow dynamic updates
        self.cookies = dict(self.COOKIES)
    
    def _get_headers(self) -> Dict[str, str]:
        """Headers chuẩn"""
        return {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "referer": f"{Config.SMAILPRO_BASE}/temporary-email",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
    
    def create_email(self, username: str = "random") -> TempEmail:
        """Tạo email mới"""
        params = {
            "username": username,
            "type": "real",
            "domain": "gmail.com",
            "server": "2",
        }
        
        proxies = self.proxy_rotator.get_proxy()
        
        try:
            resp = requests.get(
                Config.SMAILPRO_CREATE,
                params=params,
                headers=self._get_headers(),
                cookies=self.cookies,
                timeout=Config.REQUEST_TIMEOUT,
                proxies=proxies,
                verify=False,
            )
            
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            raise ValueError("SmailPro timeout - thử lại sau vài giây")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"SmailPro error: {e}")
        
        address = (
            data.get("address")
            or data.get("email")
            or (data.get("data") or {}).get("address")
        )
        
        if not address:
            raise ValueError(f"Cannot extract email from response: {data}")
        
        return TempEmail(
            address=address,
            timestamp=str(data.get("timestamp", "")),
            key=data.get("key", ""),
        )
    
    def get_inbox(self, email: TempEmail) -> tuple[Optional[str], List[InboxMessage]]:
        """Lấy inbox"""
        # Step 1: Post to SmailPro
        body = [{
            "address": email.address,
            "timestamp": int(email.timestamp) if email.timestamp else 0,
            "key": email.key,
        }]
        
        proxies = self.proxy_rotator.get_proxy(count_usage=False)
        
        try:
            resp = requests.post(
                Config.SMAILPRO_INBOX,
                headers=self._get_headers(),
                json=body,
                cookies=self.cookies,
                timeout=Config.REQUEST_TIMEOUT,
                proxies=proxies,
                verify=False,
            )
            
            resp.raise_for_status()
            inbox_resp = resp.json()
        except requests.exceptions.Timeout:
            print(f"[WARN] SmailPro inbox timeout for {email.address}")
            return None, []
        except requests.exceptions.RequestException as e:
            print(f"[WARN] SmailPro inbox error: {e}")
            return None, []
        
        # Extract payload
        payload = None
        if isinstance(inbox_resp, list) and inbox_resp:
            payload = inbox_resp[0].get("payload")
        elif isinstance(inbox_resp, dict):
            payload = inbox_resp.get("payload")
        
        if not payload:
            return None, []
        
        # Step 2: Get messages from Sonjj
        messages = self._fetch_sonjj_inbox(payload)
        return payload, messages
    
    def _fetch_sonjj_inbox(self, payload: str) -> List[InboxMessage]:
        """Lấy messages từ Sonjj"""
        url = f"{Config.SONJJ_INBOX}?payload={urllib.parse.quote(payload, safe='')}"
        
        proxies = self.proxy_rotator.get_proxy(count_usage=False)
        
        try:
            resp = requests.get(
                url,
                headers={"user-agent": "Mozilla/5.0"},
                timeout=Config.SONJJ_TIMEOUT,
                proxies=proxies,
                verify=False,
            )
            
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            print(f"[WARN] Sonjj inbox timeout")
            return []
        except requests.exceptions.RequestException as e:
            print(f"[WARN] Sonjj inbox error: {e}")
            return []
        except Exception as e:
            print(f"[WARN] Sonjj inbox unexpected error: {e}")
            return []
        
        raw_messages = data.get("messages", []) if isinstance(data, dict) else data
        
        if not isinstance(raw_messages, list):
            return []
        
        messages = []
        for msg in raw_messages:
            if isinstance(msg, dict):
                messages.append(InboxMessage(
                    mid=msg.get("mid", ""),
                    subject=msg.get("textSubject") or msg.get("subject", ""),
                    sender=msg.get("textFrom") or msg.get("from", ""),
                    date=msg.get("date") or msg.get("textDate", ""),
                    snippet=msg.get("snippet") or msg.get("textSnippet", ""),
                ))
        
        return messages
    
    def get_message_detail(self, mid: str, payload: str) -> MessageDetail:
        """Lấy chi tiết message"""
        url = f"{Config.SONJJ_MESSAGE}?payload={urllib.parse.quote(payload, safe='')}&mid={mid}"
        
        proxies = self.proxy_rotator.get_proxy(count_usage=False)
        
        try:
            resp = requests.get(
                url,
                headers={"user-agent": "Mozilla/5.0"},
                timeout=Config.SONJJ_TIMEOUT,
                proxies=proxies,
                verify=False,
            )
            
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            raise ValueError("Request timeout - Sonjj API không phản hồi")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Request error: {e}")
        
        return MessageDetail(
            mid=mid,
            subject=data.get("subject") or data.get("textSubject", ""),
            sender=data.get("from") or data.get("textFrom", ""),
            to=data.get("to") or data.get("textTo", ""),
            date=data.get("date") or data.get("textDate", ""),
            body_html=data.get("message") or data.get("htmlBody", ""),
            body_text=data.get("textBody") or data.get("text", ""),
        )


# ════════════════════════════════════════════════════════════════════
#                           FLASK APP
# ════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.config.from_object(Config)

# Initialize components
proxy_rotator = ProxyRotator(Config.PROXIES)
cache = SimpleCache()
client = SmailProClient(proxy_rotator)

# Rate limiting per client IP
client_rate_limit = defaultdict(list)
inbox_rate_limit = defaultdict(list)  # Riêng cho inbox endpoints

# Per-client email creation counter (IP -> count)
client_email_counts = defaultdict(int)

# Per-client email storage (IP -> list of email dicts, for history display)
client_emails = defaultdict(list)


# ════════════════════════════════════════════════════════════════════
#                         MIDDLEWARES
# ════════════════════════════════════════════════════════════════════

@app.before_request
def rate_limit():
    """Rate limit per client IP - tách biệt create, inbox, và chung"""
    ip = request.remote_addr
    now = time.time()
    path = request.path
    method = request.method
    
    # ── Rate limit cho create email (10 lần/phút/IP) ──
    if method == "POST" and path == "/api/create":
        client_rate_limit[ip] = [
            t for t in client_rate_limit[ip]
            if now - t < 60
        ]
        
        if len(client_rate_limit[ip]) >= Config.MAX_CREATE_PER_IP:
            return jsonify({
                "error": "Tạo email quá nhanh. Chờ một chút rồi thử lại.",
                "retry_after": 60,
                "limit_type": "create"
            }), 429
        
        client_rate_limit[ip].append(now)
        return
    
    # ── Rate limit cho inbox endpoints (10 lần/phút/IP) ──
    if path.startswith("/api/inbox/") or path.startswith("/api/messages/") or "/inbox" in path:
        inbox_rate_limit[ip] = [
            t for t in inbox_rate_limit[ip]
            if now - t < 60
        ]
        
        if len(inbox_rate_limit[ip]) >= Config.MAX_INBOX_PER_IP:
            return jsonify({
                "error": "Đang đọc mail quá nhanh. Chờ vài giây rồi thử lại.",
                "retry_after": 10,
                "limit_type": "inbox"
            }), 429
        
        inbox_rate_limit[ip].append(now)
        return  # Không tính vào general rate limit
    
    # ── Rate limit chung (30 requests/phút/IP) cho các endpoint khác ──
    client_rate_limit[ip] = [
        t for t in client_rate_limit[ip]
        if now - t < 60
    ]
    
    if len(client_rate_limit[ip]) >= 30:
        return jsonify({
            "error": "Rate limit exceeded. Please try again later.",
            "retry_after": 60
        }), 429
    
    client_rate_limit[ip].append(now)


@app.errorhandler(Exception)
def handle_error(e):
    """Global error handler"""
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    
    app.logger.error(f"Unhandled error: {e}")
    return jsonify({
        "error": "Internal server error",
        "message": str(e) if Config.DEBUG else "Something went wrong"
    }), 500


# ════════════════════════════════════════════════════════════════════
#                           API ROUTES
# ════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Homepage với UI"""
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/create", methods=["POST"])
def api_create_email():
    """
    Tạo email mới
    
    Body: { "username": "optional" }
    Response: { "email": {...} }
    """
    ip = request.remote_addr
    
    # Check email limit per client using dedicated counter
    if client_email_counts[ip] >= Config.MAX_EMAILS_PER_CLIENT:
        return jsonify({
            "success": False,
            "error": f"Đã đạt giới hạn {Config.MAX_EMAILS_PER_CLIENT} email. Vui lòng sử dụng email có sẵn."
        }), 403
    
    # Increment counter BEFORE calling API (counts even failed attempts)
    client_email_counts[ip] += 1
    
    data = request.get_json() or {}
    username = data.get("username", "random")
    
    try:
        email = client.create_email(username)
        
        # Cache email
        cache_key = f"email:{email.address}"
        cache.set(cache_key, email, Config.EMAIL_CACHE_TTL)
        
        # Store in client email list (for history table)
        email_dict = email.to_dict()
        email_dict["message_count"] = 0
        client_emails[ip].append(email_dict)
        
        return jsonify({
            "success": True,
            "email": email_dict,
            "remaining": Config.MAX_EMAILS_PER_CLIENT - client_email_counts[ip]
        })
    
    except Exception as e:
        app.logger.error(f"Create email error: {e}")
        # Counter was already incremented — this counts as a used attempt
        return jsonify({
            "success": False,
            "error": str(e),
            "remaining": Config.MAX_EMAILS_PER_CLIENT - client_email_counts[ip]
        }), 500


@app.route("/api/inbox/<path:email_address>", methods=["GET"])
def api_get_inbox(email_address: str):
    """
    Lấy inbox (full: SmailPro + Sonjj)
    Chỉ gọi SmailPro khi chưa có payload cached.
    
    Response: {
        "success": true,
        "payload": "...",
        "messages": [...]
    }
    """
    # Check inbox cache (trả ngay nếu có)
    cache_key = f"inbox:{email_address}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify({
            "success": True,
            "cached": True,
            **cached
        })
    
    # Check payload cache - nếu có thì chỉ gọi Sonjj (tiết kiệm 1 request)
    payload_cache_key = f"payload:{email_address}"
    cached_payload = cache.get(payload_cache_key)
    
    if cached_payload:
        # Có payload rồi → chỉ gọi Sonjj lấy messages
        try:
            messages = client._fetch_sonjj_inbox(cached_payload)
            
            result = {
                "payload": cached_payload,
                "messages": [m.to_dict() for m in messages],
                "count": len(messages)
            }
            
            cache.set(cache_key, result, Config.INBOX_CACHE_TTL)
            
            return jsonify({
                "success": True,
                "cached": False,
                "payload_reused": True,
                **result
            })
        except Exception as e:
            app.logger.error(f"Sonjj-only inbox error: {e}")
            # Fallback: gọi full flow
    
    # Chưa có payload → gọi full flow (SmailPro + Sonjj)
    email_cache_key = f"email:{email_address}"
    email = cache.get(email_cache_key)
    
    if not email:
        email = TempEmail(address=email_address)
    
    try:
        payload, messages = client.get_inbox(email)
        
        # Cache payload riêng (5 phút) để lần sau không cần gọi SmailPro
        if payload:
            cache.set(payload_cache_key, payload, Config.PAYLOAD_CACHE_TTL)
        
        result = {
            "payload": payload,
            "messages": [m.to_dict() for m in messages],
            "count": len(messages)
        }
        
        cache.set(cache_key, result, Config.INBOX_CACHE_TTL)
        
        return jsonify({
            "success": True,
            "cached": False,
            "payload_reused": False,
            **result
        })
    
    except Exception as e:
        app.logger.error(f"Get inbox error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/messages/<path:email_address>", methods=["GET"])
def api_get_messages_only(email_address: str):
    """
    Chỉ lấy messages (dùng payload đã cached).
    Dùng cho auto-refresh - không gọi lại SmailPro.
    Nếu chưa có payload → fallback gọi full inbox.
    
    Response: {
        "success": true,
        "payload": "...",
        "messages": [...],
        "payload_reused": true/false
    }
    """
    # Check inbox cache trước
    cache_key = f"inbox:{email_address}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify({
            "success": True,
            "cached": True,
            "payload_reused": True,
            **cached
        })
    
    # Check payload cache
    payload_cache_key = f"payload:{email_address}"
    cached_payload = cache.get(payload_cache_key)
    
    if cached_payload:
        # Có payload → chỉ gọi Sonjj
        try:
            messages = client._fetch_sonjj_inbox(cached_payload)
            
            result = {
                "payload": cached_payload,
                "messages": [m.to_dict() for m in messages],
                "count": len(messages)
            }
            
            cache.set(cache_key, result, Config.INBOX_CACHE_TTL)
            
            return jsonify({
                "success": True,
                "cached": False,
                "payload_reused": True,
                **result
            })
        except Exception as e:
            app.logger.error(f"Messages-only error: {e}")
    
    # Không có payload → fallback full inbox
    email_cache_key = f"email:{email_address}"
    email = cache.get(email_cache_key)
    
    if not email:
        email = TempEmail(address=email_address)
    
    try:
        payload, messages = client.get_inbox(email)
        
        if payload:
            cache.set(payload_cache_key, payload, Config.PAYLOAD_CACHE_TTL)
        
        result = {
            "payload": payload,
            "messages": [m.to_dict() for m in messages],
            "count": len(messages)
        }
        
        cache.set(cache_key, result, Config.INBOX_CACHE_TTL)
        
        return jsonify({
            "success": True,
            "cached": False,
            "payload_reused": False,
            **result
        })
    
    except Exception as e:
        app.logger.error(f"Messages fallback error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/message/<mid>", methods=["POST"])
def api_get_message(mid: str):
    """
    Lấy chi tiết message
    
    Body: { "payload": "..." }
    Response: { "message": {...} }
    """
    data = request.get_json() or {}
    payload = data.get("payload")
    
    if not payload:
        return jsonify({
            "success": False,
            "error": "Payload is required"
        }), 400
    
    # Check cache
    cache_key = f"message:{mid}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify({
            "success": True,
            "cached": True,
            "message": cached
        })
    
    try:
        message = client.get_message_detail(mid, payload)
        message_dict = message.to_dict()
        
        # Cache message
        cache.set(cache_key, message_dict, 300)  # 5 phút
        
        return jsonify({
            "success": True,
            "cached": False,
            "message": message_dict
        })
    
    except Exception as e:
        app.logger.error(f"Get message error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/health", methods=["GET"])
def api_health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_size": len(cache.data),
        "proxies": len(proxy_rotator.proxies)
    })


@app.route("/api/cookies", methods=["POST"])
def api_update_cookies():
    """
    Update SmailPro cookies
    
    Body: { "xsrf_token": "...", "sonjj_session": "..." }
    """
    data = request.get_json() or {}
    xsrf_token = data.get("xsrf_token", "").strip()
    sonjj_session = data.get("sonjj_session", "").strip()
    
    if not xsrf_token and not sonjj_session:
        return jsonify({
            "success": False,
            "error": "At least one cookie value is required"
        }), 400
    
    # Update cookies in SmailProClient
    if xsrf_token:
        client.cookies["XSRF-TOKEN"] = xsrf_token
    if sonjj_session:
        client.cookies["sonjj_session"] = sonjj_session
    
    return jsonify({
        "success": True,
        "message": "Cookies updated successfully",
        "cookies": {
            "XSRF-TOKEN": "set" if client.cookies.get("XSRF-TOKEN") else "not set",
            "sonjj_session": "set" if client.cookies.get("sonjj_session") else "not set"
        }
    })


@app.route("/api/emails", methods=["GET"])
def api_get_emails():
    """
    Lấy danh sách email của client
    
    Response: { "emails": [...], "count", "limit", "remaining" }
    """
    ip = request.remote_addr
    emails = client_emails.get(ip, [])
    used = client_email_counts.get(ip, 0)
    
    return jsonify({
        "success": True,
        "emails": emails,
        "count": len(emails),
        "used": used,
        "limit": Config.MAX_EMAILS_PER_CLIENT,
        "remaining": max(Config.MAX_EMAILS_PER_CLIENT - used, 0)
    })


@app.route("/api/emails/<path:email_address>/inbox", methods=["GET"])
def api_get_email_inbox(email_address: str):
    """
    Lấy inbox cho email trong lịch sử
    """
    ip = request.remote_addr
    emails = client_emails.get(ip, [])
    
    # Find email in client history
    email_data = None
    for e in emails:
        if e["address"] == email_address:
            email_data = e
            break
    
    if not email_data:
        return jsonify({
            "success": False,
            "error": "Email not found in your history"
        }), 404
    
    # Check inbox cache
    cache_key = f"inbox:{email_address}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify({
            "success": True,
            "cached": True,
            **cached
        })
    
    # Check payload cache - nếu có thì chỉ gọi Sonjj
    payload_cache_key = f"payload:{email_address}"
    cached_payload = cache.get(payload_cache_key)
    
    if cached_payload:
        try:
            messages = client._fetch_sonjj_inbox(cached_payload)
            
            result = {
                "payload": cached_payload,
                "messages": [m.to_dict() for m in messages],
                "count": len(messages)
            }
            
            # Update message count
            for e in emails:
                if e["address"] == email_address:
                    e["message_count"] = len(messages)
                    break
            
            cache.set(cache_key, result, Config.INBOX_CACHE_TTL)
            
            return jsonify({
                "success": True,
                "cached": False,
                "payload_reused": True,
                **result
            })
        except Exception as e:
            app.logger.error(f"Email inbox Sonjj-only error: {e}")
            # Fallback to full flow
    
    # Build TempEmail from stored data
    email = TempEmail(
        address=email_data["address"],
        timestamp=email_data.get("timestamp", ""),
        key=email_data.get("key", "")
    )
    
    try:
        payload, messages = client.get_inbox(email)
        
        # Cache payload riêng
        if payload:
            cache.set(payload_cache_key, payload, Config.PAYLOAD_CACHE_TTL)
        
        result = {
            "payload": payload,
            "messages": [m.to_dict() for m in messages],
            "count": len(messages)
        }
        
        # Update message count in client_emails
        for e in emails:
            if e["address"] == email_address:
                e["message_count"] = len(messages)
                break
        
        # Cache inbox
        cache.set(cache_key, result, Config.INBOX_CACHE_TTL)
        
        return jsonify({
            "success": True,
            "cached": False,
            "payload_reused": False,
            **result
        })
    
    except Exception as e:
        app.logger.error(f"Get email inbox error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ════════════════════════════════════════════════════════════════════
#                         HTML TEMPLATE
# ════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TempMail Pro - Disposable Email Service</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --primary: #6366f1;
            --primary-dark: #4f46e5;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --bg: #f8fafc;
            --card: #ffffff;
            --text: #1e293b;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --shadow: 0 1px 3px rgba(0,0,0,0.1);
            --shadow-lg: 0 10px 25px rgba(0,0,0,0.1);
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        /* Header */
        header {
            background: var(--card);
            box-shadow: var(--shadow);
            margin-bottom: 30px;
            border-bottom: 3px solid var(--primary);
        }
        
        .header-content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .logo {
            font-size: 24px;
            font-weight: bold;
            color: var(--primary);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .logo-icon {
            font-size: 32px;
        }
        
        .stats {
            display: flex;
            gap: 20px;
            font-size: 14px;
            color: var(--text-muted);
        }
        
        .stat-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        /* Cards */
        .card {
            background: var(--card);
            border-radius: 12px;
            padding: 24px;
            box-shadow: var(--shadow);
            margin-bottom: 20px;
        }
        
        .card-header {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        /* Cookie Input */
        .cookie-section {
            margin-bottom: 20px;
            padding: 16px;
            background: var(--bg);
            border: 2px solid var(--border);
            border-radius: 8px;
        }
        
        .cookie-section .section-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
        }
        
        .cookie-section .section-title:hover {
            color: var(--primary);
        }
        
        .cookie-fields {
            display: none;
            flex-direction: column;
            gap: 10px;
        }
        
        .cookie-fields.expanded {
            display: flex;
        }
        
        .cookie-field {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .cookie-field label {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-muted);
            min-width: 120px;
        }
        
        .cookie-field input {
            flex: 1;
            padding: 10px 12px;
            border: 2px solid var(--border);
            border-radius: 6px;
            font-size: 13px;
            font-family: monospace;
            transition: border-color 0.2s;
        }
        
        .cookie-field input:focus {
            outline: none;
            border-color: var(--primary);
        }
        
        .cookie-field input::placeholder {
            color: #94a3b8;
        }
        
        /* Email Box */
        .email-box {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .email-display {
            flex: 1;
            padding: 16px;
            background: var(--bg);
            border: 2px solid var(--border);
            border-radius: 8px;
            font-size: 16px;
            font-weight: 500;
            color: var(--text);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .email-text {
            user-select: all;
        }
        
        .email-placeholder {
            color: var(--text-muted);
        }
        
        /* Buttons */
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            white-space: nowrap;
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .btn-primary {
            background: var(--primary);
            color: white;
        }
        
        .btn-primary:hover:not(:disabled) {
            background: var(--primary-dark);
            transform: translateY(-2px);
            box-shadow: var(--shadow-lg);
        }
        
        .btn-secondary {
            background: var(--bg);
            color: var(--text);
            border: 2px solid var(--border);
        }
        
        .btn-secondary:hover:not(:disabled) {
            border-color: var(--primary);
            color: var(--primary);
        }
        
        .btn-success {
            background: var(--success);
            color: white;
        }
        
        .btn-icon {
            padding: 12px;
        }
        
        /* Loading */
        .loading {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        /* Inbox */
        .inbox-empty {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }
        
        .inbox-empty-icon {
            font-size: 64px;
            margin-bottom: 16px;
            opacity: 0.5;
        }
        
        .message-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .message-item {
            padding: 16px;
            background: var(--bg);
            border: 2px solid var(--border);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .message-item:hover {
            border-color: var(--primary);
            transform: translateX(4px);
        }
        
        .message-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        
        .message-subject {
            font-weight: 600;
            font-size: 15px;
        }
        
        .message-date {
            font-size: 12px;
            color: var(--text-muted);
        }
        
        .message-from {
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }
        
        .message-snippet {
            font-size: 13px;
            color: var(--text-muted);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        /* Message Detail Modal */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
            padding: 20px;
            overflow-y: auto;
        }
        
        .modal.active {
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .modal-content {
            background: var(--card);
            border-radius: 12px;
            max-width: 800px;
            width: 100%;
            max-height: 90vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        
        .modal-header {
            padding: 20px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .modal-title {
            font-size: 18px;
            font-weight: 600;
        }
        
        .modal-close {
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--text-muted);
            padding: 0;
            width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 4px;
        }
        
        .modal-close:hover {
            background: var(--bg);
        }
        
        .modal-body {
            padding: 20px;
            overflow-y: auto;
            flex: 1;
        }
        
        .message-detail-meta {
            margin-bottom: 20px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
        }
        
        .meta-item {
            margin-bottom: 8px;
            font-size: 14px;
        }
        
        .meta-label {
            font-weight: 600;
            color: var(--text-muted);
            display: inline-block;
            width: 60px;
        }
        
        .message-body {
            line-height: 1.8;
        }
        
        .message-body iframe {
            width: 100%;
            min-height: 400px;
            border: 1px solid var(--border);
            border-radius: 4px;
        }
        
        /* Alerts */
        .alert {
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .alert-success {
            background: #d1fae5;
            color: #065f46;
            border: 1px solid #10b981;
        }
        
        .alert-error {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #ef4444;
        }
        
        .alert-info {
            background: #dbeafe;
            color: #1e40af;
            border: 1px solid #3b82f6;
        }
        
        /* Badge */
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .badge-primary {
            background: var(--primary);
            color: white;
        }
        
        .badge-success {
            background: var(--success);
            color: white;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .header-content {
                flex-direction: column;
                gap: 16px;
            }
            
            .stats {
                width: 100%;
                justify-content: space-around;
            }
            
            .email-box {
                flex-direction: column;
            }
            
            .modal-content {
                margin: 0;
                border-radius: 0;
                max-height: 100vh;
            }
        }
        
        /* Auto-refresh indicator */
        .refresh-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: var(--text-muted);
        }
        
        .refresh-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        
        /* Email History */
        .email-history-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .email-history-table th,
        .email-history-table td {
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        
        .email-history-table th {
            background: var(--bg);
            font-weight: 600;
            font-size: 13px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .email-history-table tr {
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .email-history-table tbody tr:hover {
            background: #f1f5f9;
        }
        
        .email-history-table tbody tr.active {
            background: #eef2ff;
            border-left: 3px solid var(--primary);
        }
        
        .email-history-table .email-addr {
            font-weight: 500;
            font-family: monospace;
            font-size: 14px;
        }
        
        .email-history-table .msg-count {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            background: var(--bg);
            color: var(--text-muted);
            border: 1px solid var(--border);
        }
        
        .email-history-table .msg-count.has-messages {
            background: #dbeafe;
            color: #1e40af;
            border-color: #3b82f6;
        }
        
        /* Limit Bar */
        .limit-bar-container {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }
        
        .limit-bar {
            flex: 1;
            height: 8px;
            background: var(--bg);
            border-radius: 4px;
            overflow: hidden;
            border: 1px solid var(--border);
        }
        
        .limit-bar-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s ease;
            background: var(--primary);
        }
        
        .limit-bar-fill.warning {
            background: var(--warning);
        }
        
        .limit-bar-fill.full {
            background: var(--danger);
        }
        
        .limit-text {
            font-size: 13px;
            font-weight: 600;
            color: var(--text-muted);
            white-space: nowrap;
        }
        
        .history-empty {
            text-align: center;
            padding: 40px 20px;
            color: var(--text-muted);
        }
        
        .history-empty-icon {
            font-size: 48px;
            margin-bottom: 12px;
            opacity: 0.5;
        }
    </style>
</head>
<body>
    <header>
        <div class="header-content">
            <div class="logo">
                <span class="logo-icon">📧</span>
                <span>TempMail Pro</span>
            </div>
            <div class="stats">
                <div class="stat-item">
                    <span>⚡</span>
                    <span id="stat-messages">0 messages</span>
                </div>
                <div class="stat-item">
                    <span>🔄</span>
                    <span id="stat-refresh">Auto-refresh</span>
                </div>
            </div>
        </div>
    </header>

    <div class="container">
        <!-- Alert container -->
        <div id="alert-container"></div>

        <!-- Email Card -->
        <div class="card">
            <div class="card-header">
                <span>📬 Your Temporary Email</span>
                <div class="refresh-indicator" id="refresh-indicator" style="display: none;">
                    <span class="refresh-dot"></span>
                    <span>Live</span>
                </div>
            </div>
            
            <!-- Cookie Section -->
            <div class="cookie-section">
                <div class="section-title" onclick="toggleCookieFields()">
                    <span>🍪 SmailPro Cookies</span>
                    <span id="cookie-toggle-icon">▼</span>
                </div>
                <div class="cookie-fields" id="cookie-fields">
                    <div class="cookie-field">
                        <label>XSRF-TOKEN:</label>
                        <input type="text" id="xsrf-token-input" placeholder="Paste XSRF-TOKEN value here...">
                    </div>
                    <div class="cookie-field">
                        <label>sonjj_session:</label>
                        <input type="text" id="sonjj-session-input" placeholder="Paste sonjj_session value here...">
                    </div>
                    <button class="btn btn-secondary" id="save-cookies-btn" onclick="saveCookies()">
                        💾 Save Cookies
                    </button>
                </div>
            </div>
            
            <div class="email-box">
                <div class="email-display" id="email-display">
                    <span class="email-placeholder">Click "Generate" to create temporary email</span>
                </div>
                <button class="btn btn-secondary btn-icon" id="copy-btn" title="Copy email" disabled>
                    📋
                </button>
                <button class="btn btn-primary" id="generate-btn">
                    <span>Generate Email</span>
                </button>
                <button class="btn btn-secondary" id="refresh-btn" disabled>
                    <span>🔄 Refresh</span>
                </button>
            </div>
        </div>

        <!-- Inbox Card -->
        <div class="card">
            <div class="card-header">
                <span>📨 Inbox</span>
                <span class="badge badge-primary" id="message-count">0</span>
            </div>
            
            <div id="inbox-container">
                <div class="inbox-empty">
                    <div class="inbox-empty-icon">📭</div>
                    <p>Your inbox is empty</p>
                    <p style="font-size: 14px; margin-top: 8px;">Messages will appear here automatically</p>
                </div>
            </div>
        </div>

        <!-- Email History Card -->
        <div class="card">
            <div class="card-header">
                <span>📋 Email History</span>
                <span class="badge badge-primary" id="history-count">0/10</span>
            </div>
            
            <div class="limit-bar-container">
                <div class="limit-bar">
                    <div class="limit-bar-fill" id="limit-bar-fill" style="width: 0%"></div>
                </div>
                <span class="limit-text" id="limit-text">0/10</span>
            </div>
            
            <div id="history-container">
                <div class="history-empty">
                    <div class="history-empty-icon">📋</div>
                    <p>No emails created yet</p>
                    <p style="font-size: 14px; margin-top: 8px;">Click "Generate Email" to create your first email</p>
                </div>
            </div>
        </div>
    </div>

    <!-- Message Detail Modal -->
    <div class="modal" id="message-modal">
        <div class="modal-content">
            <div class="modal-header">
                <div class="modal-title">Message Details</div>
                <button class="modal-close" onclick="closeModal()">×</button>
            </div>
            <div class="modal-body" id="modal-body">
                <div class="loading"></div>
            </div>
        </div>
    </div>

    <script>
        // State
        let currentEmail = null;
        let currentPayload = null;
        let autoRefreshInterval = null;
        let messages = [];
        let emailHistory = [];
        let emailLimit = 10;
        let inboxRequestVersion = 0;
        let currentAbortController = null;
        let selectEmailTimeout = null;
        let isLoadingInbox = false;

        // DOM Elements
        const emailDisplay = document.getElementById('email-display');
        const generateBtn = document.getElementById('generate-btn');
        const copyBtn = document.getElementById('copy-btn');
        const refreshBtn = document.getElementById('refresh-btn');
        const inboxContainer = document.getElementById('inbox-container');
        const messageCount = document.getElementById('message-count');
        const statMessages = document.getElementById('stat-messages');
        const refreshIndicator = document.getElementById('refresh-indicator');
        const messageModal = document.getElementById('message-modal');
        const modalBody = document.getElementById('modal-body');
        const alertContainer = document.getElementById('alert-container');
        const historyContainer = document.getElementById('history-container');
        const historyCount = document.getElementById('history-count');
        const limitBarFill = document.getElementById('limit-bar-fill');
        const limitText = document.getElementById('limit-text');

        // Generate Email
        generateBtn.addEventListener('click', async () => {
            if (generateBtn.disabled) return;
            setLoading(generateBtn, true);
            
            try {
                const response = await fetch('/api/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    currentEmail = data.email;
                    displayEmail(data.email.address);
                    showAlert('Email created successfully!', 'success');
                    
                    copyBtn.disabled = false;
                    refreshBtn.disabled = false;
                    
                    // Reload history, then fetch inbox (non-blocking)
                    loadEmailHistory();
                    startAutoRefresh();
                    fetchInboxForAddress(data.email.address);
                } else {
                    showAlert(data.error || 'Failed to create email', 'error');
                }
            } catch (error) {
                showAlert('Network error: ' + error.message, 'error');
            } finally {
                setLoading(generateBtn, false);
            }
        });

        // Copy Email
        copyBtn.addEventListener('click', () => {
            if (!currentEmail) return;
            
            navigator.clipboard.writeText(currentEmail.address).then(() => {
                showAlert('Email copied to clipboard!', 'success', 2000);
                copyBtn.innerHTML = '✓';
                setTimeout(() => {
                    copyBtn.innerHTML = '📋';
                }, 2000);
            });
        });

        // Refresh Inbox button - cooldown 5 giây
        let lastRefreshClick = 0;
        const REFRESH_COOLDOWN = 5000; // 5 giây
        let refreshCooldownTimer = null;
        
        refreshBtn.addEventListener('click', () => {
            const now = Date.now();
            const elapsed = now - lastRefreshClick;
            if (elapsed < REFRESH_COOLDOWN) {
                const waitSec = Math.ceil((REFRESH_COOLDOWN - elapsed) / 1000);
                showAlert(`Chờ ${waitSec}s nữa mới được refresh lại`, 'info', 2000);
                return;
            }
            if (currentEmail) {
                lastRefreshClick = now;
                fetchInboxForAddress(currentEmail.address);
                
                // Disable nút + đếm ngược
                refreshBtn.disabled = true;
                let remaining = Math.floor(REFRESH_COOLDOWN / 1000);
                const span = refreshBtn.querySelector('span');
                const originalText = span ? span.textContent : '🔄 Refresh';
                
                refreshCooldownTimer = setInterval(() => {
                    remaining--;
                    if (remaining <= 0) {
                        clearInterval(refreshCooldownTimer);
                        refreshCooldownTimer = null;
                        refreshBtn.disabled = false;
                        if (span) span.textContent = originalText;
                    } else {
                        if (span) span.textContent = `🔄 ${remaining}s`;
                    }
                }, 1000);
            }
        });

        /**
         * Unified inbox fetcher — address-scoped to prevent cross-email interference.
         * @param {string} address - Email address
         * @param {boolean} messagesOnly - true = dùng /api/messages/ (chỉ Sonjj, không gọi SmailPro)
         *                                  false = dùng /api/inbox/ (full flow, lần đầu)
         */
        async function fetchInboxForAddress(address, messagesOnly = false) {
            // 1. Abort previous request at NETWORK level (frees connection)
            if (currentAbortController) {
                currentAbortController.abort();
                currentAbortController = null;
            }
            
            // 2. Bump version to discard stale responses
            const version = ++inboxRequestVersion;
            
            // 3. Only proceed if this address is still the current email
            if (!currentEmail || currentEmail.address !== address) return;
            
            currentAbortController = new AbortController();
            isLoadingInbox = true;
            setLoading(refreshBtn, true);
            
            const endpoint = messagesOnly 
                ? `/api/messages/${encodeURIComponent(address)}`
                : `/api/inbox/${encodeURIComponent(address)}`;
            
            try {
                const timeoutId = setTimeout(() => {
                    if (currentAbortController) currentAbortController.abort();
                }, 15000);
                
                const response = await fetch(
                    endpoint,
                    { signal: currentAbortController.signal }
                );
                clearTimeout(timeoutId);
                
                // 4. Double-check: version + address still current?
                if (version !== inboxRequestVersion) return;
                if (!currentEmail || currentEmail.address !== address) return;
                
                // Xử lý 429 (rate limit) riêng
                if (response.status === 429) {
                    const errData = await response.json();
                    const waitSec = errData.retry_after || 10;
                    showAlert(errData.error || `Đọc mail quá nhanh, chờ ${waitSec}s`, 'info', waitSec * 1000);
                    
                    // Tạm dừng auto-refresh nếu bị rate limit
                    if (autoRefreshInterval) {
                        clearInterval(autoRefreshInterval);
                        setTimeout(() => {
                            if (currentEmail && currentEmail.address === address) {
                                startAutoRefresh();
                            }
                        }, waitSec * 1000);
                    }
                    return;
                }
                
                const data = await response.json();
                
                // 5. Final guard before writing to shared state
                if (version !== inboxRequestVersion) return;
                
                if (data.success) {
                    currentPayload = data.payload;
                    messages = data.messages || [];
                    displayInbox(messages);
                    updateStats(messages.length);
                } else {
                    showAlert(data.error || 'Failed to fetch inbox', 'error');
                }
            } catch (error) {
                if (error.name !== 'AbortError' && version === inboxRequestVersion) {
                    console.error('Fetch inbox error:', error);
                }
            } finally {
                if (version === inboxRequestVersion) {
                    isLoadingInbox = false;
                    setLoading(refreshBtn, false);
                    currentAbortController = null;
                }
            }
        }

        // Load Email History
        async function loadEmailHistory() {
            try {
                const response = await fetch('/api/emails');
                const data = await response.json();
                
                if (data.success) {
                    emailHistory = data.emails || [];
                    emailLimit = data.limit || 10;
                    renderEmailHistory(emailHistory, data.count, emailLimit);
                    updateLimitBar(data.used, emailLimit);
                }
            } catch (error) {
                console.error('Load email history error:', error);
            }
        }

        // Render Email History Table
        function renderEmailHistory(emails, count, limit) {
            if (!emails || emails.length === 0) {
                historyContainer.innerHTML = `
                    <div class="history-empty">
                        <div class="history-empty-icon">📋</div>
                        <p>No emails created yet</p>
                        <p style="font-size: 14px; margin-top: 8px;">Click "Generate Email" to create your first email</p>
                    </div>
                `;
                return;
            }

            const rows = emails.map((email, index) => {
                const isActive = currentEmail && currentEmail.address === email.address;
                const msgCount = email.message_count || 0;
                const createdTime = new Date(email.created_at).toLocaleString();
                const shortAddr = email.address.length > 35 ? email.address.substring(0, 35) + '...' : email.address;
                
                return `
                    <tr class="${isActive ? 'active' : ''}" onclick="selectEmail('${escapeHtml(email.address)}')">
                        <td>${index + 1}</td>
                        <td class="email-addr" title="${escapeHtml(email.address)}">${escapeHtml(shortAddr)}</td>
                        <td>${createdTime}</td>
                        <td><span class="msg-count ${msgCount > 0 ? 'has-messages' : ''}">${msgCount}</span></td>
                        <td>
                            <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="event.stopPropagation(); selectEmail('${escapeHtml(email.address)}')">
                                📨 View
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');

            historyContainer.innerHTML = `
                <table class="email-history-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Email Address</th>
                            <th>Created</th>
                            <th>Messages</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            `;
            
            historyCount.textContent = `${count}/${limit}`;
        }

        // Update Limit Bar
        function updateLimitBar(count, limit) {
            const pct = Math.min((count / limit) * 100, 100);
            limitBarFill.style.width = pct + '%';
            limitText.textContent = `${count}/${limit}`;
            
            limitBarFill.classList.remove('warning', 'full');
            if (count >= limit) {
                limitBarFill.classList.add('full');
                generateBtn.disabled = true;
                generateBtn.querySelector('span').textContent = 'Limit Reached';
            } else if (count >= limit - 2) {
                limitBarFill.classList.add('warning');
                generateBtn.disabled = false;
                generateBtn.querySelector('span').textContent = `Generate Email (${limit - count} left)`;
            } else {
                generateBtn.disabled = false;
                generateBtn.querySelector('span').textContent = 'Generate Email';
            }
        }

        // Select Email from History (with debounce)
        function selectEmail(address) {
            if (selectEmailTimeout) clearTimeout(selectEmailTimeout);
            selectEmailTimeout = setTimeout(() => _selectEmail(address), 150);
        }
        
        async function _selectEmail(address) {
            const emailData = emailHistory.find(e => e.address === address);
            if (!emailData) return;
            
            currentEmail = emailData;
            displayEmail(address);
            copyBtn.disabled = false;
            refreshBtn.disabled = false;
            
            // Update active row (fire-and-forget)
            loadEmailHistory();
            
            // Use unified fetcher
            fetchInboxForAddress(address);
        }

        // Display Email
        function displayEmail(email) {
            emailDisplay.innerHTML = `<span class="email-text">${email}</span>`;
        }

        // Display Inbox
        function displayInbox(messages) {
            if (!messages || messages.length === 0) {
                inboxContainer.innerHTML = `
                    <div class="inbox-empty">
                        <div class="inbox-empty-icon">📭</div>
                        <p>No messages yet</p>
                        <p style="font-size: 14px; margin-top: 8px;">Waiting for emails...</p>
                    </div>
                `;
                return;
            }

            const html = `
                <div class="message-list">
                    ${messages.map(msg => `
                        <div class="message-item" onclick="viewMessage('${msg.mid}')">
                            <div class="message-header">
                                <div class="message-subject">${escapeHtml(msg.subject || 'No Subject')}</div>
                                <div class="message-date">${escapeHtml(msg.date || '')}</div>
                            </div>
                            <div class="message-from">From: ${escapeHtml(msg.sender || 'Unknown')}</div>
                            <div class="message-snippet">${escapeHtml(msg.snippet || '')}</div>
                        </div>
                    `).join('')}
                </div>
            `;
            
            inboxContainer.innerHTML = html;
        }

        // View Message Detail
        async function viewMessage(mid) {
            if (!currentPayload) return;
            
            messageModal.classList.add('active');
            modalBody.innerHTML = '<div style="text-align: center; padding: 40px;"><div class="loading"></div></div>';
            
            try {
                const response = await fetch(`/api/message/${mid}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payload: currentPayload })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    displayMessageDetail(data.message);
                } else {
                    modalBody.innerHTML = `<div class="alert alert-error">${data.error}</div>`;
                }
            } catch (error) {
                modalBody.innerHTML = `<div class="alert alert-error">Failed to load message</div>`;
            }
        }

        // Display Message Detail
        function displayMessageDetail(message) {
            const body = message.body_html || message.body_text || 'No content';
            
            modalBody.innerHTML = `
                <div class="message-detail-meta">
                    <div class="meta-item">
                        <span class="meta-label">From:</span>
                        <span>${escapeHtml(message.sender)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">To:</span>
                        <span>${escapeHtml(message.to)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Subject:</span>
                        <span>${escapeHtml(message.subject)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Date:</span>
                        <span>${escapeHtml(message.date)}</span>
                    </div>
                </div>
                <div class="message-body">
                    ${message.body_html ? 
                        `<iframe srcdoc="${escapeHtml(body)}"></iframe>` : 
                        `<pre style="white-space: pre-wrap; font-family: inherit;">${escapeHtml(body)}</pre>`
                    }
                </div>
            `;
        }

        // Close Modal
        function closeModal() {
            messageModal.classList.remove('active');
        }

        // Click outside modal to close
        messageModal.addEventListener('click', (e) => {
            if (e.target === messageModal) {
                closeModal();
            }
        });

        // Auto-refresh
        function startAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
            }
            
            refreshIndicator.style.display = 'flex';
            
            autoRefreshInterval = setInterval(() => {
                if (currentEmail && !isLoadingInbox) {
                    // messagesOnly=true: chỉ gọi Sonjj, không gọi lại SmailPro
                    fetchInboxForAddress(currentEmail.address, true);
                }
            }, 10000); // Refresh every 10s
        }

        function stopAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }
            if (refreshCooldownTimer) {
                clearInterval(refreshCooldownTimer);
                refreshCooldownTimer = null;
                refreshBtn.disabled = false;
            }
            refreshIndicator.style.display = 'none';
        }

        // Update Stats
        function updateStats(count) {
            messageCount.textContent = count;
            statMessages.textContent = `${count} message${count !== 1 ? 's' : ''}`;
        }

        // Show Alert
        function showAlert(message, type = 'info', duration = 5000) {
            const alert = document.createElement('div');
            alert.className = `alert alert-${type}`;
            alert.innerHTML = `
                <span>${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span>
                <span>${message}</span>
            `;
            
            alertContainer.appendChild(alert);
            
            setTimeout(() => {
                alert.remove();
            }, duration);
        }

        // Set Loading State
        function setLoading(button, loading) {
            if (loading) {
                button.disabled = true;
                const span = button.querySelector('span');
                if (span) {
                    span.dataset.originalText = span.textContent;
                    span.innerHTML = '<span class="loading"></span>';
                }
            } else {
                // Không re-enable nếu đang trong cooldown (refreshCooldownTimer active)
                if (button === refreshBtn && refreshCooldownTimer) {
                    // Giữ disabled, không restore text (cooldown timer đang quản lý)
                    return;
                }
                button.disabled = false;
                const span = button.querySelector('span');
                if (span && span.dataset.originalText) {
                    span.textContent = span.dataset.originalText;
                }
            }
        }

        // Escape HTML
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {
            stopAutoRefresh();
            if (refreshCooldownTimer) {
                clearInterval(refreshCooldownTimer);
                refreshCooldownTimer = null;
            }
        });

        // Load email history on page load
        loadEmailHistory();

        // Toggle Cookie Fields
        function toggleCookieFields() {
            const fields = document.getElementById('cookie-fields');
            const icon = document.getElementById('cookie-toggle-icon');
            fields.classList.toggle('expanded');
            icon.textContent = fields.classList.contains('expanded') ? '▲' : '▼';
        }

        // Save Cookies to backend
        async function saveCookies() {
            const xsrfToken = document.getElementById('xsrf-token-input').value.trim();
            const sonjjSession = document.getElementById('sonjj-session-input').value.trim();
            
            if (!xsrfToken && !sonjjSession) {
                showAlert('Please enter at least one cookie value', 'error');
                return;
            }
            
            try {
                const response = await fetch('/api/cookies', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        xsrf_token: xsrfToken,
                        sonjj_session: sonjjSession
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showAlert('Cookies saved successfully!', 'success');
                } else {
                    showAlert(data.error || 'Failed to save cookies', 'error');
                }
            } catch (error) {
                showAlert('Network error: ' + error.message, 'error');
            }
        }
    </script>
</body>
</html>
'''


# ════════════════════════════════════════════════════════════════════
#                           MAIN
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 TEMPMAIL PRO - Starting server...")
    print("=" * 60)
    print(f"📡 Server: http://{Config.HOST}:{Config.PORT}")
    print(f"🔧 Debug: {Config.DEBUG}")
    print(f"🌐 Proxies: {len(Config.PROXIES)} configured")
    print("=" * 60)
    
    # Disable SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Run Flask app
    # use_reloader=False để tránh SystemExit:3 khi chạy qua VS Code debugger
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        threaded=True,
        use_reloader=False
    )