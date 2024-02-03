from django.contrib import admin
from .models import CustomUser, VendorProfile, TempUser

# Register your models here.

admin.site.register(CustomUser)
admin.site.register(VendorProfile)
admin.site.register(TempUser)