from django.contrib import admin

from .models import GenerationTask, QuotaTransaction, UserQuota

admin.site.register(UserQuota)
admin.site.register(QuotaTransaction)
admin.site.register(GenerationTask)
