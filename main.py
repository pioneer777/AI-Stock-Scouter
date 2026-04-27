"""
AI Stock Scouter — main.py
실행 예시:
  python main.py --market KR --report SUMMARY
  python main.py --market US --report FULL
환경변수:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  DRY_RUN=true  (텔레그램 전송 없이 콘솔 출력만)
  PAGES_URL  (index HTML 링크용)
"""

import argparse
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from data_fetcher import (
    fetch_all_stocks,
    fetch_market_index,
    fetch_supply_demand,
    fetch_supply_demand_kis,
    fetch_current_price,
)
from signal_detector import (
    SIGNAL_META,
    run_signal_detection,
    classify_trend,
)
from visualizer import generate_chart, CHARTS_DIR
from reporter import build_messages, send_telegram, generate_index_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"


# ══════════════════════════════════════════════════════════════════
# 설정 로더
# ══════════════════════════════════════════════════════════════════

def load_json(path: Path) -> dict:
    if not path.exists():
        log.warning(f"파일 없음: {path.name} — 빈 dict 반환")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"저장 완료: {path.name}")


# ══════════════════════════════════════════════════════════════════
# 재무 필터
# ══════════════════════════════════════════════════════════════════

def passes_financial_filter(info: dict) -> tuple[bool, str]:
    """
    명확한 부실 기업만 제외. yfinance 데이터 누락 시 통과.
    반환: (통과여부, 탈락사유 or "")
    한국 종목은 yfinance 재무 데이터가 자주 비어있으므로
    None 체크 후 임계치는 느슨하게 — 극단적 케이스만 차단.
    """
    per            = info.get("trailingPE")
    debt_ratio     = info.get("debtToEquity")
    revenue_growth = info.get("revenueGrowth")           # -0.25 = -25%
    op_margin      = info.get("operatingMargins")         # -0.30 = -30%
    psr            = info.get("priceToSalesTrailing12Months")

    if per is not None and per < 0:
        return False, f"PER {per:.1f} (적자)"
    if debt_ratio is not None and debt_ratio > 400:
        return False, f"부채비율 {debt_ratio:.0f}%"
    if revenue_growth is not None and revenue_growth < -0.25:
        return False, f"매출성장률 {revenue_growth*100:.1f}%"
    if op_margin is not None and op_margin < -0.30:
        return False, f"영업이익률 {op_margin*100:.1f}%"
    if psr is not None and psr > 50:
        return False, f"PSR {psr:.1f}배"
    return True, ""


# ══════════════════════════════════════════════════════════════════
# 시그널 히스토리 관리 (FULL 모드 전용)
# ══════════════════════════════════════════════════════════════════

def record_signals(
    history: dict,
    code: str,
    name: str,
    signals: list[str],
    current_price: float,
    today: str,
) -> dict:
    expiry = (
        date.fromisoformat(today) + timedelta(days=365)
    ).isoformat()

    if code not in history:
        history[code] = []

    existing = {
        e["시그널"] for e in history[code]
        if e.get("유효기간만료", "") >= today
    }

    for sig in signals:
        if sig in existing:
            log.info(f"[{name}] {sig} — 유효기간 내 기존 기록, 스킵")
            continue
        history[code].append({
            "종목명":      name,
            "시그널":      sig,
            "선정일":      today,
            "진입가":      current_price,
            "유효기간만료": expiry,
        })
        log.info(f"[{name}] {sig} 기록 → 진입가 {current_price:,.0f}")

    return history


# ══════════════════════════════════════════════════════════════════
# 승패 테이블 집계
# ══════════════════════════════════════════════════════════════════

