# Smart Street Food Safety Test Checklist

Record the tester, environment, MySQL version, application commit, date, and
result for every release candidate.

## Environment and database

- [ ] Python dependencies install without errors.
- [ ] MySQL 8.0 is reachable using `.env` credentials.
- [ ] `schema.sql` creates every table and index on an empty database.
- [ ] Functions, triggers, procedures, views, and seed scripts install in the documented order.
- [ ] `get_hygiene_grade` returns A/B/C/D at the documented boundaries.
- [ ] Inspection score insert, update, and delete triggers recalculate totals.
- [ ] Invalid scores above the criterion maximum are rejected by MySQL.
- [ ] `calculate_stall_risk` includes unresolved complaint penalties.
- [ ] All five analytical queries in `database/analytics.sql` execute.

## Authentication and authorization

- [ ] Customer registration hashes the password and rejects duplicates.
- [ ] Valid users are redirected to the dashboard for their role.
- [ ] Invalid credentials show a generic error.
- [ ] Inactive and suspended accounts cannot log in.
- [ ] Disabling an active user invalidates their next authenticated request.
- [ ] CSRF protection rejects missing or incorrect tokens.
- [ ] Customer, vendor, and inspector accounts receive HTTP 403 on admin pages.
- [ ] Vendor A cannot access Vendor B's stalls, food items, actions, or evidence.
- [ ] Inspector A cannot view Inspector B's inspection details.

## Admin module

- [ ] KPI values match direct MySQL counts.
- [ ] Dashboard charts render with empty and populated databases.
- [ ] Vendor create, search, edit, and delete work.
- [ ] Stall create, search, edit, and delete work.
- [ ] Inspector create, search, edit, and delete work.
- [ ] Foreign-key dependent records produce a friendly delete error.
- [ ] Complaints can be filtered and opened.
- [ ] Admin can mark complaints open, under review, resolved, or rejected.
- [ ] Admin can assign a corrective action and due date.
- [ ] All reports load and match direct SQL samples.

## Inspector workflow

- [ ] Inspector sees only active stalls in the assigned area.
- [ ] Every active criterion appears with its maximum score.
- [ ] Missing, negative, nonnumeric, and excessive scores are rejected.
- [ ] Criterion comments and overall remarks persist.
- [ ] Inspection and all scores commit in one transaction.
- [ ] A failure during any score insert rolls back the inspection and earlier scores.
- [ ] Result page shows MySQL total, grade, risk, and reinspection date.

## Vendor module

- [ ] Dashboard shows every owned stall and no foreign stall.
- [ ] Current score, grade, risk, reasons, and reinspection date are correct.
- [ ] Inspection history is newest first.
- [ ] Food item create, update, availability, and delete work.
- [ ] Vendor complaint list contains only complaints for owned stalls.
- [ ] Corrective action requires notes and evidence.
- [ ] Only PNG, JPG, JPEG, and PDF evidence is accepted.
- [ ] Evidence upload marks the action completed.
- [ ] Evidence download enforces ownership.

## Customer module

- [ ] Search finds stalls by name, address, and code.
- [ ] Area, category, and risk filters work individually and together.
- [ ] Stall details show current safety data, menu, and visible reviews.
- [ ] A customer can submit exactly one review per stall.
- [ ] Rating outside 1–5 is rejected.
- [ ] Complaint requires type, title, and description.
- [ ] Customer sees only their own complaint tracking records.
- [ ] Resolved and rejected complaints show their closure time.

## Responsive and usability

- [ ] Admin sidebar and charts render at 1920×1080 and 1366×768.
- [ ] Admin navigation becomes a mobile drawer below the large breakpoint.
- [ ] Vendor, inspector, and customer pages remain usable at 390×844.
- [ ] Tables scroll horizontally without clipping controls.
- [ ] Flash messages clearly report success and failure.
- [ ] Keyboard focus and form labels are visible and usable.

## Release checks

- [ ] `python -m unittest discover -s tests -v` passes.
- [ ] `python -m compileall -q app.py config.py models routes` passes.
- [ ] `git diff --check` reports no whitespace errors.
- [ ] No test databases, test evidence, credentials, or debug logs remain.
- [ ] Production uses a long random `SECRET_KEY` and secure cookies over HTTPS.
