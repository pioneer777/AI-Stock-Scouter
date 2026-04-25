"""
signal_detector.py — 4가지 시그널 탐지 + 강도 점수 + 추세 분류

각 시그널은 5개 조건 × 20점 = 100점 만점.
MIN_SIGNAL_SCORE(75점) 이상만 텔레그램 전송.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

MIN_SIGNAL_SCORE = 75

SIGNAL_META = {
    "그랜드": {"color": "#00C851", "icon": "🟢", "short": "그랜", "period": "1~3개월"},
    "골든":   {"color": "#FFB300", "icon": "🟡", "short": "골든", "period": "2~4주"},
    "응축":   {"color": "#AA00FF", "icon": "🟣", "short": "응축", "period": "1~6개월"},
    "폭발":   {"color": "#FF3D00", "icon": "🔴", "short": "폭발", "period": "1~2주"},
}

TREND_LABELS = {
    "상승지속":   "📈",
    "건강한조정": "📉",
    "횡보중":     "➡️",
    "하락주의":   "🔻",
}


# ══════════════════════════════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════════════════════════════

def is_large_cap(info: dict) -> bool:
    return info.get("market_cap", 0) >= 1_000_000_000_000


def _safe(df: pd.DataFrame, col: str, idx: int = -1):
    try:
        val = df[col].iloc[idx]
        return None if pd.isna(val) else val
    except (KeyError, IndexError):
        return None


def _pts(val, tiers: list[tuple]) -> int:
    for threshold, pts in tiers:
        if val >= threshold:
            return pts
    return 0


def _passes_liquidity(df: pd.DataFrame, market: str) -> bool:
    """일 평균 거래대금 최소 기준. KR ≥ 50억, US ≥ 100만 달러."""
    if len(df) < 20:
        return True
    avg_value = (df["Close"] * df["Volume"]).iloc[-20:].mean()
    threshold = 5_000_000_000 if market == "KR" else 1_000_000
    return avg_value >= threshold


# ══════════════════════════════════════════════════════════════════
# 시그널 1: 그랜드
# ══════════════════════════════════════════════════════════════════

def score_grand(df: pd.DataFrame, info: dict) -> int:
    """
    조건 (5개 × 20점):
      1. SMA20 > SMA60 크로스 신선도 (최근 2일=20 / 3일=15 / 5일=10)
      2. RSI (>60=20 / >55=15 / >50=10)
      3. 거래량 배율 (>160%=20 / >145%=15 / >threshold=10)
      4. 주가 vs SMA120 여유 (>3%=20 / >1%=15 / just above=10)
      5. 직전 60일 낙폭 (≤80%=20 / ≤85%=15 / ≤90%=10)

    하드게이트 (0점 즉시 반환):
      - 크로스 직전 60일 중 SMA20<SMA60 일수 20일 미만 (상승장 중 크로스 = 반전 아님)
      - 52주 고점 대비 현재가 90% 이상 (이미 고점 근처)
      - RSI ≥ 70 (과매수)
      - 20일 상승률 ≥ 40% (단기 급등 후 지연 반응)
      - SMA120이 60일 전 대비 5% 이상 하락 (하락추세 SMA120)
    """
    if len(df) < 65:
        return 0

    vol_thr = 1.20 if is_large_cap(info) else 1.30

    # 크로스 신선도
    cross_days = None
    for i in range(-5, 0):
        p20 = _safe(df, "SMA20", i - 1)
        p60 = _safe(df, "SMA60", i - 1)
        c20 = _safe(df, "SMA20", i)
        c60 = _safe(df, "SMA60", i)
        if None in (p20, p60, c20, c60):
            continue
        if p20 <= p60 and c20 > c60:
            cross_days = abs(i)
            break
    if cross_days is None:
        return 0

    # ── 하드게이트 1: 크로스 전 하락/횡보 확인 ──────────────────────
    # 크로스 직전 60일 중 최소 20일 이상 SMA20 < SMA60 이어야 진짜 반전.
    # 하락 후 단기 회복(20~30일 base)과 장기 횡보(40~60일 base) 모두 포함.
    # 이 조건이 없으면 이미 상승 중인 종목이 잠깐 조정 후 재돌파해도 통과됨.
    _pre_end   = -(cross_days + 1)   # 크로스 바로 전날
    _pre_start = -(cross_days + 61)  # 그보다 60일 전
    pre_cross  = df.iloc[_pre_start:_pre_end]
    if len(pre_cross) >= 30:
        days_below = (pre_cross["SMA20"] < pre_cross["SMA60"]).sum()
        if days_below < 20:
            return 0
    # ────────────────────────────────────────────────────────────────

    rsi    = _safe(df, "RSI")
    vol    = _safe(df, "Volume")
    vma20  = _safe(df, "Volume_MA20")
    close  = _safe(df, "Close")
    sma120 = _safe(df, "SMA120")

    if None in (rsi, vol, vma20, close, sma120):
        return 0
    if close <= sma120:
        return 0

    # ── 하드게이트 ──────────────────────────────────────────────
    # RSI 과매수
    if rsi >= 70:
        return 0

    # 52주 고점 근처 (이미 많이 오른 종목)
    lookback  = min(252, len(df))
    yr_high   = df.iloc[-lookback:]["High"].max()
    if close / yr_high >= 0.90:
        return 0

    # 단기 급등 후 이동평균 지연 반응
    if len(df) >= 20:
        close_20d = df["Close"].iloc[-20]
        if close_20d > 0 and close / close_20d - 1 >= 0.40:
            return 0

    # SMA120 하락추세 (60일 전 대비 5% 이상 하락)
    sma120_60d = _safe(df, "SMA120", -60)
    if sma120_60d is not None and sma120 < sma120_60d * 0.95:
        return 0
    # ────────────────────────────────────────────────────────────

    w60        = df.iloc[-60:]
    max_px     = w60["Close"].max()
    min_px     = w60["Close"].min()
    pull_ratio = min_px / max_px

    s1 = 20 if cross_days <= 2 else (15 if cross_days <= 3 else 10)
    s2 = _pts(rsi,          [(60, 20), (55, 15), (50, 10)])
    s3 = _pts(vol / vma20,  [(1.60, 20), (1.45, 15), (vol_thr, 10)])
    s4 = _pts(close / sma120 - 1, [(0.03, 20), (0.01, 15), (0, 10)])
    s5 = 20 if pull_ratio <= 0.80 else (15 if pull_ratio <= 0.85 else 10)

    return s1 + s2 + s3 + s4 + s5


# ══════════════════════════════════════════════════════════════════
# 시그널 2: 골든
# ══════════════════════════════════════════════════════════════════

def score_golden(df: pd.DataFrame, info: dict) -> int:
    """
    조건 (5개 × 20점):
      1. 30일 상승폭 (>20%=20 / >15%=15 / >10%=10)
      2. SMA20 근접도 (±3%=20 / ±5%=15 / ±7%=10)
      3. RSI 스윗스팟 (40~55=20 / 35~60=15)
      4. 거래량 감소 (<70%=20 / <85%=15 / <100%=10)
      5. SMA20 > SMA60 여유 (>3%=20 / >1%=15 / just above=10)

    하드게이트:
      - 현재가 > SMA20 × 1.02 (아직 눌림 시작 전)
      - SMA20이 5일 전보다 하락 (우상향 유지 아님)
      - SMA20/SMA60 간격이 5일 전보다 축소 (데드크로스 임박)
    """
    if len(df) < 35:
        return 0

    rsi   = _safe(df, "RSI")
    vol   = _safe(df, "Volume")
    vma20 = _safe(df, "Volume_MA20")
    close = _safe(df, "Close")
    sma20 = _safe(df, "SMA20")
    sma60 = _safe(df, "SMA60")

    if None in (rsi, vol, vma20, close, sma20, sma60):
        return 0
    if sma20 <= sma60:
        return 0

    w30  = df.iloc[-30:]
    rise = w30["Close"].max() / w30["Close"].iloc[0] - 1
    if rise < 0.10:
        return 0

    pull_dist = abs(close / sma20 - 1)
    if pull_dist > 0.07:
        return 0

    # ── 하드게이트 ──────────────────────────────────────────────
    # 주가가 SMA20보다 2% 이상 위 = 아직 눌림 시작 안 됨
    if close > sma20 * 1.02:
        return 0

    sma20_5d = _safe(df, "SMA20", -5)
    sma60_5d = _safe(df, "SMA60", -5)

    # SMA20 꺾임 감지
    if sma20_5d is not None and sma20 <= sma20_5d:
        return 0

    # SMA20/SMA60 간격 축소 = 데드크로스 임박
    if sma20_5d is not None and sma60_5d is not None and sma60_5d > 0:
        gap_now  = sma20 / sma60 - 1
        gap_prev = sma20_5d / sma60_5d - 1
        if gap_now < gap_prev:
            return 0
    # ────────────────────────────────────────────────────────────

    s1 = _pts(rise, [(0.20, 20), (0.15, 15), (0.10, 10)])
    s2 = 20 if pull_dist <= 0.03 else (15 if pull_dist <= 0.05 else 10)
    s3 = 20 if 40 <= rsi <= 55 else (15 if 35 <= rsi <= 60 else 0)
    s4 = _pts(1 - vol / vma20, [(0.30, 20), (0.15, 15), (0, 10)])
    s5 = _pts(sma20 / sma60 - 1, [(0.03, 20), (0.01, 15), (0, 10)])

    return s1 + s2 + s3 + s4 + s5


# ══════════════════════════════════════════════════════════════════
# 시그널 3: 응축
# ══════════════════════════════════════════════════════════════════

def score_squeeze(df: pd.DataFrame, info: dict) -> int:
    """
    조건 (5개 × 20점):
      1. BB폭 분위 120일 기준 (하위15%=20 / 하위20%=15 / 하위30%=10)
      2. 20일 변동폭 (<5%=20 / <6%=15 / <8%=10)
      3. SMA 수렴도 (<1%=20 / <2%=15 / <3%=10)
      4. 주가 vs SMA60 위치 (>2%=20 / >1%=15 / just above=10)
      5. 거래량 후반 증가 (>120%=20 / >110%=15 / >90%=10)

    하드게이트:
      - 주가 < SMA60 (기존 조건 유지)
      - 주가 < SMA200 (장기 하락추세 제외 — 기존엔 없었음)
    """
    if len(df) < 125:
        return 0

    close  = _safe(df, "Close")
    sma20  = _safe(df, "SMA20")
    sma60  = _safe(df, "SMA60")
    sma200 = _safe(df, "SMA200")
    bbw    = _safe(df, "BB_Width")

    if None in (close, sma20, sma60, bbw):
        return 0
    if close < sma60:
        return 0

    # SMA200 위 조건 (데이터 있을 때만)
    if sma200 is not None and close < sma200:
        return 0

    # BB폭 분위를 120일 기준으로 계산 (기존 60일 → 더 의미있는 응축 기준)
    w120 = df.iloc[-120:]
    w20  = df.iloc[-20:]

    bb_range = w120["BB_Width"].max() - w120["BB_Width"].min()
    bb_pct   = (bbw - w120["BB_Width"].min()) / (bb_range + 1e-9)
    rng      = w20["High"].max() / w20["Low"].min() - 1
    conv     = abs(sma20 / sma60 - 1)
    price_up = close / sma60 - 1
    vol_mid  = w20["Volume"].iloc[:10].mean()
    vol_late = w20["Volume"].iloc[10:].mean()
    vol_ratio = vol_late / (vol_mid + 1e-9)

    s1 = 20 if bb_pct <= 0.15 else (15 if bb_pct <= 0.20 else (10 if bb_pct <= 0.30 else 0))
    s2 = _pts(1 - rng, [(0.95, 20), (0.94, 15), (0.92, 10)])
    s3 = 20 if conv <= 0.01 else (15 if conv <= 0.02 else (10 if conv <= 0.03 else 0))
    s4 = _pts(price_up, [(0.02, 20), (0.01, 15), (0, 10)])
    s5 = _pts(vol_ratio, [(1.20, 20), (1.10, 15), (0.90, 10)])

    return s1 + s2 + s3 + s4 + s5


# ══════════════════════════════════════════════════════════════════
# 시그널 4: 폭발
# ══════════════════════════════════════════════════════════════════

def score_explosion(
    df: pd.DataFrame,
    info: dict,
    market_index_df: pd.DataFrame | None = None,
) -> int:
    """
    조건 (5개 × 20점):
      1. 지수 20일 상승폭 (>5%=20 / >3%=15 / >2%=10)
      2. 개별주 조정폭 (-10~-12% 스윗스팟=20 / -8~-10%=15 / -7%=10)
      3. MACD 반등 강도 (3일 연속+가속=20 / 3일 연속=15)
      4. 주가 vs SMA200 여유 (>5%=20 / >2%=15 / just above=10)
      5. RSI 스윗스팟 (45~55=20 / 40~60=15)

    하드게이트:
      - 주가 ≤ SMA200 (장기 추세 미확인)
      - SMA200이 60일 전보다 하락 (하락추세 SMA200)
      - 주가 > SMA200 × 1.20 (충분히 눌리지 않음 — 조정이 얕음)
      - 지수 20일 상승률 ≤ 2% (기존 0%에서 강화)
      - MACD 반등 없음
    """
    if len(df) < 25:
        return 0

    close  = _safe(df, "Close")
    sma200 = _safe(df, "SMA200")
    rsi    = _safe(df, "RSI")

    if None in (close, sma200, rsi):
        return 0
    if close <= sma200:
        return 0

    # ── 하드게이트 ──────────────────────────────────────────────
    # SMA200 방향성: 60일 전보다 하락이면 탈락
    sma200_60d = _safe(df, "SMA200", -60)
    if sma200_60d is not None and sma200 <= sma200_60d:
        return 0

    # SMA200 대비 너무 위 = 충분히 눌리지 않은 상태
    if close > sma200 * 1.20:
        return 0
    # ────────────────────────────────────────────────────────────

    recent_high = df.iloc[-10:]["High"].max()
    pull        = close / recent_high - 1
    if pull > -0.07:
        return 0

    # 지수 상승폭 (기존 >0% → >2%로 강화)
    idx_rise = 0.0
    if market_index_df is not None and len(market_index_df) >= 20:
        idx      = market_index_df["Close"]
        idx_rise = float(idx.iloc[-1]) / float(idx.iloc[-20]) - 1
    if idx_rise <= 0.02:
        return 0

    # MACD
    macd_score = 0
    if len(df) >= 4:
        h = df["MACD_Hist"].iloc[-4:]
        if not h.isna().any():
            rising3 = h.iloc[-1] > h.iloc[-2] > h.iloc[-3]
            accel   = (h.iloc[-1] - h.iloc[-2]) > (h.iloc[-2] - h.iloc[-3])
            if rising3 and accel:
                macd_score = 20
            elif rising3:
                macd_score = 15
    if macd_score == 0:
        return 0

    s1 = _pts(idx_rise, [(0.05, 20), (0.03, 15), (0.02, 10)])
    s2 = 20 if -0.12 <= pull <= -0.10 else (15 if pull <= -0.08 else 10)
    s3 = macd_score
    s4 = _pts(close / sma200 - 1, [(0.05, 20), (0.02, 15), (0, 10)])
    s5 = 20 if 45 <= rsi <= 55 else (15 if 40 <= rsi <= 60 else 0)

    return s1 + s2 + s3 + s4 + s5


# ══════════════════════════════════════════════════════════════════
# 통합 실행
# ══════════════════════════════════════════════════════════════════

def run_signal_detection(
    df: pd.DataFrame,
    info: dict,
    market_index_df: pd.DataFrame | None = None,
    market: str = "KR",
) -> list[dict]:
    """
    4가지 시그널 점수 계산.
    MIN_SIGNAL_SCORE 이상만 반환: [{"name": str, "score": int}, ...]
    """
    if df is None or df.empty:
        return []

    # 유동성 필터: 일평균 거래대금 KR≥50억, US≥100만달러
    if not _passes_liquidity(df, market):
        log.debug("유동성 미달 — 시그널 탐지 스킵")
        return []

    checks = [
        ("그랜드", score_grand,     (df, info)),
        ("골든",   score_golden,    (df, info)),
        ("응축",   score_squeeze,   (df, info)),
        ("폭발",   score_explosion, (df, info, market_index_df)),
    ]

    detected = []
    for name, func, args in checks:
        try:
            s = func(*args)
            if s >= MIN_SIGNAL_SCORE:
                detected.append({"name": name, "score": s})
                log.debug(f"{name} 시그널 발생 (점수: {s})")
        except Exception as e:
            log.warning(f"{name} 시그널 탐지 오류: {e}")

    return detected


# ══════════════════════════════════════════════════════════════════
# 추세 분류 (섹션4용)
# ══════════════════════════════════════════════════════════════════

def classify_trend(df: pd.DataFrame) -> str:
    if df is None or len(df) < 20:
        return "횡보중"

    close  = _safe(df, "Close")
    sma20  = _safe(df, "SMA20")
    sma60  = _safe(df, "SMA60")
    sma200 = _safe(df, "SMA200")
    rsi    = _safe(df, "RSI")

    if None in (close, sma20, sma60):
        return "횡보중"

    w20    = df.iloc[-20:]
    ret_20 = close / float(w20["Close"].iloc[0]) - 1

    above_sma20  = close > sma20
    above_sma60  = close > sma60
    above_sma200 = (close > sma200) if sma200 else True

    if above_sma20 and above_sma60 and ret_20 > 0.03:
        return "상승지속"
    elif above_sma60 and not above_sma20 and (rsi is None or rsi > 35):
        return "건강한조정"
    elif above_sma200 and abs(ret_20) < 0.05:
        return "횡보중"
    else:
        return "하락주의"
