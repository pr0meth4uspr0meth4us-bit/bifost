# Changelog

All notable changes to the `bifrost` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.2] - 2026-01-22

### Fixed
- **Webhook Implementation**: Resolved `NameError: name 'Config' is not defined` in `bifrost/internal/routes.py` by switching to `current_app.config`.
- **Missing Imports**: Added missing `asyncio` and `process_webhook_update` imports required for the synchronous webhook wrapper.
- **Stability**: The `/internal/telegram-webhook` route is now fully operational within synchronous Gunicorn workers.

## [1.6.1] - 2026-01-22

### Fixed
- **Webhook Crash**: Resolved `RuntimeError: Install Flask with the 'async' extra` by converting the `/telegram-webhook` route to a synchronous wrapper.
- **Worker Compatibility**: Implemented a manual `asyncio` event loop within the webhook route. This allows the async Telegram Bot logic to run safely inside standard synchronous Gunicorn workers without requiring ASGI or additional dependencies.

## [1.6.0] - 2026-01-22 

### Added
- **Subscription Reaper**: Implemented `bifrost/scheduler.py`, a background cron job that runs every 60 minutes.
  - Automatically finds users with `expires_at < NOW` who are still marked as `premium_user` or `admin`.
  - Downgrades their role to `user`.
  - Removes the `expires_at` field.
- **Expiration Webhooks**: The Reaper now triggers an `account_role_change` webhook event to all client apps immediately upon downgrading a user. This ensures client apps (like Finance Bot) invalidate their local cache instantly.
- **Scheduler Integration**: Updated `bifrost/__init__.py` to start the background scheduler thread when the Flask app launches.

### Changed
- **Dependencies**: Added `schedule` to `requirements.txt` to handle background task timing.

## [1.5.0] - 2026-01-22

### Added
- **Tenant Dashboard**: Created `bifrost/backoffice.py` to allow App Admins to manage their specific users.
- **Role Hierarchy**:
  - **Super Admin**: Full access to all apps via Backoffice login.
  - **App Admin**: Access restricted to apps where they hold the `admin` or `owner` role.
- **User Management UI**: Added `app_users.html` allowing Admins to manually change user roles (e.g., grant Premium) and extend subscription duration.
- **Security**: Added `login_required` decorator and role-based checks (`get_managed_apps`) to isolate tenant data.

### Changed
- **Models**: Added `get_managed_apps(account_id)` and `get_app_users(app_id)` to `BifrostDB` to support the dashboard views.
- **Blueprint Registration**: Registered `backoffice_bp` in `bifrost/__init__.py`.

## [1.4.0] - 2026-01-22

### Added
- **Subscription Expiration**: Updated `BifrostDB` models to support `expires_at` for app links.
- **Dynamic Pricing**: Bifrost Bot now parses `duration` (e.g., '1m', '1y') and `client_ref_id` from the payment payload.
- **Improved Parsing**: Added support for `/pay` command and complex deep-link payloads (format: `client_id__price__duration__role__ref`).
- **App Branding**: The Payment Bot now looks up and displays the actual "App Name" (e.g., "Finance Bot") during the payment flow instead of the raw client ID.

### Changed
- **Transaction Model**: Added `duration` and `client_ref_id` fields to the Transaction schema.

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