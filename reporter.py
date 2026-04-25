"""
reporter.py — 텔레그램 4섹션 메시지 생성 + 전송 + index HTML 생성
"""

import logging
import os
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

SIGNAL_COLORS = {
    "그랜드": "#00C851",
    "골든":   "#FFB300",
    "응축":   "#AA00FF",
    "폭발":   "#FF3D00",
}

DAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


# ══════════════════════════════════════════════════════════════════
# 메시지 빌더
# ══════════════════════════════════════════════════════════════════

def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━━"


def _fmt_price(px: float) -> str:
    return f"{px:,.0f}"


def _fmt_pnl(pnl: float) -> str:
    sign = "+" if pnl >= 0 else ""
    icon = "✅" if pnl >= 0 else "❌"
    return f"{sign}{pnl:.1f}% {icon}"


def build_message(
    market: str,
    mode: str,
    now_str: str,
    results: dict,
    chart_url: str = "",
) -> str:
    """
    4섹션 텔레그램 메시지 생성.
    results 구조:
      신규시그널: [{code, name, signals, price, sector, outlook}]
      승패테이블: [{name, signal, entry_date, entry_px, cur_px, pnl}]
      추세분석:   {상승지속: [name,...], 건강한조정: [...], 횡보중: [...], 하락주의: [...]}
      수급TOP:    {기관: [{종목명, 순매수},...], 외인: [...]}
    """
    lines = []

    # ── 헤더 ──────────────────────────────────────────────────────
    mode_tag = "📊" if mode == "SUMMARY" else "📊✅"
    lines.append(f"{mode_tag} <b>AI Stock Scouter - {market}</b> | {now_str}")
    lines.append(_sep())
    lines.append("")

    # ── 섹션 1: 핵심 시그널 ───────────────────────────────────────
    lines.append("🔥 <b>1. 핵심 시그널</b>")

    new_signals = results.get("신규시그널", [])
    signal_codes_today = set()

    if not new_signals:
        lines.append("  (오늘 발생한 시그널 없음)")
    else:
        by_type: dict[str, list[str]] = {k: [] for k in SIGNAL_ICONS}
        for item in new_signals:
            signal_codes_today.add(item["code"])
            warn = " ⚠️" if item.get("outlook") == "negative" else ""
            for sig in item["signals"]:
                by_type.setdefault(sig, []).append(f"{item['name']}{warn}")

        for sig_name, icon in SIGNAL_ICONS.items():
            names = by_type.get(sig_name, [])
            if names:
                pad = " " * max(0, 4 - len(sig_name))
                lines.append(f"[{sig_name}{icon}]{pad}  {' | '.join(names)}")

    lines.append("")
    lines.append(_sep())

    # ── 섹션 2: 승패 테이블 ───────────────────────────────────────
    lines.append("📊 <b>2. 승패 테이블</b>")

    table = results.get("승패테이블", [])
    if not table:
        lines.append("  (추적 중인 종목 없음)")
    else:
        win = sum(1 for r in table if r["pnl"] >= 0)
        lose = len(table) - win
        rate = win / len(table) * 100 if table else 0

        lines.append(
            f"{'종목명':<10} {'시그널':<6} {'선정일':<8} "
            f"{'진입가':>8} {'현재가':>8} {'수익률':>10}"
        )
        lines.append("─" * 52)

        for r in sorted(table, key=lambda x: -x["pnl"]):
            sig_icon = SIGNAL_ICONS.get(r["signal"], "")
            d = r["entry_date"][5:].replace("-", "/")  # "04/22"
            lines.append(
                f"{r['name'][:8]:<10} "
                f"{r['signal']}{sig_icon}  "
                f"{d}  "
                f"{_fmt_price(r['entry_px']):>8} "
                f"{_fmt_price(r['cur_px']):>8} "
                f"{_fmt_pnl(r['pnl']):>12}"
            )

        lines.append("─" * 52)
        lines.append(
            f"전체 승률: <b>{rate:.0f}%</b> "
            f"(승{win} / 패{lose}) | 보유 {len(table)}종목"
        )

    lines.append("")
    lines.append(_sep())

    # ── 섹션 3: 수급 분석 (KR 전용) ──────────────────────────────
    if market == "KR":
        lines.append("💧 <b>3. 수급 분석</b>")
        supply = results.get("수급TOP", {})

        for label in ["기관", "외인"]:
            items = supply.get(label, [])
            lines.append(f"[{label} 순매수 TOP3]")
            if not items:
                lines.append("  데이터 없음")
            else:
                for i, item in enumerate(items[:3], 1):
                    amt = item.get("순매수", 0)
                    sign = "+" if amt >= 0 else ""
                    lines.append(
                        f"  {i}위 {item['종목명']:<12} {sign}{amt:,}억"
                    )
        lines.append("")
        lines.append(_sep())
    else:
        # US는 수급 없이 섹션 번호 유지
        lines.append("💧 <b>3. 수급 분석</b>")
        lines.append("  (미국 시장 — 수급 데이터 없음, 지표로 판단)")
        lines.append("")
        lines.append(_sep())

    # ── 섹션 4: 추세 분석 (시그널 종목 제외) ─────────────────────
    lines.append("📈 <b>4. 추세 분석</b>")
    lines.append("  <i>(섹션1 종목 자동 제외)</i>")

    trends = results.get("추세분석", {})
    has_any = False
    for trend_name, icon in TREND_ICONS.items():
        names = [
            n for n in trends.get(trend_name, [])
            if n not in signal_codes_today
        ]
        if names:
            lines.append(f"{icon} {trend_name}  {'  |  '.join(names)}")
            has_any = True

    if not has_any:
        lines.append("  (분석 데이터 없음)")

    lines.append("")
    lines.append(_sep())

    # ── 푸터 ──────────────────────────────────────────────────────
    if chart_url:
        lines.append(f'🔗 <a href="{chart_url}">전체 차트 ({market} 클라우드 보기)</a>')

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 텔레그램 전송
# ══════════════════════════════════════════════════════════════════

