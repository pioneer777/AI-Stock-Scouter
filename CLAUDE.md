# AI Stock Scouter — CLAUDE.md
> 이 파일은 Claude Code가 자동으로 읽는 프로젝트 컨텍스트 파일입니다.
> 변경사항은 이 파일을 수정하면 즉시 반영됩니다.

---

## 1. 페르소나 및 기본 원칙

- 너는 파이썬 기반 주식 분석 봇 **'AI Stock Scouter'**의 전문 개발자야.
- 사용자 **'태진님'**에게 항상 예의를 갖춰 존댓말로 답변해.
- 복잡한 코드 설명보다 **명확한 결과물**과 **직관적인 UI** 개선에 집중해.
- 최종 목표: 승률 100%에 가까운 퀀트 트레이딩 시그널 시스템 구축.

---

## 2. 프로젝트 개요

- **기능**: 한국/미국 주식 데이터 수집 → 퀀트 지표 분석 → SMA 눌림목 시그널 포착 → 텔레그램 리포트 + GitHub 클라우드 HTML 차트 생성
- **기술 스택**: Python, Pandas, Plotly, yfinance, KIS API, DART API, Telegram Bot API, GitHub Actions
- **대상 종목**: 태진님이 직접 관리하는 종목 리스트 (재무 약한 기업 사전 제외)
- **시장**: 한국(KR) / 미국(US) 분리 운영

---

## 3. 시그널 정의 — SMA 눌림목 시스템

> 핵심 원칙: 주가는 SMA를 중심으로 피보나치처럼 등락한다.
> 주가가 SMA에 가까이 붙었을 때 = 눌림목 매수 기회.
> 시그널 수 제한 없음. 하루 0개도 괜찮고, 진짜 기회만 잡는 것이 목표.

### 종목 유형 구분 (대전제)

```
[횡보주] SMA200 기울기 (60일 전 대비 변화율) ±5% 이내
         → SMA200이 방향 없이 제자리를 맴도는 종목

[우상향주] SMA200 기울기 60일 변화율 +5% 초과
           → SMA200이 꾸준히 우상향 중인 종목

[하락주] SMA200 기울기 60일 변화율 -5% 미만
         → 시그널 탐지 자체 스킵 (하락추세)
```

### 눌림목 유효 범위

```
[SMA 위 눌림] 주가 > SMA, 거리 +3% ~ +15%
  → "위+X%" 표시
  → +15% 초과: 아직 눌림 미도달 (스킵)

[SMA 아래 눌림] 주가 < SMA, 거리 -1% ~ -10%
  → "아래-X%" 표시
  → -10% 초과: 지지선 붕괴 가능 (스킵)

※ +3% 미만 (너무 가까움) 도 스킵 — 이미 올라탄 구간
```

### 4가지 시그널 (근접 SMA 개수 기준)

```
[전선수렴🔴] SMA20 + SMA60 + SMA120 + SMA200 모두 근접
  조건: 주가가 4개 SMA 모두 눌림목 유효 범위 이내
        + 4개 이평선 최대 간격 5% 이내 (전선 수렴)
  의미: 장단기 이평선 전부 수렴 = 역대급 눌림목 / 세력 매집 구간
  색상: #FF3D00 🔴

[SMA20+60+120🟡] SMA20 + SMA60 + SMA120 동시 근접
  조건: 주가가 SMA20, SMA60, SMA120 각각 눌림목 유효 범위 이내
        + 3개 이평선 간격 각각 5% 이내 (3선 수렴)
  의미: 단중장기 이평선 3선 수렴 = 강한 매집 구간
  색상: #FFB300 🟡

[SMA20+60🟢] SMA20 + SMA60 동시 근접
  조건: 주가가 SMA20, SMA60 각각 눌림목 유효 범위 이내
        + SMA20과 SMA60 간격 5% 이내 (수렴 중)
  의미: 단중기 이평선 수렴 = 중기 지지 구간
  색상: #00C853 🟢

[SMA20🔵] SMA20만 근접
  조건: 주가가 SMA20 기준 눌림목 유효 범위 이내
  의미: 단기 이평선 지지/저항 테스트
  색상: #2196F3 🔵
```

