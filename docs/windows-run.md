# Windows Setup and Final Run Instructions

The commands below assume PowerShell and project location
`C:\Food safety system`.

## 1. Install prerequisites

Install:

- Python 3.11 or newer
- MySQL Server 8.0 or newer
- MySQL Client (`mysql.exe`)

Confirm:

```powershell
py --version
mysql --version
```

Start the MySQL Windows service if necessary:

```powershell
Get-Service *mysql*
Start-Service MySQL80
```

The service name can differ. Use the name returned by `Get-Service`.

## 2. Open the project

```powershell
Set-Location "C:\Food safety system"
```

## 3. Create the virtual environment

```powershell
py -3.11 -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 4. Configure environment variables

```powershell
Copy-Item .env.example .env
notepad .env
```

Set at least:

```dotenv
FLASK_APP=app.py
FLASK_DEBUG=True
SECRET_KEY=replace-with-a-long-random-secret

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=smart_street_food_safety

SESSION_COOKIE_SECURE=false
UPLOAD_FOLDER=static/uploads/evidence
```

Generate a secure development secret:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output into `SECRET_KEY`.

## 5. Install a fresh database

Warning: `schema.sql` drops and recreates the application tables.

Open MySQL:

```powershell
mysql -u root -p
```

At the MySQL prompt, use forward-slash paths:

```sql
source C:/Food safety system/database/schema.sql;
source C:/Food safety system/database/functions.sql;
source C:/Food safety system/database/triggers.sql;
source C:/Food safety system/database/procedures.sql;
source C:/Food safety system/database/views.sql;
source C:/Food safety system/database/seed_data.sql;
exit
```

For an existing database, do not rerun `schema.sql`. Review and apply the
required scripts in `database/migrations/`, for example:

```sql
source C:/Food safety system/database/migrations/001_add_corrective_action_evidence.sql;
```

## 6. Create the first admin account

```powershell
flask --app app create-admin
```

Enter the administrator name, email, and a password of at least eight
characters. The password is stored as a Werkzeug secure hash.

## 7. Run validation

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py config.py models routes
```

Optional MySQL analytics check:

```powershell
mysql -u root -p
```

```sql
source C:/Food safety system/database/analytics.sql;
exit
```

## 8. Start the project

Development server:

```powershell
flask --app app run
```

To allow testing from another device on the same trusted network:

```powershell
flask --app app run --host 0.0.0.0 --port 5000
```

Open:

```text
http://127.0.0.1:5000
```

Stop the server with `Ctrl+C`.

## 9. Role entry points

After login, the application redirects automatically:

- Admin: `/dashboard/admin`
- Inspector: `/inspector/inspections/`
- Vendor: `/vendor/`
- Customer: `/customer/stalls`

Reports are available to administrators at `/admin/reports/`.

## 10. Common Windows issues

### PowerShell blocks Activate.ps1

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### MySQL command is not found

Add the MySQL `bin` directory to `PATH`, commonly:

```text
C:\Program Files\MySQL\MySQL Server 8.0\bin
```

Restart PowerShell afterward.

### Password contains @ or another reserved URL character

Use the individual `MYSQL_*` settings. The application builds the SQLAlchemy
URL safely and does not require manual URL encoding.

### Access denied for MySQL user

Verify `MYSQL_USER`, `MYSQL_PASSWORD`, host permissions, and database grants.

### Unknown column evidence_path

Apply:

```sql
source C:/Food safety system/database/migrations/001_add_corrective_action_evidence.sql;
```

### Charts are blank

Confirm the browser can load the Chart.js CDN and that MySQL contains
inspection/reporting data. Empty data produces empty charts rather than
invented values.

## 11. Production handoff

Before production:

1. Set `FLASK_DEBUG=False`.
2. Replace `SECRET_KEY`.
3. Enable HTTPS and set `SESSION_COOKIE_SECURE=true`.
4. Use a production WSGI server.
5. Use a restricted MySQL service account.
6. Configure database and evidence backups.
7. Complete every item in `docs/test-checklist.md`.
