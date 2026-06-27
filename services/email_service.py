# services/email_service.py
"""
Email service — all 3rd-party calls (SmailPro + Sonjj) go through
Cloudflare Worker for IP rotation.  Telegram API calls are direct.
"""

import os
import time
import urllib.parse
import urllib3
import requests
from typing import Tuple, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from requests.adapters import HTTPAdapter

urllib3.disable_warnings()


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


@dataclass
class InboxMessage:
    """Message trong inbox"""
    mid: str
    subject: str = ""
    sender: str = ""
    date: str = ""
    snippet: str = ""


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


# ════════════════════════════════════════════════════════════════════
#                    WORKER CLIENT (IP Rotation)
# ════════════════════════════════════════════════════════════════════

class WorkerClient:
    """All 3rd-party calls (SmailPro + Sonjj) go through Worker for IP rotation."""

    def __init__(self):
        worker_url = os.getenv("CLOUDFLARE_WORKER_URL", "").rstrip("/")
        # Force HTTP — HF Spaces has SSL errors with Cloudflare Workers via HTTPS
        self.worker_url = worker_url.replace("https://", "http://")
        self.api_key = os.getenv("WORKER_API_KEY", "")
        self.session = requests.Session()
        self.session.verify = False

        adapter = HTTPAdapter(pool_connections=2, pool_maxsize=5, pool_block=False)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.session.headers.update({
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "Connection": "close",
        })

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "Connection": "close",
        }

    def _clear_pool(self):
        for prefix in ("https://", "http://"):
            adapter = self.session.get_adapter(prefix)
            if hasattr(adapter, "poolmanager"):
                adapter.poolmanager.clear()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 15)
        kwargs.setdefault("headers", self._headers())
        for attempt in range(2):
            try:
                return self.session.request(method, url, **kwargs)
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
                if attempt == 0:
                    self._clear_pool()
                    time.sleep(0.5)
                    continue
                raise

    # ── SmailPro via Worker ──

    def create_email(self, username: str = "random") -> TempEmail:
        resp = self._request("GET", f"{self.worker_url}/create", params={"username": username})
        if resp.status_code == 429:
            raise ValueError("SmailPro rate limit — Worker IP bị block tạm thời")
        resp.raise_for_status()
        data = resp.json()

        address = (
            data.get("address")
            or data.get("email")
            or (data.get("data") or {}).get("address")
        )
        if not address:
            raise ValueError(f"Cannot extract email from Worker response: {data}")

        return TempEmail(
            address=address,
            timestamp=str(data.get("timestamp", "")),
            key=data.get("key", ""),
        )

    def get_inbox(self, email: TempEmail) -> Tuple[Optional[str], List[InboxMessage]]:
        resp = self._request(
            "POST",
            f"{self.worker_url}/inbox/{urllib.parse.quote(email.address, safe='')}",
            json={"timestamp": email.timestamp, "key": email.key},
        )
        if resp.status_code == 429:
            return None, []
        resp.raise_for_status()
        inbox_resp = resp.json()

        payload = None
        if isinstance(inbox_resp, list) and inbox_resp:
            payload = inbox_resp[0].get("payload")
        elif isinstance(inbox_resp, dict):
            payload = inbox_resp.get("payload")

        if not payload:
            return None, []

        messages = self._fetch_sonjj_inbox(payload)
        return payload, messages

    # ── Sonjj via Worker ──

    def _fetch_sonjj_inbox(self, payload: str) -> List[InboxMessage]:
        try:
            resp = self._request(
                "GET",
                f"{self.worker_url}/sonjj/inbox",
                params={"payload": payload},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[WARN] Sonjj inbox error: {e}")
            return []

        raw = data.get("messages", []) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            return []

        return [
            InboxMessage(
                mid=m.get("mid", ""),
                subject=m.get("textSubject") or m.get("subject", ""),
                sender=m.get("textFrom") or m.get("from", ""),
                date=m.get("date") or m.get("textDate", ""),
                snippet=m.get("snippet") or m.get("textSnippet", ""),
            )
            for m in raw if isinstance(m, dict)
        ]

    def get_message_detail(self, mid: str, payload: str) -> MessageDetail:
        resp = self._request(
            "GET",
            f"{self.worker_url}/sonjj/message",
            params={"payload": payload, "mid": mid},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # Sonjj API returns: {"body": "<html>..."}
        body_html = data.get("body", "")

        return MessageDetail(
            mid=mid,
            body_html=body_html,
            body_text="",
        )


# ════════════════════════════════════════════════════════════════════
#                        EMAIL SERVICE
# ════════════════════════════════════════════════════════════════════

class EmailService:
    """Unified email service — all 3rd-party calls via Worker."""

    def __init__(self):
        self._client = WorkerClient()

    @property
    def client_type(self) -> str:
        return "worker"

    def create_email(self, username: str = "random") -> TempEmail:
        return self._client.create_email(username)

    def get_inbox(self, email: TempEmail) -> Tuple[Optional[str], List[InboxMessage]]:
        return self._client.get_inbox(email)

    def get_message_detail(self, mid: str, payload: str) -> MessageDetail:
        return self._client.get_message_detail(mid, payload)


# Global instance
email_service = EmailService()
