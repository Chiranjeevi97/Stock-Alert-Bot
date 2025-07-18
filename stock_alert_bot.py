import os
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from telegram import Bot

# ==== CONFIG FROM ENV ====
EMAIL_FROM = os.environ.get('EMAIL_FROM')
EMAIL_TO = os.environ.get('EMAIL_FROM')  # sending to same address
EMAIL_APP_PASSWORD = os.environ.get('EMAIL_APP_PASSWORD')

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

STOCKS = {
    'NVDA': (1, 3),
    'MSFT': (1, 3),
    'TSLA': (2, 5),
    'GOOGL': (2, 5),
    'META': (2, 5),
    'RDDT': (1, 3)
}
# ==========================

def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print("Email sent!")

def send_telegram(message):
    bot = Bot(token=TELEGRAM_TOKEN)
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    print("Telegram message sent!")

def check_stocks():
    alert_messages = []
    for symbol, (low, high) in STOCKS.items():
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")  # Yesterday and today
        if len(hist) < 2:
            continue

        yesterday_close = hist['Close'].iloc[-2]
        today_price = hist['Close'].iloc[-1]
        drop_percent = ((yesterday_close - today_price) / yesterday_close) * 100

        if low <= drop_percent <= high:
            msg = f"{symbol} dropped {drop_percent:.2f}% (from {yesterday_close:.2f} to {today_price:.2f})"
            alert_messages.append(msg)

    if alert_messages:
        combined_msg = "\n".join(alert_messages)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        final_msg = f"[{timestamp}] ALERT:\n{combined_msg}"
        send_email("📉 Stock Drop Alert", final_msg)
        send_telegram(final_msg)

if __name__ == "__main__":
    check_stocks()

