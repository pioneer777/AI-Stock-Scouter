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

- **기능**: 한국/미국 주식 데이터 수집 → 퀀트 지표 분석 → 4가지 시그널 포착 → 텔레그램 리포트 + GitHub 클라우드 HTML 차트 생성
- **기술 스택**: Python, Pandas, Plotly, yfinance, Telegram Bot API, GitHub Actions
- **대상 종목**: 태진님이 직접 관리하는 종목 리스트 (재무 약한 기업 사전 제외)
- **시장**: 한국(KR) / 미국(US) 분리 운영

---

## 3. 4가지 시그널 정의 및 알고리즘

> 시그널 수 제한 없음. 단, 품질 최우선 — 하루 0개도 괜찮고, 진짜 기회만 잡는 것이 목표.

### 🟢 그랜드 (Grand) — 횡보/하락에서 대상승 시작 포착
```
조건 (모두 충족):
  - SMA20이 SMA60을 상향돌파 (최근 5일 내 크로스)
  - RSI > 50 (상승 모멘텀 확인)
  - 거래량 > 20일 평균의 130% (대형주 120%)
  - 주가 > SMA120 (중기 추세 우위)
  - 직전 60일 내 -10% 이상 하락 또는 횡보 구간 존재
색상: #00C851 (밝은 에메랄드그린)
```

### 🟡 골든 (Golden) — 1차 상승 후 눌림목 매수 기회
```
조건 (모두 충족):
  - 최근 30일 내 10% 이상 상승 이력
  - 현재가가 SMA20 기준 ±7% 이내 (눌림 확인)
  - RSI 35~60 사이 (과매도 아닌 건강한 조정)
  - 눌림 중 거래량 감소 (20일 평균 이하, 매도 압력 약함)
  - SMA20 > SMA60 (상승 추세 유효)
색상: #FFB300 (진한 골드/앰버)
```

### 🟣 응축 (Squeeze) — 세력 매집 구간 포착
```
조건 (모두 충족):
  - 볼린저밴드 폭이 최근 60일 중 하위 30% (squeeze)
  - 20일 변동폭 8% 이내 (횡보 확인)
  - SMA20과 SMA60 간격 3% 이내 (이평선 수렴)
  - 거래량: 감소 후 소폭 증가 추세 (매집 패턴)
  - 주가 SMA60 이상 유지
색상: #AA00FF (딥 퍼플)
```

### 🔴 폭발 (Explosion) — 대상승장 중 눌림목
```
조건 (모두 충족):
  - KOSPI 또는 S&P500이 20일 상승 추세
  - 개별주 단기 -7% 이상 조정 (과도한 하락 아님)
  - MACD 히스토그램 바닥 후 반등 시작
  - 주가 SMA200 위 (장기 추세 유효)
  - RSI 40 이상 (붕괴 아닌 조정)
색상: #FF3D00 (딥 오렌지레드)
```

### 대형주 / 중소형주 기준 분리
```
대형주 (시총 1조+, KOSPI200 포함):
  - 거래량 기준: 20일 평균의 120% 이상
  - 변동폭 기준: 더 좁게 적용

중소형주:
  - 거래량 기준: 20일 평균의 150% 이상 (노이즈 필터)
  - 변동폭 기준: 더 넓게 적용
```

---

## 4. 재무 필터 (자동 검증)

```python
# 재무 필터 (yfinance 기반) — 데이터 없으면 통과 (KR 누락 잦음)
PER > 0                    # 흑자 기업 (순손실 기업 제외)
부채비율 < 400%             # 심각한 재무 위험 제외
매출성장률 > -25%           # 사업 붕괴 수준 매출 급감 제외
영업이익률 > -30%           # 심각한 적자 구조 제외
PSR < 50배                 # 매출 대비 극단적 고평가 제외
```

> 임계치는 느슨하게 설정 — yfinance KR 데이터 신뢰도 낮음.
> 탈락 시 로그에 사유 출력: `[종목명] 재무 필터 탈락 — PER -3.2 (적자)`

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
    "시그널": "그랜드",
    "선정일": "2026-04-24",
    "진입가": 3200,
    "유효기간만료": "2027-04-24"
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

## 8. 차트 스펙 (visualizer.py)

### 전체 레이아웃
```
높이: 950px (모바일 최적화)
서브플롯 비중: 주가(58%) / 거래량(18%) / 보조지표(24%)
배경: 다크모드
테두리: 4면 mirror=True, showline=True
주말 제거: rangebreaks=[dict(bounds=["sat", "mon"])]
RangeSlider: visible=False (무조건)
데이터 로드 기간: 현재 기준 3년 (레인지 버튼 전 구간 커버용)
기본 표시 범위: xaxis_range = 현재 기준 1년 (datetime 객체)
드래그 이동: 완전 비활성화 (dragmode=False)
핀치 줌: 비활성화 (모바일 오터치 방지)
```

