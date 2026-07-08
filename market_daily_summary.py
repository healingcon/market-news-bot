#!/usr/bin/env python3
"""
오늘의 종합 시황 리포트 -> 텔레그램 전송

포함 내용:
1. 코스피/코스닥 지수 등락 (네이버 realtime API)
2. 상승/하락 TOP5 (코스피+코스닥)
3. 거래대금 TOP5
4. 증시 뉴스 헤드라인 (기존 fetch_and_send_free.py 로직 재사용)

필요한 환경변수 (GitHub Actions Secrets):
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

TOP_N = 5


# ---------------------------------------------------------
# 1. 코스피/코스닥 지수
# ---------------------------------------------------------

def fetch_index_summary():
    url = "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ"
    lines = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"[DEBUG] 지수 API status={r.status_code}")
        data = r.json()
        print(f"[DEBUG] 지수 API 원본 일부: {json.dumps(data, ensure_ascii=False)[:500]}")

        items = data.get("datas") if isinstance(data, dict) else None
        if not items:
            raise ValueError("datas 키를 찾지 못함")

        for item in items:
            name = item.get("itemCode") or item.get("cd") or "지수"
            close = item.get("closePrice") or item.get("nv")
            change = item.get("compareToPreviousClosePrice") or item.get("cv")
            rate = item.get("fluctuationsRatio") or item.get("cr")
            sign_info = item.get("compareToPreviousPrice") or {}
            sign_text = sign_info.get("text", "") if isinstance(sign_info, dict) else ""
            direction = "🔺" if "상승" in sign_text else "🔻" if "하락" in sign_text else "➖"
            lines.append(f"{name}: {close} {direction} {change} ({rate}%)")

    except Exception as e:
        print(f"[WARN] 지수 데이터 가져오기 실패: {e}", file=sys.stderr)
        lines.append("지수 데이터를 가져오지 못했습니다. (API 구조 확인 필요)")

    return "\n".join(lines)


# ---------------------------------------------------------
# 2. 상승/하락/거래대금 TOP (네이버 sise 페이지 공통 파서)
# ---------------------------------------------------------

def fetch_sise_table(path: str, sosok: int, top_n: int = TOP_N):
    """
    path 예: 'sise_rise', 'sise_fall', 'sise_quant'
    sosok: 0=코스피, 1=코스닥
    """
    url = f"https://finance.naver.com/sise/{path}.naver?sosok={sosok}"
    rows_out = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table.type_2")
        if table is None:
            raise RuntimeError("테이블을 찾지 못했습니다. (페이지 구조 확인 필요)")

        trs = table.select("tr")
        for tr in trs:
            name_tag = tr.select_one("a.tltle")
            if not name_tag:
                continue
            name = name_tag.get_text(strip=True)
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            rows_out.append({"name": name, "raw_tds": tds})
            if len(rows_out) >= top_n:
                break

        if rows_out:
            print(f"[DEBUG] {path} sosok={sosok} 첫 행 예시: {rows_out[0]}")
        else:
            print(f"[DEBUG] {path} sosok={sosok} 데이터 없음")

    except Exception as e:
        print(f"[WARN] {path} sosok={sosok} 실패: {e}", file=sys.stderr)

    return rows_out


def format_sise_rows(rows_out):
    if not rows_out:
        return "데이터를 가져오지 못했습니다. (페이지 구조 확인 필요)"

    lines = []
    for i, row in enumerate(rows_out, 1):
        tds = row["raw_tds"]
        # 일반적인 열 순서: [종목명, 현재가, 전일비, 등락률, 거래량, ...]
        extra = " | ".join(tds[:4]) if tds else ""
        lines.append(f"{i}. {row['name']} - {extra}")
    return "\n".join(lines)


# ---------------------------------------------------------
# 3. 뉴스 헤드라인 (기존 free 파이프라인 재사용)
# ---------------------------------------------------------

def fetch_news_section():
    try:
        from fetch_and_send_free import fetch_headlines, filter_market_moving
        items = filter_market_moving(fetch_headlines())
        if not items:
            return "오늘은 조건에 맞는 뉴스가 없습니다."
        lines = [f"{i}. {it['title']}" for i, it in enumerate(items[:5], 1)]
        return "\n".join(lines)
    except Exception as e:
        print(f"[WARN] 뉴스 섹션 가져오기 실패: {e}", file=sys.stderr)
        return "뉴스 데이터를 가져오지 못했습니다. (fetch_and_send_free.py 확인 필요)"


# ---------------------------------------------------------
# 4. 메시지 조립 & 전송
# ---------------------------------------------------------

def build_message():
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    header = f"📋 {now_str} 오늘의 시황 종합 리포트\n\n"

    sections = []

    sections.append("📊 [지수]\n" + fetch_index_summary())

    for market_name, sosok in (("코스피", 0), ("코스닥", 1)):
        rise = format_sise_rows(fetch_sise_table("sise_rise", sosok))
        fall = format_sise_rows(fetch_sise_table("sise_fall", sosok))
        sections.append(f"🔺 [{market_name} 상승 TOP{TOP_N}]\n{rise}")
        sections.append(f"🔻 [{market_name} 하락 TOP{TOP_N}]\n{fall}")

    quant_kospi = format_sise_rows(fetch_sise_table("sise_quant", 0))
    quant_kosdaq = format_sise_rows(fetch_sise_table("sise_quant", 1))
    sections.append(f"💰 [코스피 거래대금 TOP{TOP_N}]\n{quant_kospi}")
    sections.append(f"💰 [코스닥 거래대금 TOP{TOP_N}]\n{quant_kosdaq}")

    sections.append("📰 [증시 뉴스]\n" + fetch_news_section())

    return header + "\n\n".join(sections)


def send_to_telegram(text: str):
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
    message = build_message()

    print("----- 전송할 메시지 -----")
    print(message)
    print("-------------------------")

    send_to_telegram(message)


if __name__ == "__main__":
    main()
