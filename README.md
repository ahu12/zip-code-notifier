# Zip Code Notifier

Python/Django program that takes a list of ZIP codes and email addresses from a CSV file, gets the state and state abbreviation from Zippopotam.us API, saves the results with a status to an output CSV, and sends an email notification to the supplied email addresses.

## What it Does
* Scans an inbox folder for CSV files
* Reads the CSV files for ZIP codes and email addresses
* Writes the results to an output CSV file with a status for each row
* Emails each email address the results
* Scans for new files every 2 minutes

## Requirements

* Python 3.12 or newer. macOS: check with `python3 --version`
* Git
* A Gmail account with an app password (if you want to send real emails using Gmail SMTP)

## Setup

### 1. Clone the Repository

```
git clone https://github.com/ahu12/zip-code-notifier
cd zip-code-notifier
```

### 2. Create a Virtual Environment
Windows:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```
If activation is blocked: 
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

macOS/Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```
pip install -r requirements.txt
```

### 4. Set up .env
Copy the .env.example contents to .env:

Windows:
```powershell
Copy-Item .env.example .env
```

macOS/Linux:
```bash
cp .env.example .env
```

### 5. Generate the Django Secret Key

Verify the virtual environment is activated.

Copy/paste the generated key in .env with no quotes or spaces: `SECRET_KEY=paste_the_generated_key_here`
```
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

### 6. Verify the setup is successful

```
python manage.py check
```

Expected output:
```text
System check identified no issues (0 silenced).
```

If you see `SECRET_KEY not found`, check that `.env` exists in the project folder and contains the `SECRET_KEY` line.

## Configuration

Steps 1 and 2 are optional - follow these if you want to send real emails using Gmail SMTP instead of through the terminal console.

Restart `run_scheduler` after changing `.env` settings. Settings are only read when a command starts.

### 1. Obtaining a Gmail App password
1. Use a Gmail account with 2-Step Verification turned on (Google Account -> Security). App passwords cannot be generated without 2-Step Verification.
2. Once 2-Step Verification is turned on, go to https://myaccount.google.com/apppasswords to create one (for example, zip-code-notifier)
3. Copy the 16-character password without spaces into `EMAIL_HOST_PASSWORD` in `.env` (see Step 2). Google will only give you the app password once.

### 2. .env SMTP setup

Email settings in `.env`. The SMTP settings below are only used when `EMAIL_BACKEND` is set to SMTP to send real emails.

| Variable | Purpose | Default | Gmail |
|---|---|---|---|
| `EMAIL_BACKEND` | Console (prints emails in the console) or SMTP (sends real emails). See the values to use below the table. | Console | SMTP |
| `EMAIL_HOST` | Mail server address | `localhost` | `smtp.gmail.com` |
| `EMAIL_PORT` | Mail server port | `25` | `587` |
| `EMAIL_USE_TLS` | Encrypt the connection to the mail server | `False` | `True` |
| `EMAIL_TIMEOUT` | Number of seconds before the connection to the mail server times out | `10` | `10` |
| `EMAIL_HOST_USER` | Email address used to log in to the mail server | empty | Your Gmail address |
| `EMAIL_HOST_PASSWORD` | Password for the mail server | empty | Your Gmail app password (not your regular email password. Obtained in Step 1) |
| `DEFAULT_FROM_EMAIL` | Sender address shown on the emails | `zip-notifier@example.com` | Same address as `EMAIL_HOST_USER` - Gmail replaces any other sending address with the logged-in account |

`EMAIL_BACKEND` values:
```text
Console: django.core.mail.backends.console.EmailBackend
SMTP:    django.core.mail.backends.smtp.EmailBackend
```

### 3. Folder Paths

Folders are created automatically. Relative paths start from the project folder.

| Folder | Purpose | `.env` variable |
|---|---|---|
| `data/inbox` | Input CSVs go here | `INBOX_DIR` |
| `data/output` | Result CSVs are written here | `OUTPUT_DIR` |
| `data/processed` | Inputs that processed successfully | `PROCESSED_DIR` |
| `data/error` | Invalid or failed inputs | `ERROR_DIR` |
| `logs` | The log file | `LOGS_DIR` |

## Input

The program scans `data/inbox` for new input CSV files.

The file must have the following headers: zip_code,email
```csv
zip_code,email
12345,name@example.com
54321,alice@example.com
94143,bob@example.com
```

ZIP Code Rules:
* ZIP codes must only contain digits
* For ZIP + 4 format, it will take the first 5 digits. It must be the exact format 12345-1234. Anything less or more is invalid
* Less than 5 digits will be padded with leading zeros. 
* Spaces inside the ZIP are invalid
* More than 5 digits is invalid

Email Rules:
* Must have a valid format: name@example.com
* White spaces before and after the email address are removed.

