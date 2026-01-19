# Changelog

All notable changes to the `bifrost` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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