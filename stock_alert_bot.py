import yfinance as yf
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import smtplib
from email.message import EmailMessage
from telegram import Bot
import os
import json
import pandas as pd
from datetime import datetime
import pytz

CONFIG_FILE = "stocks.json"
ALERT_LOG = "alert_history.csv"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
ALPHAVANTAGE_KEY = os.getenv("ALPHAVANTAGE_KEY")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
FORCE_TEST_ALERT = os.getenv("FORCE_TEST_ALERT", "false").lower() == "true"

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
        return config.get("stocks", {})
    except Exception as e:
        print(f"⚠️ Failed to load config: {e}")
        return {}

def within_market_hours():
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern)
    return 7 <= now.hour < 17  # 7 AM to 5 PM EST

def get_price_change(ticker):
    data = yf.Ticker(ticker).history(period="5d")
    if data.empty or len(data) < 2:
        return None, None, None, None

    data = data.sort_index()
    close_prices = data['Close']
    volume = data['Volume']

    previous_close = close_prices.iloc[-2]
    latest_close = close_prices.iloc[-1]
    change = (latest_close - previous_close) / previous_close * 100

    avg_volume = volume.iloc[-5:-1].mean()
    current_volume = volume.iloc[-1]

    return round(change, 2), previous_close, latest_close, (current_volume / avg_volume)

def summary_insight(rsi, volume_ratio, sentiment):
    insight = []

    # Interpret RSI
    if rsi is None:
        rsi_summary = "No RSI data available"
    elif rsi < 30:
        rsi_summary = f"RSI at {rsi} signals oversold territory."
    elif rsi < 50:
        rsi_summary = f"Hovering around {rsi}, in neutral-to-buy zone."
    elif rsi < 70:
        rsi_summary = f"Hovering around {rsi}, in neutral-to-sell zone."
    else:
        rsi_summary = f"RSI at {rsi} indicates strong overbought conditions."

    insight.append(rsi_summary)

    # Volume insight
    if volume_ratio is not None:
        if volume_ratio > 2:
            insight.append(f"Volume surging (~{round(volume_ratio, 1)}x avg).")
        elif volume_ratio > 1.2:
            insight.append(f"Volume above average (~{round(volume_ratio, 1)}x).")
        else:
            insight.append("Volume within normal range.")

    # Sentiment interpretation
    if sentiment > 0.4:
        insight.append("Sentiment clearly positive.")
    elif sentiment < -0.4:
        insight.append("Sentiment strongly negative.")
    elif abs(sentiment) <= 0.15:
        insight.append("Sentiment neutral.")
    else:
        insight.append("Mixed sentiment.")

    return "✅ Summary: " + " ".join(insight)

def get_rsi_yf(ticker, period=14):
    try:
        data = yf.Ticker(ticker).history(period="30d")
        if data.empty or len(data) < period:
            return None
        delta = data['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 2)
    except Exception as e:
        print(f"⚠️ RSI (yfinance) failed for {ticker}: {e}")
        return None

def get_rsi_alpha_vantage(ticker, interval="daily", time_period=14):
    try:
        url = (f"https://www.alphavantage.co/query?"
               f"function=RSI&symbol={ticker}&interval={interval}&"
               f"time_period={time_period}&series_type=close&apikey={ALPHAVANTAGE_KEY}")
        res = requests.get(url)
        data = res.json()
        rsi_data = data.get("Technical Analysis: RSI", {})
        if not rsi_data:
            return None
        latest = sorted(rsi_data.keys())[-1]
        return round(float(rsi_data[latest]["RSI"]), 2)
    except Exception as e:
        print(f"⚠️ RSI (Alpha Vantage) failed for {ticker}: {e}")
        return None

def get_rsi_finnhub(ticker, resolution="D", period=14):
    try:
        url = f"https://finnhub.io/api/v1/indicator?symbol={ticker}&resolution={resolution}&indicator=rsi&timeperiod={period}&token={FINNHUB_KEY}"
        res = requests.get(url)
        data = res.json()
        if 'rsi' in data and 'result' in data and data['rsi'] and data['rsi'][-1]:
            return round(data['rsi'][-1], 2)
    except Exception as e:
        print(f"⚠️ RSI (Finnhub) failed for {ticker}: {e}")
    return None

def get_rsi_twelve_data(ticker, interval="1day", time_period=14):
    try:
        url = f"https://api.twelvedata.com/rsi?symbol={ticker}&interval={interval}&time_period={time_period}&apikey={TWELVE_DATA_KEY}"
        res = requests.get(url)
        data = res.json()
        if 'value' in data and data['value']:
            return round(float(data['value']), 2)
    except Exception as e:
        print(f"⚠️ RSI (Twelve Data) failed for {ticker}: {e}")
    return None
def get_multi_rsi(ticker):
    rsi_sources = []

    # yFinance
    yf_rsi = get_rsi_yf(ticker)
    if yf_rsi is not None:
        print(f"✅ yFinance RSI for {ticker}: {yf_rsi}")
        rsi_sources.append(yf_rsi)

    # Alpha Vantage
    av_rsi = get_rsi_alpha_vantage(ticker)
    if av_rsi is not None:
        print(f"✅ AlphaVantage RSI for {ticker}: {av_rsi}")
        rsi_sources.append(av_rsi)

    # Finnhub
    finnhub_rsi = get_rsi_finnhub(ticker)
    if finnhub_rsi is not None:
        print(f"✅ Finnhub RSI for {ticker}: {finnhub_rsi}")
        rsi_sources.append(finnhub_rsi)

    # Twelve Data
    td_rsi = get_rsi_twelve_data(ticker)
    if td_rsi is not None:
        print(f"✅ TwelveData RSI for {ticker}: {td_rsi}")
        rsi_sources.append(td_rsi)

    if not rsi_sources:
        print(f"❌ No RSI sources succeeded for {ticker}.")
        return None

    avg_rsi = round(sum(rsi_sources) / len(rsi_sources), 2)
    print(f"🎯 Final RSI for {ticker} (avg of {len(rsi_sources)}): {avg_rsi}")
    return avg_rsi

def get_news(ticker):
    url = f"https://newsapi.org/v2/everything?q={ticker}&apiKey={NEWSAPI_KEY}&sortBy=publishedAt"
    res = requests.get(url)
    return res.json().get('articles', [])[:5]

def analyze_sentiment(articles):
    analyzer = SentimentIntensityAnalyzer()
    scores = [analyzer.polarity_scores(a['title'])['compound'] for a in articles]
    return round(sum(scores) / len(scores), 2) if scores else 0

def make_recommendation(change, sentiment, rsi, volume_ratio):
    if rsi is None:
        rsi = 50  # neutral fallback

    # Rules-based logic
    if change < -2 and sentiment > 0.3 and rsi < 35 and volume_ratio > 1:
        return "📈 Buy Opportunity (Dip + Positive News + Oversold + High Volume)"
    elif change > 2 and sentiment < -0.2 and rsi > 70 and volume_ratio > 1:
        return "📉 Sell Alert (Spike + Bad News + Overbought + High Volume)"
    elif abs(change) > 3 and volume_ratio > 2:
        return "⚠️ Volatile Move - Watch Closely"
    return "📊 Hold"

def send_telegram(message):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        bot = Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    else:
        print("⚠️ Telegram credentials not set.")

def send_email(subject, message):
    if EMAIL_FROM and EMAIL_TO and EMAIL_APP_PASSWORD:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg.set_content(message)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
    else:
        print("⚠️ Email credentials not set.")

def log_alert(ticker, change, sentiment, rsi, volume_ratio, recommendation, price):
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "ticker": ticker,
        "change%": change,
        "sentiment": sentiment,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "recommendation": recommendation,
        "price": price
    }
    df = pd.DataFrame([log_data])
    if not os.path.exists(ALERT_LOG):
        df.to_csv(ALERT_LOG, index=False)
    else:
        df.to_csv(ALERT_LOG, mode='a', header=False, index=False)

