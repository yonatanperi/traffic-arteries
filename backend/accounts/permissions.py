from rest_framework.permissions import BasePermission

ROLE_RANK = {"user": 0, "editor": 1, "admin": 2}


def effective_role(user):
    """Collapses is_superuser + the role field into one of user/editor/admin.

    Django's is_superuser flag (set via createsuperuser) always counts as
    admin regardless of the role field — admin is a Django-admin concept,
    not something granted through the app's own approval flow.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser or getattr(user, "role", None) == "admin":
        return "admin"
    return getattr(user, "role", "user")


class IsEditorOrAdmin(BasePermission):
    message = "אין לך הרשאה לבצע פעולה זו."

    def has_permission(self, request, view):
        return ROLE_RANK.get(effective_role(request.user), -1) >= ROLE_RANK["editor"]


class IsAdmin(BasePermission):
    message = "פעולה זו מותרת למנהלי מערכת בלבד."

    def has_permission(self, request, view):
        return effective_role(request.user) == "admin"