### 중복 처리 규칙

```
같은 종목이 여러 시그널에 해당하면 가장 강한 시그널만 표시
우선순위: 전선수렴 > SMA20+60+120 > SMA20+60 > SMA20
```

### 공통 유동성 필터

```
일 평균 거래대금 KR ≥ 50억, US ≥ 100만 달러
→ 미달 시 시그널 탐지 자체 스킵
```

### 시장 국면 필터

```
지수 SMA20 > SMA60 → 강세장: 4가지 시그널 모두 활성
지수 SMA20 < SMA60 → 약세장: 전선수렴 + SMA20+60+120 만 허용 (강한 수렴만)
데이터 부족 → unknown: 모든 시그널 허용 (안전 처리)

중기 약세장(2~3개월 하락)에만 반응.
1~2주 단기 급락은 SMA 크로스 발생 안 하므로 자동 허용.
지수 데이터: fetch_market_index(period="1y")
```

---

## 4. 재무 필터 (자동 검증)

```python
# 재무 필터 — KR: DART 우선 + yfinance 보완 / US: yfinance
PER > 0                    # 흑자 기업 (순손실 기업 제외)         → yfinance
부채비율 < 400%             # 심각한 재무 위험 제외               → DART(KR) / yfinance
매출성장률 > -25%           # 사업 붕괴 수준 매출 급감 제외        → DART(KR) / yfinance
영업이익률 > -30%           # 심각한 적자 구조 제외               → DART(KR) / yfinance
PSR < 50배                 # 매출 대비 극단적 고평가 제외         → yfinance
```

> KR 종목: DART 공식 재무제표 기준으로 부채비율/영업이익률/매출성장률 계산 (정확도 대폭 향상)
> 데이터 없으면 통과 (안전 처리). 탈락 시 로그: `[종목명] 재무 필터 탈락 — PER -3.2 (적자)`

> 업황/미래비전/기업 철학은 태진님이 종목 리스트에 편입할 때 1차로 직접 판단.
> 봇은 숫자로 검증, 사람은 업황으로 검증 — 최강 조합.

---

## 5. 업황 시스템 (sector_outlook.json)

`sector_outlook.json` 파일을 직접 수정하거나 Claude Code에 말로 요청:

```json
{
  "반도체": "negative",
  "LNG/에너지": "positive",
  "방산": "positive",
  "2차전지": "neutral",
  "바이오": "neutral",
  "금융": "positive"
}
```

- `negative` 업황 섹터 종목은 시그널 발생 시 ⚠️ 경고 표시 (제외 아님, 판단은 태진님이)
- Claude Code에서 `"반도체 업황 negative로 업데이트해줘"` 식으로 수정 가능

---

## 6. 승패 추적 시스템

```
시그널 최초 발생일 → 진입가 기록
매일 현재가 비교:
  +수익률 → 승 🟢
  -수익률 → 패 🔴
유효기간: 시그널 발생일로부터 1년
승률 목표: 100% (현실적으로 지속 개선)
```

### 승패 기록 파일 구조
```
signal_history_KR.json
signal_history_US.json

{
  "종목코드": {
    "종목명": "퓨런티어",
    "시그널": "SMA20+60+120",
    "종목유형": "횡보주",
    "SMA위치": "위",
    "선정일": "2026-05-12",
    "진입가": 3200,
    "유효기간만료": "2027-05-12"
  }
}
```

---

## 7. 종목 리스트 구조

> 실제 데이터는 `data/stock_list_KR.json` / `data/stock_list_US.json`에 위치.
> `data/generate_stock_lists.py`를 실행하면 전체 리스트 재생성 가능.

