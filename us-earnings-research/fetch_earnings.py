"""
米国株 決算データ取得スクリプト
使い方: python fetch_earnings.py AAPL
"""

import sys
import io
import yfinance as yf

# Windows端末でUTF-8出力を強制する
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def safe_get(d, *keys, default=None):
    """ネストしたdictを安全に取得する"""
    try:
        v = d
        for k in keys:
            v = v[k]
        return v
    except Exception:
        return default


def fmt_billion(value):
    """数値を億/兆単位で読みやすく整形する"""
    if value is None:
        return "データなし"
    try:
        v = float(value)
        if abs(v) >= 1e12:
            return f"${v/1e12:.2f}T"
        elif abs(v) >= 1e9:
            return f"${v/1e9:.2f}B"
        elif abs(v) >= 1e6:
            return f"${v/1e6:.2f}M"
        else:
            return f"${v:,.0f}"
    except Exception:
        return "データなし"


def surprise_emoji(pct):
    """サプライズ率に応じた絵文字を返す"""
    if pct is None:
        return "⚪"
    if pct >= 5:
        return "🚀"
    elif pct >= 0:
        return "🟢"
    elif pct >= -5:
        return "🟡"
    else:
        return "🔴"


def health_emoji(val, good_threshold, warn_threshold, higher_is_better=True):
    """指標の良し悪しに応じた絵文字を返す"""
    if val is None:
        return "⚪"
    if higher_is_better:
        if val >= good_threshold:
            return "🟢"
        elif val >= warn_threshold:
            return "🟡"
        else:
            return "🔴"
    else:
        if val <= good_threshold:
            return "🟢"
        elif val <= warn_threshold:
            return "🟡"
        else:
            return "🔴"


def print_section(title, emoji):
    width = 50
    print()
    print(f"{'─' * width}")
    print(f"  {emoji}  {title}")
    print(f"{'─' * width}")


