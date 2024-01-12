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

- Create a local environment file (customize according to your needs) from the provided template: `cp grm/.example.env grm/.env`. For example fill database credentials. Create the appropriate couchdb databases (db, adb, grm, grmabd)
- Do the same for `local_settings.py`: `cp grm/local_settings_template.py grm/local_settings.py`

- `python3 manage.py migrate`
- `python3 manage.py runserver`