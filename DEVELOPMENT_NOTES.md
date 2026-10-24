# SELF-WEIGH SERVICE
## Project Overview, Technical Decisions and Development Journey

## 1. Project Overview

Self-Weigh Service is a Python-based API project intended to support a self-service baggage weighing and airline baggage-fee workflow.

The project provides a foundation for handling baggage-related transactions, applying business rules, protecting selected operations with API keys, and maintaining financial records.

The application is being developed incrementally. Each change should be understood, implemented, tested, reviewed, committed, and pushed to GitHub.

## 2. Why We Started with a Small, Manageable Step

We began by working with the existing repository rather than rebuilding the entire application.

This approach helps us:
- Understand the existing code before changing it.
- Keep working functionality intact.
- Identify and fix problems in small steps.
- Test changes before adding more complexity.
- Maintain a clear Git history of our progress.

Our goal is to build a reliable service while learning professional software development practices.

## 3. Why We Chose FastAPI

FastAPI is the framework used for the API.

Its advantages include:
- Automatic interactive API documentation.
- Request validation using Python type annotations.
- Support for asynchronous request handling.
- A straightforward way to create and organise API endpoints.
- Integration with Python testing tools.

Flask is another lightweight option, while Django provides a broader framework with more built-in features. FastAPI is a suitable starting point for an API-focused service.

The framework alone does not guarantee security or reliability. These must be addressed through implementation, testing, and deployment practices.

## 4. Technology Stack

### Python
The main programming language used to implement the service.

### FastAPI
The web framework used to define API endpoints and handle requests.

### PostgreSQL
The relational database used when running through Docker Compose (PostgreSQL 16). Local development without Docker uses a SQLite file by default; `DATABASE_URL` selects the database. Some behaviour differs by database: for example, the outbox claim query uses `SKIP LOCKED` on PostgreSQL only.

### SQLAlchemy
The Python SQL toolkit and ORM used for all database access (SQLAlchemy 2.0 style models in `app/models.py`). Tables are created automatically at startup; Alembic migrations are not set up yet.

### pytest
The testing framework used to execute automated tests.

### Docker
A tool for packaging and running applications in consistent environments. The repository has a `Dockerfile` and a `docker-compose.yml` (API plus PostgreSQL). The Compose file uses development keys and hard-coded database credentials, so it is for local use only.

### Git and GitHub
Git tracks code changes, while GitHub hosts the repository and its shared history.

## 5. Main Business Capabilities

The project is intended to support a baggage-service workflow. The repository has included work related to the following areas; each feature should be checked against the current code and tests before being described as production-ready.

### Baggage and Pricing
- Baggage weighing and related service workflows.
- Excess-baggage pricing or fee calculations.
- Airline-specific rules where implemented.

### Transactions and Payments
- Transaction records.
- Payment-related workflow support.
- Controls for authorised operations.

A transaction record does not by itself prove that a real payment has been processed. Payment-provider integration and reconciliation must be verified separately.

### Airline Access
- API-key protection for selected operations.
- Separation of access between authorised parties where implemented.

API-key protection should be reviewed for secure storage, rotation, logging, and appropriate permissions.

### Financial Records
- Ledger-related functionality.
- Fee-waiver workflows.
- Statement generation in PDF or CSV where implemented.
- Reconciliation support.

These functions require appropriate validation and financial-integrity checks before production use.

### Audit Trail
The project has a hash-chained audit log, one chain per airline, covering weigh, payment, waiver, payout and statement events. It detects tampering but does not prevent it (see the README's "Honest limits"). Its integrity guarantees must be tested further before relying on it for formal auditing.

### Event Outbox
A transactional outbox (`app/outbox.py`, `app/outbox_publisher.py`) lets the service queue events in the same database transaction as the action that caused them, and deliver them later with a lease-based publisher. Only `TRANSACTION_WEIGHED` is queued so far, and no worker or Kafka broker runs it yet. See the README's "Event outbox" section.

## 6. Development Environment

The project is developed locally on Windows using PowerShell and Python 3.12.

The local virtual environment is named `.venv312`. It is a development environment and should not be committed to Git.

The repository uses a `.gitignore` file to exclude the local virtual environment.

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

The commands above assume that the application entry point remains `app.main:app` and that the repository contains `requirements.txt`.

## 8. Running the Tests

Run the automated test suite from the repository directory:

```powershell
python -m pytest
```

The test suite most recently reported locally on Windows using Python 3.12:

`85 passed, 1 warning in 26.80s`

This records a test result observed during development. It is not a guarantee that all possible scenarios are tested or that the application is production-ready.

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
python -m pytest
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

A clean working tree means there are no remaining tracked or untracked changes reported by Git. It does not independently prove that the application works correctly.

## 10. Development Milestones

The following milestones are recorded in the repository's development history:

- Initial self-weigh service implementation (`5c6ede0`), including the multi-airline design, settlement ledger, audit log with waivers, statements and cash reconciliation described in the README.
- Local setup documentation and `.gitignore` rules for the local virtual environment.
- Project development notes and inactive API-key regression tests.
- Improved README setup instructions and API examples.
- Simulated passenger verification (`POST /passenger/verify`), with documentation.
- Production configuration safeguards (the app refuses to start in production with default keys), with tests and documentation.
- Tests for staff-management authorisation.
- Added transactional outbox groundwork for weigh events and a lease-based event publisher (`3c49321`). Other event types, a worker process and Kafka integration remain planned.

Run `git log --oneline` for the full, current history; it is the authority if this list falls behind.

## 11. Engineering Principles

We will follow these principles throughout development:

- **Understand before changing:** inspect existing code and behaviour first.
- **Small changes:** avoid combining unrelated improvements.
- **Test continuously:** use automated tests to catch regressions.
- **Protect sensitive information:** never commit passwords, API keys, tokens, or real customer data.
- **Review every change:** inspect the diff before committing.
- **Keep a useful history:** write clear commit messages.
- **Verify Git operations:** confirm successful pushes and a clean working tree.
- **Document honestly:** distinguish implemented and tested features from planned features.
- **Build for maintainability:** favour clear, readable code over unnecessary complexity.

## 12. Future Development Direction

Future work should be driven by inspection of the current code, test coverage, and the project's requirements.

Next steps, in the order they are likely to be tackled (Step 5 of the roadmap):

- Queue outbox events for payments, waivers, payouts and statements (only `TRANSACTION_WEIGHED` is queued today).
- Add a worker process that runs the publisher, then a Kafka producer and broker in Docker Compose.
- Add retry limits, backoff and dead-letter handling for events that keep failing.
- Build the operations dashboard.

Other areas to investigate:

- Alembic database migrations (tables are currently created automatically).
- Splitting `app/main.py` (about 560 lines) into routers.
- Refunds and corrections, and mid-period collector changes (both unhandled).
- Per-kiosk cash tracking (reconciliation uses one combined total).
- Secrets management and deployment configuration beyond the local Docker Compose setup.
- Reviewing error handling, logging, monitoring, backups and recovery.

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

## Summary

Self-Weigh Service is an evolving API project. Our focus is to develop it incrementally, understand the technical decisions behind it, preserve working functionality, test changes, and maintain a clear history in GitHub.

This document records the project's direction and development practices. The current source code, tests, configuration, and Git history remain the authorities for determining which features are actually implemented and verified.