```json
{
  "318020": {
    "종목명": "퓨런티어",
    "시장":   "KOSDAQ",
    "티커":   "318020.KQ",
    "섹터":   "의료기기",
    "카테고리": "스마트폰 카메라 모듈 밸류체인",
    "상장여부": true,
    "언급일": [
      {"날짜": "2025-08-08", "차수": "1차"},
      {"날짜": "2026-04-22", "차수": "2차"}
    ]
  },
  "비상장_달바글로벌": {
    "종목명": "달바글로벌",
    "상장여부": false
  }
}
```

### 중요 규칙
- `상장여부: false` 이거나 코드가 `비상장_`으로 시작하면 **자동으로 분석 제외**
- `언급일`에 `가격` 필드는 없음 — 차트에서는 날짜/차수만 표시
- `티커` 필드가 있으면 yfinance에 직접 사용 (KOSPI: `.KS`, KOSDAQ: `.KQ`)

---

## 8. 외부 API 연동

### KIS API (한국투자증권) — KR 전용
```
용도: 기관/외인 순매수 데이터 (수급)
토큰: APP key + APP secret → Bearer token (23시간 캐시)
per-stock: fetch_stock_supply_demand_kis(code) → 차트 2단 기관/외인 막대
market-wide: fetch_supply_demand_kis(stock_list) → 텔레그램 섹션3 TOP3
fallback: KIS 실패 시 Naver 스크래핑 자동 전환
실패 알림: KIS 토큰 발급 실패 시 텔레그램 섹션3에 ⚠️ 경고 메시지 전송
Secrets: KIS_APP_KEY, KIS_APP_SECRET
```

### DART API (금융감독원 전자공시) — KR 전용
```
용도: 공식 재무제표 기반 재무 필터 (yfinance KR 데이터 대체)
corp_code 매핑: 최초 1회 ZIP 다운로드 → 메모리 캐시 (stock_code → corp_code)
조회 순서: 전년 사업보고서(11011) → 반기(11012), 연결(CFS) → 별도(OFS)
제공 데이터: 부채비율, 영업이익률, 매출성장률 (PER/PSR은 yfinance 유지)
Secrets: DART_API_KEY
```

---

## 9. 차트 스펙 (visualizer.py)

### 전체 레이아웃
```
높이: 1000px (모바일 최적화)
서브플롯 비중: 주가(55%) / 거래량(18%) / 보조지표(27%)
배경: 화이트 테마 (paper=#FFFFFF, plot=#FAFAFA, font=#222222)
테두리: 4면 mirror=True, showline=True, linecolor=#CCCCCC
주말 제거: rangebreaks=[dict(bounds=["sat", "mon"])]
RangeSlider: visible=False (무조건)
데이터 로드 기간: 현재 기준 3년 (레인지 버튼 전 구간 커버용)
기본 표시 범위: 1Y + 우측 5% 여백 (today + 18일)
드래그 이동: 완전 비활성화 (dragmode=False)
핀치 줌: 비활성화 (모바일 오터치 방지)
```

### 차트 탐색 방식 — A안 (레인지 버튼 전용)
```
[탐색 방법] 상단 레인지 버튼만 사용, 드래그/스와이프 없음

레인지 버튼:
  [ 3M ]   [ 6M ]   [ 1Y★ ]   [ 2Y ]   [ 전체 ]
  (3개월)  (6개월) (1년 기본) (2년)   (3년 전체)

기본 선택: 1Y (차트 오픈 시 우측 5% 여백 포함 자동 설정)
버튼 클릭 시: 우측 5%(최대 30일) 여백 자동 추가 (JS post_script)
버튼 스타일: 밝은 회색 배경, 진한 글자

Plotly 설정:
  activecolor="#FFB300" (선택 버튼 골드)
  bgcolor="#F0F0F0"
  div_id="chart" + post_script=_RANGE_PAD_JS (JS 우측 여백)
```

### 크로스헤어 (A안 — Plotly spike)
```
hovermode: "x unified" → 터치/호버 시 해당 날짜 수직선 + OHLC 표시
spikemode: "across" → 모든 패널에 수직선 동시 표시
OHLC hovertemplate: 시가/고가/저가/종가 한국어 표시
```

