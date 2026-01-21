import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # --- CORE DATABASE & SECURITY ---
    SECRET_KEY = os.environ.get('SECRET_KEY')
    MONGO_URI = os.environ.get('MONGO_URI')
    DB_NAME = os.environ.get('DB_NAME', 'bifrost_db')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

    # --- EMAIL SERVICE ---
    EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SENDER_EMAIL = 'bifrostbyhelm@gmail.com'

    # --- PUBLIC URLS ---
    BIFROST_PUBLIC_URL = os.environ.get('BIFROST_PUBLIC_URL', 'http://localhost:5000')
    BIFROST_BOT_TOKEN = os.environ.get('BIFROST_BOT_TOKEN')
    BIFROST_BOT_SECRET = os.getenv("BIFROST_BOT_SECRET")
    BIFROST_BOT_USERNAME = 'bifrost_byhelm_bot'
    PAYMENT_GROUP_ID = os.environ.get('PAYMENT_GROUP_ID')

    # --- INTERNAL SERVICE AUTH (Bot talking to API) ---
    BIFROST_API_URL = os.environ.get('BIFROST_API_URL', 'http://localhost:8000')
    BIFROST_ROOT_CLIENT_ID = os.environ.get('BIFROST_CLIENT_ID')
    BIFROST_ROOT_CLIENT_SECRET = os.environ.get('BIFROST_CLIENT_SECRET')

    # --- ABA PAYWAY ---
    PAYWAY_API_URL = os.environ.get('PAYWAY_API_URL', 'https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/purchase')
    PAYWAY_MERCHANT_ID = os.environ.get('PAYWAY_MERCHANT_ID', 'ec462892')
    PAYWAY_API_KEY = os.environ.get('PAYWAY_API_KEY', '8f43f99f4b8bfb7b050f55f0c2b79858cc237dcb')

    # --- GUMROAD ---
    GUMROAD_PRODUCT_PERMALINK = os.environ.get('GUMROAD_PRODUCT_PERMALINK')
    GUMROAD_BASE_URL = "https://gumroad.com/l"

    @staticmethod
    def check_critical():
        """Ensures vital keys are present."""
        if not Config.SECRET_KEY or not Config.MONGO_URI:
            raise RuntimeError("CRITICAL: Missing SECRET_KEY or MONGO_URI in environment.")