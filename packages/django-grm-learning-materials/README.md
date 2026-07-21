# django-grm-learning-materials

> Reusable Django package for creating and managing training/learning materials (articles, videos, PDFs) with bilingual support (French/English), role-based targeting, and a rich CRUD UI.

## Installation

```bash
pip install grm-learning-materials
```

Or from a local path:

```bash
pip install path/to/grm-learning-materials
```

## Quick Start

### 1. Add to `INSTALLED_APPS`

```python
# settings.py
INSTALLED_APPS = [
    ...
    "grm_learning_materials",
]
```

### 2. Include the URLs

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    ...
    path("learning-materials/", include("grm_learning_materials.urls")),
]
```

### 3. Run migrations

```bash
python manage.py migrate grm_learning_materials
```

## Configuration

All settings are optional and go under the `GRM_LEARNING_MATERIALS` dict:

```python
# settings.py
GRM_LEARNING_MATERIALS = {
    # Template extended by all learning-materials templates.
    # Default: "layouts/base.html"
    "BASE_TEMPLATE": "myapp/base.html",

    # Dotted path to a permission-check function.
    # The function receives the request and returns True/False.
    # Example: "myapp.utils.is_admin"
    # If None (default), any authenticated user can access.
    "PERMISSION_CALLBACK": "myapp.utils.is_admin",

    # Directory prefix for file uploads under MEDIA_ROOT.
    # Default: "learning_materials"
    "UPLOAD_PATH_PREFIX": "my_uploads",

    # URL namespace used by the package.
    # Default: "grm_learning_materials"
    "URL_NAMESPACE": "grm_learning_materials",
}
```

## Features

- **Bilingual content** — French and English fields with language tabs in the UI
- **Content types** — Articles, Videos, PDFs
- **Categories** — Getting Started, Filing a Grievance, Your Rights, Triage & Processing, Escalation, Reporting Duties, FAQ
- **Role targeting** — Citizen, Facilitator, Village Secretary (multi-select)
- **Workflow states** — Draft, Published, Archived
- **File attachments** — PDF, JPG, PNG uploads
- **AJAX DataTable** — Server-side pagination, sorting, filtering
- **Rich form UI** — Language pills, segmented controls, role cards, file dropzone, live preview

## URLs

| URL | View | Name |
|---|---|---|
| `/learning-materials/` | List + KPIs | `home` |
| `/learning-materials/data/` | AJAX DataTable data | `data` |
| `/learning-materials/create/` | Create form | `create` |
| `/learning-materials/<pk>/` | Redirect to update | `detail` |
| `/learning-materials/<pk>/update/` | Update form | `update` |
| `/learning-materials/<pk>/delete/` | Delete confirmation | `delete` |

Use with `{% url 'grm_learning_materials:home' %}` (or your configured `URL_NAMESPACE`).

## Permissions

By default, any authenticated user can access learning materials. Set `PERMISSION_CALLBACK` to restrict access:

```python
# myapp/utils.py
def is_admin(request):
    return request.user.is_staff
```

The callback receives the `request` object and must return `True` (grant access) or `False` (return 403).

## Running Tests

```bash
cd src
python manage.py test grm_learning_materials --verbosity=2
```

## Requirements

- Django >= 4.2
- Python >= 3.10

## Templates

Templates extend the configured `BASE_TEMPLATE`. The base template must include these Django blocks:

- `{% block content %}` — main content area
- `{% block extracss %}` — extra stylesheets
- `{% block javascript %}` — extra scripts (must include `{{ block.super }}` for jQuery/DataTables)

The list view uses **jQuery** and **DataTables** — your base template should include both.

## Migration Safety

The model uses `db_table = "dashboard_learningmaterial"` for zero-downtime migration from the original monolith. If this is a fresh install, the table will be created automatically. If migrating from the GRM-Web-App-Benin monolith, existing data in `dashboard_learningmaterial` is preserved — the package's migration uses `SeparateDatabaseAndState` and never touches the actual database table.
