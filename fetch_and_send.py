#!/usr/bin/env python3
"""
증시 영향 뉴스 자동 수집 -> AI 요약(한글) -> 텔레그램 전송

동작 방식:
1. Yahoo Finance / Investing.com RSS 피드에서 최신 뉴스 헤드라인 수집
2. Claude API로 "주식시장에 영향을 줄만한 기사"만 필터링 + 한글 요약
3. 텔레그램 봇으로 정리된 메시지 전송

필요한 환경변수 (GitHub Actions Secrets에 등록):
- ANTHROPIC_API_KEY : Claude API 키
- TELEGRAM_BOT_TOKEN : 기존에 쓰던 텔레그램 봇 토큰
- TELEGRAM_CHAT_ID   : 메시지 받을 채팅방 ID
"""

import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone

import feedparser
import requests

# ---------------------------------------------------------
# 설정
# ---------------------------------------------------------

RSS_FEEDS = [
    # Yahoo Finance
    "https://finance.yahoo.com/news/rssindex",
    "https://finance.yahoo.com/rss/topstories",
    # Investing.com (한국어 경제 뉴스)
    "https://kr.investing.com/rss/news_25.rss",       # 경제 뉴스
    "https://kr.investing.com/rss/stock_Stock.rss",    # 증시 뉴스
]

MAX_ITEMS_PER_FEED = 15
MAX_ARTICLE_AGE_HOURS = 20  # 이 시간보다 오래된 기사는 제외

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"


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
            summary = getattr(entry, "summary", "").strip()
            published = getattr(entry, "published", "") or getattr(entry, "updated", "")

            if not title or not link:
                continue

            items.append({
                "title": title,
                "link": link,
                "summary": summary[:500],  # 너무 길면 잘라냄
                "published": published,
                "source": url,
            })

    # 제목 기준 중복 제거
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
# 2. Claude API로 필터링 + 요약(한글)
# ---------------------------------------------------------

def summarize_with_claude(items):
    if not items:
        return "오늘은 수집된 뉴스가 없습니다."

    # 모델에 넘길 원문 리스트 구성 (제목 + 요약만, 본문 전체 아님)
    articles_text = "\n\n".join(
        f"[{i+1}] 제목: {it['title']}\n요약: {it['summary']}\n링크: {it['link']}"
        for i, it in enumerate(items)
    )

    system_prompt = (
        "너는 한국 투자자를 위한 증시 뉴스 큐레이터야. "
        "아래 영어/한글 뉴스 헤드라인과 요약 목록 중에서, "
        "주식시장(특히 미국 증시, 필요하면 한국 증시 연관)에 실질적으로 영향을 줄 만한 "
        "기사만 골라서 한국어로 정리해줘.\n\n"
        "규칙:\n"
        "- 최대 8개까지만 선정 (중요도 높은 순)\n"
        "- 각 기사는 원문을 그대로 옮기지 말고, 핵심 내용을 한국어로 새로 요약할 것 (2문장 이내)\n"
        "- 왜 증시에 영향을 주는지 한 줄 코멘트 추가\n"
        "- 단순 홍보성, 광고성, 증시와 무관한 기사는 제외\n"
        "- 텔레그램 메시지로 바로 보낼 수 있는 형태로 출력 (마크다운 최소화, 이모지 활용 가능)\n"
        "- 형식:\n"
        "📊 [날짜] 증시 영향 헤드라인\n\n"
        "1. <제목 요약>\n"
        "   → <영향 코멘트>\n"
        "   🔗 <링크>\n\n"
        "(반복)"
    )

    user_prompt = f"오늘 수집된 뉴스 목록:\n\n{articles_text}"

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 2000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    resp = requests.post(CLAUDE_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    result = "\n".join(text_blocks).strip()

    if not result:
        result = "요약 생성에 실패했습니다. (Claude 응답이 비어있음)"

    return result


# ---------------------------------------------------------
# 3. 텔레그램 전송
# ---------------------------------------------------------

def send_to_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # 텔레그램 메시지 길이 제한(4096자) 대응: 필요시 분할 전송
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
    if not ANTHROPIC_API_KEY:
        print("[ERROR] ANTHROPIC_API_KEY 환경변수가 없습니다.", file=sys.stderr)
        sys.exit(1)

    items = fetch_headlines()
    summary_text = summarize_with_claude(items)

    today_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    header = f"📈 {today_str} 미국 증시 영향 헤드라인 요약\n\n"
    final_text = header + summary_text

    print("----- 전송할 메시지 -----")
    print(final_text)
    print("-------------------------")

    send_to_telegram(final_text)


if __name__ == "__main__":
    main()
