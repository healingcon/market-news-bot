import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TOP_N = 20  # 시장별로 몇 종목씩 보여줄지

API_URL = "https://finance.daum.net/api/trend/after_hours_spac"

HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "referer": "https://finance.daum.net/domestic/after_hours?market=KOSPI",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
    "x-requested-with": "XMLHttpRequest",
}

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------
# 1. 다음 금융 API 호출
# ---------------------------------------------------------

def fetch_after_hours(market: str, change_type: str, per_page: int = TOP_N):
    """
    market: 'KOSPI' or 'KOSDAQ'
    change_type: 'CHANGE_RISE' (상승) or 'CHANGE_FALL' (하락)
    """
    params = {
        "page": 1,
        "perPage": per_page,
        "fieldName": "changeRate",
        "order": "desc" if change_type == "CHANGE_RISE" else "asc",
        "market": market,
        "type": change_type,
        "pagination": "true",
    }

    r = requests.get(API_URL, headers=HEADERS, params=params, timeout=15)

    print(f"[DEBUG] {market} {change_type} status={r.status_code}")

    if r.status_code != 200:
        print(f"[DEBUG] 응답 본문 일부: {r.text[:300]}")
        return []

    try:
        data = r.json()
    except json.JSONDecodeError:
        print(f"[DEBUG] JSON 파싱 실패. 응답 본문 일부: {r.text[:300]}")
        return []

    # 실제 리스트가 들어있는 키를 유연하게 탐색
    items = None
    if isinstance(data, dict):
        for key in ("data", "list", "items", "rows"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
    elif isinstance(data, list):
        items = data

    if items is None:
        print(f"[DEBUG] 알 수 없는 응답 구조. 최상위 키: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return []

    if items:
        print(f"[DEBUG] 첫 번째 항목 예시: {items[0]}")

    return items


# ---------------------------------------------------------
# 2. 항목 -> 보기 좋은 텍스트로 변환
# ---------------------------------------------------------

def format_item(item: dict) -> str:
    name = item.get("name") or item.get("symbolName") or "종목명 미상"

    price = (
        item.get("tradePrice")
        or item.get("price")
        or item.get("afterMarketPrice")
        or "-"
    )

    change_rate = item.get("changeRate")
    if change_rate is not None:
        change_rate_str = f"{change_rate:+.2f}%" if isinstance(change_rate, (int, float)) else str(change_rate)
    else:
        change_rate_str = "-"

    change = item.get("change")
    change_symbol = item.get("changeSymbol") or item.get("change_price_type") or ""

    direction = "🔺" if "RISE" in str(change_symbol).upper() or (isinstance(change, (int, float)) and change > 0) else \
                "🔻" if "FALL" in str(change_symbol).upper() or (isinstance(change, (int, float)) and change < 0) else "➖"

    price_str = f"{price:,}" if isinstance(price, (int, float)) else str(price)
    change_str = f"{change:+,}" if isinstance(change, (int, float)) else str(change) if change is not None else ""

    return f"{name}\n   {price_str}원 {direction} {change_str} ({change_rate_str})"


def build_message():
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    header = f"🌙 {now_str} 국내 시간외 단일가 TOP{TOP_N}\n\n"

    sections = []
    for market in ("KOSPI", "KOSDAQ"):
        rise_items = fetch_after_hours(market, "CHANGE_RISE")
        fall_items = fetch_after_hours(market, "CHANGE_FALL")

        lines = [f"[{market} 상승 TOP{min(TOP_N, len(rise_items))}]"]
        if rise_items:
            for i, item in enumerate(rise_items, 1):
                lines.append(f"{i}. {format_item(item)}")
        else:
            lines.append("데이터를 가져오지 못했습니다. (페이지 구조 확인 필요)")

        lines.append("")
        lines.append(f"[{market} 하락 TOP{min(TOP_N, len(fall_items))}]")
        if fall_items:
            for i, item in enumerate(fall_items, 1):
                lines.append(f"{i}. {format_item(item)}")
        else:
            lines.append("데이터를 가져오지 못했습니다. (페이지 구조 확인 필요)")

        sections.append("\n".join(lines))

    return header + "\n\n".join(sections)


# ---------------------------------------------------------
# 3. 텔레그램 전송
# ---------------------------------------------------------

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
