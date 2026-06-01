"""
米国株決算リサーチツール - ローカルWebアプリ
起動: python app.py
ブラウザで http://localhost:5000 を開く
"""

from flask import Flask, request, render_template_string
from earnings_ui import fetch_data, build_html

app = Flask(__name__)

# ── トップページ（検索フォーム）──────────────────────────────────

TOP_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>米国株 決算リサーチ</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #f0f4f8;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 24px 16px;
  }
  .container {
    width: 100%;
    max-width: 480px;
    text-align: center;
  }
  h1 {
    font-size: 22px;
    font-weight: 800;
    color: #1c1c1e;
    margin-bottom: 6px;
  }
  p.sub {
    font-size: 13px;
    color: #8e8e93;
    margin-bottom: 28px;
  }
  .search-box {
    display: flex;
    gap: 10px;
    background: #fff;
    border-radius: 18px;
    padding: 8px 8px 8px 18px;
    box-shadow: 0 4px 20px rgba(0,0,0,.10);
  }
  .search-box input {
    flex: 1;
    border: none;
    outline: none;
    font-size: 18px;
    font-weight: 600;
    color: #1c1c1e;
    background: transparent;
    text-transform: uppercase;
  }
  .search-box input::placeholder {
    color: #c7c7cc;
    font-weight: 400;
    text-transform: none;
  }
  .search-box button {
    background: #1c1c1e;
    color: #fff;
    border: none;
    border-radius: 12px;
    padding: 12px 22px;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    transition: background .15s;
  }
  .search-box button:hover { background: #3a3a3c; }
  .examples {
    margin-top: 16px;
    font-size: 12px;
    color: #8e8e93;
  }
  .examples a {
    color: #636366;
    text-decoration: none;
    background: #e5e7eb;
    padding: 4px 10px;
    border-radius: 20px;
    margin: 3px;
    display: inline-block;
    transition: background .15s;
  }
  .examples a:hover { background: #d1d5db; }
  {% if error %}
  .error-msg {
    margin-top: 20px;
    background: #fee2e2;
    color: #b91c1c;
    border-radius: 12px;
    padding: 12px 16px;
    font-size: 13px;
    font-weight: 600;
  }
  {% endif %}
</style>
</head>
<body>
<div class="container">
  <h1>📊 米国株 決算リサーチ</h1>
  <p class="sub">ティッカーシンボルを入力して最新決算を確認</p>
  <form action="/result" method="get">
    <div class="search-box">
      <input type="text" name="ticker" placeholder="例: AAPL, NVDA, MSFT"
             autofocus autocomplete="off" spellcheck="false"
             value="{{ query }}">
      <button type="submit">検索</button>
    </div>
  </form>
  <div class="examples">
    よく使われる銘柄：
    <a href="/result?ticker=AAPL">AAPL</a>
    <a href="/result?ticker=NVDA">NVDA</a>
    <a href="/result?ticker=MSFT">MSFT</a>
    <a href="/result?ticker=GOOGL">GOOGL</a>
    <a href="/result?ticker=AMZN">AMZN</a>
    <a href="/result?ticker=META">META</a>
    <a href="/result?ticker=TSLA">TSLA</a>
  </div>
  {% if error %}
  <div class="error-msg">{{ error }}</div>
  {% endif %}
</div>
</body>
</html>
"""

# ── 結果ページ ────────────────────────────────────────────────────

RESULT_WRAPPER = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} 決算サマリー</title>
{styles}
<style>
  .back-bar {{
    width: 390px;
    max-width: 100%;
    margin: 0 auto 12px;
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .back-bar a {{
    font-size: 13px;
    color: #636366;
    text-decoration: none;
    background: #fff;
    padding: 8px 14px;
    border-radius: 20px;
    font-weight: 600;
    box-shadow: 0 2px 6px rgba(0,0,0,.08);
  }}
  .back-bar a:hover {{ background: #f2f2f7; }}
  .search-mini {{
    flex: 1;
    display: flex;
    background: #fff;
    border-radius: 20px;
    overflow: hidden;
    box-shadow: 0 2px 6px rgba(0,0,0,.08);
  }}
  .search-mini input {{
    flex: 1;
    border: none;
    outline: none;
    padding: 8px 14px;
    font-size: 14px;
    font-weight: 600;
    text-transform: uppercase;
    background: transparent;
    color: #1c1c1e;
  }}
  .search-mini button {{
    background: #1c1c1e;
    color: #fff;
    border: none;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
  }}
</style>
</head>
<body>
<div class="back-bar">
  <a href="/">← 戻る</a>
  <form action="/result" method="get" class="search-mini">
    <input type="text" name="ticker" placeholder="別の銘柄を検索..."
           autocomplete="off" spellcheck="false">
    <button type="submit">検索</button>
  </form>
</div>
{body}
</body>
</html>
"""


@app.route("/api/result")
def api_result():
    from flask import jsonify
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        resp = jsonify({"error": "ticker required"})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400
    try:
        data = fetch_data(ticker)
        resp = jsonify(data)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:
        resp = jsonify({"error": str(e)})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 500


@app.route("/")
def index():
    return render_template_string(TOP_HTML, query="", error=None)


@app.route("/result")
def result():
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        return render_template_string(TOP_HTML, query="", error="ティッカーを入力してください")

    try:
        data = fetch_data(ticker)
        # 企業名が取れない場合はティッカー不明とみなす
        if data["company"] == ticker and data["rev_actual"] is None and data["fcf"] is None:
            return render_template_string(
                TOP_HTML, query=ticker,
                error=f'「{ticker}」のデータが見つかりませんでした。ティッカーを確認してください。'
            )
        full_html = build_html(data)
        # build_html が返す完全HTMLから <style> と <body> 中身を抽出して埋め込む
        import re
        style_match = re.search(r"<style>(.*?)</style>", full_html, re.DOTALL)
        body_match  = re.search(r"<body>(.*?)</body>",  full_html, re.DOTALL)
        styles = f"<style>{style_match.group(1)}</style>" if style_match else ""
        body   = body_match.group(1) if body_match else full_html
        return RESULT_WRAPPER.format(ticker=ticker, styles=styles, body=body)
    except Exception as e:
        return render_template_string(
            TOP_HTML, query=ticker,
            error=f"データ取得中にエラーが発生しました: {e}"
        )


if __name__ == "__main__":
    import webbrowser, threading
    def open_browser():
        webbrowser.open("http://localhost:5000")
    threading.Timer(1.0, open_browser).start()
    print("🚀 サーバー起動中... http://localhost:5000")
    app.run(debug=False, port=5000)
