"""
signal_detector.py — 4가지 시그널 탐지 + 강도 점수 + 추세 분류

각 시그널은 5개 조건 × 20점 = 100점 만점.
MIN_SIGNAL_SCORE(75점) 이상만 텔레그램 전송.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

MIN_SIGNAL_SCORE       = 75
MIN_SQUEEZE_SCORE      = 70  # 응축은 하드게이트 2개가 이미 엄격해 임계 완화

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
    "단기하락":   "🔻",
    "추세하락":   "⛔",
}


# ══════════════════════════════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════════════════════════════

def is_large_cap(info: dict) -> bool:
    return info.get("market_cap", 0) >= 1_000_000_000_000


def _b(pct: float, thr: float = 3.0) -> str:
    """±thr% 이내면 볼드, 아니면 일반 텍스트."""
    s = f"{pct:+.1f}%"
    return f"<b>{s}</b>" if abs(pct) <= thr else s


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


def _market_regime(market_index_df: "pd.DataFrame | None") -> str:
    """
    시장 국면 판별: 지수 SMA20 > SMA60이면 강세장(bull), 아니면 약세장(bear).
    데이터 부족 시 unknown 반환 → 모든 시그널 허용.
    """
    if market_index_df is None or len(market_index_df) < 60:
        return "unknown"
    idx   = market_index_df["Close"]
    sma20 = idx.rolling(20).mean().iloc[-1]
    sma60 = idx.rolling(60).mean().iloc[-1]
    if pd.isna(sma20) or pd.isna(sma60):
        return "unknown"
    return "bull" if float(sma20) > float(sma60) else "bear"


# ══════════════════════════════════════════════════════════════════
# 시그널 1: 그랜드
# ══════════════════════════════════════════════════════════════════

def score_grand(df: pd.DataFrame, info: dict) -> tuple[int, str]:
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

    표시: "크로스 3일전 | SMA120 +2.1% / SMA200 -8.3% | RSI 58"
    """
    if len(df) < 65:
        return 0, ""

    vol_thr = 1.20 if is_large_cap(info) else 1.30

    # 크로스 신선도 (최근 20일 이내 크로스 탐색)
    cross_days = None
    for i in range(-20, 0):
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
        return 0, ""

    # ── 하드게이트 1: 크로스 전 하락/횡보 확인 ──────────────────────
    _pre_end   = -(cross_days + 1)
    _pre_start = -(cross_days + 61)
    pre_cross  = df.iloc[_pre_start:_pre_end]
    if len(pre_cross) >= 30:
        days_below = (pre_cross["SMA20"] < pre_cross["SMA60"]).sum()
        if days_below < 20:
            return 0, ""

    # ── 하드게이트 2: 크로스 시점에 SMA60이 여전히 상승 중이면 반전 아님 ──
    sma60     = _safe(df, "SMA60")
    sma60_30d = _safe(df, "SMA60", -(cross_days + 30))
    if sma60 is not None and sma60_30d is not None and sma60_30d > 0:
        if sma60 > sma60_30d * 1.03:
            return 0, ""
    # ────────────────────────────────────────────────────────────────

    rsi    = _safe(df, "RSI")
    vol    = _safe(df, "Volume")
    vma20  = _safe(df, "Volume_MA20")
    close  = _safe(df, "Close")
    sma120 = _safe(df, "SMA120")
    sma200 = _safe(df, "SMA200")

    if None in (rsi, vol, vma20, close, sma120):
        return 0, ""
    if close <= sma120:
        return 0, ""

    # ── 하드게이트 ──────────────────────────────────────────────
    if rsi >= 70:
        return 0, ""

    lookback  = min(252, len(df))
    yr_high   = df.iloc[-lookback:]["High"].max()
    if close / yr_high >= 0.90:
        return 0, ""

    if sma200 is not None and close > sma200 * 1.10:
        return 0, ""

    if len(df) >= 20:
        close_20d = df["Close"].iloc[-20]
        if close_20d > 0 and close / close_20d - 1 >= 0.40:
            return 0, ""

    sma120_60d = _safe(df, "SMA120", -60)
    if sma120_60d is not None and sma120 < sma120_60d * 0.95:
        return 0, ""
    # ────────────────────────────────────────────────────────────

    w60        = df.iloc[-60:]
    max_px     = w60["Close"].max()
    min_px     = w60["Close"].min()
    pull_ratio = min_px / max_px

    s1 = 20 if cross_days <= 2 else (15 if cross_days <= 5 else (10 if cross_days <= 10 else 5))
    s2 = _pts(rsi,          [(60, 20), (55, 15), (50, 10)])
    s3 = _pts(vol / vma20,  [(1.60, 20), (1.45, 15), (vol_thr, 10)])
    s4 = _pts(close / sma120 - 1, [(0.03, 20), (0.01, 15), (0, 10)])
    s5 = 20 if pull_ratio <= 0.80 else (15 if pull_ratio <= 0.85 else 10)

    score = s1 + s2 + s3 + s4 + s5

    sma120_pct = (close / sma120 - 1) * 100
    sma200_pct = (close / sma200 - 1) * 100 if sma200 else None
    sma200_str = f" / SMA200 {_b(sma200_pct)}" if sma200_pct is not None else ""
    display = f"크로스 {cross_days}일전 | SMA120 {_b(sma120_pct)}{sma200_str} | RSI {rsi:.0f}"

    return score, display


