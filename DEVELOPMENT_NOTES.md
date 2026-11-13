# SELF-WEIGH SERVICE
## Project Overview, Technical Decisions and Development Journey

## 1. Project Overview

Self-Weigh Service is a Python-based API project designed to support a self-service baggage weighing and airline baggage-fee workflow.

The service provides a foundation for handling baggage-related transactions, applying airline-specific business rules, protecting selected operations with authentication, maintaining financial records, and publishing events for downstream systems.

The project is being developed incrementally. Each change should be understood, implemented, tested, reviewed, committed, and pushed to GitHub.

The project is a concept implementation. Airline allowances, rates, limits, and payment workflows are illustrative and should not be treated as real airline or airport tariffs or production payment integrations.

## 2. Why We Started with a Small, Manageable Step

We began by working with the existing repository rather than rebuilding the entire application.

This approach helps us:

- Understand the existing code before changing it.
- Keep working functionality intact.
- Identify and fix problems in small steps.
- Test changes before adding more complexity.
- Maintain a clear Git history of our progress.
- Build practical software engineering skills through real implementation work.

Our goal is to build a reliable service while learning professional software development practices.

## 3. Why We Chose FastAPI

FastAPI is the framework used for the API.

Its advantages include:

- Automatic interactive API documentation.
- Request validation using Python type annotations.
- Support for asynchronous request handling.
- A straightforward way to create and organise API endpoints.
- Integration with Python testing tools.

Flask is another lightweight option, while Django provides a broader framework with more built-in features. FastAPI is a suitable choice for this API-focused service.

The framework alone does not guarantee security or reliability. These must be addressed through implementation, testing, and deployment practices.

## 4. Technology Stack

### Python

The main programming language used to implement the service.

### FastAPI

The web framework used to define API endpoints and handle requests.

### PostgreSQL

The relational database used when running through Docker Compose (PostgreSQL 16).

Local development without Docker uses SQLite by default. The `DATABASE_URL` setting selects the database.

Some database behaviour differs. For example, the outbox publisher uses PostgreSQL's `FOR UPDATE SKIP LOCKED` when claiming events.

### SQLAlchemy

The Python SQL toolkit and ORM used for database access. The application uses SQLAlchemy 2.0-style models in `app/models.py`.

### Alembic

Alembic manages database schema migrations. Migration changes are version-controlled and can be applied to the configured database.

### pytest

The testing framework used to execute automated tests.

### Docker and Docker Compose

Docker packages and runs the application in a consistent environment.

The Docker Compose setup includes the API, PostgreSQL database, separate outbox worker service, and Redpanda Kafka-compatible broker.

The Compose configuration is intended for development and testing. Its development credentials and configuration should not be reused as production secrets.

### Git and GitHub

Git tracks code changes, while GitHub hosts the repository and its shared history.

## 5. Main Business Capabilities

The project supports a baggage-service workflow. The following capabilities are implemented to varying degrees and should not automatically be interpreted as production-ready integrations.

### Baggage and Pricing

- Baggage weighing and related service workflows.
- Excess-baggage pricing and fee calculations.
- Airline-specific allowances and rules.
- Weight validation and safeguards.

### Transactions and Payments

- Transaction records.
- Payment-related workflow support.
- Support for different payment methods in the concept workflow.
- Controls for authorised operations.

A transaction record does not by itself prove that a real payment has been processed. Payment-provider integration and reconciliation must be verified separately.

### Airline Access

- API-key protection for selected operations.
- Separation of access between authorised parties.
- Kiosk and staff-management authentication safeguards where implemented.
- Admin-protected airline API-key rotation through `POST /airlines/{airline_id}/rotate-key`.

When an airline key is rotated:

- The administrator must provide a valid admin key.
- A new airline API key is generated.
- The previous key is invalidated.
- The new key is returned in the response and should be securely saved because it is only shown once.
- Only the hash of the new key is stored in the database.
- The airline record and its existing transaction history are preserved.

Authentication and authorisation should continue to be reviewed for secure storage, rotation, logging, and appropriate permissions.

