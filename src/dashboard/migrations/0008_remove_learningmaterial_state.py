from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0007_learning_material_file"),
    ]

    state_operations = [
        migrations.DeleteModel(
            name="LearningMaterial",
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=state_operations,
            database_operations=[],
        ),
    ]