### 차트 1단 — 주가 (55%)
```
캔들스틱: 상승=빨강(#EF5350), 하락=파랑(#1E88E5)
이동평균선 (중요도 순 굵기):
  SMA200 → 핑크  (#E91E63), 굵기 2.5  ← 1위 (장기 핵심)
  SMA20  → 파랑  (#2196F3), 굵기 2.0  ← 2위
  SMA120 → 초록  (#4CAF50), 굵기 1.5  ← 3위 (SMA60과 동일)
  SMA60  → 주황  (#FF9800), 굵기 1.5  ← 3위

[박스 표기 — 캔들 고점 위 충분한 간격 (캔들 겹침 없음)]
언급일 박스:
  라인1: "1차_4/22"  (또는 2차, 3차...)
  라인2: 해당일 실제 종가 (df에서 조회, 저장된 가격 아님)
  색상: 흰 배경(#FFFFFF) + 진한 테두리(#444444)
  ay=-65 (캔들 위 65px 위치)
  → 언급 차수 모두 표시 (1차부터 존재하는 차수까지)
  → 세로 점선(#BBBBBB dash)으로 날짜 표시

시그널 박스:
  라인1: "전선수렴_5/12"  (SMA20+60+120_ / SMA20+60_ / SMA20_)
  라인2: 진입가 (선정 당일 종가)
  색상: 시그널별 고유 색상 배경 + 흰 글자
  ay=-60 (첫 번째), -115 (두 번째), ... (55px 간격 스택)

TODAY 박스: 검정 배경(#222222) 흰 글씨, ay=-40
  예: "TODAY: 3,660"
```

### 차트 2단 — 거래량 (18%)
```
거래량 막대: 상승=빨강(#EF5350), 하락=파랑(#1E88E5), opacity=1.0 (진하게)
거래량 20일 이평: 검정 점선 (#333333, width=1.2, dash="dot")
거래량 200일 이평: 회색 점선 (#888888, width=1, dash="dot")
기관 순매수: 초록 반투명 막대 rgba(0,180,60,0.55) — KR만
외인 순매수: 주황 반투명 막대 rgba(255,160,0,0.55) — KR만
```

### 차트 3단 — 보조지표 (27%)
```
MACD 히스토그램: 막대 (양수=#4CAF50, 음수=#EF5350)
MACD선: 파랑 실선 (#2196F3, showlegend=True)
시그널선: 주황 실선 (#FF9800, showlegend=True, name="시그널선")
RSI: 진회색 점선 (#555555, secondary_y, showlegend=True)
RSI 70선: #EF5350 점선 (기준선, showlegend=False)
RSI 30선: #1E88E5 점선 (기준선, showlegend=False)
RSI 현재값 박스: xref="x" yref="y4" → 마지막 캔들 우측에 실제 RSI 수준으로 배치
  xanchor="left" (우측 5% 여백 공간 활용)
```

### 범례
```
위치: 최상단 (y=1.07), 가로 배치, 흰 배경 테두리 포함
SMA20, SMA60, SMA120, SMA200 (라인 아이콘)
전선수렴, SMA20+60+120, SMA20+60, SMA20 (정사각형 마커, 더미 트레이스)
MACD, 시그널선, RSI (라인 아이콘)
```

---

## 10. 텔레그램 메시지 포맷 (4섹션)

> 모바일 최적화. 차트는 이미지 전송 아님 → GitHub 하이퍼링크 클릭으로 연결.

