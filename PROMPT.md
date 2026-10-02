# Copilot Prompt Log
Tool: GitHub Copilot Chat (Agent mode) in VSCode

## Step 1 - Processing

### Prompt
```
Create processor/services.py. Use #file:DESIGN.md as a reference. The goal is to read an input CSV, look up each ZIP code, and return a result for each row with a status. Also add a function to write those results to an output CSV.

Do not build email notifications, folder handling, file moving, output file naming, or scheduling yet. I plan to build these out in separate steps.

Follow the Input and Validation section for reading the CSV. If the file is empty, required headers are missing, or there are headers but no rows, raise a custom exception so it can be handled later.

Follow the ZIP rules in the design. Spaces inside a ZIP are invalid, and only digits 0–9 should be accepted.

Strip spaces around the email and check it with Django's email validator. Still look up the ZIP if the email is invalid.

Follow the ZIP Code Lookup section for the lookup and its retry rules, timeout, and pauses.

Each ZIP should only be looked up once per file. Check each row's email separately, even when the ZIP was already looked up.

Use the five statuses from the design. ZIP problems take priority over email problems.

Follow the Output section for the CSV columns and values. If writing fails, delete the partial file and raise the error so emails do not get sent later.

Use requests for HTTP calls, logging instead of print, and a docstring and comments on each function.

Add unit tests for the main behaviors, mocking the API calls and the retry pauses.

Run python manage.py test processor -v 2 and report the results.
```

### Copilot response
````
````

### Notes

---