from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from portal.permissions import is_portal_admin


class PortalAdminLoginForm(AdminAuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not is_portal_admin(user):
            raise self.get_invalid_login_error()


class PortalAdminSite(AdminSite):
    index_template = "admin/portal/finance_index.html"
    login_form = PortalAdminLoginForm

    def has_permission(self, request):
        return is_portal_admin(request.user)
