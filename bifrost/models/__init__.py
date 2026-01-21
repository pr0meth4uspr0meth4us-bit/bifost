from .base import BaseMixin
from .auth import AuthMixin
from .apps import AppMixin
from .payments import PaymentMixin
from werkzeug.local import LocalProxy
from flask import current_app

class BifrostDB(BaseMixin, AuthMixin, AppMixin, PaymentMixin):
    """
    Central Database Manager for Bifrost.
    Combines functionality from Auth, Apps, and Payment mixins.
    """
    def __init__(self, mongo_client, db_name):
        super().__init__(mongo_client, db_name)