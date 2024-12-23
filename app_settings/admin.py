from django.contrib import admin
from . import models

# Register your models here.
admin.site.register(models.GLAccount)
admin.site.register(models.GLEntryState)
admin.site.register(models.ProductCategoryGLEntry)