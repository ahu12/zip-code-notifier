# Design Notes

## Overview

This application will read a CSV containing ZIP codes and email addresses, use Zippopotam.us to get the state information, and write the results to an output CSV. It will email the results to the supplied addresses and check for new files every two minutes.

Flow: input CSV → read and validate → look up ZIP codes → write output → send emails → move input file.


## Requirements and Design Choices

### Assignment Requirements

- Build the application using Python/Django or Spring Boot. This project will use Python/Django.
- Read CSV files from a specific folder and retrieve state information using Zippopotam.us.
- Write the ZIP codes and results to an output CSV.
- Check for new files every two minutes and notify the email addresses from the input.
- Use GitHub Copilot, share the repository, include an AI prompt log, and document how to run the application.

### Design Choices

- Use Django for management commands, configuration, email validation, and sending email.
- Keep each input row in the output with a status so errors can be reviewed.
- Send one email per email address per file, containing all ZIP code results for that address.
- Retry temporary API failures and reuse results for repeated ZIP codes within a file.
- Use console email for local testing and SMTP for actual sending.
- Process one file at a time, with one application instance running.

## Components

- **Processing:** Read the CSV, validate rows, look up ZIP codes, and write results.
- **Notifications:** Group results by email address and send them through Django.
- **Inbox job:** Find new files, run the processing steps, log results, and move the input files.
- **Commands:** `process_inbox` will run one scan for testing. `run_scheduler` will run scans every two minutes.

## Input and Validation

- Require the headers `zip_code` and `email`. Remove surrounding spaces from headers and accept UTF-8 CSVs, including files saved with a BOM by Excel.
- An empty file, a file with missing headers, or a file with headers but no data goes to the error folder.
- Keep ZIP codes as text and remove surrounding spaces. Accept five digits using 0–9. For ZIP+4, require the exact format `12345-6789` and use the first five digits.
- Pad ZIPs containing one to four digits with leading zeros and log a warning. This handles a common spreadsheet issue, but cannot confirm which ZIP the user intended. Empty ZIPs, internal spaces, letters, and other formats are invalid.
- Remove surrounding spaces from email addresses and check their format using Django. Valid emails look like name@example.com
- Mark invalid rows and continue processing. If the ZIP is valid but the email is invalid, still look up the ZIP so its state can appear in the output.

## ZIP Code Lookup

- Use `https://api.zippopotam.us/us/{zip_code}` and take `state` and `state abbreviation` from the first entry in `places`.
- Allow up to three attempts with a 10-second request timeout. Wait one second before the second attempt and two seconds before the third.
- Retry timeouts, connection errors, 429 responses, and 5xx responses. Do not retry 404, other 4xx responses, invalid JSON, or responses missing the required state information.
- Other request errors, such as too many redirects, are `API_ERROR` and are not retried.
- Look up each ZIP once per file and reuse its result, including an unsuccessful result. Check each row's email separately so one invalid address does not affect another row.

## Output

Write one UTF-8 output CSV per valid input file. Keep the rows in their original order and use these columns:

`zip_code, email, state, state_abbreviation, status`

Statuses and meaning: 
- `OK`: State information was found and the email format is valid.
- `INVALID_ZIP`: The ZIP format is invalid, so no API call was made.
- `NOT_FOUND`: The API returned 404 for the ZIP.
- `API_ERROR`: The lookup failed or the response did not contain the required state information.
- `INVALID_EMAIL`: The lookup succeeded, but the email format is invalid. State information is still included.

Rules:
- ZIP errors take priority over email errors in the status column. Email validity is checked separately before sending. Email sending failures are logged separately.
- Write the cleaned ZIP when valid, or keep the supplied value when invalid. Leading zeros remain in the CSV, although Excel may remove them when opening it.
- Use the input filename and a timestamp for the output name. Add a number if that name already exists rather than overwriting a file.
- If writing fails, remove the incomplete output and do not send emails for that file.

## Notifications

- Send one email per valid address per file, listing only that address's ZIP codes and results. Group matching addresses after removing surrounding spaces, ignoring capitalization, so one person does not receive duplicate emails. Send to the address as it was first written.
- Include unsuccessful ZIP results so the recipient can see what failed. Do not send to invalid email addresses.
- Use console email by default to preview messages locally. Configure SMTP through `.env` to send actual emails.
- If an email fails, log it and continue with the remaining addresses. Keep the output CSV and move the input to the error folder for review. Do not automatically resend it.

## File Processing

- Use four folders: inbox, output, processed, and error, and create any missing folders at startup.
- Move the input to `processed` after writing the output and sending all eligible notifications.
- Move invalid files or files with processing or email failures to `error`. Log the reason, keep any completed output, and continue with the next file.
- Avoid overwriting files in the processed and error folders by adding a timestamp or number when needed. If an input cannot be moved out of the inbox (for example, because it is open in Excel), log the error and stop: process_inbox exits, and run_scheduler shuts down instead of continuing, so the file is not processed and emailed again on the next scan.

## Scheduling

- Use APScheduler 3.x in the `run_scheduler` command to handle the two-minute interval without needing a separate worker service.
- Scan at startup and then every two minutes. If a scan is still running, skip the next scheduled run.
- Write logs to the console and a local file, including scans, file results, retries, and email failures.

## Configuration

- Keep the Django secret key, email settings, sender address, and folder paths in `.env`. Provide local defaults where credentials are not needed.
- Include `.env.example` with placeholders. Keep secrets, generated files, logs, and the virtual environment out of Git.