"""
米国株 決算データ → スマホ風HTML UI 生成スクリプト
使い方: python -X utf8 earnings_ui.py AAPL
"""

import sys
import io
import os
import webbrowser
import tempfile
import yfinance as yf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ─── ユーティリティ ─────────────────────────────────────────────

def safe_float(v, default=None):
    try:
        return float(v)
    except Exception:
        return default


def fmt_billion(value):
    if value is None:
        return "―"
    v = safe_float(value)
    if v is None:
        return "―"
    if abs(v) >= 1e12:
        return f"${v/1e12:.2f}T"
    elif abs(v) >= 1e9:
        return f"${v/1e9:.2f}B"
    elif abs(v) >= 1e6:
        return f"${v/1e6:.2f}M"
    return f"${v:,.0f}"


def surprise_color(pct):
    if pct is None:
        return "#888"
    if pct >= 0:
        return "#22c55e"   # green
    return "#ef4444"       # red


def surprise_sign(pct):
    if pct is None:
        return ""
    return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"


def margin_color(pct):
    if pct is None:
        return "#888"
    if pct >= 20:
        return "#22c55e"
    if pct >= 10:
        return "#f59e0b"
    return "#ef4444"


def fcf_color(val):
    if val is None:
        return "#888"
    return "#22c55e" if val >= 0 else "#ef4444"


# 判定バッジ: {"text": "優秀", "color": "#...", "bg": "#...", "reason": "..."}
def judge_margin(pct):
    if pct is None:
        return None
    if pct >= 25:
        return {"text": "優秀", "color": "#15803d", "bg": "#dcfce7", "reason": "売上の4分の1以上が利益に残る"}
    if pct >= 15:
        return {"text": "良好", "color": "#16a34a", "bg": "#f0fdf4", "reason": "売上から十分な利益を稼いでいる"}
    if pct >= 8:
        return {"text": "普通", "color": "#92400e", "bg": "#fef9c3", "reason": "利益は出ているが改善の余地あり"}
    return {"text": "注意", "color": "#b91c1c", "bg": "#fee2e2", "reason": "売上に対して利益が少ない状態"}


def surprise_comment(rev_yoy_pct, eps_surprise_pct):
    """売上YoY・EPSサプライズを総合して一言コメントを返す"""
    rev_score = 0
    if rev_yoy_pct is not None:
        if rev_yoy_pct >= 20:   rev_score = 2
        elif rev_yoy_pct >= 5:  rev_score = 1
        elif rev_yoy_pct >= -5: rev_score = 0
        else:                   rev_score = -1

    eps_score = 0
    if eps_surprise_pct is not None:
        if eps_surprise_pct >= 5:   eps_score = 2
        elif eps_surprise_pct >= 2: eps_score = 1
        elif eps_surprise_pct >= -2: eps_score = 0
        else:                       eps_score = -1

    total = rev_score + eps_score

    if total >= 4:
        return {"emoji": "🚀", "text": "売上・EPS ともに大幅上振れ。非常に好調な決算！",
                "color": "#14532d", "bg": "#dcfce7"}
    if total >= 2:
        return {"emoji": "✅", "text": "売上・EPS ともに堅調。市場の期待を超えました",
                "color": "#15803d", "bg": "#f0fdf4"}
    if total == 1:
        return {"emoji": "🟢", "text": "概ね好調。一部の指標が予想を上回りました",
                "color": "#166534", "bg": "#f0fdf4"}
    if total == 0:
        return {"emoji": "🟡", "text": "予想通りの着地。大きなサプライズはなし",
                "color": "#92400e", "bg": "#fef9c3"}
    if total >= -1:
        return {"emoji": "⚠️", "text": "一部の指標が予想を下回りました。要注視",
                "color": "#9a3412", "bg": "#fff7ed"}
    return {"emoji": "🔴", "text": "売上・EPS ともに予想を下回る軟調な決算",
            "color": "#b91c1c", "bg": "#fee2e2"}


