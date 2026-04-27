"""
data_fetcher.py — 주가 데이터 수집 + 기술 지표 계산
  - pykrx : KR OHLCV + 지수 + 수급 (1차, KRX 공식 데이터)
  - yfinance: US OHLCV + 재무 정보 (KR 재무는 DART 보완)
  - KIS API: KR 수급 시계열 차트용 (pykrx 보완)
  - Naver Finance: 수급 최종 fallback
"""

import io
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

try:
    from pykrx import stock as krx_stock
    _PYKRX_OK = True
except ImportError:
    _PYKRX_OK = False
    logging.getLogger(__name__).warning("pykrx 미설치 — KR 데이터는 yfinance fallback")

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
    # min_periods=1: 데이터 시작부터 SMA 표시 (전체 기간 뷰에서 SMA 공백 방지)
    df["SMA20"]  = c.rolling(20,  min_periods=1).mean()
    df["SMA60"]  = c.rolling(60,  min_periods=1).mean()
    df["SMA120"] = c.rolling(120, min_periods=1).mean()
    df["SMA200"] = c.rolling(200, min_periods=1).mean()

    # ── 거래량 이동평균 ───────────────────────────────────────────
    df["Volume_MA20"]  = v.rolling(20,  min_periods=1).mean()
    df["Volume_MA200"] = v.rolling(200, min_periods=1).mean()

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
# pykrx — KR 전용 데이터 수집
# ══════════════════════════════════════════════════════════════════

def _period_to_dates(period: str) -> tuple[str, str]:
    """"3y" → ("20230427", "20260427") 형식 변환."""
    end  = date.today()
    days = {"1y": 365, "2y": 730, "3y": 1095, "5d": 5, "1mo": 30}
    delta = timedelta(days=days.get(period, 1095))
    start = end - delta
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _rename_pykrx_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """pykrx 한글 컬럼 → 표준 영어 컬럼명 변환."""
    rename = {"시가": "Open", "고가": "High", "저가": "Low",
              "종가": "Close", "거래량": "Volume", "거래대금": "Value"}
    df = df.rename(columns=rename)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in df.columns:
            return pd.DataFrame()
    return df[["Open", "High", "Low", "Close", "Volume"]].copy()


def fetch_stock_data_pykrx(code: str, period: str = "3y") -> pd.DataFrame | None:
    """pykrx로 KR 종목 OHLCV + 시가총액 수집."""
    if not _PYKRX_OK:
        return None
    clean = _clean_code(code)
    from_dt, to_dt = _period_to_dates(period)
    try:
        df = krx_stock.get_market_ohlcv_by_date(from_dt, to_dt, clean)
        if df is None or df.empty:
            return None
        df = _rename_pykrx_ohlcv(df)
        if df.empty:
            return None

        # 시가총액 병합 (대형주 판별용 — 마지막 날만 빠르게)
        try:
            cap_df = krx_stock.get_market_cap_by_date(to_dt, to_dt, clean)
            if cap_df is not None and not cap_df.empty:
                df.attrs["market_cap"] = int(cap_df["시가총액"].iloc[-1])
        except Exception:
            pass

        df.dropna(subset=["Close", "Volume"], inplace=True)
        df = compute_indicators(df)
        log.info(f"[{clean}] pykrx {len(df)}일 수집 완료 (최신: {df.index[-1].date()})")
        return df
    except Exception as e:
        log.warning(f"[{clean}] pykrx 수집 실패: {e}")
        return None


def fetch_market_index_pykrx(market: str, period: str = "1y") -> pd.DataFrame | None:
    """pykrx로 KOSPI(1001) / KOSDAQ(2001) 지수 수집."""
    if not _PYKRX_OK:
        return None
    ticker = "1001" if market == "KR" else "2001"
    from_dt, to_dt = _period_to_dates(period)
    try:
        df = krx_stock.get_index_ohlcv_by_date(from_dt, to_dt, ticker)
        if df is None or df.empty:
            return None
        df = df.rename(columns={"시가": "Open", "고가": "High",
                                 "저가": "Low",  "종가": "Close", "거래량": "Volume"})
        return df[["Open", "High", "Low", "Close", "Volume"]].copy()
    except Exception as e:
        log.warning(f"pykrx 지수 수집 실패: {e}")
        return None