Invalid rows are kept in the output with a status so it can be reviewed.

A whole file is invalid and moved to `data/error` if: missing headers, has headers but no rows, an empty file

Files that don't end in `.csv` are ignored and left in the inbox.

For a CSV file sample, see `samples/sample_input.csv`


## Running the Program

With the virtual environment activated, run:

One scan, then exits:
```
python manage.py process_inbox
```

Scans at startup, then every 2 minutes. `Ctrl + C` to stop the scheduler:
```
python manage.py run_scheduler
```

Add `--interval-seconds 10` for a quicker demo. `Ctrl + C` to stop the scheduler:
```
python manage.py run_scheduler --interval-seconds 10
```

Run only one scheduler at a time, and stop it before running `process_inbox`. If switching between SMTP and console emails, stop the scheduler. After changing `.env`, start the scheduler again.

## Output

* The program writes an output CSV to `data/output`
* The file naming convention is: `<input name>_<timestamp>.csv`. Numbers will be added at the end if needed. The timestamp format: YYYYMMDDHHMMSS in local time, for example `test_input_20261003121230.csv`
* Input files keep their names in `data/processed` or `data/error`. If a file with the same name already exists, a number is added, for example `test_input_1.csv`
* Output files will have the following headers: `zip_code, email, state, state_abbreviation, status`
* Values starting with `=`, `+`, `-`, `@`, a tab, or a carriage return get a leading apostrophe (`'`) so spreadsheet programs treat them as text instead of formulas.

Each row in the output has one of these statuses:

| Status Name | Status Meaning |
| --- | --- |
| `OK` | State information was found and the email format is valid. |
| `INVALID_ZIP` | The ZIP format is invalid, so no API call was made. |
| `NOT_FOUND` | The API returned 404 for the ZIP. |
| `API_ERROR` | The lookup failed or the response did not contain the required state information. |
| `INVALID_EMAIL` | The lookup succeeded, but the email format is invalid. State information is still included. |

Note: ZIP code problems take priority over invalid email statuses. A row with both an invalid email and an invalid ZIP code will display `INVALID_ZIP`.

Example Output:

```csv
zip_code,email,state,state_abbreviation,status
02108,alice@example.com,Massachusetts,MA,OK
02108,not-an-email,Massachusetts,MA,INVALID_EMAIL
02108,bob@example.com,Massachusetts,MA,OK
123-4567,carol@example.com,,,INVALID_ZIP
```

## Email Notifications

