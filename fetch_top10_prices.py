#!/usr/bin/env python3
"""
국내 증시 시가총액 TOP10 실시간 가격 -> 텔레그램 전송

네이버 금융 시가총액 순위 페이지를 스크래핑해서
코스피 시가총액 상위 10개 종목의 현재가/등락률을 텔레그램으로 보냅니다.
API 키 불필요, 완전 무료.

필요한 환경변수 (GitHub Actions Secrets):
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
"""

import os
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

NAVER_MARKET_CAP_URL = "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0"
TOP_N = 20

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------
# 1. 네이버 금융에서 시가총액 TOP N 스크래핑
# ---------------------------------------------------------

def fetch_top_stocks():
    resp = requests.get(NAVER_MARKET_CAP_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "euc-kr"  # 네이버 금융 구 페이지 인코딩

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.select_one("table.type_2")
    if table is None:
        raise RuntimeError("시가총액 테이블을 찾지 못했습니다. 네이버 페이지 구조가 바뀌었을 수 있습니다.")

    rows = table.select("tr")
    results = []

    for row in rows:
        cols = row.select("td")
        if len(cols) < 6:
            continue  # 헤더/광고/빈 행 스킵

        name_tag = row.select_one("a.tltle")
        if not name_tag:
            continue

        name = name_tag.get_text(strip=True)

        # 컬럼 순서: 순위, 종목명(링크), 현재가, 전일비, 등락률, 액면가, 시가총액, ...
        try:
            price = cols[2].get_text(strip=True)
            change = cols[3].get_text(strip=True).replace("\n", "").replace("\t", "")
            change_rate = cols[4].get_text(strip=True)
        except IndexError:
            continue

        # 상승/하락 방향 판단 (클래스명에 up/down 포함 여부)
        change_cell = cols[3]
        direction = ""
        cell_html = str(change_cell)
        if "ico up" in cell_html or "red" in cell_html:
            direction = "🔺"
        elif "ico down" in cell_html or "blue" in cell_html:
            direction = "🔻"

        results.append({
            "name": name,
            "price": price,
            "change": change,
            "change_rate": change_rate,
            "direction": direction,
        })

        if len(results) >= TOP_N:
            break

    print(f"[INFO] 수집된 종목 수: {len(results)}")
    return results


# ---------------------------------------------------------
# 2. 메시지 생성
# ---------------------------------------------------------

def build_message(stocks):
    now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    header = f"📊 {now_str} 국내 시가총액 TOP10 현재가\n\n"

    if not stocks:
        return header + "데이터를 가져오지 못했습니다."

    lines = []
    for i, s in enumerate(stocks, 1):
        lines.append(
            f"{i}. {s['name']}\n"
            f"   {s['price']}원 {s['direction']} {s['change']} ({s['change_rate']})"
        )

    return header + "\n".join(lines)


# ---------------------------------------------------------
# 3. 텔레그램 전송
# ---------------------------------------------------------

def send_to_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
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
    message = build_message(stocks)

    print("----- 전송할 메시지 -----")
    print(message)
    print("-------------------------")

    send_to_telegram(message)


if __name__ == "__main__":
    main()
