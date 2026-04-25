"""
signal_detector.py — 4가지 시그널 탐지 + 강도 점수 + 추세 분류

각 시그널은 5개 조건 × 20점 = 100점 만점.
MIN_SIGNAL_SCORE(75점) 이상만 텔레그램 전송 → 진짜 좋은 것만 알림.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

MIN_SIGNAL_SCORE = 75  # 이 점수 미만은 무시

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
    """val을 기준값과 비교해 점수 반환. tiers = [(threshold, pts), ...] 내림차순."""
    for threshold, pts in tiers:
        if val >= threshold:
            return pts
    return 0


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
      5. 직전 60일 낙폭 (<80%=20 / <85%=15 / <=90%=10)
    """
    if len(df) < 65:
        return 0

    vol_thr = 1.20 if is_large_cap(info) else 1.30

    # 조건 1: 크로스 신선도
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

    rsi    = _safe(df, "RSI")
    vol    = _safe(df, "Volume")
    vma20  = _safe(df, "Volume_MA20")
    close  = _safe(df, "Close")
    sma120 = _safe(df, "SMA120")

    if None in (rsi, vol, vma20, close, sma120):
        return 0
    if close <= sma120:
        return 0

    w60     = df.iloc[-60:]
    max_px  = w60["Close"].max()
    min_px  = w60["Close"].min()
    pull_ratio = min_px / max_px

    s1 = _pts(cross_days, [(1, 20), (2, 20), (3, 15), (5, 10)])  # 작을수록 좋음
    s1 = 20 if cross_days <= 2 else (15 if cross_days <= 3 else 10)

    s2 = _pts(rsi,   [(60, 20), (55, 15), (50, 10)])
    s3 = _pts(vol / vma20, [(1.60, 20), (1.45, 15), (vol_thr, 10)])
    s4 = _pts(close / sma120 - 1, [(0.03, 20), (0.01, 15), (0, 10)])

    # 낙폭: 비율이 낮을수록(많이 빠졌을수록) 좋음
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

    w30     = df.iloc[-30:]
    rise    = w30["Close"].max() / w30["Close"].iloc[0] - 1
    if rise < 0.10:
        return 0

    pull_dist = abs(close / sma20 - 1)
    if pull_dist > 0.07:
        return 0

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
      1. BB폭 분위 (하위15%=20 / 하위20%=15 / 하위30%=10)
      2. 20일 변동폭 (<5%=20 / <6%=15 / <8%=10)
      3. SMA 수렴도 (<1%=20 / <2%=15 / <3%=10)
      4. 주가 vs SMA60 위치 (>2%=20 / >1%=15 / just above=10)
      5. 거래량 후반 증가 (>120%=20 / >110%=15 / >90%=10)
    """
    if len(df) < 65:
        return 0

    close = _safe(df, "Close")
    sma20 = _safe(df, "SMA20")
    sma60 = _safe(df, "SMA60")
    bbw   = _safe(df, "BB_Width")

    if None in (close, sma20, sma60, bbw):
        return 0
    if close < sma60:
        return 0

    w60  = df.iloc[-60:]
    w20  = df.iloc[-20:]

    bb_pct   = (bbw - w60["BB_Width"].min()) / (w60["BB_Width"].max() - w60["BB_Width"].min() + 1e-9)
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
      1. 지수 20일 상승폭 (>5%=20 / >2%=15 / >0%=10)
      2. 개별주 조정폭 (-10~-12% 스윗스팟=20 / -8~-10%=15 / -7%=10)
      3. MACD 반등 강도 (3일 연속+가속=20 / 3일 연속=15)
      4. 주가 vs SMA200 여유 (>5%=20 / >2%=15 / just above=10)
      5. RSI 스윗스팟 (45~55=20 / 40~60=15)
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

    recent_high = df.iloc[-10:]["High"].max()
    pull        = close / recent_high - 1
    if pull > -0.07:
        return 0

    # 지수 상승폭
    idx_rise = 0.0
    if market_index_df is not None and len(market_index_df) >= 20:
        idx = market_index_df["Close"]
        idx_rise = float(idx.iloc[-1]) / float(idx.iloc[-20]) - 1
    if idx_rise <= 0:
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

    s1 = _pts(idx_rise, [(0.05, 20), (0.02, 15), (0, 10)])
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
) -> list[dict]:
    """
    4가지 시그널 점수 계산.
    MIN_SIGNAL_SCORE 이상만 반환: [{"name": str, "score": int}, ...]
    """
    if df is None or df.empty:
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
