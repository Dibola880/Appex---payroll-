# Appex Payroll SaaS — Phase 1 MVP

A starter multi-tenant-ready Flask payroll portal for Appex, designed around a Deel Local Payroll integration.

## Included
- Employer dashboard
- Employee management
- Payroll preview
- Deel connection status page
- SQLite database for local development
- PostgreSQL-ready DATABASE_URL configuration
- Render Procfile
- Server-side Deel credential placeholders

## Run locally

1. Install Python 3.11+.
2. Create and activate a virtual environment.
3. Install dependencies:
   `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and change SECRET_KEY.
5. Start:
   `python run.py`
6. Open `http://127.0.0.1:5000`

Demo data is created automatically on first run.

## Render

Create a Web Service from this project/ZIP:
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn run:app`
- Add environment variables from `.env.example`.
- For production, use a managed PostgreSQL database and set DATABASE_URL.

## Deel
Do not put a real Client Secret in source code or commit it to GitHub.
This Phase 1 build intentionally stops at the integration boundary. Live API calls should be implemented only after matching the exact Local Payroll API contract and sandbox credentials supplied to Appex by Deel.


## Near one-click Render deployment

This package includes `render.yaml`. Push the project to GitHub, then in Render choose **New → Blueprint**, connect the repository, review the services, and deploy. Render can provision the web service and PostgreSQL database from the Blueprint. The Deel variables are intentionally marked `sync: false`; enter their real values in Render after deployment.

Health check: `/health`.

Do not use this MVP with real employee/payroll data until authentication, authorization, audit logging, backups, security controls, and the exact Deel API integration have been completed and tested.
