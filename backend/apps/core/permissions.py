from rest_framework.permissions import BasePermission


class IsVerifiedUser(BasePermission):
    message = "E-mail verification required"

    def has_permission(self, request, view):
        return bool(request.user and getattr(request.user, "email_verified", False))