def send_telegram(text: str, dry_run: bool = False) -> bool:
    """HTML parse_mode로 텔레그램 전송. dry_run=True면 콘솔 출력만."""
    if dry_run:
        print("\n" + "=" * 60)
        print("[DRY RUN] 텔레그램 전송 미리보기:")
        print("=" * 60)
        # HTML 태그 제거해서 출력
        import re
        clean = re.sub(r"<[^>]+>", "", text)
        print(clean)
        print("=" * 60 + "\n")
        return True

    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수 미설정")
        return False

    # 메시지가 4096자 초과 시 분할 전송
    max_len = 4000
    chunks  = [text[i:i+max_len] for i in range(0, len(text), max_len)]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok  = True
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

    if ok:
        log.info("텔레그램 전송 성공")
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
    """
    signal_history 기반으로 index_{market}.html 생성.
    각 카드: 종목명 / 시그널 배지 / 선정일 / 진입가 / 수익률 / 차트 링크
    """
    today = datetime.now().strftime("%Y-%m-%d")

    cards_html = []
    for code, entries in signal_history.items():
        for entry in entries:
            if entry.get("유효기간만료", "") < today:
                continue

            name      = entry.get("종목명", code)
            sig       = entry.get("시그널", "")
            entry_dt  = entry.get("선정일", "")
            entry_px  = entry.get("진입가", 0)
            color     = SIGNAL_COLORS.get(sig, "#888888")
            icon      = SIGNAL_ICONS.get(sig, "")

            # 차트 파일 경로 (상대 경로)
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

    cards = "\n".join(cards_html) if cards_html else "<p style='color:#aaa'>기록된 시그널이 없습니다.</p>"
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