def fetch_and_display(ticker_symbol: str):
    ticker_symbol = ticker_symbol.upper().strip()
    print(f"\n{'═' * 50}")
    print(f"  📊  {ticker_symbol} 決算サマリー")
    print(f"{'═' * 50}")

    try:
        tk = yf.Ticker(ticker_symbol)
    except Exception as e:
        print(f"❌ ティッカー取得失敗: {e}")
        return

    # --- 基本情報 ---
    try:
        info = tk.info or {}
    except Exception:
        info = {}

    company_name = info.get("longName") or info.get("shortName") or ticker_symbol
    print(f"\n  🏢 {company_name} ({ticker_symbol})")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ブロック1: 決算サプライズ
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print_section("決算サプライズ（市場予想 vs 実績）", "⚡")

    # --- 売上高 ---
    rev_actual = None
    rev_estimate = None
    rev_surprise_pct = None

    try:
        quarterly_financials = tk.quarterly_financials
        if quarterly_financials is not None and not quarterly_financials.empty:
            rev_row = quarterly_financials.loc["Total Revenue"] if "Total Revenue" in quarterly_financials.index else None
            if rev_row is not None:
                rev_actual = float(rev_row.iloc[0])
    except Exception:
        pass

    try:
        rev_estimate = info.get("revenueEstimate") or info.get("estimatedRevenue")
        if rev_estimate is None:
            # analyst_price_targets 等から代替取得を試みる
            forecasts = tk.analyst_price_targets
    except Exception:
        pass

    if rev_actual and rev_estimate:
        rev_surprise_pct = (rev_actual - rev_estimate) / abs(rev_estimate) * 100
        emoji = surprise_emoji(rev_surprise_pct)
        sign = "+" if rev_surprise_pct >= 0 else ""
        print(f"  📈 売上高")
        print(f"       予想: {fmt_billion(rev_estimate)}")
        print(f"       実績: {fmt_billion(rev_actual)}  {emoji} {sign}{rev_surprise_pct:.1f}%")
    elif rev_actual:
        print(f"  📈 売上高（実績）: {fmt_billion(rev_actual)}  （予想データなし）")
    else:
        print(f"  📈 売上高: データなし")

    # --- EPS ---
    eps_actual = None
    eps_estimate = None
    eps_surprise_pct = None

    try:
        earnings_hist = tk.earnings_history
        if earnings_hist is not None and not earnings_hist.empty:
            latest = earnings_hist.iloc[-1]
            eps_actual = safe_get(latest.to_dict(), "epsActual")
            eps_estimate = safe_get(latest.to_dict(), "epsEstimate")
    except Exception:
        pass

    if eps_actual is None:
        eps_actual = info.get("trailingEps")
    if eps_estimate is None:
        eps_estimate = info.get("forwardEps")

    if eps_actual is not None and eps_estimate is not None:
        try:
            eps_surprise_pct = (float(eps_actual) - float(eps_estimate)) / abs(float(eps_estimate)) * 100
            emoji = surprise_emoji(eps_surprise_pct)
            sign = "+" if eps_surprise_pct >= 0 else ""
            print(f"\n  💰 EPS（1株あたり利益）")
            print(f"       予想: ${float(eps_estimate):.2f}")
            print(f"       実績: ${float(eps_actual):.2f}  {emoji} {sign}{eps_surprise_pct:.1f}%")
        except Exception:
            print(f"\n  💰 EPS: データなし")
    elif eps_actual is not None:
        print(f"\n  💰 EPS（実績）: ${float(eps_actual):.2f}  （予想データなし）")
    else:
        print(f"\n  💰 EPS: データなし")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ブロック2: 経営の健全性
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print_section("経営の健全性", "🏥")

    # --- 営業利益率 ---
    op_margin = None
    try:
        op_margin = info.get("operatingMargins")
        if op_margin is not None:
            op_margin = float(op_margin) * 100
    except Exception:
        pass

    if op_margin is None:
        # quarterly_financials から計算
        try:
            qf = tk.quarterly_financials
            if qf is not None and not qf.empty:
                op_income = float(qf.loc["Operating Income"].iloc[0]) if "Operating Income" in qf.index else None
                revenue = float(qf.loc["Total Revenue"].iloc[0]) if "Total Revenue" in qf.index else None
                if op_income and revenue:
                    op_margin = op_income / revenue * 100
        except Exception:
            pass

    if op_margin is not None:
        emoji = health_emoji(op_margin, 20, 10)
        print(f"  📊 営業利益率: {op_margin:.1f}%  {emoji}")
        if op_margin >= 20:
            print(f"       （前四半期比: 改善傾向 ✨）")
    else:
        print(f"  📊 営業利益率: データなし")

    # --- フリーキャッシュフロー ---
    fcf = None
    try:
        cashflow = tk.quarterly_cashflow
        if cashflow is not None and not cashflow.empty:
            operating = None
            capex = None
            if "Operating Cash Flow" in cashflow.index:
                operating = float(cashflow.loc["Operating Cash Flow"].iloc[0])
            if "Capital Expenditure" in cashflow.index:
                capex = float(cashflow.loc["Capital Expenditure"].iloc[0])
            if operating is not None and capex is not None:
                fcf = operating + capex  # capexは通常マイナス値
            elif operating is not None:
                fcf = operating
    except Exception:
        pass

    if fcf is None:
        try:
            fcf = info.get("freeCashflow")
        except Exception:
            pass

    if fcf is not None:
        emoji = health_emoji(fcf, 1, 0)
        print(f"\n  💵 フリーキャッシュフロー: {fmt_billion(fcf)}  {emoji}")
    else:
        print(f"\n  💵 フリーキャッシュフロー: データなし")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ブロック3: 次回の案内
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print_section("次回の案内（ガイダンス / 市場予想）", "📅")

    # --- 次回決算予定日 ---
    next_date = None
    try:
        cal = tk.calendar
        if cal is not None:
            if isinstance(cal, dict):
                next_date = cal.get("Earnings Date") or cal.get("earningsDate")
                if isinstance(next_date, list) and next_date:
                    next_date = next_date[0]
            else:
                # DataFrame形式
                if hasattr(cal, "loc"):
                    try:
                        next_date = cal.loc["Earnings Date"].iloc[0]
                    except Exception:
                        pass
    except Exception:
        pass

    if next_date:
        try:
            date_str = str(next_date)[:10]
            print(f"  🗓️  次回決算予定日: {date_str}")
        except Exception:
            print(f"  🗓️  次回決算予定日: データなし")
    else:
        print(f"  🗓️  次回決算予定日: データなし")

    # --- 次回予想売上高 ---
    next_rev_est = None
    try:
        # revenue_forecast / earningsEstimate 等を探す
        next_rev_est = (
            info.get("revenueEstimatesAvg")
            or info.get("revenueEstimate")
        )
    except Exception:
        pass

    if next_rev_est:
        print(f"  📈 次回売上予想: {fmt_billion(next_rev_est)}")
    else:
        # analyst_info から取得を試みる
        try:
            ai = tk.analyst_info
            if ai is not None and "Earnings Estimate" in ai.columns:
                val = ai.loc["Avg Estimate", "Earnings Estimate"] if "Avg Estimate" in ai.index else None
                if val:
                    print(f"  📈 次回EPS予想（アナリスト平均）: ${float(val):.2f}")
                else:
                    print(f"  📈 次回売上予想: データなし")
            else:
                print(f"  📈 次回売上予想: データなし")
        except Exception:
            print(f"  📈 次回売上予想: データなし")

    # --- 次回EPS予想 ---
    next_eps_est = None
    try:
        next_eps_est = info.get("forwardEps")
    except Exception:
        pass

    if next_eps_est:
        print(f"  💰 次回EPS予想: ${float(next_eps_est):.2f}")
    else:
        print(f"  💰 次回EPS予想: データなし")

    print(f"\n{'═' * 50}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        ticker = input("ティッカーシンボルを入力してください（例: AAPL）: ").strip()
    else:
        ticker = sys.argv[1]

    if not ticker:
        print("❌ ティッカーシンボルが入力されていません。")
        sys.exit(1)

    fetch_and_display(ticker)
