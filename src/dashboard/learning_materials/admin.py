from django.contrib import admin

from dashboard.models import LearningMaterial


@admin.register(LearningMaterial)
class LearningMaterialAdmin(admin.ModelAdmin):
    list_display = ('title_fr', 'category', 'content_type', 'status', 'updated_date')
    list_filter = ('category', 'content_type', 'status')
    search_fields = ('title_fr', 'title_en', 'summary_fr', 'summary_en')