# ══════════════════════════════════════════════════════════════════
# 시그널 2: 골든MA
# ══════════════════════════════════════════════════════════════════

def score_golden(df: pd.DataFrame, info: dict) -> tuple[int, str]:
    """
    골든MA — SMA200 우상향 + 다중 이평선 수렴 + 주가 근접

    하드게이트:
      - SMA200이 60일 전보다 낮음 (하락추세 SMA200)
      - SMA20~SMA120 간격 > 20% (수렴 아님)
      - 주가가 SMA60/SMA120/SMA200 중 어느 것에도 -12%~+3% 이내 아님
      - RSI ≥ 70 (과매수)

    점수 (5개 × 20점):
      s1: SMA200 우상향 강도 (60일 기울기 >5%=20 / >3%=15 / >1%=10)
      s2: 이평선 수렴도 (gap ≤7%=20 / ≤13%=15 / ≤20%=10)
      s3: 주가~가장 가까운 이평선 거리 (≤3%=20 / ≤6%=15 / ≤12%=10)
      s4: RSI 중립권 (40~60=20 / 35~65=15 / 30~70=10)
      s5: 거래량 감소 (vol<70%=20 / <85%=15 / <100%=10)

    표시: "SMA200 우상향 | SMA20 -5.2% / SMA60 -1.8% / SMA120 +4.3%"
    """
    if len(df) < 200:
        return 0, ""

    close  = _safe(df, "Close")
    sma20  = _safe(df, "SMA20")
    sma60  = _safe(df, "SMA60")
    sma120 = _safe(df, "SMA120")
    sma200 = _safe(df, "SMA200")
    rsi    = _safe(df, "RSI")
    vol    = _safe(df, "Volume")
    vma20  = _safe(df, "Volume_MA20")

    if None in (close, sma20, sma60, sma120, sma200, rsi):
        return 0, ""

    # 하드게이트 1: SMA200 우상향
    sma200_60d = _safe(df, "SMA200", -60)
    if sma200_60d is None or sma200 <= sma200_60d:
        return 0, ""

    # 하드게이트 2: 이평선 수렴 ≤ 12% (SMA20~SMA120 최대-최소 / 최소)
    ma_max = max(sma20, sma60, sma120)
    ma_min = min(sma20, sma60, sma120)
    ma_gap = (ma_max - ma_min) / ma_min
    if ma_gap > 0.12:
        return 0, ""

    # 하드게이트 3: 주가가 SMA60/SMA120/SMA200 중 하나에 -12%~+3% 이내
    def in_range(ref): return -0.12 <= close / ref - 1 <= 0.03
    if not (in_range(sma60) or in_range(sma120) or in_range(sma200)):
        return 0, ""

    # 하드게이트 4: RSI 과매수 제외
    if rsi >= 70:
        return 0, ""

    # 점수 계산
    sma200_slope = sma200 / sma200_60d - 1
    s1 = _pts(sma200_slope, [(0.05, 20), (0.03, 15), (0.01, 10)])
    s2 = 20 if ma_gap <= 0.04 else (15 if ma_gap <= 0.08 else 10)

    dist60  = abs(close / sma60  - 1)
    dist120 = abs(close / sma120 - 1)
    dist200 = abs(close / sma200 - 1)
    min_dist = min(dist60, dist120, dist200)
    s3 = 20 if min_dist <= 0.03 else (15 if min_dist <= 0.06 else 10)

    s4 = 20 if 40 <= rsi <= 60 else (15 if 35 <= rsi <= 65 else (10 if 30 <= rsi <= 70 else 0))

    vol_ratio = vol / (vma20 + 1e-9) if (vol is not None and vma20 is not None) else 1.0
    s5 = 20 if vol_ratio < 0.70 else (15 if vol_ratio < 0.85 else (10 if vol_ratio < 1.00 else 0))

    score = s1 + s2 + s3 + s4 + s5

    # 표시 문자열: SMA20/60/120/200 대비 주가 위치 (±3% 이내 볼드)
    p20  = (close / sma20  - 1) * 100
    p60  = (close / sma60  - 1) * 100
    p120 = (close / sma120 - 1) * 100
    p200 = (close / sma200 - 1) * 100
    display = f"SMA20 {_b(p20)} / SMA60 {_b(p60)} / SMA120 {_b(p120)} / SMA200 {_b(p200)}"

    return score, display


