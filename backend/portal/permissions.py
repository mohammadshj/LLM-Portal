from rest_framework.permissions import BasePermission


def is_portal_admin(user):
    return user.is_active and user.is_staff and user.is_superuser


class IsPortalAdmin(BasePermission):
    def has_permission(self, request, view):
        return is_portal_admin(request.user)
