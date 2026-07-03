#!/usr/bin/env python3
"""
증시 영향 뉴스 자동 수집 -> 키워드 필터링 -> 텔레그램 전송 (완전 무료 버전)

Claude API를 쓰지 않고, 제목에 특정 키워드가 포함된 기사만
규칙 기반으로 골라서 텔레그램으로 전송합니다.
번역 없이 원문(영어/한글) 헤드라인 그대로 보냅니다.

필요한 환경변수 (GitHub Actions Secrets):
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
"""

import os
import sys
import time
from datetime import datetime, timezone

import feedparser
import requests
from deep_translator import GoogleTranslator

# ---------------------------------------------------------
# 설정
# ---------------------------------------------------------

RSS_FEEDS = [
    # 해외(미국) 증시
    "https://finance.yahoo.com/news/rssindex",
    "https://finance.yahoo.com/rss/topstories",
    "https://kr.investing.com/rss/news_25.rss",
    "https://kr.investing.com/rss/stock_Stock.rss",
    # 국내 증시
    "https://www.hankyung.com/feed/finance",       # 한국경제 증권
    "http://news.mk.co.kr/rss/stock.xml",          # 매일경제 증권
]

MAX_ITEMS_PER_FEED = 20
MAX_HEADLINES_TO_SEND = 12

# 증시에 영향 줄만한 기사를 판별하는 키워드 (필요에 따라 추가/수정하세요)
KEYWORDS = [
    # 거시경제
    "fed", "federal reserve", "interest rate", "rate cut", "rate hike",
    "inflation", "cpi", "jobs report", "unemployment", "gdp", "recession",
    "금리", "연준", "인플레이션", "고용지표", "경기침체",
    # 시장/지수
    "s&p", "nasdaq", "dow jones", "stock market", "wall street",
    "코스피", "코스닥", "증시",
    # 기업 이슈
    "earnings", "guidance", "layoff", "ipo", "merger", "acquisition",
    "bankruptcy", "lawsuit", "sec ", "antitrust",
    "실적", "인수", "합병", "상장",
    # 원자재/에너지
    "oil price", "crude oil", "opec", "gold price",
    "유가", "원유",
    # 지정학/정책
    "tariff", "trade war", "sanctions", "war", "conflict",
    "관세", "무역", "제재",
    # 반도체/AI (사용자 관심사 반영)
    "nvidia", "semiconductor", "chip", "ai stock",
    "반도체", "엔비디아",
    # 크립토 (사용자 관심사 반영)
    "bitcoin", "crypto", "btc",
    "비트코인", "암호화폐",
    # 국내 증시 특화
    "삼성전자", "SK하이닉스", "코스피200", "외국인 순매수", "외국인 순매도",
    "기관 매수", "공매도", "상한가", "하한가", "신저가", "신고가",
    "금융위", "금감원", "배당", "자사주",
]

ANTHROPIC_UNUSED = None  # AI 미사용 버전 표시용

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ---------------------------------------------------------
# 1. RSS 수집
# ---------------------------------------------------------

def fetch_headlines():
    items = []
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
            items.append({"title": title, "link": link})

    seen = set()
    unique_items = []
    for it in items:
        key = it["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(it)

    print(f"[INFO] 수집된 헤드라인: {len(unique_items)}건")
    return unique_items


# ---------------------------------------------------------
# 2. 키워드 기반 필터링 (AI 없음, 비용 0원)
# ---------------------------------------------------------

def translate_title(title):
    """헤드라인만 한글로 번역 (무료, 비공식 구글 번역 엔드포인트 사용)"""
    try:
        translated = GoogleTranslator(source="auto", target="ko").translate(title)
        return translated if translated else title
    except Exception as e:
        print(f"[WARN] 번역 실패, 원문 사용: {title} ({e})", file=sys.stderr)
        return title


def filter_market_moving(items):
    filtered = []
    for it in items:
        title_lower = it["title"].lower()
        if any(kw.lower() in title_lower for kw in KEYWORDS):
            filtered.append(it)

    print(f"[INFO] 키워드 매칭된 헤드라인: {len(filtered)}건")
    return filtered[:MAX_HEADLINES_TO_SEND]


# ---------------------------------------------------------
# 3. 텔레그램 전송
# ---------------------------------------------------------

def build_message(items):
    today_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    header = f"📈 {today_str} 증시 영향 헤드라인 (키워드 필터)\n\n"

    if not items:
        return header + "오늘은 조건에 맞는 뉴스가 없습니다."

    lines = []
    for i, it in enumerate(items, 1):
        ko_title = translate_title(it["title"])
        lines.append(f"{i}. {ko_title}\n   (원문: {it['title']})\n🔗 {it['link']}")

    return header + "\n\n".join(lines)


def send_to_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 3800
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [text]

    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            print(f"[ERROR] 텔레그램 전송 실패: {r.status_code} {r.text}", file=sys.stderr)
            r.raise_for_status()
        time.sleep(0.5)

    print("[INFO] 텔레그램 전송 완료")


# ---------------------------------------------------------
# 메인
# ---------------------------------------------------------

def main():
    items = fetch_headlines()
    filtered = filter_market_moving(items)
    message = build_message(filtered)

    print("----- 전송할 메시지 -----")
    print(message)
    print("-------------------------")

    send_to_telegram(message)


if __name__ == "__main__":
    main()
