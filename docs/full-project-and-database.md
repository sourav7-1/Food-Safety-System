# Smart Street Food Safety — Full Project and Database Documentation

## 1. Project Summary

**Smart Street Food Safety** is a role-based Flask and MySQL web application for registering and monitoring street-food stalls. It supports inspections, weighted hygiene scoring, risk analysis, complaints, reviews, corrective actions, evidence uploads, and administrative reports.

The system has four user roles:

| Role | Main responsibilities |
|---|---|
| Admin | Manage vendors, stalls, inspectors, users, complaints, reviews, reports, and risk analysis |
| Inspector | Create inspections, score active criteria, submit findings, and create corrective actions |
| Vendor | Manage stall information and food items, view complaints, and submit corrective-action evidence |
| Customer | Search stalls, view safety information, post one review per stall, and submit/track complaints |

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, Flask 3 |
| Authentication | Flask-Login, Werkzeug password hashing |
| ORM | Flask-SQLAlchemy / SQLAlchemy 2 |
| Database | MySQL 8.0+, PyMySQL |
| Frontend | Jinja2, Bootstrap 5, Font Awesome, Chart.js |
| Configuration | `.env`, `python-dotenv` |
| Testing | Python `unittest` |

## 3. Main Features

- Secure login, registration, logout, role-based authorization, CSRF validation, and account-status enforcement.
- Admin CRUD workflows for vendors, stalls, inspectors, complaints, reviews, and users.
- Admin review of submitted inspections, approving or rejecting each one before it counts toward a stall's public risk/grade.
- Inspector workflow that writes an inspection and its criterion scores as one transaction.
- Database-triggered score validation, weighted total calculation, risk classification, and reinspection scheduling.
- Vendor food-item management and corrective-action completion with PNG, JPG, JPEG, or PDF evidence.
- Customer stall search/filter, safety-profile viewing, reviews, complaints, and complaint tracking.
- MySQL-backed dashboards and reports for trends, risk, hygiene, complaints, high-risk stalls, and reinspections.
- Duplicate-safe import of Google Forms street-food registration data from a CSV ZIP.

## 4. Project Structure

```text
Food safety system/
├── app.py                         # App factory, security hooks, Flask CLI
├── config.py                      # Environment, MySQL, cookie, upload settings
├── extensions.py                  # SQLAlchemy and Flask-Login objects
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment-variable template
├── models/
│   └── __init__.py                # All SQLAlchemy models and relationships
├── routes/
│   ├── auth.py                    # Login, registration, logout
│   ├── dashboard.py               # Role dashboards
│   ├── admin.py                   # Administration workflows
│   ├── inspector.py               # Inspection workflow
│   ├── vendor.py                  # Vendor portal
│   ├── customer.py                # Customer portal
│   └── reports.py                 # Administrative reports
├── services/
│   ├── database_setup.py          # Non-destructive DB initialization
│   └── registration_import.py     # Google Forms CSV ZIP import
├── database/
│   ├── schema.sql                 # Destructive full schema creation
│   ├── functions.sql              # Scalar functions
│   ├── triggers.sql               # Validation and scoring automation
│   ├── procedures.sql             # Risk-analysis procedure
│   ├── views.sql                  # Reporting views
│   ├── analytics.sql              # Reusable analytical queries
│   ├── seed_data.sql              # Roles, criteria, and sample/reference data
│   └── migrations/                # Non-destructive upgrades
├── templates/                     # Jinja pages by role
├── static/
│   ├── css/                       # Shared and role-specific styles
│   ├── images/                    # Project images
│   ├── vendor/                    # Locally stored frontend libraries
│   └── uploads/evidence/          # Default corrective-evidence location
├── tests/                         # Unit/sample and live-MySQL tests
└── docs/                          # Setup, design, and test documentation
```

## 5. Application Architecture

```text
Browser
   │ HTTP forms/pages
   ▼
Flask blueprints ──► service layer
   │                     │
   ├── SQLAlchemy ORM ───┤
   ▼                     ▼
MySQL tables, functions, triggers, procedure, and views
```

