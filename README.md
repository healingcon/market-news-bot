# 증시 영향 헤드라인 자동 요약 → 텔레그램 봇

매일 자동으로 Yahoo Finance / Investing.com 뉴스를 수집해서,
주식시장에 영향을 줄 만한 기사만 골라 **한국어로 요약**한 뒤
텔레그램으로 전송하는 GitHub Actions 파이프라인입니다.

---

## 1. 폴더 구조

```
market-news-bot/
├── fetch_and_send.py              # 메인 스크립트
├── requirements.txt
└── .github/
    └── workflows/
        └── daily-market-news.yml  # 매일 자동 실행 설정
```

---

## 2. 설치 방법

### 2-1. GitHub 저장소 만들기
1. GitHub에서 새 저장소 생성 (예: `market-news-bot`, private 추천)
2. 이 폴더 전체를 그대로 push

```bash
cd market-news-bot
git init
git add .
git commit -m "init: 증시 뉴스 자동 요약 봇"
git branch -M main
git remote add origin https://github.com/힐링콘/market-news-bot.git
git push -u origin main
```

### 2-2. GitHub Secrets 등록 (중요!)

저장소 → **Settings → Secrets and variables → Actions → New repository secret**
아래 3개를 등록해주세요.

| Secret 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API 키 (console.anthropic.com에서 발급) |
| `TELEGRAM_BOT_TOKEN` | 기존에 쓰시던 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 메시지를 받을 채팅방/채널 ID |

> `TELEGRAM_CHAT_ID`를 모르시면, 봇에게 아무 메시지나 보낸 뒤
> `https://api.telegram.org/bot<봇토큰>/getUpdates` 를 브라우저로 열어서
> `"chat":{"id": ...}` 값을 확인하시면 됩니다.

### 2-3. 실행 확인

- 저장소 → **Actions** 탭 → `Daily Market News to Telegram` 워크플로우 선택
- **Run workflow** 버튼으로 수동 실행 → 텔레그램으로 메시지 오는지 확인
- 문제없으면 이후 매일 한국시간 오전 8시에 자동 실행됩니다.

---

## 3. 동작 방식 요약

1. `fetch_and_send.py`가 Yahoo Finance / Investing.com RSS에서 최신 헤드라인 수집
2. Claude API에 "주식시장에 영향 줄만한 것만 골라서 한국어로 요약"하도록 요청
   - 원문을 그대로 복사하지 않고, 핵심만 새로 요약 (저작권 안전)
   - 각 기사마다 "왜 증시에 영향을 주는지" 코멘트 포함
3. 텔레그램 봇 API로 메시지 전송 (4096자 초과 시 자동 분할)

---

## 4. 커스터마이징 팁

- **전송 시간 변경**: `daily-market-news.yml`의 `cron: "0 23 * * *"` 수정
  (UTC 기준이므로 KST -9시간 계산 필요)
- **뉴스 소스 추가**: `fetch_and_send.py`의 `RSS_FEEDS` 리스트에 URL 추가
  (예: CNBC RSS `https://www.cnbc.com/id/10001147/device/rss/rss.html`)
- **선정 기준 변경**: `summarize_with_claude()`의 `system_prompt` 문구 수정
  (예: "코인/BTC 관련 기사도 포함해줘" 등 60초브리핑 소재에 맞게 조정 가능)
- **60초브리핑 연동**: 이 요약을 그대로 다음 단계(대본 생성)의 입력으로
  넘기는 두 번째 워크플로우를 이어 붙이면 완전 자동화 파이프라인 구성 가능

---

## 5. 로컬에서 테스트하기

```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY="sk-ant-..."
export TELEGRAM_BOT_TOKEN="123456:ABC-..."
export TELEGRAM_CHAT_ID="123456789"

python fetch_and_send.py
```