### 차트 탐색 방식 — A안 (레인지 버튼 전용)
```
[탐색 방법] 상단 레인지 버튼만 사용, 드래그/스와이프 없음

레인지 버튼:
  [ 3M ]   [ 6M ]   [ 1Y★ ]   [ 2Y ]   [ 전체 ]
  (3개월)  (6개월) (1년 기본) (2년)   (3년 전체)

기본 선택: 1Y (차트 오픈 시 자동)
버튼 위치: 차트 최상단 좌측
버튼 스타일: 다크모드 어울리는 반투명 버튼

Plotly 설정:
  fig.update_layout(
      dragmode=False,
      xaxis=dict(
          rangeselector=dict(
              buttons=[
                  dict(count=3,  label="3M",  step="month", stepmode="backward"),
                  dict(count=6,  label="6M",  step="month", stepmode="backward"),
                  dict(count=1,  label="1Y",  step="year",  stepmode="backward"),
                  dict(count=2,  label="2Y",  step="year",  stepmode="backward"),
                  dict(step="all", label="전체"),
              ],
              activecolor="#FFB300",    # 선택된 버튼 강조 (골드)
              bgcolor="#1E1E1E",
              font=dict(color="#FFFFFF"),
          ),
          rangeslider=dict(visible=False),
          rangebreaks=[dict(bounds=["sat", "mon"])],
      ),
  )
```

### 차트 1단 — 주가 (58%)
```
캔들스틱: 상승=빨강(#FF3D00), 하락=파랑(#1565C0)
이동평균선:
  SMA20  → 파랑  (#2196F3), 굵기 1.2
  SMA60  → 주황  (#FF9800), 굵기 1.2
  SMA120 → 초록  (#4CAF50), 굵기 1.2
  SMA200 → 핑크  (#E91E63), 굵기 1.5 (강조)

[박스 표기 — 캔들 고점 위 배치, 가운데 정렬]
언급일 박스:
  라인1: "1차_4/22"  (또는 2차, 3차...)
  라인2: "35,000"
  색상: 흰 배경 + 진한 테두리
  → 언급 차수 모두 표시 (1차부터 존재하는 차수까지)
  → 세로 점선(회색 dash)으로 날짜 표시

시그널 박스:
  라인1: "골든_4/22"  (그랜_/응축_/폭발_ 등)
  라인2: "45,000"
  색상: 시그널별 고유 색상 배경
  → 최초 선정 날짜만 표시
  → 같은 날 여러 시그널 겹치면 위아래 자동 배열 (겹침 없음)

TODAY 박스: 현재가 위치에 검정 배경 흰 글씨
  예: "TODAY: 3,660"
```

### 차트 2단 — 거래량 (18%)
```
거래량 막대: 주가 등락에 따른 색상 매칭 (상승=빨강, 하락=파랑)
거래량 20일 이동평균: 검은색 얇은 점선 (dash, width=1)
거래량 200일 이동평균: 회색 얇은 점선 (dash, width=1)
기관 순매수: 초록 반투명 막대 (한국 시장만)
외인 순매수: 주황 반투명 막대 (한국 시장만)
Y축 타이틀: '거래량' (가운데 고정)
주가 이평선과 절대 혼동되지 않도록 스타일 명확히 구분
```

### 차트 3단 — 보조지표 (24%)
```
MACD 히스토그램: 막대 (양수=초록, 음수=빨강)
MACD선: 파랑 실선
시그널선: 주황 실선
RSI: 검은색 점선 (secondary_y)
RSI 70선: 빨강 점선 (기준선)
RSI 30선: 파랑 점선 (기준선)
RSI 현재값 박스: 차트 우측 최하단(y=0.03) 배치
```

### 범례
```
위치: 최상단 (y=1.06), 가로 1줄 분산
좌측: 이평선 설명 (SMA20/60/120/200)
우측: 시그널 설명 (그랜드/골든/응축/폭발)
```

---

## 9. 텔레그램 메시지 포맷 (4섹션)

> 모바일 최적화. 차트는 이미지 전송 아님 → GitHub 하이퍼링크 클릭으로 연결.