# ══════════════════════════════════════════════════════════════════
# 시그널 3: 응축
# ══════════════════════════════════════════════════════════════════

def score_squeeze(df: pd.DataFrame, info: dict) -> int:
    """
    세력 매집 구간 포착 — 위치(SMA 위/아래) 무관하게 수렴 자체가 본질.
    바닥 횡보(SMA200 아래)와 1차 상승 후 눌림목 모두 해당.

    하드게이트 (수렴 강도 필수):
      - BB폭 분위 > 30% (수렴 아님)
      - 20일 변동폭 > 8% (횡보 아님)

    점수 (5개 × 20점):
      1. BB폭 분위 120일 기준 (하위15%=20 / 하위20%=15 / 하위30%=10)
      2. 20일 변동폭 (<5%=20 / <6%=15 / <8%=10)
      3. SMA20/SMA60 수렴도 (<1%=20 / <2%=15 / <3%=10)
      4. SMA200 근접도 (±3%=20 / ±5%=15 / ±10%=10 / 초과=5)
      5. 거래량 후반 증가 (>120%=20 / >110%=15 / >90%=10)
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

    w120 = df.iloc[-120:]
    w20  = df.iloc[-20:]

    bb_range = w120["BB_Width"].max() - w120["BB_Width"].min()
    bb_pct   = (bbw - w120["BB_Width"].min()) / (bb_range + 1e-9)
    rng      = w20["High"].max() / w20["Low"].min() - 1

    # 수렴 강도 하드게이트 — 이것이 응축의 본질
    # 대형주는 변동성이 낮으니 기준 좁게, 중소형주는 넓게
    rng_thr = 0.08 if is_large_cap(info) else 0.15
    if bb_pct > 0.30:
        return 0
    if rng > rng_thr:
        return 0

    conv      = abs(sma20 / sma60 - 1)
    vol_mid   = w20["Volume"].iloc[:10].mean()
    vol_late  = w20["Volume"].iloc[10:].mean()
    vol_ratio = vol_late / (vol_mid + 1e-9)

    # SMA200 근접도: 장기 지지선에 가까울수록 매집 의미 강화
    if sma200 is not None:
        dist200 = abs(close / sma200 - 1)
        s4 = 20 if dist200 <= 0.03 else (15 if dist200 <= 0.05 else (10 if dist200 <= 0.10 else 5))
    else:
        s4 = 10  # SMA200 데이터 없으면 중간 점수

    s1 = 20 if bb_pct <= 0.15 else (15 if bb_pct <= 0.20 else 10)
    s2 = _pts(1 - rng, [(0.95, 20), (0.94, 15), (0.92, 10)])
    s3 = 20 if conv <= 0.01 else (15 if conv <= 0.02 else (10 if conv <= 0.03 else 0))
    s5 = _pts(vol_ratio, [(1.20, 20), (1.10, 15), (0.90, 10)])

    score = s1 + s2 + s3 + s4 + s5

    # 표시 문자열: BB분위 + 변동폭 + SMA200 거리 (±3% 이내 볼드)
    sma200_str = f" | SMA200 {_b((close / sma200 - 1)*100)}" if sma200 is not None else ""
    display = f"BB 하위 {bb_pct*100:.0f}% | 변동폭 {rng*100:.1f}%{sma200_str}"

    return score, display


# ══════════════════════════════════════════════════════════════════
# 시그널 4: 폭발
# ══════════════════════════════════════════════════════════════════

def score_explosion(
    df: pd.DataFrame,
    info: dict,
    market_index_df: pd.DataFrame | None = None,
) -> int:
    """
    응축 돌파형: 20~60일 횡보 후 저항선 돌파 + 거래량 폭발
    목표 보유기간 1~2주 (국장 상한가 / 미장 +5~15% 단기 스윙)

    하드게이트:
      - 주가 < SMA60
      - 거래량 < 20일 평균 250% (거래량 폭발 없음)
      - 응축 기간 20일 미만 (진짜 횡보 매집 없음)
      - 오늘 종가 ≤ 응축 구간 최고가 (저항선 미돌파)

    점수 (5개 × 20점):
      1. 거래량 배율 (>500%=20 / >400%=15 / >300%=10 / >250%=5)
      2. 돌파 강도 — 종가 vs 저항선 (>3%=20 / >1%=15 / 돌파=10)
      3. 응축 기간 (40일+=20 / 30일+=15 / 20일+=10)
      4. RSI 스윗스팟 (45~65=20 / 40~70=15)
      5. SMA200 위 여유 (>10%=20 / >5%=15 / just above=10 / SMA200없으면 SMA60 기준)
    """
    if len(df) < 25:
        return 0

    close  = _safe(df, "Close")
    vol    = _safe(df, "Volume")
    vma20  = _safe(df, "Volume_MA20")
    sma60  = _safe(df, "SMA60")
    sma200 = _safe(df, "SMA200")
    rsi    = _safe(df, "RSI")

    if None in (close, vol, vma20, sma60, rsi):
        return 0

    # 하드게이트: 거래량 미달 (대형주 250%, 중소형주 200%)
    vol_ratio = vol / (vma20 + 1e-9)
    vol_thr   = 2.50 if is_large_cap(info) else 2.00
    if vol_ratio < vol_thr:
        return 0

    # 응축 기간 계산: 어제부터 거슬러 올라가며 가격 범위 8% 이내인 일수
    w_high = float(df["High"].iloc[-2])
    w_low  = float(df["Low"].iloc[-2])
    consol_days = 1
    max_lookback = min(60, len(df) - 2)
    for offset in range(3, max_lookback + 2):
        if offset >= len(df):
            break
        h = float(df["High"].iloc[-offset])
        l = float(df["Low"].iloc[-offset])
        new_high = max(w_high, h)
        new_low  = min(w_low, l)
        if new_high / new_low - 1 > 0.10:
            break
        w_high = new_high
        w_low  = new_low
        consol_days += 1

    # 하드게이트: 응축 기간 20일 미만
    if consol_days < 20:
        return 0

    # 저항선 = 응축 구간의 최고가
    resistance = w_high

    # 하드게이트: 저항선 미돌파
    if close <= resistance:
        return 0

    breakout_pct = close / resistance - 1

    s1 = 20 if vol_ratio >= 5.0 else (15 if vol_ratio >= 4.0 else (10 if vol_ratio >= 3.0 else 5))
    s2 = 20 if breakout_pct > 0.03 else (15 if breakout_pct > 0.01 else 10)
    s3 = 20 if consol_days >= 40 else (15 if consol_days >= 30 else 10)
    s4 = 20 if 45 <= rsi <= 65 else (15 if 40 <= rsi <= 70 else 0)

    if sma200 is not None:
        s5 = _pts(close / sma200 - 1, [(0.10, 20), (0.05, 15), (0, 10)])
    else:
        s5 = _pts(close / sma60 - 1, [(0.05, 20), (0.02, 15), (0, 10)])

    score = s1 + s2 + s3 + s4 + s5

    # 표시 문자열: 거래량배율 + 저항돌파 + 응축기간
    display = f"거래량 {vol_ratio*100:.0f}% | 저항 {breakout_pct*100:+.1f}% | 응축 {consol_days}일"

    return score, display


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

    # 시장 국면 필터: 약세장에서는 골든/폭발 스킵
    # 그랜드는 약세장 바닥권 반전 포착이 핵심 — 종목 자체 SMA크로스가 이미 엄격히 필터링
    regime    = _market_regime(market_index_df)
    bear_skip = {"골든", "폭발"}

    checks = [
        ("그랜드", score_grand,     (df, info)),
        ("골든",   score_golden,    (df, info)),
        ("응축",   score_squeeze,   (df, info)),
        ("폭발",   score_explosion, (df, info, market_index_df)),
    ]

    detected = []
    for name, func, args in checks:
        if regime == "bear" and name in bear_skip:
            log.debug(f"{name} 스킵 — 약세장 국면 (SMA20 < SMA60)")
            continue
        try:
            result = func(*args)
            if isinstance(result, tuple):
                s, display = result
            else:
                s, display = result, ""
            threshold = MIN_SQUEEZE_SCORE if name == "응축" else MIN_SIGNAL_SCORE
            if s >= threshold:
                detected.append({"name": name, "score": s, "display": display})
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
    elif above_sma60 and not above_sma20 and (rsi is None or rsi > 30):
        return "건강한조정"
    elif above_sma200 and abs(ret_20) < 0.05:
        return "횡보중"
    else:
        return "하락주의"