### Financial Records

- Airline ledger-related functionality.
- Fee-waiver workflows.
- Payout recording.
- Statement generation in PDF and CSV formats.
- Cash reconciliation support.

These functions require appropriate validation and financial-integrity checks before production use.

### Audit Trail

The project has a hash-chained audit log, with a separate chain for each airline.

It records events related to weighing, payments, fee waivers, payouts, and statement generation.

The hash chain can help detect tampering, but it does not prevent tampering. Its integrity guarantees and operational controls require further testing before formal audit reliance.


### Event Outbox and Kafka Delivery

The service uses a transactional outbox implemented in `app/outbox.py` and `app/outbox_publisher.py`.

An event is saved in the same database transaction as the business action that caused it. This prevents the application from recording an event independently of the transaction it represents.

The following event types are currently queued:

- `TRANSACTION_WEIGHED`
- `PAYMENT_RECEIVED`
- `FEE_WAIVED`
- `PAYOUT_RECORDED`
- `STATEMENT_GENERATED`

The publisher uses leases, claim tokens and PostgreSQL `FOR UPDATE SKIP LOCKED` to coordinate event processing between workers.

Delivery uses **at-least-once semantics**. Downstream consumers must deduplicate events using their event IDs because an event can be delivered more than once.

The publisher supports:

- Configurable worker batch sizes and polling intervals.
- Lease-based event claims.
- Retry limits.
- Exponential backoff with a maximum delay.
- Dead-letter handling after the configured maximum number of failed attempts.
- Recording delivery errors and retry information.

### Kafka and Redpanda Integration

Kafka delivery is implemented in `app/kafka_producer.py` and integrated with the worker in `app/worker.py`.

The Docker Compose environment includes Redpanda, a Kafka-compatible broker.

The worker uses:

- `KAFKA_BOOTSTRAP_SERVERS` to configure the broker connection.
- `KAFKA_TOPIC` to select the destination topic.
- `KAFKA_DELIVERY_TIMEOUT_SECONDS` to configure delivery timeouts.

The Kafka producer enables idempotence, requests acknowledgements from all in-sync replicas, and waits for delivery acknowledgement.

When Kafka is configured, the worker publishes events to the broker. When no Kafka bootstrap address is configured, it falls back to logging delivery.

If delivery fails, the outbox records the failure and applies its retry and dead-letter handling. The worker continues processing subsequent batches rather than stopping permanently after a failed batch.

The delivery implementation remains at-least-once from the application's perspective. Kafka producer idempotence does not remove the need for downstream consumers to deduplicate by event ID.

### Operations Dashboard

A React, TypeScript and Vite frontend is available in the `frontend/` directory.

The dashboard connects to the FastAPI backend through the Vite development proxy.

The backend provides protected administrative endpoints for:

- `GET /admin/outbox/statistics`
- `GET /admin/outbox/dead-lettered`

The statistics endpoint reports total, pending, claimed, retrying, published and dead-lettered events.

The dashboard currently displays:

- Backend service connection status.
- Pending event count.
- Published event count.
- Dead-lettered event count.
- A table of dead-lettered events, including event ID, airline ID, event type, attempts, last error and timestamp.

The dashboard supports manual refresh and automatic data refresh every 30 seconds. Backend connection health is checked every 10 seconds.

The frontend development proxy uses the local `ADMIN_API_KEY` environment variable to add the administrative authentication header. Local secrets must not be committed to Git.

The dashboard is an operational monitoring interface, not a complete production monitoring or event-management platform.

## 6. Development Environment

The project is developed locally on Windows using PowerShell and Python 3.12.

The local virtual environment is named `.venv312`. It is a development environment and should not be committed to Git.

The repository uses a `.gitignore` file to exclude local development files and other items that should not be version-controlled.

## 7. Running the Application Locally

From the repository directory, activate the virtual environment if it is not already active:

```powershell
.\.venv312\Scripts\Activate.ps1
```

Install the project dependencies if necessary:

```powershell
python -m pip install -r requirements.txt
```

Start the development server:

```powershell
python -m uvicorn app.main:app --reload
```

When the server starts successfully, open the interactive API documentation:

http://127.0.0.1:8000/docs

Stop the server with `Ctrl + C` when finished.

These commands assume that the application entry point remains `app.main:app` and that the repository contains `requirements.txt`.

For the Docker Compose environment, use the repository's Compose configuration to start the API, database, and worker services.

## 8. Running the Tests

Run the automated test suite from the repository directory with the `.venv312` environment active:

```powershell
python -m pytest -q
```

The most recently verified full local test run, using Python 3.12, reported:

**169 passed, 2 skipped, 1 warning.**

The two skipped tests cover PostgreSQL-specific concurrency behaviour:

- Payout row-locking.
- Outbox `SKIP LOCKED` behaviour.

These tests require PostgreSQL and are exercised through the PostgreSQL CI workflow.

The warning is a Starlette/AnyIO test-client dependency deprecation warning. It should be monitored and addressed when the relevant dependency compatibility work is undertaken.

This test result records a specific run during development. It is not a guarantee that every possible scenario is covered or that the application is production-ready.

When a test fails:

1. Read the failure message carefully.
2. Identify the affected endpoint or function.
3. Inspect the relevant code and test.
4. Make the smallest appropriate correction.
5. Run the relevant test, followed by the full suite.
6. Review the changes before committing.

Warnings should be investigated when appropriate rather than automatically ignored.

## 9. Git and GitHub Workflow

The repository is hosted at:

https://github.com/Dimakyi/self-weigh-service

The primary branch is `main`.

Our preferred workflow is:

1. Check the working tree.
2. Inspect the relevant code before editing.
3. Explain the purpose of the proposed change.
4. Make one focused change at a time.
5. Run the relevant checks and tests.
6. Review the diff.
7. Stage only the intended files.
8. Review the staged changes.
9. Commit with a clear message.
10. Push to GitHub.
11. Confirm that the local branch and remote branch are synchronised.

Useful commands:

```powershell
git status
git diff --check
git diff
python -m pytest -q
```

After staging a change:

```powershell
git diff --cached --check
git --no-pager diff --cached
```

After committing and pushing:

```powershell
git status
git log -5 --oneline
```

A clean working tree means Git reports no remaining tracked or untracked changes. It does not independently prove that the application works correctly.

## 10. Development Milestones

The following milestones are confirmed by the recent repository history:

- Improved README setup instructions and API documentation.
- Added production configuration safeguards to prevent the application from starting with default secrets in production (`25c3e5f`).
- Added PostgreSQL migration validation to the CI workflow (`53d6beb`).
- Hardened database migration handling and Docker startup (`db0c4f9`).
- Strengthened weighing safeguards and validation tests (`953f696`).
- Added transactional outbox events for fee waivers (`749ef08`), payouts (`c419eac`), and statement generation (`f516365`), in addition to the earlier weighing and payment events.
- Added a separate outbox worker service (`4ed9581`).
- Added retry limits, exponential backoff, and dead-letter handling (`5632ac7`).
- Fixed a retry backoff calculation that could overflow when configured with a very high maximum attempt count (`04d6788`).
- Updated the README to reflect the current outbox implementation (`fadd68c`).
- Integrated Kafka-compatible event delivery through Redpanda, including producer acknowledgement and delivery failure handling.
- Added a React, TypeScript and Vite operations dashboard for monitoring backend health and outbox event statistics (`1c840fd`).
- Added a Vite development proxy to connect the frontend to the protected backend API without exposing the administrative key in frontend source code.

- Verified the frontend with `npm run lint` and `npm run build`.
- Rebased the dashboard work onto the latest remote `main` branch and successfully pushed the synchronised history.
- Added an admin-protected airline API-key rotation endpoint (`POST /airlines/{airline_id}/rotate-key`), with tests covering successful rotation, old-key invalidation, preserved transaction history, authentication failures, and unknown airline IDs (`ce95db1`).
- Added offset-based pagination to the admin dead-letter listing, including negative-offset validation, deterministic ordering, and API tests (`dba73f9`).
- Documented a successful manual Redpanda broker outage recovery test. The API accepted a transaction during the outage, and the existing worker delivered its event after broker recovery without a manual restart (`b782098`). Delivery remains at-least-once.