def build_pnl_table(
    signal_history: dict,
    stock_list: dict,
    market: str,
    today: str,
) -> list[dict]:
    rows = []
    for code, entries in signal_history.items():
        for entry in entries:
            if entry.get("유효기간만료", "") < today:
                continue

            entry_px = entry.get("진입가", 0)
            if not entry_px:
                continue

            # 현재가 조회 (stock_list에 exchange 정보 우선 사용)
            exchange = stock_list.get(code, {}).get("exchange")
            cur_px = fetch_current_price(code, market, exchange=exchange)
            if cur_px is None:
                cur_px = entry_px  # 조회 실패 시 진입가 유지

            pnl = (cur_px / entry_px - 1) * 100

            rows.append({
                "code":       code,
                "name":       entry.get("종목명", code),
                "signal":     entry.get("시그널", ""),
                "entry_date": entry.get("선정일", ""),
                "entry_px":   entry_px,
                "cur_px":     cur_px,
                "pnl":        pnl,
            })
    return rows


# ══════════════════════════════════════════════════════════════════
# 메인 실행 흐름
# ══════════════════════════════════════════════════════════════════

def run(market: str, report_mode: str) -> None:
    today    = date.today().isoformat()
    now_dt   = datetime.now()
    day_kr   = ["월", "화", "수", "목", "금", "토", "일"][now_dt.weekday()]
    now_str  = now_dt.strftime(f"%m.%d({day_kr}) %H:%M")
    is_full       = report_mode == "FULL"
    should_record = os.environ.get("RECORD_SIGNALS", "false").lower() == "true"
    dry_run       = os.environ.get("DRY_RUN", "false").lower() == "true"

    log.info("=" * 55)
    log.info(f"AI Stock Scouter | 시장: {market} | 모드: {report_mode}")
    if dry_run:
        log.info("★ DRY RUN 모드 — 텔레그램 전송 안 함")
    log.info("=" * 55)

    # ── 설정 로드 ──────────────────────────────────────────────────
    # data/ 폴더 우선, 없으면 루트 fallback
    _list_path = DATA_DIR / f"stock_list_{market}.json"
    if not _list_path.exists():
        _list_path = BASE_DIR / f"stock_list_{market}.json"
    stock_list     = load_json(_list_path)

    # 비상장 종목 자동 제외
    stock_list = {
        code: meta for code, meta in stock_list.items()
        if meta.get("상장여부", True) and not code.startswith("비상장_")
    }
    signal_history = load_json(BASE_DIR / f"signal_history_{market}.json")
    sector_outlook = load_json(BASE_DIR / "sector_outlook.json")

    if not stock_list:
        log.error(f"stock_list_{market}.json 비어있음. 종료.")
        return

    # ── 시장 지수 (폭발 시그널용) ─────────────────────────────────
    log.info("시장 지수 데이터 수집 중...")
    market_index_df = fetch_market_index(market, period="1y")

    # ── 전체 종목 데이터 수집 ─────────────────────────────────────
    log.info(f"종목 데이터 수집 시작 ({len(stock_list)}종목)...")
    all_data = fetch_all_stocks(stock_list, market, period="3y")

    # ── 결과 컨테이너 ─────────────────────────────────────────────
    new_signals: list[dict] = []
    trend_buckets: dict[str, list[str]] = {
        "상승지속": [], "건강한조정": [], "횡보중": [], "하락주의": []
    }
    signal_codes_today: set[str] = set()

    # ── 종목별 분석 ───────────────────────────────────────────────
    for code, data in all_data.items():
        df   = data["df"]
        info = data["info"]
        meta = data["meta"]
        name = meta.get("종목명", code)

        # 재무 필터
        ok, reason = passes_financial_filter(info)
        if not ok:
            log.info(f"[{name}] 재무 필터 탈락 — {reason}")
            continue

        current_price = float(df["Close"].iloc[-1])

        # 시그널 탐지
        signals = run_signal_detection(df, info, market_index_df, market=market)

        # 업황 경고
        sector  = meta.get("섹터", "")
        outlook = sector_outlook.get(sector, "neutral")
        if signals and outlook == "negative":
            log.warning(f"[{name}] 시그널 발생, 업황 negative ⚠️")

        if signals:
            new_signals.append({
                "code":     code,
                "name":     name,
                "signals":  signals,
                "price":    current_price,
                "sector":   sector,
                "outlook":  outlook,
                "mentions": meta.get("언급일", []),
            })
            signal_codes_today.add(code)

            # 장 종료 후 실행(RECORD_SIGNALS=true)에서만 히스토리 기록
            if should_record:
                signal_names = [s["name"] for s in signals]
                signal_history = record_signals(
                    signal_history, code, name, signal_names, current_price, today
                )
        else:
            # 추세 분류 (시그널 없는 종목만 섹션4)
            trend = classify_trend(df)
            trend_buckets[trend].append({"name": name, "code": code})

        # 차트 생성
        sig_history_for_code = signal_history.get(code, [])
        # KR: 종목별 수급 시계열 (선택적)
        supply_df = None
        if market == "KR":
            try:
                from data_fetcher import fetch_stock_supply_demand
                supply_df = fetch_stock_supply_demand(code, market_name=meta.get("시장", ""))
            except Exception:
                pass

        try:
            generate_chart(
                df=df,
                code=code,
                meta=meta,
                signals_today=signals,
                signal_history=sig_history_for_code,
                market=market,
                supply_df=supply_df,
            )
        except Exception as e:
            log.warning(f"[{name}] 차트 생성 실패 — 스킵: {e}")

    # ── 승패 테이블 ───────────────────────────────────────────────
    log.info("승패 테이블 집계 중...")
    pnl_table = build_pnl_table(signal_history, stock_list, market, today)

    # ── 수급 데이터 (KR 전용) — KIS 우선, Naver fallback ─────────
    supply_top = {}
    kis_failed = False
    if market == "KR":
        log.info("수급 데이터 수집 중 (KIS → Naver fallback)...")
        # KIS 자격증명이 설정되어 있는데 토큰 발급에 실패하면 알림
        from data_fetcher import _get_kis_token
        kis_key_set = bool(os.environ.get("KIS_APP_KEY"))
        if kis_key_set and _get_kis_token() is None:
            kis_failed = True
            log.warning("⚠️ KIS 토큰 발급 실패 — APP key/secret 확인 필요")

        supply_top = fetch_supply_demand_kis(stock_list)
        if not supply_top.get("기관") and not supply_top.get("외인"):
            log.info("KIS 수급 없음 — Naver fallback")
            supply_top = fetch_supply_demand()

    # ── 텔레그램 메시지 생성 ──────────────────────────────────────
    pages_url = os.environ.get("PAGES_URL", "")
    chart_url = f"{pages_url}/index_{market}.html" if pages_url else ""

    results = {
        "신규시그널": new_signals,
        "승패테이블": pnl_table,
        "kis_failed":  kis_failed,
        "추세분석":   trend_buckets,
        "수급TOP":   supply_top,
    }

    messages = build_messages(
        market=market,
        mode=report_mode,
        now_str=now_str,
        results=results,
        chart_url=chart_url,
        pages_url=pages_url,
    )

    send_telegram(messages, dry_run=dry_run)

    # ── 장 종료 후 전용: 히스토리 저장 + index HTML 생성 ─────────
    if should_record:
        save_json(BASE_DIR / f"signal_history_{market}.json", signal_history)

        generate_index_html(
            market=market,
            signal_history=signal_history,
            stock_list=stock_list,
            charts_dir=CHARTS_DIR,
            out_path=BASE_DIR / f"index_{market}.html",
        )

    log.info(f"완료 | {market} {report_mode} | 신규시그널 {len(new_signals)}건")


# ══════════════════════════════════════════════════════════════════
# 진입점
# ══════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Stock Scouter")
    parser.add_argument(
        "--market",
        choices=["KR", "US"],
        required=True,
        help="분석 시장 (KR: 한국, US: 미국)",
    )
    parser.add_argument(
        "--report",
        choices=["SUMMARY", "FULL"],
        required=True,
        help="SUMMARY: 장중 모니터링(기록X) / FULL: 장마감(기록O + 인덱스 생성)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(market=args.market, report_mode=args.report)