* One email is sent for each unique email address per file. If there are multiple ZIP codes they are grouped into one email. Capitalization is ignored when grouping. For example, `Bob@example.com` and `bob@example.com` get one email.
* Invalid email addresses are skipped
* Rows with ZIP problems are still included, with their status.
* If an email fails, it gets logged and the input file moves to `data/error`. It is not re-sent automatically.
* Email notifications are printed to the console by default. SMTP can be set up by following the steps in [Configure SMTP](#configuration)
* Email notifications contain a subject with the input file name, and an email body with one line per ZIP code with its state, state abbreviation, and status. Example:

```
Subject: ZIP code results for sample_input.csv

- 90210 | California | CA | OK
```

## Verification

### 1. Create a CSV in `data/inbox` or copy `samples/sample_input.csv`:

Windows:
```powershell
Copy-Item samples\sample_input.csv data\inbox\
```

macOS/Linux:
```bash
cp samples/sample_input.csv data/inbox/
```

If copying the file from `samples/sample_input.csv`, `data/inbox` should have `sample_input.csv`

### 2. Process it
```
python manage.py process_inbox
```

If this is run using the default print to console, the console should print `...processor.notifications Email sent to...` along with the Subject, From, To, Date, Email Body. It should also display whether the file was processed or not. When using the sample, frank@example.com gets one email with two lines, while not-an-email gets no email.

### 3. Check the folders

Windows:
```powershell
Get-ChildItem data\output, data\processed
```

macOS / Linux:
```bash
ls data/output data/processed
```

If using a valid CSV, a new CSV should be created in `data/output`, the input CSV should be moved to `data/processed`, and `data/inbox` should be empty. If using the `sample_input.csv`, it would look like: `sample_input_20261004120000.csv`


### 4. View the results

Open the newest file in `data/output`

Each row should have a ZIP code and a status.

### 5. (optional) Run the scheduler

```
python manage.py run_scheduler --interval-seconds 10
```

While the scheduler is running, create a new CSV in `data/inbox` or copy the sample into the inbox again. It should attempt to process the file within 10 seconds of creating or copying the file. Press `Ctrl + C` to stop the scheduler.

## Running Tests

The tests cover CSV reading and validation, the ZIP rules, API retry rules, email grouping and failures, file processing, and the scheduler. Run all tests with:
```
python manage.py test processor -v 2
```

* A successful run shows 31 tests, all `ok`, ending with `OK`.
* ERROR lines and tracebacks in the output are expected: some tests simulate failures on purpose.
* The tests mock the ZIP API and email sending - they run without network access and never send real emails.
* The tests check the logic and error handling. The [Verification](#verification) steps check the real API. The Gmail setup in [Configuration](#configuration) was used to check real email delivery.

## Logs

* Logs are written to both the console and to a log file found at: `logs/zipcode_notifier.log`.
* In console mode, email bodies are printed to the terminal only, not the log file
* Logs contain email addresses. `logs/` is excluded from git.

Items being logged:

| Module Name | What is being logged |
| --- | --- |
| `processor.inbox` | Each scan starting and finishing. Each file's results - processed, or moved to error with the reason. Files moved to error, unexpected errors and failed moves with full tracebacks |
| `processor.services` | ZIP warnings: padded, not found, HTTP errors, each retry attempt, failed lookups |
| `processor.notifications` | Emails sent, invalid addresses skipped, failed sends with full tracebacks |
| `run_scheduler` and APScheduler | When scheduler is starting, when it's running, schedule run times, when it's stopped or interrupted, errors |

## Files in this Repo
```text
zip-code-notifier/
├── processor/                        # Django app for the processing jobs
│   ├── management/
│   │   └── commands/
│   │       ├── process_inbox.py      # A command to run a scan
│   │       └── run_scheduler.py      # A command that runs a scan at startup and every 2 minutes
│   ├── inbox.py                      # Processes the inbox: reads, looks up, writes the output, sends emails, and moves each file.
│   ├── notifications.py              # Groups results by email and sends the notification emails
│   ├── services.py                   # Reads and validates the CSV, looks up ZIPs with retries, checks emails, and writes the output
│   ├── tests.py                      # Tests for processing, inbox handling, and the scheduler
│   └── test_notifications.py         # Tests for email grouping, skipped addresses, and failed sends
├── zipcode_notifier/                 # The main Django project
│   └── settings.py                   # The main configuration file. Contains installed apps, folder, email, and logging settings.
├── samples/
│   └── sample_input.csv              # Example CSV with test cases
├── data/                             # (created when the app runs, not in git)
├── logs/                             # (created when the app runs, not in git)
├── .env.example                      # Template for the .env
├── DESIGN.md                         # The program design used to prompt Copilot
├── PROMPT.md                         # AI prompt log
├── README.md
├── manage.py
└── requirements.txt                  # Python packages and versions to install
```

## Design Decisions
* **State tracking:** For the scope of the assignment, I used folders to track which files were processed or had errors. This kept setup and testing simpler without needing a database. The trade-off is that retrying a file or restarting after a crash can send duplicate emails, because there is no record of what was already sent. Tracking processed files and sent emails is the next step I'd take.
* **Scheduler:** I used APScheduler because there is only one job running every two minutes, and it works on Windows. Celery would add a message broker and worker processes that this assignment didn't need. `process_inbox()` could run as a Celery task without changes.
* **Notifications:** I group results so each address gets one email per file, with all of its results. This avoids sending one person several emails for the same file and lets them see which ZIP codes had problems.
* **Partial results:** For valid input files, the output is always written with a status for each row, even if some API lookups fail. Successful results are delivered right away, but rows marked `API_ERROR` are not retried automatically.

See [DESIGN.md](DESIGN.md) for the full design.

## Known Limitations
* Only place saved files in the inbox. Files still being copied or written may be read partially.
* Run only one scheduler at any given time and stop it before running `process_inbox`. Two scans running at once may process the same file.
* Failed emails are not re-sent automatically. They are logged and the input goes to the `data/error` folder.
* Retrying a file or restarting after a crash may send duplicate emails. Check `data/error` before retrying.
* Excel may display `02108` as `2108`, but the leading zero is still in the CSV.
* Puerto Rico and other US territory ZIP codes return `NOT_FOUND` because the API lists them separately from US ZIPs.
* Email validation checks the email format, but cannot verify if a mailbox actually exists.
* During an API outage, each unique ZIP code is retried up to three times, so a large file can take a long time to process.
* Keeps all data folders on the same drive. Moving files between drives is not supported and stops the run.
* Developed and tested on Windows 11. The code is intended to work across platforms, but macOS and Linux commands have not been tested.

## Design and AI Usage
* [DESIGN.md](DESIGN.md) : Program requirements and design decisions.
* [PROMPT.md](PROMPT.md) : AI Prompts, Copilot responses, and notes.

## API Credit
This project uses the [zippopotam.us Zippopotamus API](https://zippopotam.us) for ZIP code lookups.