def judge_fcf(val):
    if val is None:
        return None
    if val >= 5e9:
        return {"text": "優秀", "color": "#15803d", "bg": "#dcfce7", "reason": "潤沢なキャッシュを創出"}
    if val >= 5e8:
        return {"text": "良好", "color": "#16a34a", "bg": "#f0fdf4", "reason": "安定したキャッシュ創出"}
    if val >= 0:
        return {"text": "普通", "color": "#92400e", "bg": "#fef9c3", "reason": "わずかなキャッシュ余剰"}
    return {"text": "注意", "color": "#b91c1c", "bg": "#fee2e2", "reason": "キャッシュが流出している"}


# ─── データ取得 ──────────────────────────────────────────────────

def fetch_data(ticker_symbol: str) -> dict:
    tk = yf.Ticker(ticker_symbol)
    info = {}
    try:
        info = tk.info or {}
    except Exception:
        pass

    data = {
        "ticker": ticker_symbol,
        "company": info.get("longName") or info.get("shortName") or ticker_symbol,
        "rev_actual": None,
        "rev_year_ago": None,     # 前年同期の売上高（YoY比較用）
        "rev_yoy_pct": None,      # 売上高の前年同月比 %
        "eps_actual": None,
        "eps_estimate": None,
        "eps_surprise_pct": None,
        "op_margin": None,
        "op_margin_yoy": None,    # 営業利益率の前年同月比（%ポイント差）
        "fcf": None,
        "next_date": None,
        "next_rev_est": None,
        "next_eps_est": None,
        "quarter": None,
    }

    # ── 四半期財務データ（実績 + 前年同月比） ──────────────────────
    try:
        qf = tk.quarterly_financials
        if qf is not None and not qf.empty:
            ncols = len(qf.columns)
            rev_row = qf.loc["Total Revenue"] if "Total Revenue" in qf.index else None
            op_row  = qf.loc["Operating Income"] if "Operating Income" in qf.index else None

            if rev_row is not None:
                data["rev_actual"] = safe_float(rev_row.iloc[0])
                if ncols >= 5:
                    data["rev_year_ago"] = safe_float(rev_row.iloc[4])

            if op_row is not None and data["rev_actual"]:
                op_curr = safe_float(op_row.iloc[0])
                if op_curr is not None:
                    data["op_margin"] = op_curr / data["rev_actual"] * 100
                # 前年同月比（4四半期前 = 同じ季節）
                if ncols >= 5 and data["rev_year_ago"]:
                    op_prev = safe_float(op_row.iloc[4])
                    if op_prev is not None and data["rev_year_ago"] != 0:
                        margin_prev = op_prev / data["rev_year_ago"] * 100
                        if data["op_margin"] is not None:
                            data["op_margin_yoy"] = data["op_margin"] - margin_prev

            # 売上高 前年同月比 %
            if data["rev_actual"] and data["rev_year_ago"] and data["rev_year_ago"] != 0:
                data["rev_yoy_pct"] = (
                    (data["rev_actual"] - data["rev_year_ago"]) / abs(data["rev_year_ago"]) * 100
                )

            # 四半期ラベル
            try:
                col = qf.columns[0]
                data["quarter"] = col.strftime("%Y-Q") + str((col.month - 1) // 3 + 1)
            except Exception:
                pass
    except Exception:
        pass

    # 営業利益率フォールバック（info）
    if data["op_margin"] is None:
        v = safe_float(info.get("operatingMargins"))
        if v is not None:
            data["op_margin"] = v * 100

    # ── EPS（earnings_dates から最新の報告済み行を取得） ───────────
    try:
        ed = tk.earnings_dates
        if ed is not None and not ed.empty:
            # Reported EPSが入っている行だけ = 報告済み
            reported = ed.dropna(subset=["Reported EPS"])
            if not reported.empty:
                latest = reported.iloc[0]
                data["eps_actual"]   = safe_float(latest.get("Reported EPS"))
                data["eps_estimate"] = safe_float(latest.get("EPS Estimate"))
    except Exception:
        pass

    # EPS フォールバック
    if data["eps_actual"] is None:
        data["eps_actual"] = safe_float(info.get("trailingEps"))
    if data["eps_estimate"] is None:
        data["eps_estimate"] = safe_float(info.get("forwardEps"))

    if data["eps_actual"] is not None and data["eps_estimate"] is not None:
        base = abs(data["eps_estimate"])
        if base > 0:
            data["eps_surprise_pct"] = (
                (data["eps_actual"] - data["eps_estimate"]) / base * 100
            )

    # ── FCF ────────────────────────────────────────────────────────
    try:
        cf = tk.quarterly_cashflow
        if cf is not None and not cf.empty:
            op_cf  = safe_float(cf.loc["Operating Cash Flow"].iloc[0]) if "Operating Cash Flow" in cf.index else None
            capex  = safe_float(cf.loc["Capital Expenditure"].iloc[0]) if "Capital Expenditure" in cf.index else None
            if op_cf is not None and capex is not None:
                data["fcf"] = op_cf + capex
            elif op_cf is not None:
                data["fcf"] = op_cf
    except Exception:
        pass
    if data["fcf"] is None:
        data["fcf"] = safe_float(info.get("freeCashflow"))

    # ── 次回決算日 ─────────────────────────────────────────────────
    try:
        # earnings_dates の未報告行（Reported EPS が NaN）の直近が次回
        ed = tk.earnings_dates
        if ed is not None and not ed.empty:
            future = ed[ed["Reported EPS"].isna()]
            if not future.empty:
                nd = future.index[0]
                data["next_date"] = str(nd)[:10]
    except Exception:
        pass

    if data["next_date"] is None:
        try:
            cal = tk.calendar
            if isinstance(cal, dict):
                nd = cal.get("Earnings Date") or cal.get("earningsDate")
                if isinstance(nd, list) and nd:
                    nd = nd[0]
                data["next_date"] = str(nd)[:10] if nd else None
        except Exception:
            pass

    # ── 次回予想（revenue_estimate / earnings_estimate の 0q） ──────
    try:
        re = tk.revenue_estimate
        if re is not None and not re.empty and "0q" in re.index:
            data["next_rev_est"] = safe_float(re.loc["0q", "avg"])
    except Exception:
        pass

    try:
        ee = tk.earnings_estimate
        if ee is not None and not ee.empty and "0q" in ee.index:
            data["next_eps_est"] = safe_float(ee.loc["0q", "avg"])
    except Exception:
        pass

    # フォールバック
    if data["next_eps_est"] is None:
        data["next_eps_est"] = safe_float(info.get("forwardEps"))

    return data


# ─── HTML 生成 ───────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} 決算サマリー</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #f0f4f8;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    min-height: 100vh;
    padding: 24px 12px;
  }}
  .phone {{
    width: 390px;
    max-width: 100%;
    background: #f0f4f8;
    border-radius: 40px;
    box-shadow: 0 20px 60px rgba(0,0,0,.15);
    overflow: hidden;
    padding-bottom: 32px;
  }}

  /* ヘッダー */
  .header {{
    background: #fff;
    padding: 20px 20px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    border-bottom: 1px solid #e8edf2;
  }}
  .company-icon {{
    width: 44px; height: 44px;
    background: #1c1c1e;
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 22px;
    color: #fff;
  }}
  .company-info h1 {{ font-size: 18px; font-weight: 700; color: #1c1c1e; }}
  .company-info p  {{ font-size: 12px; color: #8e8e93; margin-top: 2px; }}
  .star {{ margin-left: auto; font-size: 22px; cursor: pointer; color: #f5c542; }}

  /* メタバッジ */
  .meta {{
    background: #fff;
    padding: 10px 20px;
    display: flex;
    gap: 8px;
    font-size: 12px;
    color: #636366;
    border-bottom: 1px solid #e8edf2;
  }}
  .meta span {{ background:#f2f2f7; padding: 3px 10px; border-radius: 20px; }}

  /* セクション */
  .section {{ margin: 16px 16px 0; }}
  .section-title {{
    font-size: 13px; font-weight: 700;
    color: #636366;
    letter-spacing: .4px;
    text-transform: uppercase;
    margin-bottom: 10px;
    display: flex; align-items: center; gap: 6px;
  }}

  /* カード共通 */
  .card {{
    background: #fff;
    border-radius: 18px;
    padding: 16px 18px;
    margin-bottom: 10px;
    box-shadow: 0 2px 8px rgba(0,0,0,.06);
  }}

  /* 決算サプライズカード */
  .surprise-row {{
    display: flex; align-items: center; justify-content: space-between;
  }}
  .surprise-label {{ font-size: 13px; color: #636366; font-weight: 500; }}
  .surprise-values {{ display: flex; align-items: center; gap: 10px; }}
  .val-group {{ text-align: center; }}
  .val-group .num {{ font-size: 18px; font-weight: 700; color: #1c1c1e; }}
  .val-group .sub {{ font-size: 11px; color: #8e8e93; }}
  .arrow {{ font-size: 18px; color: #c7c7cc; }}
  .badge {{
    font-size: 13px; font-weight: 700;
    padding: 4px 10px; border-radius: 20px;
  }}
  .badge.pos {{ background: #dcfce7; color: #16a34a; }}
  .badge.neg {{ background: #fee2e2; color: #dc2626; }}
  .badge.neu {{ background: #f2f2f7; color: #636366; }}
  .divider {{ border: none; border-top: 1px solid #f2f2f7; margin: 12px 0; }}

  /* 健全性カード */
  .health-row {{
    display: flex; gap: 10px;
  }}
  .health-card {{
    flex: 1;
    background: #f9fafb;
    border-radius: 14px;
    padding: 14px;
    text-align: center;
  }}
  .health-card .icon {{ font-size: 20px; margin-bottom: 6px; }}
  .health-card .value {{
    font-size: 22px; font-weight: 800;
    margin-bottom: 2px;
  }}
  .health-card .label {{
    font-size: 11px; color: #8e8e93;
  }}
  .health-card .sub-label {{
    font-size: 10px; color: #a0aec0; margin-top: 2px;
  }}
  .judge-badge {{
    display: inline-block;
    margin-top: 8px;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
  }}
  .judge-reason {{
    font-size: 10px;
    color: #a0aec0;
    margin-top: 3px;
    line-height: 1.3;
  }}
  .summary-banner {{
    margin-top: 14px;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
    line-height: 1.4;
  }}

  /* 次回カード */
  .next-row {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 6px 0;
  }}
  .next-row .key {{ font-size: 13px; color: #636366; display: flex; align-items: center; gap: 6px; }}
  .next-row .val {{ font-size: 14px; font-weight: 600; color: #1c1c1e; }}

  .na {{ color: #c7c7cc; font-weight: 400; }}
</style>
</head>
<body>
<div class="phone">

  <!-- ヘッダー -->
  <div class="header">
    <div class="company-icon">📈</div>
    <div class="company-info">
      <h1>{company} ({ticker})</h1>
      <p>最新決算サマリー</p>
    </div>
    <div class="star">★</div>
  </div>

  <!-- メタバッジ -->
  <div class="meta">
    {date_badge}
    {quarter_badge}
  </div>

  <!-- ブロック1: 決算サプライズ -->
  <div class="section">
    <div class="section-title">⚡ 決算サプライズ</div>
    <div class="card">
      <!-- 売上高 -->
      <div class="surprise-row">
        <div class="surprise-label">📈 売上高</div>
        <div class="surprise-values">
          {rev_year_ago_html}
          {rev_arrow_html}
          {rev_actual_html}
          {rev_badge_html}
        </div>
      </div>
      <hr class="divider">
      <!-- EPS -->
      <div class="surprise-row">
        <div class="surprise-label">💰 EPS</div>
        <div class="surprise-values">
          {eps_estimate_html}
          {eps_arrow_html}
          {eps_actual_html}
          {eps_badge_html}
        </div>
      </div>
      <!-- 総合コメント -->
      {summary_banner_html}
    </div>
  </div>

  <!-- ブロック2: 経営の健全性 -->
  <div class="section">
    <div class="section-title">🏥 経営の健全性</div>
    <div class="card">
      <div class="health-row">
        <div class="health-card">
          <div class="icon">📊</div>
          <div class="value" style="color:{margin_color}">{op_margin_str}</div>
          <div class="label">営業利益率</div>
          <div class="sub-label">{op_margin_yoy_str}</div>
          {margin_judge_html}
        </div>
        <div class="health-card">
          <div class="icon">💵</div>
          <div class="value" style="color:{fcf_color}">{fcf_str}</div>
          <div class="label">フリーキャッシュフロー</div>
          <div class="sub-label">（現金を生む力）</div>
          {fcf_judge_html}
        </div>
      </div>
    </div>
  </div>

  <!-- ブロック3: 次回の案内 -->
  <div class="section">
    <div class="section-title">📅 次回の案内</div>
    <div class="card">
      <div class="next-row">
        <span class="key">🗓️ 次回決算予定日</span>
        <span class="val">{next_date_str}</span>
      </div>
      <hr class="divider">
      <div class="next-row">
        <span class="key">📈 次回売上予想</span>
        <span class="val">{next_rev_str}</span>
      </div>
      <hr class="divider">
      <div class="next-row">
        <span class="key">💰 次回EPS予想</span>
        <span class="val">{next_eps_str}</span>
      </div>
    </div>
  </div>

</div>
</body>
</html>
"""


def val_group(num_str, sub_str):
    return (
        f'<div class="val-group">'
        f'<div class="num">{num_str}</div>'
        f'<div class="sub">{sub_str}</div>'
        f'</div>'
    )


def badge_html(pct):
    if pct is None:
        return '<span class="badge neu">―</span>'
    cls = "pos" if pct >= 0 else "neg"
    sign = "+" if pct >= 0 else ""
    return f'<span class="badge {cls}">{sign}{pct:.1f}%</span>'


def build_html(d: dict) -> str:
    from datetime import date

    today = date.today().isoformat()
    date_badge = f'<span>📅 発表日: {today}</span>'
    quarter_badge = f'<span>期: {d["quarter"]}</span>' if d["quarter"] else ""

    # 売上高（前年同期 → 実績 + YoY%）
    rev_ya_num = fmt_billion(d["rev_year_ago"]) if d["rev_year_ago"] is not None else '<span class="na">―</span>'
    rev_year_ago_html = val_group(rev_ya_num, "前年同期")
    rev_arr_html = '<span class="arrow">→</span>'

    if d["rev_actual"] is not None:
        rev_act_html = val_group(fmt_billion(d["rev_actual"]), "実績")
    else:
        rev_act_html = val_group('<span class="na">―</span>', "実績")

    rev_bdg_html = badge_html(d["rev_yoy_pct"])

    # 総合コメントバナー
    sc = surprise_comment(d["rev_yoy_pct"], d["eps_surprise_pct"])
    summary_banner_html = (
        f'<div class="summary-banner" style="background:{sc["bg"]};color:{sc["color"]}">'
        f'<span style="font-size:16px">{sc["emoji"]}</span>{sc["text"]}</div>'
    )

    # EPS
    if d["eps_estimate"] is not None:
        eps_est_html = val_group(f'${d["eps_estimate"]:.2f}', "予想")
        eps_arr_html = '<span class="arrow">→</span>'
    else:
        eps_est_html = ""
        eps_arr_html = ""

    if d["eps_actual"] is not None:
        eps_act_html = val_group(f'${d["eps_actual"]:.2f}', "実績")
    else:
        eps_act_html = val_group('<span class="na">―</span>', "実績")

    eps_bdg_html = badge_html(d["eps_surprise_pct"])

    def make_judge_html(judge):
        if judge is None:
            return ""
        return (
            f'<div><span class="judge-badge" style="background:{judge["bg"]};color:{judge["color"]}">'
            f'{judge["text"]}</span></div>'
            f'<div class="judge-reason">{judge["reason"]}</div>'
        )

    # 営業利益率 + 前年同月比
    op_m = d["op_margin"]
    op_margin_str = f'{op_m:.1f}%' if op_m is not None else '―'
    m_color = margin_color(op_m)
    yoy = d.get("op_margin_yoy")
    if yoy is not None:
        sign = "▲" if yoy >= 0 else "▼"
        yoy_color = "#22c55e" if yoy >= 0 else "#ef4444"
        op_margin_yoy_str = f'前年同月比 <span style="color:{yoy_color};font-weight:700">{sign}{abs(yoy):.1f}pt</span>'
    else:
        op_margin_yoy_str = "前年同月比"

    margin_judge_html = make_judge_html(judge_margin(op_m))

    # FCF
    fcf_val = d["fcf"]
    fcf_str = fmt_billion(fcf_val)
    f_color = fcf_color(fcf_val)
    fcf_judge_html = make_judge_html(judge_fcf(fcf_val))

    # 次回
    next_date_str = d["next_date"] or '<span class="na">データなし</span>'
    next_rev_str = fmt_billion(d["next_rev_est"]) if d["next_rev_est"] else '<span class="na">データなし</span>'
    next_eps_str = f'${d["next_eps_est"]:.2f}' if d["next_eps_est"] is not None else '<span class="na">データなし</span>'

    return HTML_TEMPLATE.format(
        ticker=d["ticker"],
        company=d["company"],
        date_badge=date_badge,
        quarter_badge=quarter_badge,
        summary_banner_html=summary_banner_html,
        rev_year_ago_html=rev_year_ago_html,
        rev_arrow_html=rev_arr_html,
        rev_actual_html=rev_act_html,
        rev_badge_html=rev_bdg_html,
        eps_estimate_html=eps_est_html,
        eps_arrow_html=eps_arr_html,
        eps_actual_html=eps_act_html,
        eps_badge_html=eps_bdg_html,
        margin_color=m_color,
        op_margin_str=op_margin_str,
        op_margin_yoy_str=op_margin_yoy_str,
        margin_judge_html=margin_judge_html,
        fcf_judge_html=fcf_judge_html,
        fcf_color=f_color,
        fcf_str=fcf_str,
        next_date_str=next_date_str,
        next_rev_str=next_rev_str,
        next_eps_str=next_eps_str,
    )


# ─── メイン ─────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        ticker = input("ティッカーシンボルを入力してください（例: AAPL）: ").strip()
    else:
        ticker = sys.argv[1]

    ticker = ticker.upper().strip()
    if not ticker:
        print("❌ ティッカーが入力されていません。")
        sys.exit(1)

    print(f"📡 {ticker} のデータを取得中...")
    data = fetch_data(ticker)

    html = build_html(data)

    # 出力先をスクリプトと同じディレクトリに固定
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(out_dir, f"{ticker}_earnings.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ HTMLを生成しました: {out_path}")
    webbrowser.open(f"file:///{out_path.replace(os.sep, '/')}")
    print("🌐 ブラウザで開きました。")


if __name__ == "__main__":
    main()