`app.py` creates the application, initializes extensions, registers all blueprints, installs CSRF protection, checks disabled accounts, and exposes CLI commands. Route modules handle HTTP input and authorization. SQLAlchemy models define persistence and relationships. MySQL routines enforce scoring and risk rules close to the data.

## 6. Main URL Map

| Area | Important routes |
|---|---|
| Public/auth | `/`, `/login`, `/register`, `/logout`, `/dashboard` |
| Dashboards | `/dashboard/admin`, `/dashboard/inspector`, `/dashboard/vendor`, `/dashboard/customer` |
| Admin | `/admin/vendors`, `/admin/stalls`, `/admin/inspectors`, `/admin/complaints`, `/admin/inspections`, `/admin/inspections/<id>/approve`, `/admin/inspections/<id>/reject`, `/admin/reviews`, `/admin/risk-engine`, `/admin/users`, `/admin/settings` |
| Reports | `/admin/reports/` |
| Inspector | `/inspector/`, `/inspector/new`, `/inspector/<inspection_id>` |
| Vendor | `/vendor/`, stall profile and food-item routes, `/vendor/complaints`, corrective-action update/evidence routes |
| Customer | `/customer/stalls`, `/customer/stalls/<stall_id>`, review/complaint submission, `/customer/complaints` |

## 7. Configuration

Create `.env` from `.env.example` and set these values:

```dotenv
SECRET_KEY=replace-with-a-long-random-secret
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=smart_street_food_safety
SESSION_COOKIE_SECURE=false
# DATABASE_URL=mysql+pymysql://user:password@localhost:3306/smart_street_food_safety
# UPLOAD_FOLDER=C:/secure/path/evidence
```

`DATABASE_URL`, when present, overrides the individual MySQL settings. Maximum upload size is 8 MB. In HTTPS production, set `SESSION_COOKIE_SECURE=true`.

## 8. Installation and Run

From PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
flask --app app init-db
flask --app app create-admin
flask --app app run
```

Then open `http://127.0.0.1:5000`.

For a completely fresh database, scripts may be installed manually in this order:

1. `database/schema.sql`
2. `database/functions.sql`
3. `database/triggers.sql`
4. `database/procedures.sql`
5. `database/views.sql`
6. `database/seed_data.sql`

> **Warning:** `schema.sql` drops and recreates application tables. Use `flask --app app init-db` or an appropriate migration for an existing database.

Useful CLI commands:

```powershell
flask --app app init-db
flask --app app create-admin
flask --app app import-stalls "C:\path\registrations.zip"
```

## 9. Database Overview

- **Database:** `smart_street_food_safety`
- **Engine:** InnoDB
- **Character set:** `utf8mb4`
- **Collation:** `utf8mb4_unicode_ci`
- **Normal form:** Designed to 3NF with lookup, master, transaction, and detail data separated.
- **Tables:** 16 (`stalls` gained a nullable `photo_url` column; apply `database/migrations/002_add_stall_photo_url.sql` on databases created before this change)
- **Views:** 5
- **Stored functions:** 1
- **Stored procedures:** 1
- **Triggers:** 9

## 10. Entity Relationship Diagram

```mermaid
erDiagram
    ROLES ||--o{ USERS : assigns
    USERS ||--o| VENDORS : has
    USERS ||--o| INSPECTORS : has
    USERS ||--o{ COMPLAINTS : submits
    USERS ||--o{ REVIEWS : writes
    AREAS ||--o{ INSPECTORS : assigns
    AREAS ||--o{ STALLS : contains
    VENDORS ||--o{ STALLS : operates
    STALLS ||--o{ FOOD_ITEMS : sells
    FOOD_CATEGORIES ||--o{ FOOD_ITEMS : classifies
    STALLS ||--o{ INSPECTIONS : receives
    INSPECTORS ||--o{ INSPECTIONS : performs
    INSPECTIONS ||--o{ INSPECTION_SCORES : contains
    INSPECTION_CRITERIA ||--o{ INSPECTION_SCORES : defines
    STALLS ||--o{ COMPLAINTS : receives
    COMPLAINT_TYPES ||--o{ COMPLAINTS : classifies
    STALLS ||--o{ REVIEWS : receives
    INSPECTIONS ||--o{ CORRECTIVE_ACTIONS : causes
    COMPLAINTS ||--o{ CORRECTIVE_ACTIONS : causes
    VENDORS ||--o{ CORRECTIVE_ACTIONS : owns
```

