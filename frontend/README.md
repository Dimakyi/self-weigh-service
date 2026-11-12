# Self-Weigh Service Operations Dashboard

The Self-Weigh Service operations dashboard is a React, TypeScript and Vite frontend for monitoring backend connectivity and transactional outbox activity.

## Features

- Backend connection status.
- Pending, published and dead-lettered event counts.
- Dead-lettered event table with event ID, airline ID, event type, attempts, last error and timestamp.
- Manual dashboard refresh.
- Automatic dashboard data refresh every 30 seconds.
- Backend connection health checks every 10 seconds.

## Technology

- React
- TypeScript
- Vite

## Prerequisites

- Node.js and npm.
- The Self-Weigh Service backend running locally at `http://127.0.0.1:8000`.
- The backend administrative API key configured for local frontend development.

## Installation

Open a terminal in the `frontend/` directory and install the dependencies:

```powershell
npm install
```

## Local environment configuration

Create a local file named `.env.local` inside the `frontend/` directory.

Add the administrative API key using this variable:

```dotenv
ADMIN_API_KEY=your-local-admin-api-key

```
Use the same administrative key configured for the backend.

**Security:** Do not commit `.env.local` or expose administrative keys in frontend source code. The Vite development proxy adds the administrative authentication header when forwarding requests to the backend.

## Run the development server

From the `frontend/` directory:

```powershell
npm run dev
```

Open the local address displayed by Vite, normally:

`http://localhost:5173/`

The backend must be running for dashboard data to load.

## Quality checks

Run the frontend lint checks:

```powershell
npm run lint
```

Create a production build:

```powershell
npm run build
```

Vite writes the production build to the `dist/` directory.

## Backend integration

The frontend communicates with the backend through the `/api` development proxy.

The dashboard uses these protected administrative endpoints:

- `GET /admin/outbox/statistics`
- `GET /admin/outbox/dead-lettered`

The Vite development proxy forwards requests to the backend and supplies the administrative authentication header from the local environment configuration.

## Current limitations

The dashboard provides operational visibility into backend connectivity and outbox activity. It is not a complete production monitoring platform.

Dead-lettered events can be inspected, but controlled requeue functionality is not yet implemented. Downstream Kafka consumer processing and consumer-side event deduplication also remain future work.