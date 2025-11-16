from werkzeug.security import generate_password_hash, check_password_hash
import uuid


# --- Hashing Utilities ---

def hash_password(password):
    """Generates a secure hash for a password."""
    return generate_password_hash(password)


def check_password(password_hash, password):
    """Checks a password against a stored hash."""
    return check_password_hash(password_hash, password)


def hash_client_secret(secret):
    """
    Generates a secure hash for a client_secret.
    We re-use the password hashing for robustness.
    """
    return generate_password_hash(secret)


def check_client_secret(secret_hash, secret):
    """Checks a client_secret against a stored hash."""
    return check_password_hash(secret_hash, secret)


# --- ID & Secret Generators ---

def generate_client_id():
    """Generates a simple, unique client_id."""
    return f"bifrost_client_{uuid.uuid4().hex[:16]}"


def generate_client_secret():
    """
    Generates a secure, random client_secret.
    This is the raw secret shown to the admin once.
    """
    # Returns a 64-character hex string
    return uuid.uuid4().hex + uuid.uuid4().hex


# --- Collection Definitions & Indexes ---

def create_indexes(mongo_cx):
    """
    Applies all necessary indexes to the MongoDB collections.
    This is idempotent (safe to run multiple times).
    """

    try:
        # --- accounts collection ---
        # Create unique indexes for each login method.
        # 'sparse=True' means the index only applies to documents
        # that have this field, allowing nulls (e.g., users without 'google_id').
        mongo_cx.db.accounts.create_index("email", unique=True, sparse=True)
        mongo_cx.db.accounts.create_index("phone_number", unique=True, sparse=True)
        mongo_cx.db.accounts.create_index("google_id", unique=True, sparse=True)
        mongo_cx.db.accounts.create_index("telegram_id", unique=True, sparse=True)

        # --- applications collection ---
        mongo_cx.db.applications.create_index("client_id", unique=True)

        # --- app_links collection ---
        # Compound index to ensure an account is linked to an app only once.
        mongo_cx.db.app_links.create_index([("account_id", 1), ("app_id", 1)], unique=True)
        # Standard indexes for fast lookups
        mongo_cx.db.app_links.create_index("account_id")
        mongo_cx.db.app_links.create_index("app_id")

        # --- admins collection ---
        mongo_cx.db.admins.create_index("email", unique=True)

        print("MongoDB indexes applied successfully.")

    except Exception as e:
        print(f"Error applying indexes: {e}")