def main():
    if not FORCE_TEST_ALERT and not within_market_hours():
        print("⏰ Outside market hours. Skipping run.")
        return

    stocks = load_config()
    if not stocks:
        print("⚠️ No stocks loaded from config.")
        return

    telegram_messages = []
    email_messages = []

    for ticker, min_drop in stocks.items():
        change, prev, latest, volume_ratio = get_price_change(ticker)
        if change is None or (change > -min_drop and not FORCE_TEST_ALERT):
            continue

        rsi = get_multi_rsi(ticker)
        news = get_news(ticker)
        sentiment = analyze_sentiment(news)
        recommendation = make_recommendation(change, sentiment, rsi, volume_ratio)
        summary = summary_insight(rsi, volume_ratio, sentiment)

        # ✂️ Split summary into two lines
        summary_lines = summary.strip().split(". ")
        summary_line1 = summary_lines[0].strip() + "." if summary_lines else ""
        summary_line2 = ". ".join(summary_lines[1:]).strip()
        if summary_line2 and not summary_line2.endswith("."):
            summary_line2 += "."

        direction = "dropped" if change < 0 else "rose"
        price_str = f"${latest:.2f}, {change:+.2f}%"

        # Telegram formatted message (monospace block)
        tg_msg = (
            f"{ticker} ({price_str})\n"
            f"\tRSI:            {rsi}\n"
            f"\tVolume Ratio:   {round(volume_ratio, 2)}\n"
            f"\tSentiment:      {sentiment}\n"
            f"\tSummary:        {summary_line1}\n"
            f"\t                {summary_line2}\n"
            f"\tRecommendation: {recommendation}"
        )
        telegram_messages.append(tg_msg)

        # Email formatted message (Markdown-style)
        news_bullets = "".join([f"<li>{a['title']}</li>" for a in news])
        em_msg = (
            f"<hr>"
            f"<h2>{ticker} {'DROPPED' if change < 0 else 'ROSE'} ({change:+.2f}%)</h2>"
            f"<p>"
            f"<strong>RSI:</strong> {rsi}<br>"
            f"<strong>Volume Ratio:</strong> {round(volume_ratio, 2)}<br>"
            f"<strong>Sentiment:</strong> {sentiment}<br>"
            f"<strong>Current Price:</strong> ${latest:.2f}<br>"
            f"<strong>Previous Close:</strong> ${prev:.2f}<br>"
            f"<strong>Recommendation:</strong> {recommendation}"
            f"</p>"
            f"<h4>Insight Summary</h4>"
            f"<p>{summary.replace(chr(10), '<br>')}</p>"
            f"<h4>Top News Headlines</h4>"
            f"<ul>{news_bullets}</ul>"
        )
        email_messages.append(em_msg)
        log_alert(ticker, change, sentiment, rsi, volume_ratio, recommendation, latest)

    if not telegram_messages:
        print("✅ No alerts triggered.")
        return

    # Combine all Telegram messages into a monospace block
    final_telegram = "```\n" + "\n--------\n".join(telegram_messages) + "\n```"
    final_email = "".join(email_messages)

    print("✅ Alerts to be sent:\n", final_telegram)
    send_telegram(final_telegram)
    send_email("📉 Stock Alert Summary", final_email, html=True)

if __name__ == "__main__":
    main()