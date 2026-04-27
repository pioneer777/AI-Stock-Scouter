"""
visualizer.py — Plotly 3단 서브플롯 차트 (커스텀 HTML 버튼 구조)

구조 변경 요점:
  - Plotly 내장 rangeselector 제거 → HTML 커스텀 버튼 (post_script로 주입)
  - 버튼 클릭: xaxis.range + 모든 yaxis bounds 직접 계산해서 한번만 relayout
  - 이벤트 가로채기 없음 → 피드백 루프 없음
  - 좌측 여백 0%, 우측 여백 3% (기간별 절대값 계산)
  - 디폴트 뷰: 6개월
  - 토글: 같은 버튼 재클릭 → 6M 기본뷰 복귀
  - 모바일 핀치줌: touch-action auto → 브라우저 페이지 확대
  - 범례: 4개 독립 legend (chart1 좌/우, chart3 좌/우)
  - 박스: paper 좌표 상단 고정, 같은 날짜 xshift로 좌우 회피
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

log = logging.getLogger(__name__)

BASE_DIR   = Path(__file__).parent
CHARTS_DIR = BASE_DIR / "charts"

SIGNAL_COLORS = {
    "그랜드": "#00C851",
    "골든":   "#FFB300",
    "응축":   "#AA00FF",
    "폭발":   "#FF3D00",
}

# 중요도: SMA200 > SMA20 > SMA60 = SMA120
SMA_STYLES = [
    ("SMA20",  "#7C4DFF", 2.0, "SMA20"),   # 보라
    ("SMA60",  "#4CAF50", 1.5, "SMA60"),   # 초록
    ("SMA120", "#D4AC0D", 1.5, "SMA120"),  # 진한 노랑
    ("SMA200", "#800020", 2.5, "SMA200"),  # 버건디
]

_CANDLE_UP   = "#EF5350"   # 빨강 (상승)
_CANDLE_DOWN = "#1E88E5"   # 파랑 (하락)

# ── 서브플롯 도메인 계산 (row_heights=[0.55,0.18,0.27], spacing=0.03) ──
# chart1(주가): paper y ∈ [0.483, 1.0]
# chart2(거래량): paper y ∈ [0.284, 0.453]
# chart3(MACD/RSI): paper y ∈ [0.0, 0.254]
_CHART1_TOP  = 0.98   # 박스 배치 y (chart1 내부 상단)
_CHART3_TOP  = 0.254  # legend3/4 y 기준

# ── 커스텀 버튼 + 초기화 JS ───────────────────────────────────────────
_CHART_JS = r"""
(function () {
    var gd = document.getElementById('chart');
    if (!gd) return;

    /* 모바일 핀치줌 → 브라우저 페이지 확대/축소 (차트가 터치 캡처 안 함) */
    gd.style.touchAction = 'auto';
    setTimeout(function () {
        gd.querySelectorAll('.draglayer,.dragcover,.nsewdrag,.nwdrag,.ewdrag,.sndrag')
          .forEach(function (el) { el.style.touchAction = 'auto'; });
    }, 600);

    /* viewport: user-scalable 허용 */
    (function () {
        var m = document.querySelector('meta[name="viewport"]');
        if (m) { m.content = 'width=device-width,initial-scale=1.0'; }
        else {
            m = document.createElement('meta');
            m.name = 'viewport';
            m.content = 'width=device-width,initial-scale=1.0';
            document.head.appendChild(m);
        }
    }());

    /* ── 날짜 유틸 ───────────────────────────────────────────────── */
    function addDays(d, n)    { var dt=new Date(d); dt.setDate(dt.getDate()+n); return dt.toISOString().slice(0,10); }
    function subMonths(d, n)  { var dt=new Date(d); dt.setMonth(dt.getMonth()-n); return dt.toISOString().slice(0,10); }
    function subYears(d, n)   { var dt=new Date(d); dt.setFullYear(dt.getFullYear()-n); return dt.toISOString().slice(0,10); }

    function getDataEnd() {
        var latest = '';
        gd.data.forEach(function (tr) {
            if (!tr.x || !tr.x.length) return;
            var s = String(tr.x[tr.x.length-1]).slice(0,10);
            if (s > latest) latest = s;
        });
        return latest || new Date().toISOString().slice(0,10);
    }
    function getDataStart() {
        var earliest = '';
        gd.data.forEach(function (tr) {
            if (!tr.x || !tr.x.length) return;
            var s = String(tr.x[0]).slice(0,10);
            if (!earliest || s < earliest) earliest = s;
        });
        return earliest || new Date().toISOString().slice(0,10);
    }

    /* ── 가시 x 구간 내 y 최솟값/최댓값 ────────────────────────── */
    function yBounds(axisId, t0, t1) {
        var lo = Infinity, hi = -Infinity;
        gd.data.forEach(function (tr) {
            if ((tr.yaxis || 'y') !== axisId) return;
            var xs = tr.x; if (!xs || !xs.length) return;
            for (var i = 0; i < xs.length; i++) {
                var t = new Date(xs[i]).getTime();
                if (isNaN(t) || t < t0 || t > t1) continue;
                if (tr.type === 'candlestick') {
                    if (tr.low  && tr.low[i]  != null) lo = Math.min(lo, +tr.low[i]);
                    if (tr.high && tr.high[i] != null) hi = Math.max(hi, +tr.high[i]);
                } else if (tr.y && tr.y[i] != null) {
                    var v = +tr.y[i]; if (!isNaN(v)) { lo=Math.min(lo,v); hi=Math.max(hi,v); }
                }
            }
        });
        return (isFinite(lo) && isFinite(hi)) ? [lo, hi] : null;
    }

    /* ── x + 모든 y 동시 relayout ───────────────────────────────── */
    function applyRange(x0, x1) {
        var ms0 = new Date(x0).getTime(), ms1 = new Date(x1).getTime();
        var upd = { 'xaxis.range[0]': x0, 'xaxis.range[1]': x1 };

        var p1 = yBounds('y', ms0, ms1);
        if (p1) {
            var pad1 = Math.max(p1[1]-p1[0], p1[0]*0.005) * 0.04;
            upd['yaxis.range'] = [p1[0]-pad1, p1[1]+pad1*1.5];
        }
        var p2 = yBounds('y2', ms0, ms1);
        if (p2) upd['yaxis2.range'] = [0, p2[1]*1.15];
        var p3 = yBounds('y3', ms0, ms1);
        if (p3) {
            var r3 = Math.max(p3[1]-p3[0], Math.abs(p3[0]||0.01)*0.2);
            upd['yaxis3.range'] = [p3[0]-r3*0.12, p3[1]+r3*0.12];
        }
        Plotly.relayout(gd, upd);
    }

    /* ── 버튼별 [x0, x1] 계산 ────────────────────────────────────
       우측 여백: 기간의 3% (캘린더 일수 기준)
       idx: 0=1M, 1=3M, 2=1Y, 3=2Y, 4=전체, -1=6M(default) */
    function getRange(idx) {
        var end = getDataEnd();
        var x0, margin;
        if      (idx===0) { x0=subMonths(end,1);  margin=1;  }
        else if (idx===1) { x0=subMonths(end,3);  margin=3;  }
        else if (idx===2) { x0=subYears(end,1);   margin=11; }
        else if (idx===3) { x0=subYears(end,2);   margin=22; }
        else if (idx===4) { x0=getDataStart();     margin=33; }
        else              { x0=subMonths(end,6);  margin=5;  }
        return [x0, addDays(end, margin)];
    }

    /* ── 커스텀 버튼 생성 ────────────────────────────────────────── */
    var _active = -1;
    var _btns   = [];
    var LABELS  = ['1M','3M','1Y','2Y','전체'];

    function styleBtn() {
        _btns.forEach(function (b, j) {
            var on = (j === _active);
            b.style.background = on ? '#222222' : '#F0F0F0';
            b.style.color      = on ? '#FFFFFF'  : '#333333';
            b.style.fontWeight = on ? '600'      : '400';
            b.style.borderColor= on ? '#222222'  : '#CCCCCC';
        });
    }

    var bar = document.createElement('div');
    bar.style.cssText = 'display:flex;gap:6px;justify-content:center;padding:10px 0 4px;font-family:Segoe UI,sans-serif;';

    LABELS.forEach(function (label, idx) {
        var btn = document.createElement('button');
        btn.textContent = label;
        btn.style.cssText = 'padding:5px 15px;border:1px solid #CCCCCC;border-radius:4px;cursor:pointer;font-size:13px;';
        btn.addEventListener('click', function () {
            _active = (_active === idx) ? -1 : idx;
            styleBtn();
            var r = getRange(_active);
            applyRange(r[0], r[1]);
        });
        _btns.push(btn);
        bar.appendChild(btn);
    });
    styleBtn();
    gd.parentNode.insertBefore(bar, gd);

    /* ── 모바일 높이 핏 ─────────────────────────────────────────── */
    function fitH() {
        var vv = window.visualViewport;
        var h  = (vv ? vv.height : 0) || window.innerHeight;
        if (h > 100) Plotly.relayout(gd, {height: Math.max(400, Math.floor(h))});
    }
    window.addEventListener('resize', fitH);
    window.addEventListener('orientationchange', function () { setTimeout(fitH, 350); });
    if (window.visualViewport) window.visualViewport.addEventListener('resize', fitH);

    /* ── 초기 6M 뷰 적용 ────────────────────────────────────────── */
    gd.on('plotly_afterplot', function () {
        if (gd._initDone) return;
        gd._initDone = true;
        var r = getRange(-1);
        applyRange(r[0], r[1]);
        setTimeout(fitH, 300);
    });
}());
"""


# ══════════════════════════════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════════════════════════════

def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _date_label(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.month}/{dt.day}"
    except Exception:
        return date_str


def _get_close_at(df: pd.DataFrame, date_str: str) -> float | None:
    try:
        idx = pd.Timestamp(date_str)
        if idx in df.index:
            return float(df.loc[idx, "Close"])
        pos = min(df.index.searchsorted(idx), len(df) - 1)
        return float(df.iloc[pos]["Close"])
    except Exception:
        return None


def _get_high_at(df: pd.DataFrame, date_str: str) -> float | None:
    try:
        idx = pd.Timestamp(date_str)
        if idx in df.index:
            return float(df.loc[idx, "High"])
        pos = min(df.index.searchsorted(idx), len(df) - 1)
        return float(df.iloc[pos]["High"])
    except Exception:
        return None


def _assign_xshifts(items: list[dict]) -> list[dict]:
    """
    같은 날짜 박스끼리 겹치지 않도록 xshift(px) 배정.
    순서: 0 → +75 → -75 → +150 → -150 ...
    """
    _offsets = [0, 75, -75, 150, -150, 225, -225]
    date_count: dict[str, int] = {}
    for item in items:
        d = item["date"]
        n = date_count.get(d, 0)
        item["xshift"] = _offsets[min(n, len(_offsets) - 1)]
        date_count[d] = n + 1
    return items


# ══════════════════════════════════════════════════════════════════
# 메인 차트 생성
# ══════════════════════════════════════════════════════════════════

def generate_chart(
    df: pd.DataFrame,
    code: str,
    meta: dict,
    signals_today: list,
    signal_history: list[dict],
    market: str,
    supply_df: pd.DataFrame | None = None,
) -> Path | None:
    if df is None or df.empty:
        log.warning(f"[{code}] 데이터 없음 — 차트 생성 스킵")
        return None

    name     = meta.get("종목명", code)
    mentions = meta.get("언급일", [])
    today    = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    # ── 서브플롯 ────────────────────────────────────────────────
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.18, 0.27],
        specs=[
            [{"secondary_y": False}],
            [{"secondary_y": False}],
            [{"secondary_y": True}],
        ],
    )

    # ════════════════════════════════════════════════════════════
    # 1단: 캔들스틱 + SMA
    # ════════════════════════════════════════════════════════════

    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        increasing=dict(line=dict(color=_CANDLE_UP),   fillcolor=_CANDLE_UP),
        decreasing=dict(line=dict(color=_CANDLE_DOWN), fillcolor=_CANDLE_DOWN),
        showlegend=False, name="",
        hovertemplate=(
            "<b>%{x|%Y-%m-%d}</b><br>"
            "시가 %{open:,.0f}  고가 %{high:,.0f}<br>"
            "저가 %{low:,.0f}  종가 %{close:,.0f}"
            "<extra></extra>"
        ),
    ), row=1, col=1)

    # SMA — legend (chart1 좌측 상단 외부)
    for col, color, width, label in SMA_STYLES:
        if col in df.columns and df[col].notna().any():
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col],
                line=dict(color=color, width=width),
                name=label, showlegend=True,
                legend="legend",
                hoverinfo="skip",
            ), row=1, col=1)

    # 시그널 범례 더미 — legend2 (chart1 우측 상단 외부)
    for sig_name, sig_color in SIGNAL_COLORS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(color=sig_color, size=11, symbol="square"),
            name=sig_name, showlegend=True,
            legend="legend2", hoverinfo="skip",
        ), row=1, col=1)

    # ════════════════════════════════════════════════════════════
    # 2단: 거래량
    # ════════════════════════════════════════════════════════════

    vol_colors = [
        _CANDLE_UP if float(c) >= float(o) else _CANDLE_DOWN
        for c, o in zip(df["Close"], df["Open"])
    ]
    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"],
        marker=dict(color=vol_colors, opacity=1.0),
        showlegend=False, name="거래량",
        hovertemplate="%{y:,.0f}<extra>거래량</extra>",
    ), row=2, col=1)

    if "Volume_MA20" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Volume_MA20"],
            line=dict(color="#333333", width=1.2, dash="dot"),
            showlegend=False, name="거래량MA20", hoverinfo="skip",
        ), row=2, col=1)

    if "Volume_MA200" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Volume_MA200"],
            line=dict(color="#888888", width=1.0, dash="dot"),
            showlegend=False, name="거래량MA200", hoverinfo="skip",
        ), row=2, col=1)

    if market == "KR" and supply_df is not None and not supply_df.empty:
        _add_supply_traces(fig, supply_df)

    # ════════════════════════════════════════════════════════════
    # 3단: MACD + RSI
    # ════════════════════════════════════════════════════════════

    if "MACD_Hist" in df.columns:
        macd_colors = [
            _CANDLE_UP if (v >= 0 if pd.notna(v) else False) else _CANDLE_DOWN
            for v in df["MACD_Hist"]
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=df["MACD_Hist"],
            marker_color=macd_colors,
            showlegend=False, name="MACD Hist", hoverinfo="skip",
        ), row=3, col=1)

    # MACD — legend3 (chart3 좌측 상단 외부)
    if "MACD" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD"],
            line=dict(color="#2196F3", width=1.2),
            showlegend=True, name="MACD",
            legend="legend3", hoverinfo="skip",
        ), row=3, col=1)

    if "MACD_Signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD_Signal"],
            line=dict(color="#FF9800", width=1.2),
            showlegend=True, name="시그널선",
            legend="legend3", hoverinfo="skip",
        ), row=3, col=1)

    # RSI — legend4 (chart3 우측 상단 외부)
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"],
            line=dict(color="#555555", width=1.2, dash="dot"),
            showlegend=True, name="RSI",
            legend="legend4",
            hovertemplate="RSI: %{y:.1f}<extra></extra>",
        ), row=3, col=1, secondary_y=True)

        for level, color in [(70, _CANDLE_UP), (30, _CANDLE_DOWN)]:
            fig.add_trace(go.Scatter(
                x=[df.index[0], df.index[-1]], y=[level, level],
                mode="lines",
                line=dict(color=color, width=0.8, dash="dot"),
                showlegend=False, hoverinfo="skip",
            ), row=3, col=1, secondary_y=True)

    # ════════════════════════════════════════════════════════════
    # 어노테이션 + 세로 점선
    # 모든 박스: paper 좌표 chart1 내부 상단 고정
    # 같은 날짜 → xshift로 좌우 회피
    # 시그널 + 언급 모두 세로 점선 표시
    # ════════════════════════════════════════════════════════════

    annotations: list[dict] = []
    shapes:      list[dict] = []

    # 박스 후보 수집 (date, text, bgcolor, font_color, border_color)
    box_items: list[dict] = []

    # TODAY 현재가 박스 (고정 우측 상단, 날짜 무관)
    if not df.empty:
        latest_close = float(df["Close"].iloc[-1])
        annotations.append(dict(
            x=0.99, xref="paper",
            y=_CHART1_TOP, yref="paper",
            text=f"<b>TODAY {latest_close:,.0f}</b>",
            showarrow=False,
            bgcolor="#222222",
            font=dict(color="#FFFFFF", size=10),
            bordercolor="#444444", borderwidth=1, borderpad=4,
            xanchor="right", yanchor="top",
        ))

    # 시그널 히스토리 박스 + 오늘 SUMMARY 모드 시그널 합산
    all_sig_entries = list(signal_history)
    existing_today_sigs = {
        e["시그널"] for e in signal_history if e.get("선정일") == today_str
    }
    for sig in signals_today:
        sig_name = sig["name"] if isinstance(sig, dict) else sig
        if sig_name not in existing_today_sigs:
            latest_px = float(df["Close"].iloc[-1]) if not df.empty else 0
            all_sig_entries.append({
                "시그널": sig_name,
                "선정일": today_str,
                "진입가": latest_px,
            })

    for entry in all_sig_entries:
        date_str = entry.get("선정일", "")
        sig      = entry.get("시그널", "")
        px       = entry.get("진입가", 0)
        color    = SIGNAL_COLORS.get(sig, "#888888")
        box_items.append({
            "date":         date_str,
            "text":         f"<b>{sig}_{_date_label(date_str)}</b><br>{px:,.0f}",
            "bgcolor":      _hex_to_rgba(color, 0.15),
            "font_color":   color,
            "border_color": color,
            "line_color":   color,
            "xshift":       0,
        })

    # 언급일 박스
    for mention in mentions:
        date_str = mention.get("날짜", "")
        m_ord    = mention.get("차수", "")
        m_close  = _get_close_at(df, date_str)
        price_line = f"<br>{m_close:,.0f}" if m_close else ""
        box_items.append({
            "date":         date_str,
            "text":         f"<b>{m_ord}_{_date_label(date_str)}</b>{price_line}",
            "bgcolor":      "#FFFFFF",
            "font_color":   "#222222",
            "border_color": "#444444",
            "line_color":   "#AAAAAA",
            "xshift":       0,
        })

    # 같은 날짜 xshift 배정
    box_items = _assign_xshifts(box_items)

    # 박스 + 세로점선 생성
    for item in box_items:
        date_str = item["date"]
        if not date_str:
            continue

        # 세로 점선 (전체 차트 높이)
        shapes.append(dict(
            type="line",
            x0=date_str, x1=date_str,
            y0=0, y1=1,
            xref="x", yref="paper",
            line=dict(color=item["line_color"], width=1, dash="dash"),
        ))

        # 박스 (chart1 내부 상단)
        annotations.append(dict(
            x=date_str, xref="x",
            y=_CHART1_TOP, yref="paper",
            text=item["text"],
            showarrow=False,
            xshift=item["xshift"],
            bgcolor=item["bgcolor"],
            font=dict(color=item["font_color"], size=10),
            bordercolor=item["border_color"], borderwidth=1.5, borderpad=4,
            xanchor="center", yanchor="top",
        ))

    # RSI 현재값 박스 (chart3 우측 상단)
    if "RSI" in df.columns and df["RSI"].notna().any():
        latest_rsi = float(df["RSI"].dropna().iloc[-1])
        rsi_color  = "#EF5350" if latest_rsi >= 70 else ("#1E88E5" if latest_rsi <= 30 else "#555555")
        annotations.append(dict(
            x=0.99, xref="paper",
            y=_CHART3_TOP - 0.01, yref="paper",
            text=f"<b>RSI {latest_rsi:.0f}</b>",
            showarrow=False,
            bgcolor=rsi_color,
            font=dict(color="#FFFFFF", size=10),
            bordercolor=rsi_color, borderwidth=1, borderpad=4,
            xanchor="right", yanchor="top",
        ))

    # ════════════════════════════════════════════════════════════
    # 레이아웃
    # ════════════════════════════════════════════════════════════

    axis_common = dict(
        showgrid=True,  gridcolor="#EBEBEB",
        showline=True,  linecolor="#CCCCCC",
        mirror=True, zeroline=False,
        tickfont=dict(color="#555555"),
    )
    x_common = dict(
        **axis_common,
        rangeslider=dict(visible=False),
        rangebreaks=[dict(bounds=["sat", "mon"])],
        type="date",
        showspikes=True, spikemode="across",
        spikesnap="cursor", spikecolor="#AAAAAA",
        spikethickness=1, spikedash="solid",
    )

    fig.update_layout(
        height=1000,
        title=dict(
            text=f"<b>{name} ({code})</b>",
            font=dict(size=16, color="#222222"),
            x=0.5, xanchor="center",
        ),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FAFAFA",
        font=dict(color="#222222", family="Segoe UI, sans-serif"),
        dragmode=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#F5F5F5", font_color="#222222", bordercolor="#CCCCCC"),
        margin=dict(l=60, r=60, t=80, b=40),

        # legend: SMA — chart1 좌측 상단 외부
        legend=dict(
            orientation="h",
            x=0.0, y=1.02,
            xanchor="left", yanchor="bottom",
            font=dict(size=11, color="#333333"),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#DDDDDD", borderwidth=1,
            itemsizing="constant",
        ),
        # legend2: 시그널 — chart1 우측 상단 외부
        legend2=dict(
            orientation="h",
            x=1.0, y=1.02,
            xanchor="right", yanchor="bottom",
            font=dict(size=11, color="#333333"),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#DDDDDD", borderwidth=1,
            itemsizing="constant",
        ),
        # legend3: MACD/시그널선 — chart3 좌측 상단 외부
        legend3=dict(
            orientation="h",
            x=0.0, y=_CHART3_TOP + 0.005,
            xanchor="left", yanchor="bottom",
            font=dict(size=10, color="#333333"),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#DDDDDD", borderwidth=1,
            itemsizing="constant",
        ),
        # legend4: RSI — chart3 우측 상단 외부
        legend4=dict(
            orientation="h",
            x=1.0, y=_CHART3_TOP + 0.005,
            xanchor="right", yanchor="bottom",
            font=dict(size=10, color="#333333"),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#DDDDDD", borderwidth=1,
            itemsizing="constant",
        ),

        annotations=annotations,
        shapes=shapes,

        # rangeselector 없음 — 커스텀 버튼으로 대체
        xaxis=dict(
            **x_common,
            showticklabels=False,
        ),
        xaxis2=dict(**x_common, showticklabels=False, matches="x"),
        xaxis3=dict(**x_common, showticklabels=True,
                    tickformat="%y/%m/%d", matches="x"),

        yaxis=dict(
            **axis_common,
            title=dict(text="주가", standoff=5, font=dict(size=11, color="#888888")),
            tickformat=",",
            showspikes=True, spikemode="across",
            spikethickness=1, spikecolor="#CCCCCC",
        ),
        yaxis2=dict(
            **axis_common,
            title=dict(text="거래량", standoff=5, font=dict(size=11, color="#888888")),
            tickformat=".2s",
            showspikes=True, spikemode="across",
            spikethickness=1, spikecolor="#CCCCCC",
        ),
        yaxis3=dict(
            **axis_common,
            title=dict(text="MACD", standoff=5, font=dict(size=11, color="#888888")),
            showspikes=True, spikemode="across",
            spikethickness=1, spikecolor="#CCCCCC",
        ),
        yaxis4=dict(
            range=[0, 100],
            showgrid=False, showline=False,
            tickvals=[30, 70], ticktext=["30", "70"],
            tickfont=dict(size=9, color="#888888"),
            title=dict(text="RSI", standoff=5, font=dict(size=10, color="#888888")),
        ),
    )

    # ── 저장 ────────────────────────────────────────────────────
    out_dir = CHARTS_DIR / market
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{code}_{name}.html"

    fig.write_html(
        str(out_path),
        include_plotlyjs="cdn",
        full_html=True,
        div_id="chart",
        post_script=_CHART_JS,
        config={
            "displayModeBar": False,
            "staticPlot":     False,
            "scrollZoom":     False,
            "responsive":     True,
        },
    )
    log.info(f"차트 저장 → {out_path}")
    return out_path


# ══════════════════════════════════════════════════════════════════
# 수급 트레이스 (2단 차트용)
# ══════════════════════════════════════════════════════════════════

def _add_supply_traces(fig: go.Figure, supply_df: pd.DataFrame) -> None:
    if "기관" in supply_df.columns:
        fig.add_trace(go.Bar(
            x=supply_df.index, y=supply_df["기관"],
            name="기관",
            marker_color="rgba(0,180,60,0.55)",
            showlegend=False,
            hovertemplate="기관: %{y:+,.0f}<extra></extra>",
        ), row=2, col=1)

    if "외인" in supply_df.columns:
        fig.add_trace(go.Bar(
            x=supply_df.index, y=supply_df["외인"],
            name="외인",
            marker_color="rgba(255,160,0,0.55)",
            showlegend=False,
            hovertemplate="외인: %{y:+,.0f}<extra></extra>",
        ), row=2, col=1)
