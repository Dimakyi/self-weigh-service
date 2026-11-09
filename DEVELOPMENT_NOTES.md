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

### Event Outbox

The service uses a transactional outbox implemented in `app/outbox.py` and `app/outbox_publisher.py`.

The outbox allows an event to be saved in the same database transaction as the business action that caused it. This prevents the application from reporting an event as successfully queued when the corresponding database transaction has failed.

The following event types are currently queued:

- `TRANSACTION_WEIGHED`
- `PAYMENT_RECEIVED`
- `FEE_WAIVED`
- `PAYOUT_RECORDED`
- `STATEMENT_GENERATED`

The publisher uses leases and claim tokens to coordinate event processing. PostgreSQL claims events using `FOR UPDATE SKIP LOCKED`.

Delivery uses at-least-once semantics. Downstream consumers must deduplicate using event IDs because an event may be delivered more than once.

The publisher also supports:

- Configurable worker batch sizes and polling intervals.
- Lease-based event claims.
- Retry limits.
- Exponential backoff with a maximum delay.
- Dead-letter handling after the configured maximum number of failed attempts.
- Recording delivery errors and retry information.

The separate worker runs with:

```powershell
python -m app.worker
```

Docker Compose also provides a worker service.

**Current limitation:** The worker currently uses a logging delivery stand-in. Kafka producer and broker integration have not yet been implemented. There is also no dedicated dead-letter inspection and requeue endpoint.

See the README's "Event outbox" section for the current implementation details.

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

**144 passed, 2 skipped, 1 warning in 49.04 seconds.**

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

Future work should be driven by inspection of the current code, test coverage, and project requirements.

The remaining outbox roadmap includes:

- Add a Kafka producer and broker integration.
- Replace the current logging delivery stand-in with actual downstream event delivery.
- Build the operations dashboard.
- Consider dead-letter inspection and controlled requeue functionality.

Other areas to investigate include:

- Splitting `app/main.py` into smaller routers and modules.
- Refunds and corrections.
- Mid-period collector changes.
- Per-kiosk cash tracking; current reconciliation uses one combined total.
- Secrets management and deployment configuration beyond the local Docker Compose setup.
- Reviewing error handling, logging, monitoring, backups, and recovery.
- Further database migration and concurrency testing.
- Expanding test coverage for important business and failure scenarios.

These are development opportunities, not claims that the work has already been completed.

## 13. Current Working Agreement

We will continue working together step by step.

For each meaningful change, we will:

1. Understand what we are changing and why.
2. Agree on the next action.
3. Run the required command or edit.
4. Check the result.
5. Test the application where appropriate.
6. Review the diff.
7. Commit the verified change.
8. Push it to GitHub and confirm the result.

We will not claim that a change has been committed, pushed, or verified until the command output confirms it.

We will also avoid staging unrelated files, backups, diagnostic output, or local database files.

## Summary

Self-Weigh Service is an evolving API project. It now includes baggage and pricing workflows, multi-airline functionality, financial records, audit logging, database migrations, and a transactional event outbox with a separate worker, retry handling, and dead-letter support.

The current event delivery implementation still uses a logging stand-in. Kafka integration and the operations dashboard remain future work.

Our focus is to develop the service incrementally, understand the technical decisions behind it, preserve working functionality, test changes, and maintain a clear history in GitHub.

This document records the project's direction and development practices. The current source code, tests, configuration, README, and Git history remain the authorities for determining which features are actually implemented and verified.
