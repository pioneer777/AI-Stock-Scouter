"""
signal_detector.py — SMA 눌림목 시그널 탐지 V3.0

핵심 원칙: 주가가 SMA에 가까이 붙었을 때 = 눌림목 매수 기회.
근접한 SMA 개수가 많을수록 강한 시그널. 조건 충족 시 즉시 발화 (점수 없음).
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

SIGNAL_META = {
    "전선수렴":      {"color": "#FF3D00", "icon": "🔴", "priority": 1},
    "SMA20+60+120": {"color": "#FFB300", "icon": "🟡", "priority": 2},
    "SMA20+60":     {"color": "#00C853", "icon": "🟢", "priority": 3},
    "SMA20":        {"color": "#2196F3", "icon": "🔵", "priority": 4},
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

def _safe(df: pd.DataFrame, col: str, idx: int = -1):
    try:
        val = df[col].iloc[idx]
        return None if pd.isna(val) else val
    except (KeyError, IndexError):
        return None


def _passes_liquidity(df: pd.DataFrame, market: str) -> bool:
    """일 평균 거래대금 최소 기준. KR ≥ 50억, US ≥ 100만 달러."""
    if len(df) < 20:
        return True
    avg_value = (df["Close"] * df["Volume"]).iloc[-20:].mean()
    threshold = 5_000_000_000 if market == "KR" else 1_000_000
    return avg_value >= threshold


def _market_regime(market_index_df: "pd.DataFrame | None") -> str:
    """지수 SMA20 > SMA60이면 강세장(bull), 아니면 약세장(bear)."""
    if market_index_df is None or len(market_index_df) < 60:
        return "unknown"
    idx   = market_index_df["Close"]
    sma20 = idx.rolling(20).mean().iloc[-1]
    sma60 = idx.rolling(60).mean().iloc[-1]
    if pd.isna(sma20) or pd.isna(sma60):
        return "unknown"
    return "bull" if float(sma20) > float(sma60) else "bear"


# ══════════════════════════════════════════════════════════════════
# 종목 유형 분류
# ══════════════════════════════════════════════════════════════════

def _stock_type(df: pd.DataFrame) -> str:
    """SMA200 기울기(60일 변화율)로 종목 유형 분류."""
    if len(df) < 65:
        return "unknown"
    sma200     = _safe(df, "SMA200")
    sma200_60d = _safe(df, "SMA200", -60)
    if sma200 is None or sma200_60d is None or sma200_60d <= 0:
        return "unknown"
    slope = sma200 / sma200_60d - 1
    if slope > 0.05:
        return "우상향"
    if slope < -0.05:
        return "하락"
    return "횡보"


# ══════════════════════════════════════════════════════════════════
# 눌림목 유효 범위 체크
# ══════════════════════════════════════════════════════════════════

def _pullback_info(close: float, sma: float) -> tuple[bool, str, float]:
    """
    SMA 기준 눌림목 유효 범위 확인.
      위 눌림: +3% ~ +15%
      아래 눌림: -1% ~ -10%
    Returns: (is_valid, position, dist_pct)
    """
    if not sma or sma <= 0:
        return False, "", 0.0
    dist = close / sma - 1
    if dist >= 0:
        if 0.03 <= dist <= 0.15:
            return True, "위", dist * 100
    else:
        if -0.10 <= dist <= -0.01:
            return True, "아래", dist * 100
    return False, "", 0.0


# ══════════════════════════════════════════════════════════════════
# 시그널 탐지 (SMA 눌림목)
# ══════════════════════════════════════════════════════════════════

def _detect_signals(df: pd.DataFrame, stock_type: str) -> list[dict]:
    """
    SMA 눌림목 시그널 탐지.
    우선순위: 전선수렴 > SMA20+60+120 > SMA20+60 > SMA20
    가장 강한 시그널 하나만 반환.
    """
    close  = _safe(df, "Close")
    sma20  = _safe(df, "SMA20")
    sma60  = _safe(df, "SMA60")
    sma120 = _safe(df, "SMA120")
    sma200 = _safe(df, "SMA200")

    if close is None or sma20 is None:
        return []

    v20,  pos20,  d20  = _pullback_info(close, sma20)
    v60,  _,      _    = _pullback_info(close, sma60)  if sma60  else (False, "", 0.0)
    v120, _,      _    = _pullback_info(close, sma120) if sma120 else (False, "", 0.0)
    v200, _,      _    = _pullback_info(close, sma200) if sma200 else (False, "", 0.0)

    def gap_ok(a, b) -> bool:
        return abs(a / b - 1) <= 0.05 if (a and b and b > 0) else False

    dist_str = f"{'+' if d20 >= 0 else ''}{d20:.1f}%"
    display  = f"{pos20}{dist_str}" if pos20 else ""

    def _sig(name: str) -> list[dict]:
        return [{"name": name, "stock_type": stock_type,
                 "position": pos20, "dist_pct": d20, "display": display}]

    # 1. 전선수렴: 4개 모두 범위 이내 + 4선 최대 간격 ≤5%
    if v20 and v60 and v120 and v200:
        smas    = [sma20, sma60, sma120, sma200]
        max_gap = max(smas) / min(smas) - 1
        if max_gap <= 0.05:
            return _sig("전선수렴")

    # 2. SMA20+60+120: 3개 범위 이내 + 3선 간격 각각 ≤5%
    if v20 and v60 and v120:
        if gap_ok(sma20, sma60) and gap_ok(sma60, sma120):
            return _sig("SMA20+60+120")

    # 3. SMA20+60: 2개 범위 이내 + SMA20/60 간격 ≤5%
    if v20 and v60:
        if gap_ok(sma20, sma60):
            return _sig("SMA20+60")

    # 4. SMA20만
    if v20:
        return _sig("SMA20")

    return []


# ══════════════════════════════════════════════════════════════════
# 통합 실행
# ══════════════════════════════════════════════════════════════════

def run_signal_detection(
    df: pd.DataFrame,
    info: dict,
    market_index_df: "pd.DataFrame | None" = None,
    market: str = "KR",
) -> list[dict]:
    """
    SMA 눌림목 시그널 탐지 V3.0.
    반환: [{"name", "stock_type", "position", "dist_pct", "display"}] or []
    """
    if df is None or df.empty:
        return []

    if not _passes_liquidity(df, market):
        log.debug("유동성 미달 — 시그널 탐지 스킵")
        return []

    stock_type = _stock_type(df)
    if stock_type == "하락":
        log.debug("하락추세 종목 — 시그널 탐지 스킵")
        return []

    regime  = _market_regime(market_index_df)
    signals = _detect_signals(df, stock_type)

    # 약세장: 전선수렴 + SMA20+60+120 만 허용
    if regime == "bear" and signals:
        bear_allowed = {"전선수렴", "SMA20+60+120"}
        signals = [s for s in signals if s["name"] in bear_allowed]

    return signals


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
    if above_sma60 and not above_sma20 and (rsi is None or rsi > 30):
        return "건강한조정"
    if above_sma200 and abs(ret_20) < 0.05:
        return "횡보중"
    return "하락주의"