```
📊 AI Stock Scouter - KR | 05.12(화) 16:30
━━━━━━━━━━━━━━━━━━━━━

🔥 1. 핵심 시그널
[전선수렴🔴] 삼성전자(횡보·위+5.2%) | 아모레퍼시픽(횡보·아래-3.1%)
[SMA20+60+120🟡] 현대차(우상향·위+8.7%) | SK하이닉스(횡보·위+6.3%)
[SMA20+60🟢] JW생명과학(우상향·위+11.2%) | 클래시스(횡보·아래-4.5%)
[SMA20🔵] 퓨런티어(횡보·위+13.1%) | 파마리서치(우상향·아래-2.8%)

━━━━━━━━━━━━━━━━━━━━━
📊 2. 승패 테이블
종목명       시그널          날짜    진입가   현재가   수익률
퓨런티어     SMA20+60+120   05-01  3,200  3,660  +14.4%✅
클래시스     SMA20+60       04-20  52,000 54,300  +4.4%✅
브이티       SMA20          04-18  18,500 17,900  -3.2%❌
────────────────────
전체 승률: 75% (승9 / 패3) | 보유 15종목

━━━━━━━━━━━━━━━━━━━━━
💧 3. 수급 분석
[기관 순매수 TOP3]
1위 삼성전자   +125억
2위 현대차     +89억
3위 SK하이닉스  +67억

[외인 순매수 TOP3]
1위 POSCO홀딩스 +210억
2위 LG에너지솔루션 +155억
3위 카카오     +92억

━━━━━━━━━━━━━━━━━━━━━
📈 4. 추세 분석  (시그널 발생 종목 제외, 나머지 관심종목 전체)
⚠️ 규칙: 섹션1에 등장한 종목은 당일 섹션4에서 자동 제외. 중복 표시 금지.
상승지속 📈  삼성전자 | JW생명과학 | KSS해운
건강한조정 📉  SK오션플랜트 | 한미글로벌
횡보중 ➡️    아모레퍼시픽 | 코스메카코리아
하락주의 🔻   종목A | 종목B

━━━━━━━━━━━━━━━━━━━━━
🔗 전체 차트: [KR 클라우드 보기](링크)
```

---

## 11. 리포트 구분 (main.py)

```
--report SUMMARY (장중): 시그널 기록 X, 모니터링 전용
--report FULL (장마감):  시그널 JSON 기록 O, 인덱스 HTML 생성 O
```

### 운영 스케줄 (수신 목표 기준)
```
[GitHub Actions 딜레이 30분~2시간 존재 → 크론을 일찍 발사해 흡수]

KR 장전 2H:  KST ~07:00 수신 목표  (크론: UTC 20:30 = KST 05:30 발사)
KR 장 중간:  KST ~12:00 수신 목표  (크론: UTC 01:00 = KST 10:00 발사, 03:00 UTC 피크 회피)
KR 장 종료:  KST ~16:30            (크론: UTC 07:30 발사) RECORD_SIGNALS=true

US 장전 2H:  KST ~20:30 수신 목표  (크론: UTC 10:30 발사, EDT/EST 공통)
US 장 중간:  KST ~01:30 수신 목표  (크론: UTC 15:30 발사, EDT/EST 공통)
US 장 종료:  UTC 22:00 발사         (EDT 18:00 / EST 17:00) RECORD_SIGNALS=true
```
> RECORD_SIGNALS=true 인 실행만 signal_history 저장 + index HTML 생성.
> US는 EDT/EST 단일 크론 통합 (계절별 1시간 드리프트 허용, 중복 메시지 없음).

### 인덱스 파일 분리
```
index_KR.html  ← 한국 시장 전용
index_US.html  ← 미국 시장 전용
```

---

## 12. 파일 구조

```
C:\CLAUDE_Project\ai-stock-scouter\
├── CLAUDE.md                    ← 이 파일 (V3.0 현행)
├── CLAUDE_V2.2_backup.md        ← V2.2 백업 보존
├── main.py                      ← 운영 오케스트레이터
├── data_fetcher.py              ← yfinance + Naver 크롤링 + 지표 계산
├── signal_detector.py           ← SMA 눌림목 시그널 알고리즘 + 추세 분류
├── visualizer.py                ← Plotly 3단 차트 생성
├── reporter.py                  ← 텔레그램 4섹션 메시지 + index HTML
├── sector_outlook.json          ← 업황 수동 입력 (루트에 위치)
├── signal_history_KR.json       ← KR 시그널 승패 기록 (FULL 실행 시 생성)
├── signal_history_US.json       ← US 시그널 승패 기록 (FULL 실행 시 생성)
├── index_KR.html                ← KR 클라우드 인덱스 (FULL 실행 시 생성)
├── index_US.html                ← US 클라우드 인덱스 (FULL 실행 시 생성)
├── requirements.txt
├── data/
│   ├── stock_list_KR.json
│   ├── stock_list_US.json
│   ├── stock_list_INTL.json
│   └── generate_stock_lists.py
├── charts/
│   ├── KR/
│   └── US/
└── .github/
    └── workflows/
        ├── run_kr.yml
        ├── run_us.yml
        └── test.yml
```

