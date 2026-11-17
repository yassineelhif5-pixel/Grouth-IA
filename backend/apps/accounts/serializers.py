import re

from rest_framework import serializers

from .models import UserProfile

USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,29}")


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["id", "email", "username", "full_name", "avatar_url", "locale", "theme", "timezone", "platform_role_code",
                  "status", "mfa_enabled", "last_login_at", "version_number"]
        read_only_fields = ["id", "email", "platform_role_code", "status", "mfa_enabled", "last_login_at", "version_number"]

    def validate_username(self, value):
        if value in (None, ""):
            return None
        v = value.strip().lower()
        if not USERNAME_RE.fullmatch(v):
            raise serializers.ValidationError("3 à 30 caractères : lettres minuscules, chiffres, « . », « _ » ou « - », sans espace ni @.")
        return v


class DemoSignupSerializer(serializers.Serializer):
    tenant_name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=63)
    full_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