def fetch_supply_demand_pykrx(stock_list: dict) -> dict:
    """
    pykrx: 관심종목 기관/외인 최근 거래일 순매수 TOP3 (KIS fallback용).
    5일 창으로 조회 후 마지막 행 사용 (장중엔 당일 데이터 없어 전일 기준).
    반환: {"기관": [...], "외인": [...]}
    """
    if not _PYKRX_OK:
        return {"기관": [], "외인": []}
    result  = {"기관": [], "외인": []}
    from_dt, to_dt = _period_to_dates("5d")
    records = []
    for code, meta in stock_list.items():
        clean = _clean_code(code)
        name  = meta.get("종목명", code)
        try:
            df = krx_stock.get_market_trading_value_by_date(from_dt, to_dt, clean)
            if df is None or df.empty:
                continue
            row = df.iloc[-1]
            inst = int(row.get("기관합계", 0) or 0)
            forg = int(row.get("외국인합계", 0) or 0)
            records.append({"종목명": name, "기관": inst // 100_000_000,
                             "외인": forg // 100_000_000})
            time.sleep(0.05)
        except Exception:
            pass

    if records:
        df_r = pd.DataFrame(records)
        for col, label in [("기관", "기관"), ("외인", "외인")]:
            top = (df_r[df_r[col] > 0]
                   .nlargest(3, col)[["종목명", col]]
                   .rename(columns={col: "순매수"})
                   .to_dict("records"))
            result[label] = top
    return result


def fetch_stock_supply_demand_pykrx(code: str) -> pd.DataFrame:
    """pykrx: 종목 기관/외인 일별 순매수 시계열 (차트용)."""
    if not _PYKRX_OK:
        return pd.DataFrame()
    clean = _clean_code(code)
    from_dt, to_dt = _period_to_dates("3y")
    try:
        df = krx_stock.get_market_trading_value_by_date(from_dt, to_dt, clean)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"기관합계": "기관", "외국인합계": "외인"})
        df["기관"] = df["기관"] // 100_000_000  # 원 → 억
        df["외인"] = df["외인"] // 100_000_000
        return df[["기관", "외인"]].copy()
    except Exception as e:
        log.warning(f"[{clean}] pykrx 수급 시계열 실패: {e}")
        return pd.DataFrame()


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
    OHLCV 수집 후 기술 지표 계산.
    KR: pykrx 우선 → yfinance fallback
    US: yfinance
    ticker_override: stock_list의 '티커' 필드 (예: "005930.KS") — 있으면 yfinance 직접 사용
    """
    # KR: pykrx 우선 (ticker_override 없을 때 — KRX 공식 데이터)
    if market == "KR" and not ticker_override:
        df = fetch_stock_data_pykrx(code, period)
        if df is not None:
            return df
        log.info(f"[{code}] pykrx 실패 — yfinance fallback")

    # US 또는 KR pykrx 실패 시 yfinance
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
            auto_adjust=True,
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
    """KOSPI/KOSDAQ(pykrx) 또는 S&P500(yfinance) 지수 데이터."""
    # KR: pykrx 우선
    if market == "KR":
        df = fetch_market_index_pykrx(market, period)
        if df is not None and not df.empty:
            return df
        log.info("pykrx 지수 실패 — yfinance fallback")

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
        result = {
            "trailingPE":                       info.get("trailingPE"),
            "debtToEquity":                     info.get("debtToEquity"),
            "revenueGrowth":                    info.get("revenueGrowth"),
            "operatingMargins":                 info.get("operatingMargins"),
            "priceToSalesTrailing12Months":     info.get("priceToSalesTrailing12Months"),
            "market_cap":                       info.get("marketCap", 0),
            "sector":                           info.get("sector", ""),
            "shortName":                        info.get("shortName", code),
        }

        # KR: DART 공식 재무 데이터로 보완 (yfinance KR 재무 데이터 신뢰도 낮음)
        if market == "KR":
            dart = fetch_financial_data_dart(code)
            for k, v in dart.items():
                if v is not None:
                    result[k] = v

        return result
    except Exception as e:
        log.warning(f"[{code}] 재무 정보 수집 실패: {e}")
        return {"market_cap": 0}


# ══════════════════════════════════════════════════════════════════
# KIS API — 한국투자증권 수급 데이터 (KR 전용)
# ══════════════════════════════════════════════════════════════════

KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
_kis_token_cache: dict = {}   # {"token": str, "expires_at": datetime}


def _get_kis_token() -> str | None:
    """KIS access token 취득 (23시간 캐시, 매 실행 재발급 방지)."""
    app_key    = os.environ.get("KIS_APP_KEY")
    app_secret = os.environ.get("KIS_APP_SECRET")
    if not app_key or not app_secret:
        log.debug("KIS_APP_KEY / KIS_APP_SECRET 없음 — KIS 스킵")
        return None

    cached = _kis_token_cache
    if cached.get("token") and cached.get("expires_at"):
        if datetime.now() < cached["expires_at"]:
            return cached["token"]

    try:
        resp = requests.post(
            f"{KIS_BASE_URL}/oauth2/tokenP",
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "client_credentials",
                "appkey":     app_key,
                "appsecret":  app_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            log.warning(f"KIS 토큰 응답 이상: {resp.text[:200]}")
            return None
        cached["token"]      = token
        cached["expires_at"] = datetime.now() + timedelta(hours=23)
        log.info("KIS 토큰 발급 완료")
        return token
    except Exception as e:
        log.warning(f"KIS 토큰 발급 실패: {e}")
        return None


def _kis_headers(token: str, tr_id: str) -> dict:
    return {
        "authorization": f"Bearer {token}",
        "appkey":        os.environ.get("KIS_APP_KEY", ""),
        "appsecret":     os.environ.get("KIS_APP_SECRET", ""),
        "tr_id":         tr_id,
        "custtype":      "P",
        "Content-Type":  "application/json; charset=utf-8",
    }


def _kis_market_code(code: str, market_name: str = "") -> str:
    """KOSPI → J, KOSDAQ → Q (KIS API FID_COND_MRKT_DIV_CODE)."""
    if "KOSDAQ" in market_name.upper() or code.endswith(".KQ"):
        return "Q"
    return "J"


def _clean_code(code: str) -> str:
    """종목코드에서 .KS / .KQ suffix 제거."""
    return code.split(".")[0]


def fetch_stock_supply_demand_kis(code: str, market_name: str = "") -> pd.DataFrame:
    """
    KIS API: 특정 종목 기관/외인 일별 순매수 시계열 (차트 2단용).
    반환: DataFrame (index=datetime, columns=[기관, 외인])  단위: 백만원
    """
    token = _get_kis_token()
    if not token:
        return pd.DataFrame()

    clean = _clean_code(code)
    mkt   = _kis_market_code(code, market_name)

    try:
        resp = requests.get(
            f"{KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-investor",
            headers=_kis_headers(token, "FHKST01010300"),
            params={
                "FID_COND_MRKT_DIV_CODE": mkt,
                "FID_INPUT_ISCD":         clean,
            },
            timeout=10,
        )
        resp.raise_for_status()
        output = resp.json().get("output2", [])
        if not output:
            return pd.DataFrame()

        rows = []
        for item in output:
            d = item.get("stck_bsop_date", "")
            if len(d) == 8:
                d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            rows.append({
                "date": d,
                "기관": int(item.get("instn_ntby_tr_pbmn", 0) or 0),
                "외인": int(item.get("frgn_ntby_tr_pbmn",  0) or 0),
            })

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date").sort_index()

    except Exception as e:
        log.warning(f"[{code}] KIS 수급 시계열 실패: {e}")
        return pd.DataFrame()


def fetch_supply_demand_kis(stock_list: dict) -> dict:
    """
    KIS API: 관심종목 내 기관/외인 순매수 당일 TOP3.
    Naver 스크래핑 대체 (시장 전체 대신 관심종목 기준).
    반환: {"기관": [...], "외인": [...]}
    """
    result = {"기관": [], "외인": []}
    token  = _get_kis_token()
    if not token:
        return result

    records = []
    for code, meta in stock_list.items():
        name   = meta.get("종목명", code)
        clean  = _clean_code(code)
        mkt    = _kis_market_code(code, meta.get("시장", ""))
        try:
            resp = requests.get(
                f"{KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-investor",
                headers=_kis_headers(token, "FHKST01010300"),
                params={
                    "FID_COND_MRKT_DIV_CODE": mkt,
                    "FID_INPUT_ISCD":         clean,
                },
                timeout=10,
            )
            resp.raise_for_status()
            output = resp.json().get("output2", [])
            if output:
                latest = output[0]   # 가장 최근 거래일
                records.append({
                    "종목명": name,
                    "기관":   int(latest.get("instn_ntby_tr_pbmn", 0) or 0),
                    "외인":   int(latest.get("frgn_ntby_tr_pbmn",  0) or 0),
                })
            time.sleep(0.12)   # KIS rate limit (초당 ~8콜)
        except Exception as e:
            log.debug(f"[{name}] KIS 수급 조회 실패: {e}")

    if records:
        df_r = pd.DataFrame(records)
        for col, label in [("기관", "기관"), ("외인", "외인")]:
            top = (
                df_r[df_r[col] > 0]
                .nlargest(3, col)[["종목명", col]]
                .rename(columns={col: "순매수"})
                .to_dict("records")
            )
            result[label] = top

    return result


# ══════════════════════════════════════════════════════════════════
# 수급 데이터 — Naver Finance 크롤링 (KR 전용, fallback)
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


def _last_business_day_str() -> str:
    """오늘이 주말이면 직전 금요일, 평일이면 어제 기준 Naver 날짜 파라미터 반환 (YYYYMMDD)."""
    d = date.today()
    if d.weekday() == 5:    # 토요일 → 금요일
        d -= timedelta(days=1)
    elif d.weekday() == 6:  # 일요일 → 금요일
        d -= timedelta(days=2)
    return d.strftime("%Y%m%d")


def fetch_supply_demand() -> dict:
    """
    Naver Finance 기관/외인 순매수 TOP3 크롤링.
    주말/공휴일에는 직전 거래일 데이터를 date 파라미터로 요청.
    반환: {"기관": [...], "외인": [...]}
    """
    result = {"기관": [], "외인": []}
    bday = _last_business_day_str()

    # Naver 수급 전용 API — date 파라미터로 직전 거래일 지정
    supply_url_template = (
        "https://finance.naver.com/sise/sise_investment.nhn"
        "?type={type_}&sosok=0&date={date_}"
    )

    for label, type_code in [("기관", "P"), ("외인", "A")]:
        url = supply_url_template.format(type_=type_code, date_=bday)
        try:
            resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
            resp.encoding = "euc-kr"
            items = _parse_supply_table(resp.text, "순매수")
            result[label] = items[:3]
            time.sleep(0.5)  # 네이버 크롤링 간격
        except Exception as e:
            log.warning(f"수급 크롤링 실패 ({label}): {e}")

    return result


def fetch_stock_supply_demand(code: str, market_name: str = "") -> pd.DataFrame:
    """
    특정 종목 기관/외인 일별 순매수 시계열 (차트 2단용).
    KIS → pykrx → Naver 순서로 fallback.
    반환: DataFrame (index=datetime, columns=[기관, 외인])
    """
    df = fetch_stock_supply_demand_kis(code, market_name=market_name)
    if not df.empty:
        return df

    # pykrx fallback
    df = fetch_stock_supply_demand_pykrx(code)
    if not df.empty:
        return df

    # Naver fallback
    url = f"https://finance.naver.com/item/frgn.nhn?code={code}"
    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        if "<table" not in resp.text:
            return pd.DataFrame()
        for t in pd.read_html(io.StringIO(resp.text), thousands=","):
            if "날짜" in str(t.columns.tolist()):
                t.columns = [str(c) for c in t.columns]
                return t
    except Exception as e:
        log.warning(f"[{code}] Naver 수급 시계열 실패: {e}")
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════
# DART API — 재무 데이터 (KR 전용)
# ══════════════════════════════════════════════════════════════════

DART_BASE_URL = "https://opendart.fss.or.kr/api"
_dart_corp_codes: dict = {}      # {stock_code(6자리): corp_code(8자리)} — 프로세스 내 캐시
_dart_load_tried: bool = False   # 실패 후 재시도 방지


def _load_dart_corp_codes() -> dict:
    """
    DART 전체 상장사 corp_code 매핑 (최초 1회 다운로드 후 메모리 캐시).
    stock_code(6자리) → corp_code(8자리) 딕셔너리 반환.
    """
    global _dart_corp_codes, _dart_load_tried
    if _dart_corp_codes or _dart_load_tried:
        return _dart_corp_codes

    _dart_load_tried = True

    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        log.debug("DART_API_KEY 없음 — DART 스킵")
        return {}

    try:
        resp = requests.get(
            f"{DART_BASE_URL}/corpCode.xml",
            params={"crtfc_key": api_key},
            timeout=30,
        )
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            xml_bytes = z.read("CORPCODE.xml")

        root = ET.fromstring(xml_bytes)
        for corp in root.findall("list"):
            sc = corp.findtext("stock_code", "").strip()
            cc = corp.findtext("corp_code",  "").strip()
            if sc and cc:
                _dart_corp_codes[sc] = cc

        log.info(f"DART corp_code 로드 완료: {len(_dart_corp_codes)}개 상장사")
        return _dart_corp_codes
    except Exception as e:
        log.warning(f"DART corp_code 로드 실패: {e}")
        return {}


def _parse_dart_financials(items: list) -> dict:
    """DART 재무제표 list → 재무 비율 dict 변환."""
    def _to_int(s: str):
        s = (s or "").replace(",", "").replace(" ", "")
        return int(s) if s.lstrip("-").isdigit() else None

    raw: dict[str, dict] = {}
    for item in items:
        name = item.get("account_nm", "").strip()
        raw[name] = {
            "curr": _to_int(item.get("thstrm_amount", "")),
            "prev": _to_int(item.get("frmtrm_amount", "")),
        }

    def _get(*aliases):
        for a in aliases:
            if a in raw:
                return raw[a]
        return {}

    revenue   = _get("매출액", "수익(매출액)", "영업수익", "매출")
    op_profit = _get("영업이익", "영업이익(손실)", "영업손익")
    debt      = _get("부채총계")
    equity    = _get("자본총계")

    result = {}

    rev_curr = revenue.get("curr")
    rev_prev = revenue.get("prev")
    op_curr  = op_profit.get("curr")
    dbt_curr = debt.get("curr")
    eqt_curr = equity.get("curr")

    if dbt_curr is not None and eqt_curr and eqt_curr > 0:
        result["debtToEquity"] = round(dbt_curr / eqt_curr * 100, 1)

    if op_curr is not None and rev_curr and rev_curr > 0:
        result["operatingMargins"] = round(op_curr / rev_curr, 4)

    if rev_curr is not None and rev_prev and rev_prev > 0:
        result["revenueGrowth"] = round((rev_curr - rev_prev) / abs(rev_prev), 4)

    return result


def fetch_financial_data_dart(stock_code: str) -> dict:
    """
    DART: 특정 종목 재무 비율 (최근 사업보고서 기준, 연결 우선).
    반환: {"debtToEquity", "operatingMargins", "revenueGrowth"} — 있는 것만 포함.
    실패 또는 데이터 없으면 빈 dict (yfinance fallback 사용).
    """
    api_key    = os.environ.get("DART_API_KEY")
    corp_codes = _load_dart_corp_codes()
    corp_code  = corp_codes.get(stock_code)

    if not api_key or not corp_code:
        return {}

    current_year = datetime.now().year

    for year in [current_year - 1, current_year - 2]:
        for reprt_code in ["11011", "11012"]:   # 사업보고서 → 반기보고서
            for fs_div in ["CFS", "OFS"]:        # 연결 → 별도
                try:
                    resp = requests.get(
                        f"{DART_BASE_URL}/fnlttSinglAcnt.json",
                        params={
                            "crtfc_key":  api_key,
                            "corp_code":  corp_code,
                            "bsns_year":  str(year),
                            "reprt_code": reprt_code,
                            "fs_div":     fs_div,
                        },
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("status") != "000" or not data.get("list"):
                        continue

                    result = _parse_dart_financials(data["list"])
                    if result:
                        log.debug(f"[{stock_code}] DART 재무 적용 ({year}/{fs_div}): {result}")
                        return result

                except Exception as e:
                    log.debug(f"[{stock_code}] DART 조회 실패 ({year}/{reprt_code}): {e}")

                time.sleep(0.1)

    return {}


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
            # pykrx market_cap → info 보완 (KR yfinance 시총 누락 대비)
            if market == "KR" and not info.get("market_cap") and df.attrs.get("market_cap"):
                info["market_cap"] = df.attrs["market_cap"]
            data[code] = {"df": df, "info": info, "meta": meta}
        else:
            log.warning(f"[{name}] 데이터 수집 실패 — 스킵")

        time.sleep(0.2)  # yfinance rate limit 방지

    log.info(f"수집 완료: {len(data)}/{total}종목")
    return data
