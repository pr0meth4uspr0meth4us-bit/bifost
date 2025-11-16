import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """
    Application configuration settings.
    Loads all settings from environment variables.
    """

    # Flask settings
    # This key is required. The app will fail to start if it's not set.
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # Database settings
    # This key is required. The app will fail to start if it's not set.
    MONGO_URI = os.environ.get('MONGO_URI')

    # JWT settings
    # This key is required. The app will fail to start if it's not set.
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

    if not SECRET_KEY or not MONGO_URI or not JWT_SECRET_KEY:
        raise RuntimeError(
            "CRITICAL ERROR: .env file is missing or incomplete. "
            "Please set SECRET_KEY, MONGO_URI, and JWT_SECRET_KEY."
        )