```
📊 AI Stock Scouter - KR | 04.24(금) 14:01
━━━━━━━━━━━━━━━━━━━━━

🔥 1. 핵심 시그널
[그랜드🟢] 퓨런티어 | 잉글우드랩
[골든🟡]   JW생명과학 | 클래시스 | 인바디
[응축🟣]   아모레퍼시픽 | 파마리서치
[폭발🔴]   종목A | 종목B

━━━━━━━━━━━━━━━━━━━━━
📊 2. 승패 테이블
종목명     시그널  선정일  진입가  현재가  수익률
퓨런티어   그랜드  04-22  3,200  3,660  +14.4%✅
클래시스   골든    04-20  52,000 54,300  +4.4%✅
브이티     응축    04-18  18,500 17,900  -3.2%❌
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

## 10. 리포트 구분 (main.py)

```
--report SUMMARY (장중): 시그널 기록 X, 모니터링 전용
--report FULL (장마감):  시그널 JSON 기록 O, 인덱스 HTML 생성 O
```

### 운영 스케줄 (KST 기준)
```
KR 장중:  11:00, 14:30 → SUMMARY
KR 장마감: 17:00       → FULL
US 장중:  00:00, 04:00 → SUMMARY
US 장마감: 07:00       → FULL
```

### 인덱스 파일 분리
```
index_KR.html  ← 한국 시장 전용
index_US.html  ← 미국 시장 전용
```

---

## 11. 파일 구조

```
C:\CLAUDE_Project\ai-stock-scouter\
├── CLAUDE.md                    ← 이 파일
├── main.py                      ← 운영 오케스트레이터
├── data_fetcher.py              ← yfinance + Naver 크롤링 + 지표 계산
├── signal_detector.py           ← 4가지 시그널 알고리즘 + 추세 분류
├── visualizer.py                ← Plotly 3단 차트 생성
├── reporter.py                  ← 텔레그램 4섹션 메시지 + index HTML
├── sector_outlook.json          ← 업황 수동 입력 (루트에 위치)
├── signal_history_KR.json       ← KR 시그널 승패 기록 (FULL 실행 시 생성)
├── signal_history_US.json       ← US 시그널 승패 기록 (FULL 실행 시 생성)
├── index_KR.html                ← KR 클라우드 인덱스 (FULL 실행 시 생성)
├── index_US.html                ← US 클라우드 인덱스 (FULL 실행 시 생성)
├── requirements.txt
├── data/
│   ├── stock_list_KR.json       ← 한국 종목 리스트 (130+종목, 티커 포함)
│   ├── stock_list_US.json       ← 미국/글로벌 종목 리스트
│   ├── stock_list_INTL.json     ← 일본/홍콩/중국/대만 종목 리스트
│   └── generate_stock_lists.py  ← 종목 리스트 재생성 스크립트
├── charts/
│   ├── KR/                      ← KR 종목별 HTML 차트
│   └── US/                      ← US 종목별 HTML 차트
└── .github/
    └── workflows/
        ├── run_kr.yml           ← KR 자동 실행 (평일 11:00/14:30/17:00 KST)
        ├── run_us.yml           ← US 자동 실행 (평일 00:00/04:00/07:00 KST)
        └── test.yml             ← 수동 테스트 실행 (workflow_dispatch)
```

---

## 12. GitHub Actions 운영 환경

### GitHub Secrets (반드시 설정)
```
TELEGRAM_BOT_TOKEN   ← KR/US 동일한 토큰 사용 OK (봇은 하나여도 무방)
TELEGRAM_CHAT_ID     ← KR/US 같은 채팅방이면 동일값, 분리하려면 다른 값
GITHUB_PAGES_URL     ← index HTML 링크용 (예: https://username.github.io/ai-stock-scouter)
```

> **KR과 US는 같은 텔레그램 봇 토큰을 써도 완전히 무방.**
> 같은 채팅방에 보내면 시간대가 다르니 메시지가 겹치지 않음.
> 분리하고 싶으면 `TELEGRAM_CHAT_ID_KR` / `TELEGRAM_CHAT_ID_US` 로 분기 가능 (추후 구현).

### 수동 테스트 모드 (test.yml)
```
GitHub Actions → 🧪 Test Mode → Run workflow
  ├── market:   KR(기본) / US
  ├── report:   FULL(기본) / SUMMARY
  └── dry_run:  true(기본, 텔레그램 전송 안 함) / false
```
- `dry_run=true`: 텔레그램 전송 없이 콘솔 출력 + 차트 아티팩트만 생성
- 차트 결과물은 Actions 탭 → 해당 실행 → Artifacts에서 7일간 다운로드 가능
- `DRY_RUN` 환경변수로도 제어 가능 (`export DRY_RUN=true`)

### 로컬 직접 실행
```bash
# 테스트 (텔레그램 전송 없이)
DRY_RUN=true python main.py --market KR --report FULL

# 실제 실행
python main.py --market KR --report SUMMARY
python main.py --market US --report FULL
```

---

## 13. 핵심 버그 방지 규칙

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
    "scrollZoom": False,      # 스크롤 줌 비활성화
    "displayModeBar": False,  # 모드바 숨김 (깔끔한 UI)
    "staticPlot": False,      # 완전 정지 아님 (버튼은 동작해야)
}
# → fig.write_html(..., config=plotly_config) 로 전달
```

---

## 14. 색상 변경 가이드

색상은 운영하면서 시인성에 따라 수정 가능. 변경 시 이 파일에 반영:
```
그랜드: #00C851  (현재)
골든:   #FFB300  (현재)
응축:   #AA00FF  (현재)
폭발:   #FF3D00  (현재)
```

---

*마지막 업데이트: 2026-04-25*
*버전: V1.4 (시그널 점수제 75점 / 재무필터 5항목 강화 / 텔레그램 보유기간 가이드)*