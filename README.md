# Smart Street Food Safety

A Flask and MySQL platform for street-food registration, inspection scoring,
risk analysis, corrective action tracking, customer reviews, complaints, and
administrative reporting.

## Technology

- Python 3.11+
- Flask, Flask-Login, and Flask-SQLAlchemy
- MySQL 8.0+
- Werkzeug password hashing
- Bootstrap 5, Bootstrap Icons, Font Awesome, and Chart.js
- Inter (Google Fonts) for site typography

## Main modules

- Public landing page with live, database-backed platform statistics
- Role-based authentication for administrators, inspectors, vendors, and customers
- Admin dashboard and vendor, stall, inspector, and complaint management
- Transactional inspector workflow with MySQL score triggers and risk procedure
- Vendor safety profiles, food item CRUD, corrective actions, and evidence uploads
- Customer stall discovery, reviews, complaints, and complaint tracking
- MySQL-backed reports and reusable analytical SQL

## Public landing page

The `/` route (`app.py`) renders `templates/home.html`, which extends the
shared `templates/base.html` layout. It is the public-facing homepage shown
before login.

**Layout** (single scrollable page):

- Sticky navbar with anchor links (Home, Features, How It Works, About,
  Contact) plus Login/Register — recolors with a shadow once the page is
  scrolled
- Hero section with headline, supporting copy, Sign In / Create Account CTAs,
  and a CSS-built "live" vendor risk-dashboard preview card
- Trust/stats strip showing **Vendors Tracked**, **Inspections Logged**,
  **Risk Alerts Resolved**, and **Cities Covered**
- Features grid: Inspection Records, Vendor Profiles, Risk Scoring, Reports &
  Analytics
- "How It Works" 3-step process: Register Vendor → Conduct Inspection & Score
  Risk → Review Reports & Act on Alerts
- "Why It Matters" / About section on the public-health value of the platform
- Full-width call-to-action banner
- Site-wide footer (logo, quick links, portals, contact, copyright)

**Live stats, not placeholders.** The stats strip is populated on every
request directly from MySQL, in the `home()` view in `app.py`:

| Stat | Source query |
| --- | --- |
| Vendors Tracked | `Vendor.query.count()` |
| Inspections Logged | `Inspection.query.count()` |
| Risk Alerts Resolved | `CorrectiveAction` rows with `status="completed"` |
| Cities Covered | distinct `Area.city` values |

Numbers are recalculated on each page load, so they always reflect the
current database — no caching, no manual updates required.

**Visual details.** Styling lives in `static/css/styles.css` (brand tokens:
`--brand-green: #1f7a4d`, `--brand-green-dark`, `--brand-green-light`,
`--surface-bg: #f7f8f9`) and a small script in `templates/base.html` drives
scroll-triggered fade/slide-in animations (`.reveal` / `.reveal-visible`,
via `IntersectionObserver`) and the navbar's scrolled state. Decorative
blurred accent shapes and dot-grid textures sit behind the hero, about, and
CTA sections. All motion respects `prefers-reduced-motion` and degrades to
static, fully visible content without JavaScript.

## Quick start

Detailed Windows instructions are in
[docs/windows-run.md](docs/windows-run.md).

1. Install Python 3.11+, MySQL Server 8.0+, and MySQL Client.
2. Create and activate a virtual environment.
3. Install `requirements.txt`.
4. Copy `.env.example` to `.env` and enter local credentials.
5. Install the database scripts in this order:

   1. `database/schema.sql`
   2. `database/functions.sql`
   3. `database/triggers.sql`
   4. `database/procedures.sql`
   5. `database/views.sql`
   6. `database/seed_data.sql`

   For an existing or partially created database, use the non-destructive
   initializer instead. It keeps existing users and application data:

   ```powershell
   flask --app app init-db
   ```

6. Create the first administrator:

   ```powershell
   flask --app app create-admin
   ```

7. Start the application:

   ```powershell
   flask --app app run
   ```

8. Open <http://127.0.0.1:5000>.

> `schema.sql` drops and recreates application tables. Do not run it against a
> populated database unless a reset is intended. Existing installations should
> apply scripts in `database/migrations/` as required.

## Database intelligence

Risk calculations are not delegated solely to Python:

- `get_hygiene_grade` returns the hygiene grade.
- Inspection score triggers validate scores and recalculate weighted totals.
- `calculate_stall_risk` evaluates the latest score and unresolved complaints.
- Inspection triggers calculate reinspection dates.
- Reporting views and `database/analytics.sql` provide operational analysis.

The analytical query library contains:

- Lowest average hygiene area
- Complaint volume versus inspection score
- Most failed criterion
- Reinspection improvement
- Vendors with repeated failures

## Reports

Administrators can open `/admin/reports/` for:

- Inspection trend
- Risk distribution
- Area-wise hygiene score
- Complaint distribution
- Top hygienic stalls
- High-risk stalls
- Reinspection due schedule

Every report dataset is queried from MySQL through SQLAlchemy.

## Evidence uploads

Corrective evidence accepts PNG, JPG, JPEG, and PDF files up to 8 MB. Files
default to `static/uploads/evidence`; the location can be changed with
`UPLOAD_FOLDER`. Downloads enforce vendor ownership or administrator access.

Do not commit uploaded evidence or production credentials to source control.

## Testing

Run the included sample suite:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Compile-check the Python modules:

```powershell
.\venv\Scripts\python.exe -m compileall -q app.py config.py models routes
```

Follow [docs/test-checklist.md](docs/test-checklist.md) for MySQL procedures,
transactions, permissions, uploads, browser behavior, and release testing.

## Project structure

```text
app.py                  Flask application factory and CLI
config.py               Environment and database configuration
database/               Schema, routines, views, analytics, seed, migrations
models/                 SQLAlchemy models
routes/                 Authentication and role-specific workflows
templates/              Bootstrap/Jinja interfaces
static/css/             Public, admin, inspector, and portal styles
static/uploads/         Corrective evidence storage
docs/                   Design, Windows setup, and test checklist
tests/                  Runnable sample tests
```

## Production notes

- Use a long random `SECRET_KEY`.
- Set `SESSION_COOKIE_SECURE=true` behind HTTPS.
- Use a production WSGI server instead of Flask's development server.
- Restrict the MySQL user to the required database privileges.
- Store uploads outside the public static directory when stronger evidence
  access controls are required.
- Back up the database and evidence directory together.
