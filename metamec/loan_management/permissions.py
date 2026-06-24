from rest_framework.permissions import BasePermission


class IsAdminUserRole(BasePermission):
    message = "Admin permission required."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and (
                getattr(user, "role", None) == "admin"
                or getattr(user, "is_staff", False)
                or getattr(user, "is_superuser", False)
            )
        )