"""
visualizer.py — Plotly 3단 서브플롯 차트 생성 (화이트 테마)
  1단(55%): 캔들 + SMA + 시그널/언급/TODAY 박스
  2단(18%): 거래량 + 거래량MA + 수급(KR)
  3단(27%): MACD + RSI(secondary_y)
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
CHARTS_DIR = BASE_DIR / "charts"

SIGNAL_COLORS = {
    "그랜드": "#00C851",
    "골든":   "#FFB300",
    "응축":   "#AA00FF",
    "폭발":   "#FF3D00",
}

SIGNAL_SHORT = {
    "그랜드": "그랜드",
    "골든":   "골든",
    "응축":   "응축",
    "폭발":   "폭발",
}

# 이평선 스타일 — 중요도: SMA200 > SMA20 > SMA120 = SMA60
SMA_STYLES = [
    ("SMA20",  "#2196F3", 2.0, "SMA20"),
    ("SMA60",  "#FF9800", 1.5, "SMA60"),
    ("SMA120", "#4CAF50", 1.5, "SMA120"),
    ("SMA200", "#E91E63", 2.5, "SMA200"),
]

# 기간 버튼 클릭 시: 우측 3.5% 여백 + Y축 자동 스케일 + 모바일 최적화
_RANGE_PAD_JS = """\
(function () {
    if (!document.querySelector('meta[name="viewport"]')) {
        var _m = document.createElement('meta');
        _m.name = 'viewport';
        _m.content = 'width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no';
        document.head.appendChild(_m);
    }
    var _gd0 = document.getElementById('chart');
    function _fitH() {
        if (_gd0 && window.innerHeight > 0)
            Plotly.relayout(_gd0, {height: Math.max(500, window.innerHeight)});
    }
    window.addEventListener('resize', _fitH);
    setTimeout(_fitH, 150);
}());

