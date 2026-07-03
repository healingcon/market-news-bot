#!/usr/bin/env python3
"""
국내 증시 장 마감 시황 요약 -> 텔레그램 전송 (완전 무료, AI 미사용)

1. 네이버 금융에서 시가총액 TOP20 가격 데이터 수집 -> 상승/하락 상위 종목 추출
2. 국내 증권 RSS(한경/매경 등)에서 키워드 매칭된 오늘자 헤드라인 수집
3. 두 데이터를 합쳐서 "오늘의 마감 시황" 형태로 정리 -> 텔레그램 전송

필요한 환경변수 (GitHub Actions Secrets):
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
"""

import os
import sys
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

NAVER_MARKET_CAP_URL = "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0"
TOP_N = 20
TOP_MOVERS = 5  # 상승/하락 상위 몇 개씩 보여줄지

RSS_FEEDS = [
    "https://www.hankyung.com/feed/finance",       # 한국경제 증권
    "http://news.mk.co.kr/rss/stock.xml",          # 매일경제 증권
    "https://kr.investing.com/rss/news_25.rss",
    "https://kr.investing.com/rss/stock_Stock.rss",
]
MAX_ITEMS_PER_FEED = 20
MAX_HEADLINES_TO_SEND = 8

KEYWORDS = [
    "코스피", "코스닥", "증시", "실적", "인수", "합병", "상장",
    "반도체", "엔비디아", "삼성전자", "SK하이닉스",
    "외국인 순매수", "외국인 순매도", "기관 매수", "공매도",
    "상한가", "하한가", "신저가", "신고가",
    "금융위", "금감원", "배당", "자사주",
    "금리", "연준", "인플레이션", "환율",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------
# 1. 가격 데이터 수집
# ---------------------------------------------------------

def fetch_top_stocks():
    resp = requests.get(NAVER_MARKET_CAP_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "euc-kr"

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.select_one("table.type_2")
    if table is None:
        print("[WARN] 시가총액 테이블을 찾지 못했습니다.", file=sys.stderr)
        return []

    rows = table.select("tr")
    results = []

    for row in rows:
        cols = row.select("td")
        if len(cols) < 6:
            continue

        name_tag = row.select_one("a.tltle")
        if not name_tag:
            continue

        name = name_tag.get_text(strip=True)

        try:
            price = cols[2].get_text(strip=True)
            change = cols[3].get_text(strip=True)
            change_rate_text = cols[4].get_text(strip=True)
        except IndexError:
            continue

        # 등락률 텍스트(예: "+1.23%", "-0.87%")를 숫자로 변환
        rate_num = None
        try:
            cleaned = change_rate_text.replace("%", "").replace("+", "").strip()
            rate_num = float(cleaned)
        except ValueError:
            rate_num = 0.0

        results.append({
            "name": name,
            "price": price,
            "change": change,
            "change_rate": change_rate_text,
            "rate_num": rate_num,
        })

        if len(results) >= TOP_N:
            break

    print(f"[INFO] 수집된 종목 수: {len(results)}")
    return results


# ---------------------------------------------------------
# 2. 뉴스 헤드라인 수집 + 키워드 필터링
# ---------------------------------------------------------

def fetch_filtered_news():
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

    filtered = [
        it for it in unique_items
        if any(kw.lower() in it["title"].lower() for kw in KEYWORDS)
    ]

    print(f"[INFO] 필터링된 뉴스: {len(filtered)}건")
    return filtered[:MAX_HEADLINES_TO_SEND]


# ---------------------------------------------------------
# 3. 메시지 조합
# ---------------------------------------------------------

def build_message(stocks, news_items):
    today_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    lines = [f"📉📈 {today_str} 국내 증시 마감 시황\n"]

    if stocks:
        sorted_by_rate = sorted(stocks, key=lambda s: s["rate_num"], reverse=True)
        gainers = sorted_by_rate[:TOP_MOVERS]
        losers = sorted_by_rate[-TOP_MOVERS:][::-1]

        lines.append("🔺 상승 상위 종목")
        for s in gainers:
            lines.append(f"  {s['name']}  {s['price']}원 ({s['change_rate']})")

        lines.append("\n🔻 하락 상위 종목")
        for s in losers:
            lines.append(f"  {s['name']}  {s['price']}원 ({s['change_rate']})")
    else:
        lines.append("(시가총액 데이터를 가져오지 못했습니다)")

    lines.append("\n📰 오늘의 관련 뉴스")
    if news_items:
        for i, it in enumerate(news_items, 1):
            lines.append(f"  {i}. {it['title']}\n     🔗 {it['link']}")
    else:
        lines.append("  (조건에 맞는 뉴스가 없습니다)")

    return "\n".join(lines)


# ---------------------------------------------------------
# 4. 텔레그램 전송
# ---------------------------------------------------------

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

    print("[INFO] 텔레그램 전송 완료")


# ---------------------------------------------------------
# 메인
# ---------------------------------------------------------

def main():
    stocks = fetch_top_stocks()
    news_items = fetch_filtered_news()
    message = build_message(stocks, news_items)

    print("----- 전송할 메시지 -----")
    print(message)
    print("-------------------------")

    send_to_telegram(message)


if __name__ == "__main__":
    main()
