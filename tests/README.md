# Sample tests

Run from the project root:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

These fast samples use an in-memory SQLite database to verify password
hashing, disabled-user prevention, registration, sessions, and role guards.
MySQL-specific triggers, procedures, analytics, and transaction rollback must
also be validated using the manual checklist in `docs/test-checklist.md`.