(function () {
    var gd = document.getElementById('chart');
    if (!gd) return;
    var _busy = false;
    var _initDone = false;

    // axisId('y','y2','y3') 기준으로 t0~t1 범위의 데이터 min/max 계산
    function yBounds(axisId, t0, t1) {
        var lo = Infinity, hi = -Infinity;
        gd.data.forEach(function (tr) {
            if ((tr.yaxis || 'y') !== axisId) return;
            var xs = tr.x;
            if (!xs || !xs.length) return;
            for (var i = 0; i < xs.length; i++) {
                var t = new Date(xs[i]).getTime();
                if (isNaN(t) || t < t0 || t > t1) continue;
                if (tr.type === 'candlestick') {
                    if (tr.low  && tr.low[i]  != null) lo = Math.min(lo, +tr.low[i]);
                    if (tr.high && tr.high[i] != null) hi = Math.max(hi, +tr.high[i]);
                } else if (tr.y && tr.y[i] != null) {
                    var v = +tr.y[i];
                    if (!isNaN(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
                }
            }
        });
        return isFinite(lo) ? [lo, hi] : null;
    }

    function buildUpdate(ms0, ms1) {
        var upd = {};
        // X 우측 3.5% 여백 (좌측 0%)
        var pad = Math.min((ms1 - ms0) * 0.035, 30 * 86400000);
        var padEnd = new Date(ms1 + pad).toISOString().slice(0, 10);
        upd['xaxis.range[1]'] = padEnd;

        // Y1: 주가 (위 4%, 아래 2% 여유)
        var p1 = yBounds('y', ms0, ms1 + pad);
        if (p1) {
            var r1 = Math.max(p1[1] - p1[0], p1[0] * 0.01);
            upd['yaxis.range'] = [p1[0] - r1 * 0.02, p1[1] + r1 * 0.04];
        }
        // Y2: 거래량 (0부터 최대값 × 1.10)
        var p2 = yBounds('y2', ms0, ms1 + pad);
        if (p2) upd['yaxis2.range'] = [0, p2[1] * 1.10];
        // Y3: MACD (위아래 10% 여유)
        var p3 = yBounds('y3', ms0, ms1 + pad);
        if (p3) {
            var r3 = Math.max(p3[1] - p3[0], Math.abs(p3[0] || 0.01) * 0.2);
            upd['yaxis3.range'] = [p3[0] - r3 * 0.10, p3[1] + r3 * 0.10];
        }
        return upd;
    }

    // 초기 렌더링 후 1Y 뷰에 맞게 y축 스케일
    gd.on('plotly_afterplot', function () {
        if (_initDone || _busy) return;
        _initDone = true;
        var xr = gd._fullLayout && gd._fullLayout.xaxis && gd._fullLayout.xaxis.range;
        if (!xr) return;
        var t0 = new Date(xr[0]).getTime(), t1 = new Date(xr[1]).getTime();
        if (isNaN(t0) || isNaN(t1)) return;
        var upd = buildUpdate(t0, t1);
        delete upd['xaxis.range[1]'];  // 초기 로드 시 x범위는 변경 안 함
        _busy = true;
        Plotly.relayout(gd, upd).then(function () { _busy = false; });
    });

    // 기간 버튼 클릭 시 x범위 + y축 동시 업데이트
    gd.on('plotly_relayout', function (ev) {
        if (_busy) return;
        var x0 = ev['xaxis.range[0]'], x1 = ev['xaxis.range[1]'];
        if (!x0 || !x1) return;
        var ms0 = new Date(x0).getTime(), ms1 = new Date(x1).getTime();
        if (isNaN(ms0) || isNaN(ms1) || ms1 <= ms0) return;
        _busy = true;
        Plotly.relayout(gd, buildUpdate(ms0, ms1)).then(function () { _busy = false; });
    });
}());
"""


def _date_label(date_str: str) -> str:
    """'2026-04-22' → '4/22'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.month}/{dt.day}"
    except Exception:
        return date_str


def _get_close_at(df: pd.DataFrame, date_str: str) -> float | None:
    """특정 날짜의 종가 반환 (없으면 가장 가까운 거래일 종가)."""
    try:
        idx = pd.Timestamp(date_str)
        if idx in df.index:
            return float(df.loc[idx, "Close"])
        pos = df.index.searchsorted(idx)
        pos = min(pos, len(df) - 1)
        return float(df.iloc[pos]["Close"])
    except Exception:
        return None


def _get_high_at(df: pd.DataFrame, date_str: str) -> float | None:
    """특정 날짜의 고가 반환 (없으면 가장 가까운 거래일 고가)."""
    try:
        idx = pd.Timestamp(date_str)
        if idx in df.index:
            return float(df.loc[idx, "High"])
        pos = df.index.searchsorted(idx)
        pos = min(pos, len(df) - 1)
        return float(df.iloc[pos]["High"])
    except Exception:
        return None


def generate_chart(
    df: pd.DataFrame,
    code: str,
    meta: dict,
    signals_today: list,
    signal_history: list[dict],
    market: str,
    supply_df: pd.DataFrame | None = None,
) -> Path | None:
    """3단 차트 생성 후 HTML 저장. 반환: 저장된 파일 Path (실패 시 None)"""
    if df is None or df.empty:
        log.warning(f"[{code}] 데이터 없음 — 차트 생성 스킵")
        return None

    name         = meta.get("종목명", code)
    mentions     = meta.get("언급일", [])
    today        = datetime.now()
    one_year_ago = today - timedelta(days=365)
    # 기본 1Y 뷰 우측 3.5% 여백 (13일 ≈ 365 × 0.035)
    range_end    = today + timedelta(days=13)

    # ── 서브플롯 ──────────────────────────────────────────────────
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

    # ═════════════════════════════════════════════════════════════
    # 1단: 캔들스틱 + SMA
    # ═════════════════════════════════════════════════════════════

    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        increasing=dict(line=dict(color="#EF5350"), fillcolor="#EF5350"),
        decreasing=dict(line=dict(color="#1E88E5"), fillcolor="#1E88E5"),
        showlegend=False,
        name="",
        hovertemplate=(
            "<b>%{x|%Y-%m-%d}</b><br>"
            "시가 %{open:,.0f}  고가 %{high:,.0f}<br>"
            "저가 %{low:,.0f}  종가 %{close:,.0f}"
            "<extra></extra>"
        ),
    ), row=1, col=1)

    for col, color, width, label in SMA_STYLES:
        if col in df.columns and df[col].notna().any():
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col],
                line=dict(color=color, width=width),
                name=label,
                showlegend=True,
                hoverinfo="skip",
            ), row=1, col=1)

    # 범례 구분자: 주가 | 시그널
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers",
        marker=dict(opacity=0, size=1), name="│",
        showlegend=True, hoverinfo="skip",
    ), row=1, col=1)

    # 시그널 범례용 더미 트레이스
    for sig_name, sig_color in SIGNAL_COLORS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode="markers",
            marker=dict(color=sig_color, size=11, symbol="square"),
            name=sig_name,
            showlegend=True,
            hoverinfo="skip",
        ), row=1, col=1)

    # 범례 구분자: 시그널 | MACD/RSI
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers",
        marker=dict(opacity=0, size=1), name="│",
        showlegend=True, hoverinfo="skip",
    ), row=1, col=1)

    # ═════════════════════════════════════════════════════════════
    # 2단: 거래량 + 거래량 이평선
    # ═════════════════════════════════════════════════════════════

    vol_colors = [
        "#EF5350" if float(c) >= float(o) else "#1E88E5"
        for c, o in zip(df["Close"], df["Open"])
    ]

    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"],
        marker=dict(color=vol_colors, opacity=1.0),
        showlegend=False,
        name="거래량",
        hovertemplate="%{y:,.0f}<extra>거래량</extra>",
    ), row=2, col=1)

    if "Volume_MA20" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Volume_MA20"],
            line=dict(color="#333333", width=1.2, dash="dot"),
            showlegend=False, name="거래량MA20",
            hoverinfo="skip",
        ), row=2, col=1)

    if "Volume_MA200" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Volume_MA200"],
            line=dict(color="#888888", width=1, dash="dot"),
            showlegend=False, name="거래량MA200",
            hoverinfo="skip",
        ), row=2, col=1)

    if market == "KR" and supply_df is not None and not supply_df.empty:
        _add_supply_traces(fig, supply_df)

    # ═════════════════════════════════════════════════════════════
    # 3단: MACD + RSI (secondary_y)
    # ═════════════════════════════════════════════════════════════

    if "MACD_Hist" in df.columns:
        # 캔들과 동일: 양수(상승 모멘텀)=빨강, 음수(하락 모멘텀)=파랑
        macd_colors = [
            "#EF5350" if (v >= 0 if pd.notna(v) else False) else "#1E88E5"
            for v in df["MACD_Hist"]
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=df["MACD_Hist"],
            marker_color=macd_colors,
            showlegend=False, name="MACD Hist",
            hoverinfo="skip",
        ), row=3, col=1)

    if "MACD" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD"],
            line=dict(color="#2196F3", width=1.2),
            showlegend=True, name="MACD",
            hoverinfo="skip",
        ), row=3, col=1)

    if "MACD_Signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD_Signal"],
            line=dict(color="#FF9800", width=1.2),
            showlegend=True, name="시그널선",
            hoverinfo="skip",
        ), row=3, col=1)

    # 범례 구분자: MACD | RSI
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers",
        marker=dict(opacity=0, size=1), name="│",
        showlegend=True, hoverinfo="skip",
    ), row=3, col=1)

    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"],
            line=dict(color="#555555", width=1.2, dash="dot"),
            showlegend=True, name="RSI",
            hovertemplate="RSI: %{y:.1f}<extra></extra>",
        ), row=3, col=1, secondary_y=True)

        for level, color in [(70, "#EF5350"), (30, "#1E88E5")]:
            fig.add_trace(go.Scatter(
                x=[df.index[0], df.index[-1]],
                y=[level, level],
                mode="lines",
                line=dict(color=color, width=0.8, dash="dot"),
                showlegend=False,
                hoverinfo="skip",
            ), row=3, col=1, secondary_y=True)

    # ═════════════════════════════════════════════════════════════
    # 어노테이션: TODAY > 시그널 > 언급일 순으로 날짜별 스태킹
    # 같은 날짜 박스끼리 겹치지 않도록 ay를 위로 쌓음
    # ═════════════════════════════════════════════════════════════

    annotations = []
    shapes      = []

    _AY_BASE = -40   # 첫 박스 (캔들에 가장 가까움)
    _AY_STEP = 55    # 박스 간 간격 (px)
    _ay_slots: dict = {}  # date_str → 다음 사용할 ay

    def _next_ay(date_str: str) -> int:
        if date_str not in _ay_slots:
            _ay_slots[date_str] = _AY_BASE
        else:
            _ay_slots[date_str] -= _AY_STEP
        return _ay_slots[date_str]

    # ── TODAY 박스 먼저 등록 (항상 캔들에 가장 가까이) ──────────
    latest_date  = df.index[-1] if not df.empty else None
    latest_close = float(df["Close"].iloc[-1]) if not df.empty else 0
    latest_high  = float(df["High"].iloc[-1])  if not df.empty else 0

    if not df.empty:
        today_date_str = latest_date.strftime("%Y-%m-%d")
        annotations.append(dict(
            x=latest_date, y=latest_high,
            xref="x", yref="y",
            text=f"<b>TODAY: {latest_close:,.0f}</b>",
            showarrow=True, arrowhead=2,
            arrowcolor="#222222", arrowwidth=1.5,
            ax=0, ay=_next_ay(today_date_str),
            bgcolor="#222222",
            font=dict(color="#FFFFFF", size=11),
            bordercolor="#FFFFFF", borderwidth=1.5,
            borderpad=4,
        ))

    # ── 시그널 박스 (히스토리 + 오늘 SUMMARY 모드) ───────────────
    today_str = today.strftime("%Y-%m-%d")
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

    by_date: dict[str, list[dict]] = {}
    for entry in all_sig_entries:
        d = entry.get("선정일", "")
        by_date.setdefault(d, []).append(entry)

    for date_str, entries in by_date.items():
        high = _get_high_at(df, date_str)
        if high is None:
            continue
        for entry in entries:
            sig   = entry.get("시그널", "")
            px    = entry.get("진입가", 0)
            color = SIGNAL_COLORS.get(sig, "#888888")
            short = SIGNAL_SHORT.get(sig, str(sig)[:3])
            annotations.append(dict(
                x=date_str, y=high,
                xref="x", yref="y",
                text=f"<b>{short}_{_date_label(date_str)}</b><br>{px:,.0f}",
                showarrow=True, arrowhead=2,
                arrowcolor=color, arrowwidth=1.5,
                ax=0, ay=_next_ay(date_str),
                bgcolor=color,
                font=dict(color="#FFFFFF", size=10),
                bordercolor=color, borderwidth=1,
                borderpad=4,
            ))

    # ── 언급일 박스 + 세로 점선 ────────────────────────────────
    for mention in mentions:
        m_date  = mention.get("날짜", "")
        m_ord   = mention.get("차수", "")
        high    = _get_high_at(df, m_date)
        m_close = _get_close_at(df, m_date)
        if high is None:
            continue
        price_line = f"<br>{m_close:,.0f}" if m_close else ""
        annotations.append(dict(
            x=m_date, y=high,
            xref="x", yref="y",
            text=f"<b>{m_ord}_{_date_label(m_date)}</b>{price_line}",
            showarrow=True, arrowhead=2,
            arrowcolor="#444444", arrowwidth=1.5,
            ax=0, ay=_next_ay(m_date),
            bgcolor="#FFFFFF",
            font=dict(color="#000000", size=10),
            bordercolor="#444444", borderwidth=1.5,
            borderpad=4,
        ))
        shapes.append(dict(
            type="line",
            x0=m_date, x1=m_date,
            y0=0, y1=1,
            yref="paper", xref="x",
            line=dict(color="#BBBBBB", width=1, dash="dash"),
        ))

    # ── RSI 현재값 박스 — 3단 우측상단 모서리 고정 ───────────────
    if "RSI" in df.columns and df["RSI"].notna().any():
        latest_rsi = float(df["RSI"].dropna().iloc[-1])
        rsi_color  = "#EF5350" if latest_rsi >= 70 else ("#1E88E5" if latest_rsi <= 30 else "#555555")
        annotations.append(dict(
            x=0.99, xref="x domain",
            y=0.95, yref="y3 domain",
            text=f"<b>RSI {latest_rsi:.0f}</b>",
            showarrow=False,
            bgcolor=rsi_color,
            font=dict(color="#FFFFFF", size=10),
            bordercolor=rsi_color, borderwidth=1,
            borderpad=4,
            xanchor="right", yanchor="top",
        ))

    # ═════════════════════════════════════════════════════════════
    # 레이아웃 (화이트 테마)
    # ═════════════════════════════════════════════════════════════

    axis_common = dict(
        showgrid=True,  gridcolor="#EBEBEB",
        showline=True,  linecolor="#CCCCCC",
        mirror=True,
        zeroline=False,
        tickfont=dict(color="#555555"),
    )
    x_common = dict(
        **axis_common,
        rangeslider=dict(visible=False),
        rangebreaks=[dict(bounds=["sat", "mon"])],
        type="date",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="#AAAAAA",
        spikethickness=1,
        spikedash="solid",
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
        margin=dict(l=65, r=65, t=125, b=50),

        legend=dict(
            orientation="h",
            y=1.10, x=0,
            xanchor="left", yanchor="bottom",
            font=dict(size=10, color="#333333"),
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="#DDDDDD",
            borderwidth=1,
            itemsizing="constant",
        ),

        annotations=annotations,
        shapes=shapes,

        xaxis=dict(
            **x_common,
            showticklabels=False,
            rangeselector=dict(
                buttons=[
                    dict(count=3,  label="3M",   step="month", stepmode="backward"),
                    dict(count=6,  label="6M",   step="month", stepmode="backward"),
                    dict(count=1,  label="1Y ★", step="year",  stepmode="backward"),
                    dict(count=2,  label="2Y",   step="year",  stepmode="backward"),
                    dict(step="all", label="전체"),
                ],
                activecolor="#FFB300",
                bgcolor="#F0F0F0",
                bordercolor="#CCCCCC",
                borderwidth=1,
                font=dict(color="#333333", size=11),
                x=0, y=1.01,
                xanchor="left", yanchor="bottom",
            ),
            range=[
                one_year_ago.strftime("%Y-%m-%d"),
                range_end.strftime("%Y-%m-%d"),
            ],
        ),
        xaxis2=dict(**x_common, showticklabels=False, matches="x"),
        xaxis3=dict(**x_common, showticklabels=True, tickformat="%y/%m/%d", matches="x"),

        yaxis=dict(
            **axis_common,
            title=dict(text="주가", standoff=5, font=dict(size=11, color="#888888")),
            tickformat=",",
            showspikes=True, spikemode="across", spikethickness=1, spikecolor="#CCCCCC",
        ),
        yaxis2=dict(
            **axis_common,
            title=dict(text="거래량", standoff=5, font=dict(size=11, color="#888888")),
            tickformat=".2s",
            showspikes=True, spikemode="across", spikethickness=1, spikecolor="#CCCCCC",
        ),
        yaxis3=dict(
            **axis_common,
            title=dict(text="MACD", standoff=5, font=dict(size=11, color="#888888")),
            showspikes=True, spikemode="across", spikethickness=1, spikecolor="#CCCCCC",
        ),
        yaxis4=dict(
            range=[0, 100],
            showgrid=False, showline=False,
            tickvals=[30, 70],
            ticktext=["30", "70"],
            tickfont=dict(size=9, color="#888888"),
            title=dict(text="RSI", standoff=5, font=dict(size=10, color="#888888")),
        ),
    )

    # ── 저장 ──────────────────────────────────────────────────────
    out_dir = CHARTS_DIR / market
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{code}_{name}.html"

    fig.write_html(
        str(out_path),
        include_plotlyjs="cdn",
        full_html=True,
        div_id="chart",
        post_script=_RANGE_PAD_JS,
        config={
            "displayModeBar": False,
            "staticPlot": False,
            "scrollZoom": False,
        },
    )
    log.info(f"차트 저장 → {out_path}")
    return out_path


# ═════════════════════════════════════════════════════════════════
# 수급 트레이스 (내부 헬퍼)
# ═════════════════════════════════════════════════════════════════

def _add_supply_traces(fig: go.Figure, supply_df: pd.DataFrame) -> None:
    """기관/외인 순매수 막대를 2단 차트에 추가 (KR 전용)."""
    if "기관" in supply_df.columns:
        fig.add_trace(go.Bar(
            x=supply_df.index,
            y=supply_df["기관"],
            name="기관",
            marker_color="rgba(0, 180, 60, 0.55)",
            showlegend=True,
            hovertemplate="기관: %{y:+,.0f}<extra></extra>",
        ), row=2, col=1)

    if "외인" in supply_df.columns:
        fig.add_trace(go.Bar(
            x=supply_df.index,
            y=supply_df["외인"],
            name="외인",
            marker_color="rgba(255, 160, 0, 0.55)",
            showlegend=True,
            hovertemplate="외인: %{y:+,.0f}<extra></extra>",
        ), row=2, col=1)
