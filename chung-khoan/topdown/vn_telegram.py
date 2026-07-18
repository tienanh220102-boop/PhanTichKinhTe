# -*- coding: utf-8 -*-
"""
Gửi tin nhắn Telegram — dùng cho digest báo cáo top-down. Keyless về mặt LLM (không Gemini),
chỉ cần bot token + chat id (secret repo). Tự chunk tin dài >4096 ký tự.

ENV (khớp secret repo PhanTichKinhTe): TELEGRAM_TOKEN, TELEGRAM_CHAT.
"""
from __future__ import annotations

import os
import time
import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

_TG_LIMIT = 4096


def _chunks(text: str, limit: int = _TG_LIMIT) -> List[str]:
    """Cắt text theo ranh giới dòng để không vượt giới hạn Telegram."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        # dòng đơn quá dài (hiếm) — cắt cứng
        while len(line) > limit:
            out.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            out.append(cur); cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def send_message(text: str, token: Optional[str] = None, chat: Optional[str] = None,
                 parse_mode: Optional[str] = None, disable_preview: bool = True) -> bool:
    """Gửi (nhiều phần nếu dài). Trả True nếu tất cả phần gửi được.

    token/chat: mặc định đọc từ env TELEGRAM_TOKEN / TELEGRAM_CHAT.
    parse_mode: None (an toàn nhất, không cần escape) / 'HTML' / 'Markdown'.
    """
    token = token or os.getenv("TELEGRAM_TOKEN")
    chat = chat or os.getenv("TELEGRAM_CHAT")
    if not token or not chat:
        logger.warning("Thiếu TELEGRAM_TOKEN/TELEGRAM_CHAT → bỏ qua gửi Telegram.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for part in _chunks(text):
        payload = {"chat_id": chat, "text": part,
                   "disable_web_page_preview": disable_preview}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code != 200:
                logger.warning("Telegram trả %s: %s", r.status_code, r.text[:200])
                ok = False
        except Exception as e:  # noqa: BLE001
            logger.warning("Gửi Telegram lỗi: %s", e)
            ok = False
        time.sleep(0.5)  # tránh rate-limit khi nhiều phần
    return ok


if __name__ == "__main__":
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(level=logging.INFO)
    msg = "✅ Test gửi Telegram từ vn_telegram.py (nếu bạn thấy tin này là OK)."
    print("Kết quả:", send_message(msg))
