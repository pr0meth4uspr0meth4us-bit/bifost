# Changelog

All notable changes to the `bifrost` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.1] - 2026-01-22

### Added
- **User Invite Flow**: Implemented a system to invite new users via email when adding them to an App or assigning them as an App Admin during creation.
- **Email Service**: Added `send_invite_email` to `bifrost/services/email_service.py`.
- **UI**: Added "Initial Administrator" field to the Create App form in the Backoffice.

### Changed
- **Email Templates**: Refactored `verification_email.html` into a universal template supporting dynamic Titles, Subtitles, and Call-to-Action buttons.
- **Backoffice Logic**: Updated `create_app` and `add_user_to_app` to detect non-existent users, create placeholder accounts, and trigger invitation emails automatically.

## [2.1.0] - 2026-01-22

### Added
- **Developer Documentation**: Added a comprehensive documentation portal at `/docs`.
- **Docs Template**: Created `docs.html` with integration guides for Authentication, Payments, and Webhooks.

## [2.0.1] - 2026-01-22

### Fixed
- **Missing Webhook**: Fixed an issue where Admin Approval via the Bot triggered `account_role_change` instead of `subscription_success`.
- **Transaction Completion**: The `call_grant_premium` service now attempts to find and complete a pending transaction record before falling back to a manual role grant. This ensures the client app receives the transaction ID and amount in the webhook payload.

## [2.0.0] - 2026-01-22

### Removed
- **Legacy Admin**: Removed `bifrost/admin_panel.py` and the `flask-admin` dependency. All administration is now handled via the custom `backoffice` blueprint.

### Added
- **Unified Portal**: The `/backoffice` now serves as the single portal for both Super Admins and App Admins.
- **App Management**: Super Admins can now **Create Applications** via the UI.
- **Secret Management**: Added "Regenerate Secret" functionality in the App Details view.
- **Passkey Prep**: Database models now support `webauthn_credentials` field (placeholder for future implementation).

### Changed
- **UI Overhaul**: Migrated all Admin views to **Tailwind CSS**.
- **Authentication**: Login endpoints now explicitly check `username` OR `email` for all users.
- **Documentation**: Added comprehensive `README.md` with integration snippets.

## [1.9.8] - 2026-01-22

### Added
- **Rich Webhooks**: The webhook system now supports arbitrary data payloads via `extra_data`.
- **Subscription Events**:
  - `subscription_success`: Fired when a payment completes. Payload includes `transaction_id`, `amount`, `currency`, and `role`.
  - `subscription_expired`: Fired by the Reaper when a subscription expires.
### Changed
- **Scheduler**: The subscription reaper now sends `subscription_expired` instead of the generic `account_role_change` event for better clarity in client apps.

## [1.9.7] - 2026-01-22

### Fixed
- **UX**: The final "Payment Accepted" message now displays the human-readable App Name (e.g., "Savvify") instead of the internal `client_id`.

## [1.9.6] - 2026-01-22

### Fixed
- **Admin Approval**: Fixed a bug where the Admin Approve button failed with "App lookup_skipped not found". The bot now correctly fetches the `client_id` from the database during the `/start` command instead of relying on a placeholder.

## [1.9.5] - 2026-01-22

### Fixed
- **Critical Deadlock**: Replaced the HTTP call in `call_grant_premium` with a direct database operation. Previously, the bot tried to call its own API via HTTP, causing the server worker to freeze (waiting for itself) and timeout.

## [1.9.4] - 2026-01-22

### Fixed
- **Persistence**: Fixed a critical bug where `user_data` (containing the payment amount and app name) was lost upon bot restart. The `MongoPersistence` class now correctly reads/writes user data to the `user_data` collection.
- **Payment Flow**: Added a fallback in `receive_proof`. If the bot has forgotten the payment details (e.g., from a pre-fix session), it now asks the user to click the payment link again instead of forwarding "Unknown" to the admin.

## [1.9.1] - 2026-01-22

### Refactored
- **Payment Logic**: To prevent "Unknown App" errors, the `app_name` is now stored directly in the `transactions` collection at the time of creation. This removes the reliance on a secondary lookup by the Bot.
- **Bot Services**: Added `bson.ObjectId` handling to `bot/services.py` to ensure robust database queries even if IDs are stored as strings.

## [1.9.0] - 2026-01-22

### Refactored
- **Bot Structure**: Modularized the Telegram Bot into a package structure:
  - `handlers/`: Split monolithic logic into `commands.py` (User inputs), `payment.py` (Proof processing), and `admin.py` (Approval flows).
  - `database.py`: Centralized MongoDB connection logic, removing it from `group_listener.py`.
  - `services.py`: Isolated external API calls to Bifrost Internal API and internal DB helper functions.
### Fixed
- **Configuration**: `config.py` now uses `pathlib` to traverse up the directory tree to find the `.env` file, resolving issues where environment variables failed to load locally.

## [1.8.0] - 2026-01-22

### Refactored
- **Database Models**: Modularized the monolithic `BifrostDB` class into a `models` package containing `BaseMixin`, `AuthMixin`, `AppMixin`, and `PaymentMixin` for better maintainability.
- **Internal API**: Split `routes.py` into `routes.py` (Auth/User) and `payment_routes.py` (Transactions/Claims).
- **Middleware**: Extracted `require_service_auth` to `bifrost/internal/utils.py` to allow shared usage across route modules.

## [1.7.0] - 2026-01-22

### Added
- **Enterprise Payment Flow**: Implemented "Intent-Based" payments to prevent parameter tampering.
  - New API: `POST /internal/payments/secure-intent` allows client apps to create a transaction record before generating a link.
  - Bot Update: `/pay` and `/start` commands now accept a `transaction_id` (e.g., `tx-a1b2c3...`).
  - **Security**: The bot now fetches price, duration, and role directly from the MongoDB `transactions` collection instead of trusting the URL parameters.

### Changed
- **Models**: Updated `create_transaction` in `BifrostDB` to accept `None` for `account_id`, allowing transactions to be created before a user is identified.
- **Config**: Added `BifrostBot` as the default username for generating deep links.

### Security
- **Tamper-Proofing**: Users can no longer modify the payment amount or duration by editing the Telegram deep link, as the link now only contains a reference ID.

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