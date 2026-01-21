# Changelog

All notable changes to the `bifrost` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.1] - 2026-01-21

### Changed
- **Bot Architecture**: Migrated from Long Polling to Webhooks for cost efficiency and scalability on serverless platforms (Koyeb).
- **Process Management**: Updated `run.sh` to exclusively run the Gunicorn Web Server. The Bot process is now triggered internally via the `/telegram-webhook` route.
- **State Management**: Replaced local file storage (`PicklePersistence`) with `MongoPersistence` (`bot/persistence.py`) to store conversation states in MongoDB. This enables stateless, concurrent webhook workers to handle multiple users simultaneously without race conditions.

### Fixed
- **Concurrency Crash**: Resolved `RuntimeError: Event loop is closed` by creating an ephemeral `Application` instance for each incoming webhook request.
- **Import Errors**: Fixed `ModuleNotFoundError` for bot handlers when running within the Flask application context.
- **Telegram Conflict**: Resolved HTTP 409 Conflict errors caused by running duplicate bot instances (background process vs. container).

## [1.3.0] - 2026-01-20

### Added
- **Bifrost**: Added `GET /auth/me` endpoint to `bifrost/app/auth/routes.py` for token introspection.
- **Bifrost Bot**: Introduced a dedicated Telegram Bot (`bifrost/bot`) to handle centralized authentication and "Proof of Payment" flows for the entire ecosystem.
- **Internal API**: Added `POST /internal/grant-premium` to allow the Bifrost Bot (and other internal services) to manually upgrade a user's role for a specific application via Telegram ID.

### Changed
- **Infrastructure**: Updated `docker-compose.yml` to include the `bifrost_bot` service.

## [1.2.0] - 2026-01-20

### Added
- **Deep Linking Support**: Added `create_deep_link_token` to `BifrostDB` and `POST /internal/generate-link-token` to support secure "Web -> Telegram" account linking.
- **Unified Account Linking**: Added `POST /internal/link-account` which supports:
  - Linking Email/Password to existing accounts.
  - Linking Telegram (via legacy Widget Data).
  - Linking Telegram (via new Deep Link Token).
- **Payment Hooks**: Integrated Webhooks for Gumroad and ABA Payway.

### Changed
- **Token Verification**: Updated `verify_otp` to handle string-based tokens (for deep links) alongside numeric OTPs.

## [1.1.0] - 2026-01-19

### Added
- **Username Authentication**: Users can now set a unique username during registration.
- **Flexible Login**: The login endpoint now supports both `email` and `username` as valid identifiers.
- **New Model Method**: Added `find_account_by_username` to the database manager.

### Fixed
- **Database Integrity**: Resolved `DuplicateKeyError` on optional fields by implementing sparse unique indexes and conditional insertion logic.

## [1.0.0] - 2026-01-19 (Production Release)

### Added
- **Centralized Auth**: Promoted `bifrost` to serve as the Global Identity Provider (IdP) for the ecosystem.
- **User Model**: Implemented comprehensive `User` model supporting password hashing, account management, and application linking.
- **Authentication API**: Headless API endpoints for Login, Registration, and Telegram Authentication with JWT issuance.
- **Service-to-Service Validation**: Internal routes for client services to validate User JWTs via Basic Auth.