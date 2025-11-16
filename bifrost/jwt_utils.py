import jwt
import datetime
from flask import current_app


def create_jwt(account_id):
    """
    Creates a new JSON Web Token (JWT) for a given account_id.
    """
    try:
        payload = {
            'sub': str(account_id),  # 'sub' (subject) is a standard JWT claim for the user ID
            'iat': datetime.datetime.utcnow(),  # 'iat' (issued at)
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1)  # 'exp' (expiration) - 1 day
        }

        token = jwt.encode(
            payload,
            current_app.config['JWT_SECRET_KEY'],
            algorithm='HS256'
        )

        return token

    except Exception as e:
        current_app.logger.error(f"Error creating JWT: {e}")
        return None


def decode_jwt(token):
    """
    Decodes and validates a JWT.
    Returns the payload if valid, None otherwise.
    """
    try:
        payload = jwt.decode(
            token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=['HS256']
        )
        return payload
    except jwt.ExpiredSignatureError:
        current_app.logger.warning("Token decode error: Expired")
        return None
    except jwt.InvalidTokenError as e:
        current_app.logger.warning(f"Token decode error: Invalid: {e}")
        return None