`street_food_stall_registrations` is a staging/import table and intentionally has no foreign keys to the operational entities.

## 11. Database Tables

### 11.1 `roles`

Role lookup. Columns: `role_id` PK, `role_name` unique, `description`, `created_at`.

### 11.2 `users`

Authentication identity shared by every role. Columns: `user_id` PK, `role_id` FK, `full_name`, unique `email`, unique nullable `phone`, `password_hash`, `status`, timestamps. Status: `active`, `inactive`, or `suspended`.

### 11.3 `vendors`

One-to-one vendor profile for a user. Columns: `vendor_id` PK, unique `user_id` FK, `business_name`, unique `license_number`, `license_expiry_date`, unique nullable `national_id`, `created_at`.

### 11.4 `areas`

Geographic lookup. Columns: `area_id` PK, `area_name`, `city`, non-null `zone`, latitude, longitude, `created_at`. `(area_name, city, zone)` is unique; coordinates are range-checked.

### 11.5 `inspectors`

One-to-one inspector profile. Columns: `inspector_id` PK, unique `user_id` FK, unique `employee_code`, `designation`, nullable `assigned_area_id` FK, `created_at`.

### 11.6 `stalls`

Operational street-food stall. Columns: `stall_id` PK, `vendor_id` FK, `area_id` FK, `stall_name`, unique `stall_code`, `address`, coordinates, nullable `photo_url`, `status`, `created_at`. Status: `active`, `closed`, or `suspended`. `photo_url` is populated automatically from a CSV import's Google Drive photo link and is also editable on the admin stall form. The source photo is downloaded once and cached under `static/uploads/stall_photos/` rather than hotlinked, because Google Drive's image responses send `Cross-Origin-Resource-Policy: same-site`, which makes every visitor's browser silently refuse to load it directly from `drive.google.com`; `photo_url` therefore stores a local `/static/...` path. The customer search cards and stall-detail page display it, falling back to a placeholder icon if the image is missing.

### 11.7 `food_categories`

Food classification and inherent risk. Columns: `category_id` PK, unique `category_name`, `description`, `risk_level`. Risk: `low`, `medium`, or `high`.

### 11.8 `food_items`

Stall menu items. Columns: `food_item_id` PK, `stall_id` FK, `category_id` FK, `item_name`, non-negative nullable `price`, `is_available`, `created_at`. `(stall_id, category_id, item_name)` is unique.

### 11.9 `inspection_criteria`

Configurable inspection checklist. Columns: `criteria_id` PK, unique `criteria_name`, `description`, positive `max_score`, positive `weight`, `is_active`.

### 11.10 `inspections`

Inspection header. Columns: `inspection_id` PK, `stall_id` FK, `inspector_id` FK, `inspection_date`, calculated `overall_score`, calculated `risk_level`, calculated `reinspection_date`, `status`, `remarks`, `created_at`. Status: `draft`, `submitted`, `approved`, or `rejected`. An inspector submission always starts as `submitted`; an admin then approves or rejects it from `/admin/inspections`. Only `submitted`/`approved` inspections count as a stall's current inspection everywhere in the app (vendor/customer views, reports, risk engine), so rejecting a bad inspection removes it from those calculations without deleting the record. The app also rejects a new inspection dated earlier than the stall's existing latest `submitted`/`approved` inspection, so an out-of-order backdated entry can never be mistaken for the current one.

### 11.11 `inspection_scores`

