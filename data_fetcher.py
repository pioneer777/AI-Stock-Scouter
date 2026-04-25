"""
data_fetcher.py — 주가 데이터 수집 + 기술 지표 계산
  - yfinance: KR/US OHLCV + 재무 정보
  - Naver Finance 크롤링: 기관/외인 순매수 TOP (KR 전용)
"""

import logging
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


# ══════════════════════════════════════════════════════════════════
# 티커 변환
# ══════════════════════════════════════════════════════════════════

def get_ticker(code: str, market: str) -> str:
    """종목 코드를 yfinance 티커로 변환."""
    if market == "US":
        return code
    # KR: 6자리 숫자 코드 → KOSPI(.KS) 또는 KOSDAQ(.KQ)
    # stock_list에 exchange 필드가 있으면 우선 사용, 없으면 .KS 시도 후 .KQ fallback
    return f"{code}.KS"


def get_ticker_kr_with_fallback(code: str) -> str:
    """KOSPI 시도 후 데이터 없으면 KOSDAQ으로 재시도."""
    for suffix in [".KS", ".KQ"]:
        ticker = f"{code}{suffix}"
        try:
            df = yf.download(ticker, period="5d", progress=False, auto_adjust=True)
            if not df.empty:
                return ticker
        except Exception:
            pass
    return f"{code}.KS"  # fallback