---

## 13. GitHub Actions 운영 환경

### GitHub Secrets (반드시 설정)
```
TELEGRAM_BOT_TOKEN   ← KR/US 동일한 토큰 사용 OK
CHAT_ID_KR           ← KR 텔레그램 채팅방 ID
CHAT_ID_US           ← US 텔레그램 채팅방 ID
TEST_CHAT_ID_KR      ← 테스트 모드 KR 채팅방 ID
TEST_CHAT_ID_US      ← 테스트 모드 US 채팅방 ID
PAGES_URL            ← index HTML 링크용 (예: https://username.github.io/ai-stock-scouter)
KIS_APP_KEY          ← 한국투자증권 OpenAPI APP key
KIS_APP_SECRET       ← 한국투자증권 OpenAPI APP secret
DART_API_KEY         ← OpenDART API key
```

### 수동 테스트 모드 (test.yml)
```
GitHub Actions → 🧪 Test Mode → Run workflow
  ├── market:   KR(기본) / US
  ├── report:   FULL(기본) / SUMMARY
  └── dry_run:  true(기본, 텔레그램 전송 안 함) / false
```

### 로컬 직접 실행
```bash
# 테스트 (텔레그램 전송 없이)
DRY_RUN=true python main.py --market KR --report FULL

# 실제 실행
python main.py --market KR --report SUMMARY
python main.py --market US --report FULL
```

---

## 14. 핵심 버그 방지 규칙

```python
# 1970년/2032년 에러 방지 — 반드시 준수
from datetime import datetime, timedelta
end_date = datetime.now()
start_date_data = end_date - timedelta(days=365*3)   # 데이터는 3년치 로드
start_date_view = end_date - timedelta(days=365)     # 기본 표시는 1년
fig.update_xaxes(range=[start_date_view, end_date])

# RangeSlider 무조건 비활성화
fig.update_xaxes(rangeslider_visible=False)

# 주말 빈 공간 제거
fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

# [A안] 드래그/스와이프 완전 비활성화 — 모바일 오터치 방지
fig.update_layout(dragmode=False)

# config 설정도 함께 적용
plotly_config = {
    "scrollZoom": False,
    "displayModeBar": False,
    "staticPlot": False,
}
# → fig.write_html(..., config=plotly_config) 로 전달
```

---

## 15. 색상 가이드

```
전선수렴 (SMA20+60+120+200): #FF3D00  빨강  🔴
SMA20+60+120:                #FFB300  노랑  🟡
SMA20+60:                    #00C853  초록  🟢
SMA20:                       #2196F3  파랑  🔵
```

---

*마지막 업데이트: 2026-05-12*
*버전: V3.0*
- *시그널 시스템 완전 교체: 그랜드/골든/응축/폭발 → SMA 눌림목 4종류*
- *시그널명: 전선수렴(빨) / SMA20+60+120(노) / SMA20+60(초) / SMA20(파)*
- *종목 유형: 횡보주(SMA200 기울기 ±5%) / 우상향주(+5% 초과) / 하락주 스킵*
- *눌림목 범위: SMA 위 +3~+15% / SMA 아래 -1~-10%*
- *텔레그램 순서: 전선수렴 → SMA20+60+120 → SMA20+60 → SMA20 (강한 순)*
- *기존 CLAUDE.md(V2.2) 보존, 코드 교체 시 이 파일 내용으로 CLAUDE.md 덮어쓰기*