One score for each criterion in an inspection. Columns: `score_id` PK, `inspection_id` FK, `criteria_id` FK, `score`, `comments`. `(inspection_id, criteria_id)` is unique. Triggers reject inactive criteria and scores outside `0..max_score`.

### 11.12 `complaint_types`

Complaint classification. Columns: `complaint_type_id` PK, unique `type_name`, `description`, `severity_level`. Severity: `low`, `medium`, `high`, or `critical`.

### 11.13 `complaints`

Complaint transaction. Columns: `complaint_id` PK, `stall_id` FK, `complaint_type_id` FK, nullable `submitted_by_user_id` FK, `title`, `description`, `status`, `submitted_at`, `resolved_at`. Status: `open`, `under_review`, `resolved`, or `rejected`. The admin UI only allows the transitions `open → under_review`, `under_review → resolved/rejected/open`, and `resolved/rejected → under_review`; it rejects any other jump (e.g. `open → resolved` directly) so a complaint's history can't be skipped or flipped back and forth without passing through review. Changing a complaint's status recalculates `calculate_stall_risk` for its stall's latest inspection, since the procedure's penalty depends on open/under-review complaint counts.

### 11.14 `reviews`

Customer review. Columns: `review_id` PK, `stall_id` FK, `user_id` FK, rating from 1 to 5, `review_text`, moderation `status`, `created_at`. `(stall_id, user_id)` is unique. Status: `visible`, `hidden`, or `flagged`.

### 11.15 `corrective_actions`

Remediation assigned to a vendor. Columns: `action_id` PK, nullable `inspection_id` FK, nullable `complaint_id` FK, `assigned_to_vendor_id` FK, `action_description`, `due_date`, `status`, `completion_notes`, nullable `evidence_path`, timestamps. At least one source—inspection or complaint—is required by triggers. Status: `pending`, `in_progress`, `completed`, `overdue`, or `cancelled`. `Complaint.corrective_actions` is a real ORM relationship (shown on the admin complaint-detail page), so admins can see actions already raised for a complaint; the admin UI also refuses to add a second one while a `pending`/`in_progress` action already exists for the same complaint. Once an action reaches `completed`, the vendor can no longer resubmit evidence against it.

### 11.16 `street_food_stall_registrations`

Raw Google Forms registration import. It stores submission time, vendor and stall details, area/address, menu/pricing, four Yes/No hygiene answers, payment method, image URL, comments, and a source timestamp. This table preserves incoming registration data independently of approved operational records.

## 12. Database Automation

### Weighted inspection score

```text
overall_score = 100 × SUM(score × weight)
                      / SUM(max_score × weight for all active criteria)
```

Inspection-score insert, update, and delete triggers recalculate the total. Risk and reinspection rules are:

| Score | Risk | Reinspection |
|---:|---|---:|
| 85–100 | low | 180 days |
| 70–84.99 | medium | 90 days |
| 50–69.99 | high | 30 days |
| Below 50 | critical | 7 days |

### Function

`get_hygiene_grade(score)` returns `A` for 85+, `B` for 70+, `C` for 50+, and `D` below 50. A null score returns null.

### Procedure

`calculate_stall_risk(stall_id, OUT risk_level, OUT risk_score, OUT reinspection_date)` uses the latest submitted/approved inspection and deducts penalties for unresolved complaints:

| Complaint severity | Penalty |
|---|---:|
| low | 2 |
| medium | 6 |
| high | 12 |
| critical | 20 |

The total complaint penalty is capped at 40. A stall without an eligible inspection is treated as unverified/critical.

### Triggers

- Two inspection triggers calculate/recalculate `reinspection_date`.
- Two corrective-action triggers require an inspection or complaint source.
- Two validation triggers enforce active criteria and valid score ranges.
- Three score triggers recalculate inspection total and risk after insert, update, or delete.

### Views

| View | Purpose |
|---|---|
| `latest_stall_inspection` | Latest submitted/approved inspection per stall |
| `high_risk_stalls` | Latest high/critical stalls and overdue days |
| `area_hygiene_summary` | Area-level inspected/uninspected counts, average score, grade, and risk counts |
| `pending_reinspection` | Scheduled, due-today, and overdue reinspections |
| `complaint_summary` | Per-stall complaint totals, statuses, and severe unresolved counts |

