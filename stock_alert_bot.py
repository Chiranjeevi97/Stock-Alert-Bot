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

def get_rsi(ticker, period=14):
    data = yf.Ticker(ticker).history(period="30d")
    if data.empty or len(data) < period:
        return None
    delta = data['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)

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

    messages = []

    for ticker, min_drop in stocks.items():
        change, prev, latest, volume_ratio = get_price_change(ticker)
        if change is None or (change > -min_drop and not FORCE_TEST_ALERT):
            continue

        rsi = get_rsi(ticker)
        news = get_news(ticker)
        sentiment = analyze_sentiment(news)
        recommendation = make_recommendation(change, sentiment, rsi, volume_ratio)

        direction = "dropped" if change < 0 else "rose"
        msg = (f"📊 {ticker} {direction} {change}%\n"
               f"💹 RSI: {rsi}, Volume Ratio: {round(volume_ratio, 2)}\n"
               f"📰 Sentiment: {sentiment}\n"
               f"✅ {recommendation}")
        messages.append(msg)

        log_alert(ticker, change, sentiment, rsi, volume_ratio, recommendation, latest)

    if not messages:
        print("✅ No alerts triggered.")
        return

    final_msg = "\n\n".join(messages)
    print("✅ Alerts to be sent:\n", final_msg)
    send_telegram(final_msg)
    send_email("📉 Stock Alert Summary", final_msg)

if __name__ == "__main__":
    main()