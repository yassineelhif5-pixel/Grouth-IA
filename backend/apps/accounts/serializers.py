from rest_framework import serializers

from .models import UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["id", "email", "full_name", "avatar_url", "locale", "theme", "timezone", "platform_role_code",
                  "status", "mfa_enabled", "last_login_at", "version_number"]
        read_only_fields = ["id", "email", "platform_role_code", "status", "mfa_enabled", "last_login_at", "version_number"]


class DemoSignupSerializer(serializers.Serializer):
    tenant_name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=63)
    full_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
