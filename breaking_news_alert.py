#!/usr/bin/env python3
"""
속보 한줄 알림 -> 텔레그램 전송

기존 fetch_and_send_free.py의 RSS_FEEDS를 재사용해서,
"속보"급 키워드가 제목에 있는 새 헤드라인만 요약/번역 없이
한 줄로 즉시 전송합니다.

이미 보낸 헤드라인은 seen_ids.json에 기록해서 중복 전송을 막습니다.
(이 파일은 워크플로우에서 커밋되어 다음 실행 때도 유지돼야 합니다)

필요한 환경변수 (GitHub Actions Secrets):
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
"""

import os
import sys
import json
import hashlib
from pathlib import Path

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SEEN_FILE = Path(__file__).parent / "seen_breaking_ids.json"
MAX_SEEN_KEEP = 500  # 파일이 무한정 커지지 않도록 최근 N개만 유지

# 기존 fetch_and_send_free.py의 피드 목록 재사용
try:
    from fetch_and_send_free import RSS_FEEDS
except ImportError:
    print("[WARN] fetch_and_send_free.py를 찾지 못해 RSS_FEEDS를 자체 정의합니다.", file=sys.stderr)
    RSS_FEEDS = []

# 속보로 판단할 키워드 (제목에 하나라도 포함되면 속보로 간주)
BREAKING_KEYWORDS = [
    "속보", "긴급", "단독",
    "breaking", "urgent", "just in", "alert",
]

MAX_ITEMS_PER_FEED = 15


# ---------------------------------------------------------
# 1. 이미 보낸 헤드라인 기록 관리
# ---------------------------------------------------------

def load_seen_ids():
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except Exception as e:
        print(f"[WARN] seen_ids 로드 실패: {e}", file=sys.stderr)
        return set()


def save_seen_ids(seen_ids):
    trimmed = list(seen_ids)[-MAX_SEEN_KEEP:]
    SEEN_FILE.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")


def make_id(title: str, link: str) -> str:
    return hashlib.sha256(f"{title}|{link}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------
# 2. RSS 수집 + 속보 필터링
# ---------------------------------------------------------

def fetch_breaking_items():
    seen_ids = load_seen_ids()
    new_breaking = []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"[WARN] RSS 파싱 실패: {url} ({e})", file=sys.stderr)
            continue

        for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            if not title or not link:
                continue

            title_lower = title.lower()
            is_breaking = any(kw.lower() in title_lower for kw in BREAKING_KEYWORDS)
            if not is_breaking:
                continue

            item_id = make_id(title, link)
            if item_id in seen_ids:
                continue

            new_breaking.append({"title": title, "link": link, "id": item_id})
            seen_ids.add(item_id)

    print(f"[INFO] 새 속보 헤드라인: {len(new_breaking)}건")
    save_seen_ids(seen_ids)
    return new_breaking


# ---------------------------------------------------------
# 3. 텔레그램 전송 (한 줄씩 개별 전송)
# ---------------------------------------------------------

def send_to_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code != 200:
        print(f"[ERROR] 텔레그램 전송 실패: {r.status_code} {r.text}", file=sys.stderr)
        r.raise_for_status()


def main():
    if not RSS_FEEDS:
        print("[ERROR] RSS_FEEDS가 비어 있습니다. fetch_and_send_free.py 확인 필요.", file=sys.stderr)
        return

    items = fetch_breaking_items()

    if not items:
        print("[INFO] 새 속보 없음, 전송하지 않음.")
        return

    for it in items:
        text = f"🚨 [속보] {it['title']}\n🔗 {it['link']}"
        print(f"[전송] {text}")
        send_to_telegram(text)


if __name__ == "__main__":
    main()
