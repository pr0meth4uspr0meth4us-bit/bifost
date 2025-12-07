import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    MONGO_URI = os.environ.get('MONGO_URI')
    DB_NAME = os.environ.get('DB_NAME', 'bifrost_db')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

    # --- EMAIL SETTINGS (NEW) ---
    EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.mail.me.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'bifrost.helm@icloud.com')

    if not SECRET_KEY or not MONGO_URI or not JWT_SECRET_KEY or not EMAIL_PASSWORD:
        raise RuntimeError("CRITICAL: Missing .env keys (EMAIL_PASSWORD, SECRET_KEY, etc.)")