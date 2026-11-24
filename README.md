# GRM-benin

Requirements
- Python version : `python3.12`
- Framework : Django 5.2 LTS
- Database : `postgresql`

Run the App
`cd GRM-Web-App-Benin/src`

## Setup

Create a Python 3.12 virtual environment
`python3.12 -m venv venv`

Activate Python Environment
`source venv/bin/activate`

Upgrade pip
`pip install --upgrade pip`

Install packages

- Production only: `pip install -r requirements.txt`
- Development (includes production + tests and tooling): `pip install -r requirements.dev.txt`

`requirements.txt` only lists the direct production dependencies, pinned. Test and tooling
packages (pytest, factory-boy, Faker, black, pre-commit, pip-audit, debug toolbar) live in
`requirements.dev.txt` and must not be installed in production.

Start Application

- Create a local environment file (customize according to your needs) from the provided template: `cp grm/example.env grm/.env`. For example fill database credentials. Only `SECRET_KEY` and `DATABASE_URL` are required; CouchDB is deprecated and only needed to import data from a legacy deployment.
- Do the same for `local_settings.py`: `cp grm/local_settings_template.py grm/local_settings.py` and update if needed.
- `python manage.py migrate`
- `python manage.py runserver`

## Production deployment

Production runs with Docker on a VM (Django, Celery worker and beat, PostgreSQL, Redis, nginx): see **[DEPLOY.md](DEPLOY.md)** for the exact files to copy, the commands to run and the first start (administrator, setup wizard, Excel imports).

## Configuration (for other country usage)

- With the help of the proper specialists update the files in `couchdb/jsonCollections` folder and create the appropriate docs. The file are named following this structure `database_document_type.json`. For ex `grm_issue_age_group.json` contains multiple documents from `issue_age_group` type that will be created in the `grm` database. You can create the documents manually or use a script (`Postman` can be useful here).

- Update the appropriate views in `src/dashboard/grm/views.py` and their related forms, templates and used functions. Ex of views : `NewIssueMixin`, `NewIssueContactFormView`, `NewIssuePersonFormView`, `NewIssueDetailsFormView`, `NewIssueLocationFormView`, `NewIssueConfirmFormView`, `NewIssueConfirmationFormView`

## Development tools

### pre-commit
- We use pre-commit configurations in this project (black, isort, ...)

- Run from src/ `pre-commit install` to set up the git hook scripts. 

- More info on [pre-commit](https://pre-commit.com/)
- 
### Tests
To run the tests, you must meet the following requirements:
- Development requirements installed (`pip install -r requirements.dev.txt`).
- Your Postgres database user must have permissions
  (`ALTER USER your_db_user CREATEDB;`)

A CouchDB server is no longer required to run the tests.

Then run the command:
`pytest`

### Dependency security audit
`pip-audit -r requirements.txt`
