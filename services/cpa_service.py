# services/cpa_service.py
from typing import List, Dict
import os


class CPAService:
    """Service quản lý CPA offers"""

    def __init__(self):
        self.cpagrip_user_id = os.getenv("CPAGRIP_USER_ID", "")

    def get_offers(self, user_geo: str = "US") -> List[Dict]:
        """Lấy danh sách offers phù hợp với GEO"""

        all_offers = [
            {
                "id": "dating_us",
                "title": "🌹 Dating App Signup",
                "description": "Đăng ký app hẹn hò, nhận 5 tokens",
                "reward": 5,
                "payout": 2.50,
                "geo": ["US", "UK", "CA"],
                "link": f"https://cpagrip.com/show.php?l=0&u={self.cpagrip_user_id}&id=12345&subid={{user_id}}",
            },
            {
                "id": "game_install",
                "title": "🎮 Install Game",
                "description": "Cài game, chơi 2 phút, nhận 3 tokens",
                "reward": 3,
                "payout": 1.20,
                "geo": ["US", "UK", "CA", "VN"],
                "link": f"https://cpagrip.com/show.php?l=0&u={self.cpagrip_user_id}&id=67890&subid={{user_id}}",
            },
            {
                "id": "survey_vn",
                "title": "📋 Khảo sát 5 phút",
                "description": "Trả lời khảo sát, nhận 2 tokens",
                "reward": 2,
                "payout": 0.40,
                "geo": ["VN"],
                "link": f"https://cpagrip.com/show.php?l=0&u={self.cpagrip_user_id}&id=11111&subid={{user_id}}",
            },
        ]

        filtered = [
            o for o in all_offers
            if user_geo in o["geo"] or "ALL" in o["geo"]
        ]
        return filtered

    def format_offer_link(self, offer: Dict, user_id: int) -> str:
        """Format offer link với user tracking"""
        return offer["link"].replace("{user_id}", str(user_id))


# Global instance
cpa_service = CPAService()
