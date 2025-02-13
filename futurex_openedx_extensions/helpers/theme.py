""""Theme helpers"""
from typing import Any, Optional

from common.djangoapps.student.models import CourseAccessRole
from django.conf import settings

from futurex_openedx_extensions.helpers.roles import get_accessible_tenant_ids
from futurex_openedx_extensions.helpers.tenants import get_all_tenants_info
from futurex_openedx_extensions.helpers.users import is_system_staff_user


def get_fx_dashboard_url(request: Any) -> Optional[str]:
    """
    Get Fx Dashboard URL

    :param request: Current django request.
    :type request: Request
    :return: Fx Dashboard URL
    :rtype: str
    """
    if (
        getattr(request, 'site', None) is None or
        not getattr(request.site, 'domain', None) or
        not getattr(settings, 'NELC_DASHBOARD_BASE', None)
    ):
        return None

    if (
        is_system_staff_user(request.user) or
        CourseAccessRole.objects.filter(user_id=request.user.id).exists()
    ):
        lang = 'en' if request.LANGUAGE_CODE == 'en' else 'ar'
        tenant_id = get_all_tenants_info()['tenant_by_site'].get(request.site.domain)
        if tenant_id and tenant_id in get_accessible_tenant_ids(request.user):
            return f'{request.scheme}://{settings.NELC_DASHBOARD_BASE}/{lang}/{tenant_id}'

    return None
