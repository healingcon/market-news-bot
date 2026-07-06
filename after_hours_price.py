#!/usr/bin/env python3
"""
국내 증시 시간외 거래(시간외 단일가) 상위 종목 -> 텔레그램 전송

다음(Daum) 금융의 시간외 거래 페이지를 스크래핑합니다.
주의: 이 페이지는 구조가 자주 안 바뀌지만, 100% 검증된 상태는 아니라서
첫 실행 시 로그를 보고 파싱 로직을 조정해야 할 수 있습니다.

필요한 환경변수 (GitHub Actions Secrets):
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
"""

import os
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

DAUM_AFTER_HOURS_URL = "https://finance.daum.net/domestic/after_hours"
TOP_N = 15

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.daum.net/",
}


def fetch_after_hours():
    resp = requests.get(DAUM_AFTER_HOURS_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # 디버깅용: 페이지에 테이블이 있는지, 몇 개 있는지 로그로 남김
    tables = soup.select("table")
    print(f"[DEBUG] 페이지 내 테이블 개수: {len(tables)}", file=sys.stderr)

    rows_data = []
    for table in tables:
        trs = table.select("tr")
        for tr in trs:
            tds = tr.select("td")
            if len(tds) < 4:
                continue
            text_cells = [td.get_text(strip=True) for td in tds]
            # 종목명이 있을 법한 셀(문자 포함, 숫자만은 아닌 셀)을 찾음
            name_candidates = [c for c in text_cells if c and not c.replace(",", "").replace(".", "").replace("%", "").replace("+", "").replace("-", "").isdigit()]
            if name_candidates:
                rows_data.append(text_cells)

    print(f"[DEBUG] 후보 행 개수: {len(rows_data)}", file=sys.stderr)
    if rows_data:
        print(f"[DEBUG] 첫 번째 후보 행 예시: {rows_data[0]}", file=sys.stderr)

    return rows_data[:TOP_N]


def build_message(rows_data):
    now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    header = f"🌙 {now_str} 시간외 거래 현황 (테스트)\n\n"

    if not rows_data:
        return header + "데이터를 가져오지 못했습니다. (페이지 구조 확인 필요)"

    lines = []
    for i, row in enumerate(rows_data, 1):
        lines.append(f"{i}. {' | '.join(row[:5])}")

    return header + "\n".join(lines)


def send_to_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 3800
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [text]

    for chunk in chunks:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            print(f"[ERROR] 텔레그램 전송 실패: {r.status_code} {r.text}", file=sys.stderr)
            r.raise_for_status()

    print("[INFO] 텔레그램 전송 완료")


def main():
    rows_data = fetch_after_hours()
    message = build_message(rows_data)

    print("----- 전송할 메시지 -----")
    print(message)
    print("-------------------------")

    send_to_telegram(message)


if __name__ == "__main__":
    main()
