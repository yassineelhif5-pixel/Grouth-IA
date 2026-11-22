"""Unmanaged mappings for Tenant Marketing Center tables."""
import uuid as _uuid

from django.db import models
from django.utils import timezone as _tz


class MarketingProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    tenant_id = models.UUIDField()
    company_name = models.TextField(null=True, blank=True)
    industry = models.TextField(null=True, blank=True)
    offer = models.TextField(null=True, blank=True)
    target_audience = models.TextField(null=True, blank=True)
    differentiators = models.TextField(null=True, blank=True)
    objectives = models.JSONField(default=list)
    preferred_language = models.TextField(default="fr")
    website_url = models.TextField(null=True, blank=True)
    timezone = models.TextField(default="Europe/Paris")
    publishing_policy = models.TextField(default="manual_approval")
    created_at = models.DateTimeField(default=_tz.now)
    updated_at = models.DateTimeField(default=_tz.now)
    created_by = models.UUIDField(null=True, blank=True)
    updated_by = models.UUIDField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    version_number = models.IntegerField(default=1)
    correlation_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "tenant_marketing_profiles"


class MarketingConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    tenant_id = models.UUIDField()
    user_id = models.UUIDField()
    title = models.TextField()
    status = models.TextField(default="active")
    created_at = models.DateTimeField(default=_tz.now)
    updated_at = models.DateTimeField(default=_tz.now)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "tenant_marketing_conversations"


class MarketingStrategy(models.Model):
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    tenant_id = models.UUIDField()
    conversation_id = models.UUIDField()
    title = models.TextField()
    summary = models.TextField()
    strategy = models.JSONField(default=dict)
    status = models.TextField(default="proposed")
    approved_by = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=_tz.now)
    updated_at = models.DateTimeField(default=_tz.now)
    deleted_at = models.DateTimeField(null=True, blank=True)
    version_number = models.IntegerField(default=1)
    correlation_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "tenant_marketing_strategies"
