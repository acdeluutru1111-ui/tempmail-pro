# services/email_service.py
"""
Email service wrapping existing SmailPro + Worker logic.
Reuses the same API flow from the original app.py.
"""

import os
import re
import time
import urllib.parse
import urllib3
import requests
from typing import Tuple, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
#                        SMAILPRO CLIENT
# ════════════════════════════════════════════════════════════════════

class SmailProClient:
    """Client tương tác trực tiếp với SmailPro"""

    SMAILPRO_BASE = "https://smailpro.com"
    SMAILPRO_CREATE = f"{SMAILPRO_BASE}/app/create"
    SMAILPRO_INBOX = f"{SMAILPRO_BASE}/app/inbox"
    SONJJ_BASE = "https://api.sonjj.com"
    SONJJ_INBOX = f"{SONJJ_BASE}/v1/temp_gmail/inbox"
    SONJJ_MESSAGE = f"{SONJJ_BASE}/v1/temp_gmail/message"

    COOKIES = {
        "XSRF-TOKEN": os.getenv(
            "XSRF_TOKEN",
            "eyJpdiI6Ikk3TC9aMXZvUEJMVDFwVkxhSDJxd2c9PSIsInZhbHVlIjoiSEFtZnBPYjZwMmhBWkszZnpGenpIcXRMUWFHdGZkbE5FS09SWW8zc2lldVpPMmM4SzcwUWRJVVAwQ0crNldhK1NMYmoxQTNranNIQlJYKytBRzRHaGYrNWtpUEptelZUS0VGL2lrc0tpOWFCVTJSUkduSERiczJoMUdCOXRRYnYiLCJtYWMiOiI4YzM1MDRkMDZlNGFlMDA0MGI2N2E4NmJjZDZkZDgyNmViZDJjM2RmNjlhMThlZDZjZmE5YzdhZWQyMzYyYWQ1IiwidGFnIjoiIn0%3D"
        ),
        "sonjj_session": os.getenv(
            "SONJJ_SESSION",
            "eyJpdiI6ImMzT0tqMkswYzA0UkdPSVg3UllRdkE9PSIsInZhbHVlIjoieDkrRUVKUGg0RXJXWjMyZlptMm1sdjVlY1V2cmdqYVVJZjRIZkZTZktDeWVNbDRRNFQyUUNua0MvMnhiUnp6QzF5Yy9WcTFpVGIzenh1azNzT1kwT2NnU2Jrb2pxc1NzRnNaYldabXJXcDlzNGNUbDIyWlRxK0RiRHB1YWp3dW8iLCJtYWMiOiIxMDQ3NTU0YTkwZmFlZjNlYjBhMjY3MDc4MzhiYzU2NDM0NmRhZTcyNjFjNTk3ODdhMWNkMzc1MWQ4NGI1YTlhIiwidGFnIjoiIn0%3D"
        ),
    }

    def __init__(self):
        self.cookies = dict(self.COOKIES)

    def _get_headers(self) -> dict:
        return {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "referer": f"{self.SMAILPRO_BASE}/temporary-email",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

    def create_email(self, username: str = "random") -> TempEmail:
        params = {
            "username": username,
            "type": "real",
            "domain": "gmail.com",
            "server": "2",
        }
        resp = requests.get(
            self.SMAILPRO_CREATE,
            params=params,
            headers=self._get_headers(),
            cookies=self.cookies,
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()

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

    def get_inbox(self, email: TempEmail) -> Tuple[Optional[str], List[InboxMessage]]:
        body = [{
            "address": email.address,
            "timestamp": int(email.timestamp) if email.timestamp else 0,
            "key": email.key,
        }]
        resp = requests.post(
            self.SMAILPRO_INBOX,
            headers=self._get_headers(),
            json=body,
            cookies=self.cookies,
            timeout=15,
            verify=False,
        )
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

    def _fetch_sonjj_inbox(self, payload: str) -> List[InboxMessage]:
        url = f"{self.SONJJ_INBOX}?payload={urllib.parse.quote(payload, safe='')}"
        try:
            resp = requests.get(
                url,
                headers={"user-agent": "Mozilla/5.0"},
                timeout=10,
                verify=False,
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
        url = f"{self.SONJJ_MESSAGE}?payload={urllib.parse.quote(payload, safe='')}&mid={mid}"
        resp = requests.get(
            url,
            headers={"user-agent": "Mozilla/5.0"},
            timeout=10,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()

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
#                     WORKER CLIENT (IP Rotation)
# ════════════════════════════════════════════════════════════════════

class WorkerClient:
    """Gọi SmailPro qua Cloudflare Worker — IP thay đổi mỗi request"""

    def __init__(self):
        self.worker_url = os.getenv("CLOUDFLARE_WORKER_URL", "").rstrip("/")
        self.api_key = os.getenv("WORKER_API_KEY", "")
        self.session = requests.Session()
        self.session.verify = False

        adapter = HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            pool_block=False,
        )
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
            if hasattr(adapter, 'poolmanager'):
                adapter.poolmanager.clear()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault('timeout', 15)
        kwargs.setdefault('headers', self._headers())
        for attempt in range(2):
            try:
                return self.session.request(method, url, **kwargs)
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
                if attempt == 0:
                    self._clear_pool()
                    time.sleep(0.5)
                    continue
                raise

    def create_email(self, username: str = "random") -> TempEmail:
        resp = self._request("GET", f"{self.worker_url}/create", params={"username": username})
        if resp.status_code == 429:
            raise ValueError("SmailPro rate limit - Worker IP bị block tạm thời")
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
            print(f"[WARN] Sonjj inbox via Worker error: {e}")
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
#                        EMAIL SERVICE
# ════════════════════════════════════════════════════════════════════

class EmailService:
    """Unified email service — auto-detects Worker vs Direct"""

    def __init__(self):
        self._client = None
        self._use_worker = False
        self._init_client()

    def _init_client(self):
        worker_url = os.getenv("CLOUDFLARE_WORKER_URL", "").rstrip("/")
        if worker_url:
            print("🌐 Testing Cloudflare Worker connection...")
            test = WorkerClient()
            try:
                resp = test.session.get(
                    f"{test.worker_url}/",
                    headers={"X-API-Key": test.api_key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    print("✅ Worker connection OK — using IP rotation")
                    self._client = test
                    self._use_worker = True
                    return
                raise Exception(f"Worker returned {resp.status_code}")
            except Exception as e:
                print(f"⚠️ Worker connection failed: {e}")

        print("🔗 Using direct SmailPro connection")
        self._client = SmailProClient()
        self._use_worker = False

    @property
    def client_type(self) -> str:
        return "worker" if self._use_worker else "direct"

    def create_email(self, username: str = "random") -> TempEmail:
        """Tạo email tạm thời"""
        return self._client.create_email(username)

    def get_inbox(self, email: TempEmail) -> Tuple[Optional[str], List[InboxMessage]]:
        """Lấy inbox"""
        return self._client.get_inbox(email)

    def get_message_detail(self, mid: str, payload: str) -> MessageDetail:
        """Lấy chi tiết message"""
        return self._client.get_message_detail(mid, payload)


# Global instance
email_service = EmailService()
