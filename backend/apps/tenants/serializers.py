from rest_framework import serializers

from .models import Tenant, TenantSetting


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "legal_name", "country_code", "status", "suspended_reason", "is_demo",
                  "owner_user_id", "metadata", "created_at", "updated_at", "version_number"]
        read_only_fields = ["id", "status", "suspended_reason", "is_demo", "owner_user_id", "created_at", "updated_at",
                            "version_number"]


class TenantSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantSetting
        fields = ["id", "key", "value", "description", "updated_at", "version_number"]
        read_only_fields = ["id", "updated_at", "version_number"]


class PilotTenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=63)
    owner_user_id = serializers.UUIDField(required=False, allow_null=True)
    plan_code = serializers.ChoiceField(choices=["DEMO", "STARTER", "GROWTH", "GROWTH_ENTREPRISE"], default="STARTER")


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
