Bulk Email Campaign Management System
=====================================

Overview
--------

This is a minimal but production-grade Django web application for managing bulk email
campaigns. It allows administrators to:

- Create and schedule campaigns.
- Manage recipients with subscription status.
- Bulk upload recipients from CSV.
- Execute campaigns via Celery workers, logging each email delivery.
- View a dashboard with per-campaign statistics.
- Generate and automatically email a completion report to an admin address.


Tech Stack and Assumptions
--------------------------

- Python 3.10+
- Django 5.1.1
- Celery 5.4.0
- Redis 5.x as Celery broker and result backend
- SQLite as the relational database for simplicity
- Emails use Django's console backend by default (prints emails to stdout).
  In production, configure a real email backend via environment variables or
  overriding settings.
- Tests: Django test runner or pytest (pytest + pytest-django are included).


Project Structure
-----------------

- bulkmailer/ - Django project configuration (settings, URLs, Celery setup).
- campaigns/  - Core app with models, tasks, views, admin.
- templates/  - HTML templates (minimal Bulma-based UI).
- sample_recipients.csv - Example recipient data for bulk upload.


Setup Instructions
------------------

1. Clone and enter the project
   ---------------------------
    git clone <repository-url>

2. Create `.env` file and configure values
3. Build and start all services:

   docker compose up --build

4. Open the application:
   http://127.0.0.1:8000/

5. Run tests:
   
   docker compose run --rm web pytest

6. Stop services:
   
   docker compose down
   

## Local Development (Virtual Environment)
------------------------------------------
Use this setup if you prefer running the project without Docker.

1. Clone and enter the project
   ---------------------------
    git clone <repository-url>

2. Create and activate a virtual environment
   -----------------------------------------

   python3 -m venv .venv
   source .venv/bin/activate


3. Install dependencies
   --------------------

   pip install --upgrade pip
   pip install -r requirements.txt


4. Configure environment (.env)
   ----------------------------

   cp .env

   Key variables (.env):
   - DJANGO_SETTINGS_MODULE=bulkmailer.settings
   - SECRET_KEY=django-insecure-change-me
   - EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
   - CELERY_BROKER_URL=redis://redis:6379/0
   - CELERY_RESULT_BACKEND=redis://redis:6379/0
   - EMAIL_HOST=smtp.gmail.com
   - EMAIL_PORT=587
   - EMAIL_USE_TLS=True
   - EMAIL_USE_SSL=False
   - EMAIL_HOST_USER=azadsarkar616@gmail.com
   - EMAIL_HOST_PASSWORD=xoxx mafu mybx wcmv
   - DEFAULT_FROM_EMAIL=azadsarkar616@gmail.com


5. Apply database migrations and create a superuser
   ------------------------------------------------

   python manage.py migrate
   python manage.py createsuperuser


6. Start Redis
   -----------

   Ensure Redis is running locally (for example):

   redis-server

   Or via Docker:

   docker run -p 6379:6379 redis:7


7. Run Celery worker and beat
   --------------------------

   In one terminal (from the project root, with venv activated):

   celery -A bulkmailer worker -l info

   In another terminal:

   celery -A bulkmailer beat -l info

   Celery beat runs a periodic task that checks for scheduled campaigns every minute
   and enqueues them for sending.


8. Run the Django development server
   ---------------------------------

   python manage.py runserver

   Then open:

   http://127.0.0.1:8000/


Running Tests
-------------

- With Django’s test runner:

  python manage.py test

- With pytest (richer output):

  pytest

- Inside Docker (if using docker-compose):

  docker compose run --rm web pytest


Usage Guide
-----------

1. Upload recipients
   ------------------

   - Navigate to "Upload Recipients".
   - Use sample_recipients.csv as a starting point.
   - The CSV must include columns:
     - name
     - email
     - subscription_status (subscribed/unsubscribed)
   - The system validates email uniqueness and basic field presence, skipping
     duplicates and malformed rows while inserting efficiently using bulk_create.


2. Create a campaign
   ------------------

   - Go to "New Campaign".
   - Fill in:
     - Campaign Name
     - Subject Line
     - Email Content (plain text or HTML)
     - Scheduled Time (must be in the future)
     - Status (Draft, Scheduled, In Progress, Completed, Cancelled)
   - To have the campaign automatically sent, set status to "Scheduled" and choose
     a scheduled time.
   - When the scheduled time is reached, the Celery beat task will transition the
     campaign to "In Progress" and dispatch individual email tasks for all
     subscribed recipients.


3. Campaign execution and logging
   ------------------------------

   - For each subscribed recipient, an email is sent using Django's email system.
   - A DeliveryLog entry is recorded for each recipient with:
     - recipient_email
     - status (Sent / Failed)
     - failure_reason (if any)
     - sent_at timestamp
   - The campaign's overall status progresses automatically:
     - scheduled -> in_progress (when Celery starts processing it)
     - in_progress -> completed (when all subscribed recipients have a log)


4. Dashboard and details
   ----------------------

   - The dashboard lists all campaigns with:
     - Total Recipients (subscribed)
     - Sent Count
     - Failed Count
     - Status and progress summary (e.g., "470/500 sent").
   - Clicking a campaign opens the detail page which shows:
     - Campaign metadata (name, subject, schedule, status).
     - Aggregate counts for sent and failed.
     - A table of individual delivery logs.


5. Reporting
   ---------

   - When a campaign is marked as completed (all subscribed recipients processed),
     a Celery task generates a summary report:
     - Human-readable text summary.
     - A CSV file with columns:
       - recipient_email
       - status
       - failure_reason
       - sent_at
   - The report is emailed automatically to ADMIN_REPORT_EMAIL.
   - In development, this email is printed to the console because the console
     email backend is in use.


Notes on Design and Scalability
-------------------------------

- **Models**
  - Recipient: Stores subscriber info with a subscription status flag.
  - Campaign: Represents a campaign with scheduling metadata and status.
  - CampaignRecipient: Through model joining campaigns and recipients for
    better normalization and potential future per-recipient customizations.
  - DeliveryLog: Per-email record of delivery outcomes.

- **Bulk Operations**
  - Recipient import uses bulk_create with ignore_conflicts=True for
    efficient inserts and duplicate handling.

- **Asynchronous Execution**
  - Celery is used for all time-consuming operations:
    - Scheduling and transitioning campaigns.
    - Per-recipient email sending.
    - Report generation and dispatch.

- **Error Handling**
  - Email sending is wrapped in try/except; failures are logged with a reason.
  - CSV upload is robust to malformed rows and encoding issues.