# ══════════════════════════════════════════════════════════════════
# 기술 지표 계산
# ══════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    OHLCV DataFrame에 기술 지표 컬럼 추가.
    필요 컬럼: Open, High, Low, Close, Volume
    """
    c = df["Close"]
    v = df["Volume"]

    # ── 이동평균선 ────────────────────────────────────────────────
    df["SMA20"]  = c.rolling(20).mean()
    df["SMA60"]  = c.rolling(60).mean()
    df["SMA120"] = c.rolling(120).mean()
    df["SMA200"] = c.rolling(200).mean()

    # ── 거래량 이동평균 ───────────────────────────────────────────
    df["Volume_MA20"]  = v.rolling(20).mean()
    df["Volume_MA200"] = v.rolling(200).mean()

    # ── RSI (14일) ────────────────────────────────────────────────
    delta  = c.diff()
    gain   = delta.clip(lower=0).rolling(14).mean()
    loss   = (-delta.clip(upper=0)).rolling(14).mean()
    rs     = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # ── MACD (12, 26, 9) ──────────────────────────────────────────
    ema12       = c.ewm(span=12, adjust=False).mean()
    ema26       = c.ewm(span=26, adjust=False).mean()
    df["MACD"]       = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"]   = df["MACD"] - df["MACD_Signal"]

    # ── 볼린저밴드 ────────────────────────────────────────────────
    sma20_std    = c.rolling(20).std()
    df["BB_Upper"] = df["SMA20"] + 2 * sma20_std
    df["BB_Lower"] = df["SMA20"] - 2 * sma20_std
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["SMA20"]

    return df


# ══════════════════════════════════════════════════════════════════
# 주가 데이터 수집
# ══════════════════════════════════════════════════════════════════

def fetch_stock_data(
    code: str,
    market: str,
    period: str = "3y",
    exchange: str | None = None,
    ticker_override: str | None = None,
) -> pd.DataFrame | None:
    """
    yfinance로 OHLCV 수집 후 기술 지표 계산.
    ticker_override: stock_list의 '티커' 필드 (예: "005930.KS") — 있으면 최우선 사용
    period: "3y" (3년, 레인지버튼 전 구간 커버)
    """
    if ticker_override:
        ticker = ticker_override
    elif market == "KR":
        ticker = f"{code}{exchange}" if exchange else get_ticker_kr_with_fallback(code)
    else:
        ticker = code

    try:
        df = yf.download(
            ticker,
            period=period,
            progress=False,
            auto_adjust=True,   # 수정주가 자동 적용
        )
    except Exception as e:
        log.error(f"[{code}] yfinance 다운로드 실패: {e}")
        return None

    if df is None or df.empty:
        log.warning(f"[{code}] 데이터 없음")
        return None

    # MultiIndex 컬럼 정리 (yfinance 0.2+ 대응)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.dropna(subset=["Close", "Volume"], inplace=True)

    df = compute_indicators(df)
    log.info(f"[{code}] {len(df)}일 데이터 수집 완료 (최신: {df.index[-1].date()})")
    return df


def fetch_market_index(market: str, period: str = "3mo") -> pd.DataFrame | None:
    """KOSPI(^KS11) 또는 S&P500(^GSPC) 지수 데이터."""
    ticker = "^KS11" if market == "KR" else "^GSPC"
    try:
        df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df[["Open", "High", "Low", "Close", "Volume"]].copy()
    except Exception as e:
        log.error(f"지수 데이터 실패 ({ticker}): {e}")
        return None


def fetch_current_price(code: str, market: str, exchange: str | None = None) -> float | None:
    """현재가만 빠르게 조회 (승패 테이블용)."""
    df = fetch_stock_data(code, market, period="5d", exchange=exchange)
    if df is None or df.empty:
        return None
    return float(df["Close"].iloc[-1])


# ══════════════════════════════════════════════════════════════════
# 재무 정보 수집
# ══════════════════════════════════════════════════════════════════

def fetch_stock_info(
    code: str,
    market: str,
    exchange: str | None = None,
    ticker_override: str | None = None,
) -> dict:
    """
    yfinance Ticker.info로 재무 데이터 수집.
    반환 키: trailingPE, debtToEquity, revenueGrowth, marketCap
    """
    if ticker_override:
        ticker_str = ticker_override
    elif market == "KR":
        ticker_str = f"{code}{exchange}" if exchange else get_ticker_kr_with_fallback(code)
    else:
        ticker_str = code

    try:
        t    = yf.Ticker(ticker_str)
        info = t.info or {}
        return {
            "trailingPE":     info.get("trailingPE"),
            "debtToEquity":   info.get("debtToEquity"),
            "revenueGrowth":  info.get("revenueGrowth"),
            "market_cap":     info.get("marketCap", 0),
            "sector":         info.get("sector", ""),
            "shortName":      info.get("shortName", code),
        }
    except Exception as e:
        log.warning(f"[{code}] 재무 정보 수집 실패: {e}")
        return {"market_cap": 0}


# ══════════════════════════════════════════════════════════════════
# 수급 데이터 — Naver Finance 크롤링 (KR 전용)
# ══════════════════════════════════════════════════════════════════

def _parse_supply_table(html: str, col_name: str) -> list[dict]:
    """Naver 수급 순위 페이지 HTML에서 종목명 + 순매수 금액 파싱."""
    soup  = BeautifulSoup(html, "html.parser")
    rows  = soup.select("table.type_2 tbody tr")
    items = []
    for row in rows:
        cols = row.select("td")
        if len(cols) < 3:
            continue
        name = cols[1].get_text(strip=True)
        val  = cols[2].get_text(strip=True).replace(",", "").replace("+", "")
        if not name or not val.lstrip("-").isdigit():
            continue
        items.append({"종목명": name, col_name: int(val)})
        if len(items) >= 10:
            break
    return items


def fetch_supply_demand() -> dict:
    """
    Naver Finance 기관/외인 순매수 TOP3 크롤링.
    반환: {"기관": [...], "외인": [...]}
    """
    result = {"기관": [], "외인": []}

    # 기관 순매수 (sosok=0: 전체, type=P: 기관순매수)
    urls = {
        "기관": "https://finance.naver.com/sise/sise_quant.nhn?sosok=0",
        "외인": "https://finance.naver.com/sise/sise_quant.nhn?sosok=0",
    }

    # Naver 수급 전용 API (더 안정적)
    supply_url_template = (
        "https://finance.naver.com/sise/sise_investment.nhn"
        "?type={type_}&sosok=0"
    )

    for label, type_code in [("기관", "P"), ("외인", "A")]:
        url = supply_url_template.format(type_=type_code)
        try:
            resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
            resp.encoding = "euc-kr"
            items = _parse_supply_table(resp.text, "순매수")
            result[label] = items[:3]
            time.sleep(0.5)  # 네이버 크롤링 간격
        except Exception as e:
            log.warning(f"수급 크롤링 실패 ({label}): {e}")

    return result


def fetch_stock_supply_demand(code: str) -> dict:
    """
    특정 종목의 기관/외인 일별 순매수 시계열 (차트 2단용).
    Naver: https://finance.naver.com/item/frgn.nhn?code=005930
    반환: DataFrame (date, 기관, 외인)
    """
    url = f"https://finance.naver.com/item/frgn.nhn?code={code}"
    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        html = resp.text
        if "<table" not in html:
            log.warning(f"[{code}] 수급 시계열 실패: 유효한 HTML 없음")
            return pd.DataFrame()
        tables = pd.read_html(html, thousands=",")
        # 보통 두 번째 테이블에 날짜별 기관/외인 데이터
        for t in tables:
            if "날짜" in str(t.columns.tolist()):
                t.columns = [str(c) for c in t.columns]
                return t
    except Exception as e:
        log.warning(f"[{code}] 수급 시계열 실패: {e}")
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════
# 배치 수집 헬퍼
# ══════════════════════════════════════════════════════════════════

def fetch_all_stocks(
    stock_list: dict,
    market: str,
    period: str = "3y",
) -> dict:
    """
    stock_list 전체 종목 데이터 일괄 수집.
    반환: {code: {"df": DataFrame, "info": dict}}
    stock_list 구조: 티커 필드(예: "005930.KS") 또는 exchange 필드(".KS") 지원
    """
    data = {}
    total = len(stock_list)
    for i, (code, meta) in enumerate(stock_list.items(), 1):
        name            = meta.get("종목명", code)
        ticker_override = meta.get("티커")   # "005930.KS" 형태 직접 사용
        exchange        = meta.get("exchange")  # 없으면 None
        log.info(f"[{i}/{total}] {name} ({code}) 수집 중...")

        df   = fetch_stock_data(code, market, period=period,
                                exchange=exchange, ticker_override=ticker_override)
        info = fetch_stock_info(code, market, exchange=exchange,
                                ticker_override=ticker_override)

        if df is not None:
            data[code] = {"df": df, "info": info, "meta": meta}
        else:
            log.warning(f"[{name}] 데이터 수집 실패 — 스킵")

        time.sleep(0.2)  # yfinance rate limit 방지

    log.info(f"수집 완료: {len(data)}/{total}종목")
    return data