Run `git log --oneline` for the full repository history. Git history is the authority if this milestone list falls behind.

## 11. Engineering Principles

We will follow these principles throughout development:

- **Understand before changing:** inspect existing code and behaviour first.
- **Small changes:** avoid combining unrelated improvements.
- **Test continuously:** use automated tests to catch regressions.
- **Protect sensitive information:** never commit passwords, API keys, tokens, or real customer data.
- **Review every change:** inspect the diff before committing.
- **Keep a useful history:** write clear commit messages.
- **Verify Git operations:** confirm successful pushes and synchronisation.
- **Document honestly:** distinguish implemented and tested features from planned features.
- **Build for maintainability:** favour clear, readable code over unnecessary complexity.
- **Preserve working functionality:** avoid unnecessary rewrites and make changes deliberately.


## 12. Future Development Direction

Future work should be driven by inspection of the current code, test coverage, operational requirements, and project priorities.

The core outbox publishing workflow, Kafka-compatible delivery integration, and initial operations dashboard have been implemented. The following improvements remain candidates for future development.

### Event Delivery and Operations

- Build a downstream Kafka consumer to demonstrate and verify end-to-end event processing.
- Add consumer-side event deduplication and processing guarantees.
- Consider dead-letter event inspection and controlled requeue functionality in the dashboard.
- Improve operational monitoring, alerting, and delivery visibility.
- Evaluate production broker security, topic configuration, and deployment requirements.

### Application Improvements

- Consider splitting `app/main.py` into smaller routers and modules.
- Implement refunds and transaction corrections.
- Support mid-period collector changes.
- Consider per-kiosk cash tracking; current reconciliation uses one combined total.
- Improve secrets management and deployment configuration beyond the local Docker Compose setup.
- Review error handling, logging, monitoring, backups, and recovery procedures.
- Expand database migration and concurrency testing.
- Expand automated tests for important business workflows and failure scenarios.

These are development opportunities, not claims that the work has already been completed.

## 13. Current Working Agreement

Development will continue incrementally, with each change inspected, tested, reviewed, and documented before it is committed and pushed to GitHub.

For each meaningful change:

1. Understand the proposed change and its purpose.
2. Inspect the relevant code and existing behaviour.
3. Implement one focused change at a time.
4. Run the appropriate checks and tests.
5. Review the resulting diff.
6. Stage only the intended files.
7. Commit with a clear, descriptive message.
8. Push to GitHub and verify synchronisation.

Changes will only be described as committed, pushed, or verified when the relevant command output confirms the result.

Unrelated files, backups, diagnostic output, and local database files must not be included in a commit.

## Summary

Self-Weigh Service is an evolving baggage weighing and payment service.

The project includes baggage weighing and pricing workflows, multi-airline functionality, passenger verification, financial records, audit logging, database migrations, and a transactional event outbox.

The outbox is supported by a separate worker with retry handling, exponential backoff, dead-letter processing, and Kafka-compatible event delivery through Redpanda.

A React, TypeScript, and Vite operations dashboard provides visibility into backend connectivity and outbox event statistics.

The admin dead-letter listing supports offset pagination with deterministic ordering. A manual integration test also demonstrated successful outbox delivery recovery after a Redpanda broker outage.

The latest full local pytest run collected 171 tests: 169 passed, 2 skipped, and 1 warning. PostgreSQL-specific concurrency tests still require verification in the PostgreSQL test environment.

The project is developed incrementally, with emphasis on understanding technical decisions, preserving working functionality, testing changes, and maintaining a clear Git history.

This document records the project's direction and development practices. The current source code, tests, configuration, README, and Git history remain the authorities for determining which features are actually implemented and verified.
