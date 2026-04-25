"""
signal_detector.py — 4가지 시그널 탐지 + 추세 분류
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

SIGNAL_META = {
    "그랜드": {"color": "#00C851", "icon": "🟢", "short": "그랜"},
    "골든":   {"color": "#FFB300", "icon": "🟡", "short": "골든"},
    "응축":   {"color": "#AA00FF", "icon": "🟣", "short": "응축"},
    "폭발":   {"color": "#FF3D00", "icon": "🔴", "short": "폭발"},
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
    """NaN 안전 컬럼 접근."""
    try:
        val = df[col].iloc[idx]
        return None if pd.isna(val) else val
    except (KeyError, IndexError):
        return None


# ══════════════════════════════════════════════════════════════════
# 시그널 1: 그랜드 — 횡보/하락에서 대상승 시작 포착
# ══════════════════════════════════════════════════════════════════

def detect_grand(df: pd.DataFrame, info: dict) -> bool:
    """
    조건 (모두 충족):
      - SMA20이 SMA60 상향 돌파 (최근 5일 내)
      - RSI > 50
      - 거래량 > 20일 평균의 130% (대형주 120%)
      - 주가 > SMA120
      - 직전 60일 내 -10% 이상 하락 또는 횡보 존재
    """
    if len(df) < 65:
        return False

    vol_thr = 1.20 if is_large_cap(info) else 1.30

    # SMA20 > SMA60 크로스 (최근 5일 내)
    cross = False
    for i in range(-5, 0):
        prev_20 = _safe(df, "SMA20", i - 1)
        prev_60 = _safe(df, "SMA60", i - 1)
        curr_20 = _safe(df, "SMA20", i)
        curr_60 = _safe(df, "SMA60", i)
        if None in (prev_20, prev_60, curr_20, curr_60):
            continue
        if prev_20 <= prev_60 and curr_20 > curr_60:
            cross = True
            break

    rsi     = _safe(df, "RSI")
    vol     = _safe(df, "Volume")
    vma20   = _safe(df, "Volume_MA20")
    close   = _safe(df, "Close")
    sma120  = _safe(df, "SMA120")

    if None in (rsi, vol, vma20, close, sma120):
        return False

    rsi_ok    = rsi > 50
    vol_ok    = vol > vma20 * vol_thr
    trend_ok  = close > sma120

    w60       = df.iloc[-60:]
    max_px    = w60["Close"].max()
    min_px    = w60["Close"].min()
    pull_ok   = (min_px / max_px) <= 0.90

    result = cross and rsi_ok and vol_ok and trend_ok and pull_ok
    if result:
        log.debug(f"그랜드 시그널 발생")
    return result


# ══════════════════════════════════════════════════════════════════
# 시그널 2: 골든 — 1차 상승 후 눌림목 매수 기회
# ══════════════════════════════════════════════════════════════════

def detect_golden(df: pd.DataFrame, info: dict) -> bool:
    """
    조건 (모두 충족):
      - 최근 30일 내 10% 이상 상승
      - 현재가 SMA20 ±7% 이내
      - RSI 35~60
      - 거래량 < 20일 평균 (매도 압력 약함)
      - SMA20 > SMA60
    """
    if len(df) < 35:
        return False

    rsi    = _safe(df, "RSI")
    vol    = _safe(df, "Volume")
    vma20  = _safe(df, "Volume_MA20")
    close  = _safe(df, "Close")
    sma20  = _safe(df, "SMA20")
    sma60  = _safe(df, "SMA60")

    if None in (rsi, vol, vma20, close, sma20, sma60):
        return False

    w30      = df.iloc[-30:]
    rise_ok  = (w30["Close"].max() / w30["Close"].iloc[0] - 1) >= 0.10
    pull_ok  = abs(close / sma20 - 1) <= 0.07
    rsi_ok   = 35 <= rsi <= 60
    vol_ok   = vol < vma20
    trend_ok = sma20 > sma60

    result = rise_ok and pull_ok and rsi_ok and vol_ok and trend_ok
    if result:
        log.debug(f"골든 시그널 발생")
    return result


# ══════════════════════════════════════════════════════════════════
# 시그널 3: 응축 — 세력 매집 구간 포착
# ══════════════════════════════════════════════════════════════════

def detect_squeeze(df: pd.DataFrame, info: dict) -> bool:
    """
    조건 (모두 충족):
      - 볼린저밴드 폭이 최근 60일 중 하위 30%
      - 20일 변동폭 8% 이내
      - SMA20과 SMA60 간격 3% 이내
      - 거래량: 중반 감소 후 최근 소폭 증가
      - 주가 >= SMA60
    """
    if len(df) < 65:
        return False

    close  = _safe(df, "Close")
    sma20  = _safe(df, "SMA20")
    sma60  = _safe(df, "SMA60")
    bbw    = _safe(df, "BB_Width")

    if None in (close, sma20, sma60, bbw):
        return False

    w60    = df.iloc[-60:]
    w20    = df.iloc[-20:]

    bb_ok       = bbw <= w60["BB_Width"].quantile(0.30)
    range_ok    = (w20["High"].max() / w20["Low"].min() - 1) <= 0.08
    conv_ok     = abs(sma20 / sma60 - 1) <= 0.03
    price_ok    = close >= sma60

    vol_mid  = w20["Volume"].iloc[:10].mean()
    vol_late = w20["Volume"].iloc[10:].mean()
    vol_ok   = vol_late > vol_mid * 0.90

    result = bb_ok and range_ok and conv_ok and price_ok and vol_ok
    if result:
        log.debug(f"응축 시그널 발생")
    return result


# ══════════════════════════════════════════════════════════════════
# 시그널 4: 폭발 — 대상승장 중 눌림목
# ══════════════════════════════════════════════════════════════════

def detect_explosion(
    df: pd.DataFrame,
    info: dict,
    market_index_df: pd.DataFrame | None = None,
) -> bool:
    """
    조건 (모두 충족):
      - KOSPI/S&P500 20일 상승 추세
      - 개별주 단기 -7% 이상 조정
      - MACD 히스토그램 바닥 후 반등 (최근 3일 연속 증가)
      - 주가 > SMA200
      - RSI >= 40
    """
    if len(df) < 25:
        return False

    close   = _safe(df, "Close")
    sma200  = _safe(df, "SMA200")
    rsi     = _safe(df, "RSI")

    if None in (close, sma200, rsi):
        return False

    # 지수 20일 상승 추세
    index_rising = False
    if market_index_df is not None and len(market_index_df) >= 20:
        idx = market_index_df["Close"]
        index_rising = float(idx.iloc[-1]) > float(idx.iloc[-20])

    # 단기 -7% 이상 조정
    recent_high = df.iloc[-10:]["High"].max()
    pull_ok = (close / recent_high - 1) <= -0.07

    # MACD 히스토그램 3일 연속 증가
    macd_ok = False
    if len(df) >= 3:
        h = df["MACD_Hist"].iloc[-3:]
        if not h.isna().any():
            macd_ok = h.iloc[-1] > h.iloc[-2] > h.iloc[-3]

    price_ok = close > sma200
    rsi_ok   = rsi >= 40

    result = index_rising and pull_ok and macd_ok and price_ok and rsi_ok
    if result:
        log.debug(f"폭발 시그널 발생")
    return result


# ══════════════════════════════════════════════════════════════════
# 통합 실행
# ══════════════════════════════════════════════════════════════════

def run_signal_detection(
    df: pd.DataFrame,
    info: dict,
    market_index_df: pd.DataFrame | None = None,
) -> list[str]:
    """4가지 시그널 모두 검사 후 발생한 시그널 이름 리스트 반환."""
    if df is None or df.empty:
        return []

    detected = []
    checks = [
        ("그랜드", detect_grand,     (df, info)),
        ("골든",   detect_golden,    (df, info)),
        ("응축",   detect_squeeze,   (df, info)),
        ("폭발",   detect_explosion, (df, info, market_index_df)),
    ]
    for name, func, args in checks:
        try:
            if func(*args):
                detected.append(name)
        except Exception as e:
            log.warning(f"{name} 시그널 탐지 오류: {e}")

    return detected


# ══════════════════════════════════════════════════════════════════
# 추세 분류 (섹션4용)
# ══════════════════════════════════════════════════════════════════

def classify_trend(df: pd.DataFrame) -> str:
    """
    상승지속 / 건강한조정 / 횡보중 / 하락주의
    """
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
    ret_20 = (close / float(w20["Close"].iloc[0]) - 1)

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
