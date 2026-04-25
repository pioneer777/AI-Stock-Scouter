"""
visualizer.py — Plotly 3단 서브플롯 차트 생성
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
    "그랜드": "그랜",
    "골든":   "골든",
    "응축":   "응축",
    "폭발":   "폭발",
}

SMA_STYLES = [
    ("SMA20",  "#2196F3", 1.2, "SMA20"),
    ("SMA60",  "#FF9800", 1.2, "SMA60"),
    ("SMA120", "#4CAF50", 1.2, "SMA120"),
    ("SMA200", "#E91E63", 1.5, "SMA200"),
]


def _date_label(date_str: str) -> str:
    """'2026-04-22' → '4/22'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.month}/{dt.day}"
    except Exception:
        return date_str


def _get_high_at(df: pd.DataFrame, date_str: str) -> float | None:
    """특정 날짜의 고가 반환 (없으면 None)."""
    try:
        idx = pd.Timestamp(date_str)
        if idx in df.index:
            return float(df.loc[idx, "High"])
        # 날짜가 없으면 가장 가까운 날짜 사용
        pos = df.index.searchsorted(idx)
        pos = min(pos, len(df) - 1)
        return float(df.iloc[pos]["High"])
    except Exception:
        return None


def generate_chart(
    df: pd.DataFrame,
    code: str,
    meta: dict,
    signals_today: list[str],
    signal_history: list[dict],
    market: str,
    supply_df: pd.DataFrame | None = None,
) -> Path | None:
    """
    3단 차트 생성 후 HTML 저장.
    반환: 저장된 파일 Path (실패 시 None)
    """
    if df is None or df.empty:
        log.warning(f"[{code}] 데이터 없음 — 차트 생성 스킵")
        return None

    name     = meta.get("종목명", code)
    mentions = meta.get("언급일", [])
    today    = datetime.now()
    one_year_ago = today - timedelta(days=365)

    # ── 서브플롯 생성 ──────────────────────────────────────────────
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

    # ══════════════════════════════════════════════════════════════
    # 1단: 캔들스틱 + SMA
    # ══════════════════════════════════════════════════════════════

    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        increasing=dict(line=dict(color="#FF3D00"), fillcolor="#FF3D00"),
        decreasing=dict(line=dict(color="#1565C0"), fillcolor="#1565C0"),
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
                legendgroup="sma",
                hoverinfo="skip",
            ), row=1, col=1)

    # ══════════════════════════════════════════════════════════════
    # 2단: 거래량 + 거래량 이평선
    # ══════════════════════════════════════════════════════════════

    vol_colors = [
        "#FF3D00" if float(c) >= float(o) else "#1565C0"
        for c, o in zip(df["Close"], df["Open"])
    ]

    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"],
        marker_color=vol_colors,
        showlegend=False,
        name="거래량",
        hovertemplate="%{y:,.0f}<extra>거래량</extra>",
    ), row=2, col=1)

    if "Volume_MA20" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Volume_MA20"],
            line=dict(color="#000000", width=1, dash="dot"),
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

    # 수급: 기관/외인 (KR 전용)
    if market == "KR" and supply_df is not None and not supply_df.empty:
        _add_supply_traces(fig, supply_df)

    # ══════════════════════════════════════════════════════════════
    # 3단: MACD + RSI(secondary_y)
    # ══════════════════════════════════════════════════════════════

    if "MACD_Hist" in df.columns:
        macd_colors = [
            "#4CAF50" if (v >= 0 if pd.notna(v) else False) else "#FF3D00"
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
            showlegend=False, name="MACD",
            hoverinfo="skip",
        ), row=3, col=1)

    if "MACD_Signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD_Signal"],
            line=dict(color="#FF9800", width=1.2),
            showlegend=False, name="Signal",
            hoverinfo="skip",
        ), row=3, col=1)

    # RSI (secondary_y)
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"],
            line=dict(color="#CCCCCC", width=1, dash="dot"),
            showlegend=False, name="RSI",
            hovertemplate="RSI: %{y:.1f}<extra></extra>",
        ), row=3, col=1, secondary_y=True)

        # RSI 70/30 기준선
        for level, color in [(70, "#FF5252"), (30, "#40C4FF")]:
            fig.add_trace(go.Scatter(
                x=[df.index[0], df.index[-1]],
                y=[level, level],
                mode="lines",
                line=dict(color=color, width=1, dash="dot"),
                showlegend=False,
                hoverinfo="skip",
            ), row=3, col=1, secondary_y=True)

    # ══════════════════════════════════════════════════════════════
    # 어노테이션: 시그널 박스 + 언급일 박스 + TODAY 박스
    # ══════════════════════════════════════════════════════════════

    annotations = []

    # 언급일 박스 + 세로 점선
    shapes = []
    for mention in mentions:
        m_date = mention.get("날짜", "")
        m_px   = mention.get("가격", 0)
        m_ord  = mention.get("차수", "")
        high   = _get_high_at(df, m_date)
        if high is None:
            continue

        annotations.append(dict(
            x=m_date, y=high,
            xref="x", yref="y",
            text=f"<b>{m_ord}_{_date_label(m_date)}</b><br>{m_px:,.0f}",
            showarrow=True, arrowhead=2,
            arrowcolor="#333333", arrowwidth=1.5,
            ax=0, ay=-50,
            bgcolor="#FFFFFF",
            font=dict(color="#000000", size=10),
            bordercolor="#333333", borderwidth=1.5,
            borderpad=4,
        ))

        shapes.append(dict(
            type="line",
            x0=m_date, x1=m_date,
            y0=0, y1=1,
            yref="paper",
            xref="x",
            line=dict(color="#888888", width=1, dash="dash"),
        ))

    # 시그널 박스 (히스토리 + 오늘 시그널)
    today_str = today.strftime("%Y-%m-%d")
    all_sig_entries = list(signal_history)

    # 오늘 시그널이 히스토리에 없으면 임시 추가 (SUMMARY 모드)
    existing_today_sigs = {
        e["시그널"] for e in signal_history if e.get("선정일") == today_str
    }
    for sig in signals_today:
        if sig not in existing_today_sigs:
            latest_px = float(df["Close"].iloc[-1]) if not df.empty else 0
            all_sig_entries.append({
                "시그널": sig,
                "선정일": today_str,
                "진입가": latest_px,
            })

    # 같은 날짜의 시그널 묶어서 세로 배치
    by_date: dict[str, list[dict]] = {}
    for entry in all_sig_entries:
        d = entry.get("선정일", "")
        by_date.setdefault(d, []).append(entry)

    for date_str, entries in by_date.items():
        high = _get_high_at(df, date_str)
        if high is None:
            continue
        for i, entry in enumerate(entries):
            sig   = entry.get("시그널", "")
            px    = entry.get("진입가", 0)
            color = SIGNAL_COLORS.get(sig, "#888888")
            short = SIGNAL_SHORT.get(sig, sig[:2])
            ay    = -35 - i * 38

            annotations.append(dict(
                x=date_str, y=high,
                xref="x", yref="y",
                text=f"<b>{short}_{_date_label(date_str)}</b><br>{px:,.0f}",
                showarrow=True, arrowhead=2,
                arrowcolor=color, arrowwidth=1.5,
                ax=0, ay=ay,
                bgcolor=color,
                font=dict(color="#FFFFFF", size=10),
                bordercolor=color, borderwidth=1,
                borderpad=4,
            ))

    # TODAY 박스
    if not df.empty:
        latest_date  = df.index[-1]
        latest_close = float(df["Close"].iloc[-1])
        latest_high  = float(df["High"].iloc[-1])

        annotations.append(dict(
            x=latest_date, y=latest_high,
            xref="x", yref="y",
            text=f"<b>TODAY: {latest_close:,.0f}</b>",
            showarrow=True, arrowhead=2,
            arrowcolor="#FFFFFF", arrowwidth=1.5,
            ax=0, ay=-25,
            bgcolor="#000000",
            font=dict(color="#FFFFFF", size=11),
            bordercolor="#FFFFFF", borderwidth=1.5,
            borderpad=4,
        ))

    # RSI 현재값 박스 (우측 하단, y=0.03 paper)
    if "RSI" in df.columns and df["RSI"].notna().any():
        latest_rsi = float(df["RSI"].dropna().iloc[-1])
        rsi_color  = "#FF5252" if latest_rsi >= 70 else ("#40C4FF" if latest_rsi <= 30 else "#555555")
        annotations.append(dict(
            x=1.0, y=0.03,
            xref="paper", yref="paper",
            text=f"<b>RSI {latest_rsi:.0f}</b>",
            showarrow=False,
            bgcolor=rsi_color,
            font=dict(color="#FFFFFF", size=10),
            bordercolor=rsi_color, borderwidth=1,
            borderpad=4,
            xanchor="right", yanchor="bottom",
        ))

    # ══════════════════════════════════════════════════════════════
    # 레이아웃
    # ══════════════════════════════════════════════════════════════

    axis_common = dict(
        showgrid=True, gridcolor="#2A2A2A",
        showline=True, linecolor="#555555",
        mirror=True,
        zeroline=False,
    )
    x_common = dict(
        **axis_common,
        rangeslider=dict(visible=False),
        rangebreaks=[dict(bounds=["sat", "mon"])],
        type="date",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="#888888",
        spikethickness=1,
        spikedash="solid",
    )

    fig.update_layout(
        height=1000,
        title=dict(
            text=f"<b>{name} ({code})</b>",
            font=dict(size=16, color="#FFFFFF"),
            x=0.5, xanchor="center",
        ),
        paper_bgcolor="#0E0E0E",
        plot_bgcolor="#1A1A1A",
        font=dict(color="#E0E0E0", family="Segoe UI, sans-serif"),
        dragmode=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1E1E1E", font_color="#FFFFFF"),
        margin=dict(l=60, r=60, t=80, b=50),

        # 범례: 최상단 가로 1줄
        legend=dict(
            orientation="h",
            y=1.06, x=0,
            xanchor="left", yanchor="bottom",
            font=dict(size=11),
            bgcolor="rgba(0,0,0,0)",
            itemsizing="constant",
        ),

        # 어노테이션 + 세로선
        annotations=annotations,
        shapes=shapes,

        # X축 (레인지 버튼은 row1 xaxis에)
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
                bgcolor="#1E1E1E",
                bordercolor="#555555",
                borderwidth=1,
                font=dict(color="#FFFFFF", size=11),
                x=0, y=1.01,
                xanchor="left", yanchor="bottom",
            ),
            range=[
                one_year_ago.strftime("%Y-%m-%d"),
                today.strftime("%Y-%m-%d"),
            ],
        ),
        xaxis2=dict(**x_common, showticklabels=False, matches="x"),
        xaxis3=dict(
            **x_common,
            showticklabels=True,
            tickformat="%m/%d",
            matches="x",
        ),

        # Y축
        yaxis=dict(**axis_common, tickformat=",",
                   showspikes=True, spikemode="across", spikethickness=1, spikecolor="#444444"),
        yaxis2=dict(
            **axis_common,
            title=dict(text="거래량", standoff=5),
            tickformat=".2s",
            showspikes=True, spikemode="across", spikethickness=1, spikecolor="#444444",
        ),
        yaxis3=dict(**axis_common,
                    showspikes=True, spikemode="across", spikethickness=1, spikecolor="#444444"),
        yaxis4=dict(
            range=[0, 100],
            showgrid=False, showline=False,
            tickvals=[30, 70],
            ticktext=["30", "70"],
            tickfont=dict(size=9, color="#888888"),
        ),
    )

    # ── 파일 저장 ─────────────────────────────────────────────────
    out_dir = CHARTS_DIR / market
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{code}_{name}.html"

    fig.write_html(
        str(out_path),
        include_plotlyjs="cdn",
        full_html=True,
        config={
            "displayModeBar": False,
            "staticPlot": False,
            "scrollZoom": False,
        },
    )
    log.info(f"차트 저장 → {out_path}")
    return out_path


# ══════════════════════════════════════════════════════════════════
# 수급 트레이스 (내부 헬퍼)
# ══════════════════════════════════════════════════════════════════

def _add_supply_traces(fig: go.Figure, supply_df: pd.DataFrame) -> None:
    """기관/외인 순매수 막대를 2단 차트에 추가 (KR 전용)."""
    if "기관" in supply_df.columns:
        fig.add_trace(go.Bar(
            x=supply_df.index,
            y=supply_df["기관"],
            name="기관",
            marker_color="rgba(0, 200, 81, 0.45)",
            showlegend=True,
            hovertemplate="기관: %{y:+,.0f}<extra></extra>",
        ), row=2, col=1)

    if "외인" in supply_df.columns:
        fig.add_trace(go.Bar(
            x=supply_df.index,
            y=supply_df["외인"],
            name="외인",
            marker_color="rgba(255, 179, 0, 0.45)",
            showlegend=True,
            hovertemplate="외인: %{y:+,.0f}<extra></extra>",
        ), row=2, col=1)
