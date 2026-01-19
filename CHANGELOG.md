# Changelog

All notable changes to the `bifrost` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 2026-01-19

### Fixed
- **Database integrity:** Resolved `DuplicateKeyError` on the `phone_number` field during account registration.
- **User Model:** Refactored `create_account` to avoid inserting `null` values for optional fields and updated `init_indexes` to ensure `phone_number`, `email`, and `telegram_id` use unique sparse indexes.

## [Unreleased] - 2026-01-16

### Added
- **Centralized Auth:** Promoted `bifrost` to serve as the Global Identity Provider (IdP) for the ecosystem.
- **User Model:** Implemented comprehensive `User` model in `bifrost/models.py` supporting:
  - Password hashing using `werkzeug.security`.
  - Account creation and management.
  - Application linking logic to associate users with specific client apps (e.g., Finance Bot).
- **Authentication API:**
  - New `bifrost/auth/api.py` module containing headless API endpoints.
  - Added `POST /auth/api/login` for standard Email/Password authentication.
  - Added `POST /auth/api/register` for new user registration.
  - Added `POST /auth/api/telegram-login` for headless/widget Telegram authentication.
  - Secure JWT issuance upon successful authentication.
- **Service-to-Service Validation:**
  - Added `bifrost/internal/routes.py` to handle internal service communication.
  - Implemented `POST /internal/validate-token` endpoint to allow client services (like Finance Bot) to validate User JWTs.
  - Added `require_service_auth` decorator for securing internal routes with Client Credentials.

### Changed
- **Blueprint Registration:** Updated `bifrost/__init__.py` to correctly register `auth_api_bp` and `internal_bp` blueprints.
- **CORS Configuration:** Enabled CORS in `bifrost/__init__.py` to allow cross-origin requests from the frontend (Next.js).
- **Database Initialization:** Refactored `bifrost/__init__.py` to ensure `BifrostDB` and indexes are initialized within the application context.
- **Imports:** Standardized imports across all modified files (`models.py`, `auth/api.py`, `internal/routes.py`) to use relative imports and correct type hints.

### Fixed
- Resolved potential build crashes by wrapping database initialization in `try-except` blocks in the app factory.
- Fixed "Fix" comments in the codebase to implementation code.