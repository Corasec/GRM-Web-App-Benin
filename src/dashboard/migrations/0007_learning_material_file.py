import grm_learning_materials.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0006_learningmaterial"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningmaterial",
            name="file",
            field=models.FileField(
                blank=True,
                help_text="Upload a PDF, JPG, or PNG file",
                null=True,
                upload_to=grm_learning_materials.models.learning_material_upload_path,
                verbose_name="File",
            ),
        ),
    ]
