"""
reporter.py — 텔레그램 4섹션 메시지 생성 + 전송 + index HTML 생성
섹션별 별도 메시지 전송: 1.시그널 / 2.승패테이블 / 3.수급 / 4.추세분석
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

SIGNAL_ICONS = {
    "그랜드": "🟢",
    "골든":   "🟡",
    "응축":   "🟣",
    "폭발":   "🔴",
}

TREND_ICONS = {
    "상승지속":   "📈",
    "건강한조정": "📉",
    "횡보중":     "➡️",
    "하락주의":   "🔻",
}

TREND_DESC = {
    "상승지속":   "SMA20·60 위 + 20일 3%↑ (모멘텀 유지)",
    "건강한조정": "SMA60 위 + SMA20 아래 (단기 눌림, 관심)",
    "횡보중":     "SMA200 위 + 20일 ±5% 이내 (방향 대기)",
    "하락주의":   "SMA60 아래 또는 하락세 (신중 접근)",
}

SIGNAL_COLORS = {
    "그랜드": "#00C851",
    "골든":   "#FFB300",
    "응축":   "#AA00FF",
    "폭발":   "#FF3D00",
}


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━━"


def _fmt_price(px: float) -> str:
    return f"{px:,.0f}"


def _fmt_pnl(pnl: float) -> str:
    if abs(pnl) < 0.05:
        return "  ±0.0%➖"
    sign = "+" if pnl > 0 else ""
    icon = "✅" if pnl > 0 else "❌"
    return f"{sign}{pnl:.1f}%{icon}"


def _chart_link(pages_url: str, market: str, code: str, name: str) -> str:
    """종목별 차트 URL. pages_url 없으면 빈 문자열."""
    if not pages_url:
        return ""
    filename = f"{code}_{name}.html"
    return f"{pages_url}/charts/{market}/{filename}"


def _linked(text: str, url: str) -> str:
    """URL이 있으면 하이퍼링크, 없으면 텍스트 그대로."""
    if url:
        return f'<a href="{url}">{text}</a>'
    return text


# ══════════════════════════════════════════════════════════════════
# 섹션별 메시지 빌더
# ══════════════════════════════════════════════════════════════════

def _build_sec1(new_signals: list[dict], header: str, pages_url: str, market: str) -> str:
    """섹션 1: 핵심 시그널"""
    lines = [header, _sep(), "", "🔥 <b>1. 핵심 시그널</b>"]

    signal_codes: set[str] = set()

    if not new_signals:
        lines.append("  (오늘 발생한 시그널 없음)")
    else:
        by_type: dict[str, list[str]] = {k: [] for k in SIGNAL_ICONS}
        for item in new_signals:
            signal_codes.add(item["code"])
            warn = " ⚠️" if item.get("outlook") == "negative" else ""
            url  = _chart_link(pages_url, market, item["code"], item["name"])
            for sig in item["signals"]:
                sig_name = sig["name"] if isinstance(sig, dict) else sig
                score    = sig.get("score", 0) if isinstance(sig, dict) else 0
                label    = f"{_linked(item['name'], url)} ★{score}{warn}"
                by_type.setdefault(sig_name, []).append(label)

        for sig_name, icon in SIGNAL_ICONS.items():
            names = by_type.get(sig_name, [])
            if names:
                pad = " " * max(0, 4 - len(sig_name))
                lines.append(f"[{sig_name}{icon}]{pad}  {'  |  '.join(names)}")

    lines.append("")
    lines.append("  <i>그랜드🟢 1~3개월 | 골든🟡 2~4주 | 응축🟣 1~6개월 | 폭발🔴 1~2주</i>")

    return "\n".join(lines), signal_codes


def _build_sec2_chunks(table: list[dict], header: str) -> list[str]:
    """섹션 2: 승패 테이블. 20행씩 분할."""
    if not table:
        return ["\n".join([header, _sep(), "", "📊 <b>2. 승패 테이블</b>", "  (추적 중인 종목 없음)"])]

    win  = sum(1 for r in table if r["pnl"] >= 0)
    lose = len(table) - win
    rate = win / len(table) * 100

    sorted_table = sorted(table, key=lambda x: -x["pnl"])
    CHUNK = 20
    chunks_data = [sorted_table[i:i+CHUNK] for i in range(0, len(sorted_table), CHUNK)]
    total_chunks = len(chunks_data)

    msgs = []
    for idx, rows in enumerate(chunks_data, 1):
        part_tag = f" ({idx}/{total_chunks})" if total_chunks > 1 else ""
        lines = [
            header, _sep(), "",
            f"📊 <b>2. 승패 테이블{part_tag}</b>",
            f"<code>{'종목명':<9} {'시그널':<5} {'날짜':<6} {'진입가':>8} {'현재가':>8} {'수익률':>8}</code>",
            "<code>" + "─" * 48 + "</code>",
        ]
        for r in rows:
            sig_icon = SIGNAL_ICONS.get(r["signal"], "")
            d = r["entry_date"][5:].replace("-", "/")
            lines.append(
                f"<code>"
                f"{r['name'][:7]:<9}"
                f"{r['signal'][:3]}{sig_icon}  "
                f"{d}  "
                f"{_fmt_price(r['entry_px']):>8} "
                f"{_fmt_price(r['cur_px']):>8} "
                f"{_fmt_pnl(r['pnl']):>9}"
                f"</code>"
            )
        if idx == total_chunks:
            lines.append("<code>" + "─" * 48 + "</code>")
            lines.append(
                f"전체 승률: <b>{rate:.0f}%</b> "
                f"(승{win} / 패{lose}) | 보유 {len(table)}종목"
            )
        msgs.append("\n".join(lines))
    return msgs


def _build_sec3(supply: dict, market: str, header: str, kis_failed: bool = False) -> str:
    """섹션 3: 수급 분석"""
    lines = [header, _sep(), "", "💧 <b>3. 수급 분석</b>"]

    if kis_failed:
        lines.append("⚠️ <b>KIS API 연결 실패</b> — APP key/secret 확인 필요")
        lines.append("  (Naver 데이터로 fallback)")
        lines.append("")

    if market == "KR":
        for label in ["기관", "외인"]:
            items = supply.get(label, [])
            lines.append(f"[{label} 순매수 TOP3]")
            if not items:
                lines.append("  데이터 없음")
            else:
                for i, item in enumerate(items[:3], 1):
                    amt  = item.get("순매수", 0)
                    sign = "+" if amt >= 0 else ""
                    lines.append(f"  {i}위 {item['종목명']:<12} {sign}{amt:,}억")
    else:
        lines.append("  (미국 시장 — 수급 데이터 없음, 지표로 판단)")
    return "\n".join(lines)


def _build_sec4(trends: dict, signal_codes: set, pages_url: str, market: str,
                header: str, chart_url: str) -> str:
    """섹션 4: 추세 분석 + 푸터"""
    lines = [header, _sep(), "", "📈 <b>4. 추세 분석</b>", "  <i>(섹션1 종목 자동 제외)</i>"]

    has_any = False
    for trend_name, icon in TREND_ICONS.items():
        raw = trends.get(trend_name, [])
        stocks = []
        for s in raw:
            s_code = s["code"] if isinstance(s, dict) else s
            if s_code not in signal_codes:
                stocks.append(s)

        if stocks:
            linked = []
            for s in stocks[:20]:  # 카테고리당 최대 20종목
                if isinstance(s, dict):
                    s_name = s["name"]
                    s_code = s.get("code", "")
                    url    = _chart_link(pages_url, market, s_code, s_name)
                    linked.append(_linked(s_name, url))
                else:
                    linked.append(s)
            suffix = f" 외 {len(stocks)-20}개" if len(stocks) > 20 else ""
            desc = TREND_DESC.get(trend_name, "")
            lines.append(f"{icon} <b>{trend_name}</b>{suffix}  <i>← {desc}</i>")
            lines.append("  " + " | ".join(linked))
            has_any = True

    if not has_any:
        lines.append("  (분석 데이터 없음)")

    lines.append("")
    lines.append(_sep())
    if chart_url:
        lines.append(f'🔗 <a href="{chart_url}">전체 차트 ({market} 클라우드 보기)</a>')

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 공개 인터페이스
# ══════════════════════════════════════════════════════════════════

def build_messages(
    market: str,
    mode: str,
    now_str: str,
    results: dict,
    chart_url: str = "",
    pages_url: str = "",
) -> list[str]:
    """
    섹션별 메시지 리스트 반환 (각각 별도 텔레그램 전송).
    [섹션1, 섹션2(복수 가능), 섹션3, 섹션4]
    """
    mode_tag = "📊" if mode == "SUMMARY" else "📊✅"
    header   = f"{mode_tag} <b>AI Stock Scouter - {market}</b> | {now_str}"

    new_signals = results.get("신규시그널", [])
    table       = results.get("승패테이블", [])
    trends      = results.get("추세분석", {})
    supply      = results.get("수급TOP", {})

    kis_failed = results.get("kis_failed", False)

    sec1, signal_codes = _build_sec1(new_signals, header, pages_url, market)

    msgs = [sec1]
    msgs.extend(_build_sec2_chunks(table, header))
    msgs.append(_build_sec3(supply, market, header, kis_failed=kis_failed))
    msgs.append(_build_sec4(trends, signal_codes, pages_url, market, header, chart_url))

    return msgs


def build_message(
    market: str,
    mode: str,
    now_str: str,
    results: dict,
    chart_url: str = "",
    pages_url: str = "",
) -> str:
    """하위 호환용 — 모든 섹션을 하나의 문자열로 합쳐 반환."""
    return "\n\n".join(build_messages(
        market=market, mode=mode, now_str=now_str,
        results=results, chart_url=chart_url, pages_url=pages_url,
    ))


# ══════════════════════════════════════════════════════════════════
# 텔레그램 전송
# ══════════════════════════════════════════════════════════════════

def _split_html_safe(text: str, max_len: int = 4000) -> list[str]:
    """줄 단위로 분할해 HTML 태그가 중간에 잘리지 않도록 한다."""
    if len(text) <= max_len:
        return [text]
    chunks, buf, buf_len = [], [], 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if buf and buf_len + line_len > max_len:
            chunks.append("\n".join(buf))
            buf, buf_len = [], 0
        buf.append(line)
        buf_len += line_len
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def _send_one(text: str, token: str, chat_id: str) -> bool:
    chunks  = _split_html_safe(text)
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    ok      = True
    for chunk in chunks:
        try:
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
                timeout=30,
            )
            if not resp.ok:
                log.error(f"텔레그램 오류: {resp.text}")
                ok = False
        except Exception as e:
            log.error(f"텔레그램 전송 예외: {e}")
            ok = False
    return ok


def send_telegram(messages: "str | list[str]", dry_run: bool = False) -> bool:
    """
    섹션별 메시지 리스트 또는 단일 문자열을 텔레그램으로 전송.
    dry_run=True면 콘솔 출력만.
    """
    if isinstance(messages, str):
        messages = [messages]

    if dry_run:
        print("\n" + "=" * 60)
        print("[DRY RUN] 텔레그램 전송 미리보기:")
        print("=" * 60)
        for i, msg in enumerate(messages, 1):
            print(f"\n--- 메시지 {i}/{len(messages)} ---")
            print(re.sub(r"<[^>]+>", "", msg))
        print("=" * 60 + "\n")
        return True

    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수 미설정")
        return False

    ok = True
    for msg in messages:
        if not _send_one(msg, token, chat_id):
            ok = False

    if ok:
        log.info(f"텔레그램 전송 성공 ({len(messages)}개 메시지)")
    return ok


# ══════════════════════════════════════════════════════════════════
# index HTML 생성
# ══════════════════════════════════════════════════════════════════

def generate_index_html(
    market: str,
    signal_history: dict,
    stock_list: dict,
    charts_dir: Path,
    out_path: Path,
) -> None:
    today = datetime.now().strftime("%Y-%m-%d")

    cards_html = []
    for code, entries in signal_history.items():
        for entry in entries:
            if entry.get("유효기간만료", "") < today:
                continue

            name     = entry.get("종목명", code)
            sig      = entry.get("시그널", "")
            entry_dt = entry.get("선정일", "")
            entry_px = entry.get("진입가", 0)
            color    = SIGNAL_COLORS.get(sig, "#888888")
            icon     = SIGNAL_ICONS.get(sig, "")

            chart_filename = f"{code}_{name}.html"
            chart_path     = charts_dir / market / chart_filename
            chart_link     = f"charts/{market}/{chart_filename}" if chart_path.exists() else "#"

            cards_html.append(f"""
        <div class="card">
          <div class="badge" style="background:{color}">{sig} {icon}</div>
          <div class="name">{name}</div>
          <div class="code">{code}</div>
          <div class="info">선정일: {entry_dt}</div>
          <div class="info">진입가: {_fmt_price(entry_px)}</div>
          <a class="btn" href="{chart_link}" target="_blank">📊 차트 보기</a>
        </div>""")

    cards   = "\n".join(cards_html) if cards_html else "<p style='color:#aaa'>기록된 시그널이 없습니다.</p>"
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Stock Scouter — {market}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0E0E0E; color: #E0E0E0;
      font-family: 'Segoe UI', sans-serif;
      padding: 20px;
    }}
    h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
    .sub {{ color: #888; font-size: 0.85rem; margin-bottom: 20px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 14px;
    }}
    .card {{
      background: #1A1A1A; border: 1px solid #333;
      border-radius: 10px; padding: 16px;
      display: flex; flex-direction: column; gap: 6px;
    }}
    .badge {{
      display: inline-block; border-radius: 5px;
      padding: 3px 10px; font-size: 0.8rem;
      font-weight: bold; color: #fff;
      width: fit-content;
    }}
    .name {{ font-size: 1.05rem; font-weight: bold; }}
    .code {{ color: #888; font-size: 0.8rem; }}
    .info {{ font-size: 0.85rem; color: #bbb; }}
    .btn {{
      margin-top: 8px; padding: 7px 0;
      background: #2196F3; color: #fff;
      border-radius: 6px; text-align: center;
      text-decoration: none; font-size: 0.85rem;
      font-weight: bold;
    }}
    .btn:hover {{ background: #1565C0; }}
  </style>
</head>
<body>
  <h1>📊 AI Stock Scouter — {market} 시장</h1>
  <p class="sub">마지막 업데이트: {updated} | 유효기간 내 시그널 보유 종목</p>
  <div class="grid">
{cards}
  </div>
</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    log.info(f"index_{market}.html 생성 완료 → {out_path}")
