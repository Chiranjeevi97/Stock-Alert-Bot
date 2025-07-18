import yfinance as yf
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import smtplib
from email.message import EmailMessage
from telegram import Bot
import os
import json
from datetime import datetime
import pytz

CONFIG_FILE = "stocks.json"

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
    data = yf.Ticker(ticker).history(period="2d")
    if len(data) < 2:
        return None
    change = (data['Close'][-1] - data['Close'][-2]) / data['Close'][-2] * 100
    return round(change, 2)

def get_news(ticker):
    url = f"https://newsapi.org/v2/everything?q={ticker}&apiKey={NEWSAPI_KEY}&sortBy=publishedAt"
    res = requests.get(url)
    return res.json().get('articles', [])[:5]

def analyze_sentiment(articles):
    analyzer = SentimentIntensityAnalyzer()
    scores = [analyzer.polarity_scores(a['title'])['compound'] for a in articles]
    return round(sum(scores) / len(scores), 2) if scores else 0

def make_recommendation(change, sentiment):
    if change < -2 and sentiment > 0.3:
        return "📈 Good to Buy"
    elif change > 2 and sentiment < -0.2:
        return "📉 Good to Sell"
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
        change = get_price_change(ticker)
        if change is None or (change > -min_drop and not FORCE_TEST_ALERT):
            continue

        news = get_news(ticker)
        sentiment = analyze_sentiment(news)
        recommendation = make_recommendation(change, sentiment)

        msg = f"📊 {ticker} dropped {change}%\n📰 Sentiment: {sentiment}\n✅ {recommendation}"
        messages.append(msg)

    if not messages:
        print("✅ No alerts triggered.")
        return

    final_msg = "\n\n".join(messages)
    print("✅ Alerts to be sent:\n", final_msg)
    send_telegram(final_msg)
    send_email("📉 Stock Alert Summary", final_msg)

if __name__ == "__main__":
    main()