## 13. Key Workflows

### Inspection workflow

1. An authenticated inspector opens the new-inspection form.
2. The system limits stalls to the inspector's assigned area when applicable.
3. The inspector scores every active criterion; the chosen inspection date cannot predate the stall's existing latest submitted/approved inspection.
4. MySQL validates each score and recalculates weighted total, risk, and reinspection date.
5. The transaction is committed only when the inspection and all scores succeed.
6. The inspection is created with status `submitted`. An admin reviews it from `/admin/inspections` and approves or rejects it; only `submitted`/`approved` inspections count toward a stall's public grade and risk.
7. Low-scoring findings can create corrective actions for the vendor.

### Complaint and corrective-action workflow

1. A customer submits a complaint against a stall.
2. Admin reviews and moves it through `open → under_review → resolved`/`rejected` (or back to `under_review` to correct a mistake); other transitions are rejected. Each status change re-runs `calculate_stall_risk` for the stall's latest inspection.
3. A related corrective action may be assigned to the stall's vendor, unless one is already `pending`/`in_progress` for that complaint.
4. Vendor updates progress, adds completion notes, and uploads evidence; a `completed` action can no longer be resubmitted.
5. Evidence download checks vendor ownership or administrator access.

### Registration import workflow

1. Export Google Forms responses as a CSV ZIP.
2. Run `flask --app app import-stalls <zip_path>`.
3. The importer validates expected fields and normalizes values.
4. Duplicate source records (identical timestamp, phone, and stall name) are skipped.
5. Imported rows are stored in `street_food_stall_registrations`; the placeholder vendor account created for each row is keyed by phone number (when present), not by the row's timestamp, so a later resubmission from the same vendor reuses their existing account instead of creating a duplicate one.

## 14. Security and Data Integrity

- Passwords are stored as Werkzeug hashes, never plain text.
- POST forms require a session CSRF token.
- Login-required and role checks protect private routes.
- Inactive or suspended users are logged out.
- The post-login `?next=` redirect only accepts a same-site path (must start with a single `/`, never `//` or a backslash), closing an open-redirect bypass that a backslash-prefixed target could otherwise slip past the origin check.
- Account `status` values (user, stall) are validated against the enum on every admin create/edit form, not just the dedicated status-toggle routes.
- Foreign keys define ownership and prevent invalid references.
- Unique and check constraints enforce important business rules.
- Evidence type, size, and ownership are validated.
- Production must use a strong `SECRET_KEY`, HTTPS secure cookies, restricted database credentials, and a production WSGI server.
- Back up the database and evidence files together.

## 15. Testing

Run the sample test suite:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Compile-check Python modules:

```powershell
.\venv\Scripts\python.exe -m compileall -q app.py config.py models routes services
```

Live MySQL behavior—including triggers, procedure, views, transactions, permissions, and uploads—should also be tested using `tests/live_mysql_smoke.py` and `docs/test-checklist.md`.

## 16. Production Checklist

- Set a long random `SECRET_KEY` and production database credentials.
- Serve the application through HTTPS and enable secure cookies.
- Use Gunicorn/Waitress or another production WSGI server.
- Give the application database user only required privileges.
- Keep uploaded evidence outside a publicly served directory when stronger confidentiality is needed.
- Apply migration scripts instead of rerunning destructive `schema.sql`.
- Schedule database and evidence backups and test restoration.
- Disable Flask debug mode.

## 17. Source of Truth

When documentation and code differ, use these files as the implementation source of truth:

- Database structure: `database/schema.sql`
- Database behavior: `database/functions.sql`, `triggers.sql`, `procedures.sql`, and `views.sql`
- ORM mapping: `models/__init__.py`
- Application behavior and authorization: `app.py` and `routes/*.py`
- Environment behavior: `config.py` and `.env.example`

