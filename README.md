# GRM-benin

Run the App
`cd GRM-Web-App-Benin/src`

## Setup

Activate Python environment (use python 3)
`python3 -m venv venv`

Activate Python Environment
`source venv/bin/activate`

Install application

- `pip install -r requirements.txt`
- `pip install -r requirements.dev.txt`

Start Application

- Create a local environment file (customize according to your needs) from the provided template: `cp grm/.example.env grm/.env`. For example fill database credentials. Create the appropriate couchdb databases (administrative_levels, adb, grm, grmabd)
- Do the same for `local_settings.py`: `cp grm/local_settings_template.py grm/local_settings.py` and update if needed.
- `python3 manage.py migrate`
- `python3 manage.py runserver`

## Configuration (for other contry usage)

- With the help of the proper specialists update the files in `couchdb/jsonCollections` folder and create the appropriate docs. The file are named following this structure `database_document_type.json`. For ex `grm_issue_age_group.json` contains multiple documents from `issue_age_group` type that will be created in the `grm` database. You can create the documents mannually or use a script (`Postman` can be useful here).

- Update the appropiate views in `src/dashboard/grm/views.py` and their related forms, templates and used functions. Ex of views : `NewIssueMixin`, `NewIssueContactFormView`, `NewIssuePersonFormView`, `NewIssueDetailsFormView`, `NewIssueLocationFormView`, `NewIssueConfirmFormView`, `NewIssueConfirmationFormView`