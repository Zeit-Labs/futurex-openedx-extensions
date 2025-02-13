"""Tenant management helpers"""
from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlparse

from django.conf import settings
from django.db.models import Count, OuterRef, Subquery
from django.db.models.query import QuerySet
from eox_tenant.models import Route, TenantConfig

from futurex_openedx_extensions.helpers import constants as cs
from futurex_openedx_extensions.helpers.caching import cache_dict
from futurex_openedx_extensions.helpers.exceptions import FXExceptionCodes
from futurex_openedx_extensions.helpers.extractors import get_first_not_empty_item


def get_excluded_tenant_ids() -> Dict[int, List[int]]:
    """
    Get dictionary of tenant IDs excluded for bad configuration, along with the reasons of exclusion

    :return: List of tenant IDs to exclude
    :rtype: Dict[int, List[int]]
    """
    def check_bad_config(tenant: TenantConfig) -> List[int]:
        """Check if the tenant has a bad config"""
        reasons = []
        if tenant.routes_count == 0:
            reasons.append(FXExceptionCodes.TENANT_HAS_NO_SITE.value)
        if tenant.routes_count > 1:
            reasons.append(FXExceptionCodes.TENANT_HAS_MORE_THAN_ONE_SITE.value)

        if not tenant.lms_configs.get('LMS_BASE'):
            reasons.append(FXExceptionCodes.TENANT_HAS_NO_LMS_BASE.value)
        if not reasons and tenant.lms_configs['LMS_BASE'] != tenant.route_domain:
            reasons.append(FXExceptionCodes.TENANT_LMS_BASE_SITE_MISMATCH.value)

        if not tenant.lms_configs.get('IS_FX_DASHBOARD_ENABLED', True):
            reasons.append(FXExceptionCodes.TENANT_DASHBOARD_NOT_ENABLED.value)

        course_org_filter = tenant.lms_configs.get('course_org_filter')
        if not course_org_filter or (
            isinstance(course_org_filter, list) and not all(isinstance(org, str) for org in course_org_filter)
        ) or (
            isinstance(course_org_filter, str) and not course_org_filter.strip()
        ):
            reasons.append(FXExceptionCodes.TENANT_COURSE_ORG_FILTER_NOT_VALID.value)

        return reasons

    tenants = TenantConfig.objects.annotate(
        routes_count=Count('route'),
    ).annotate(
        route_domain=Subquery(Route.objects.filter(config_id=OuterRef('pk')).values('domain')[:1]),
    )
    return {tenant.id: check_bad_config(tenant) for tenant in tenants if check_bad_config(tenant)}


def get_all_tenants() -> QuerySet:
    """
    Get all tenants in the system that are exposed in the route table, and with a valid config

    Note: a tenant is a TenantConfig object

    :return: QuerySet of all tenants
    :rtype: QuerySet
    """
    return TenantConfig.objects.exclude(id__in=get_excluded_tenant_ids())


def fix_lms_base(domain_name: str) -> str:
    """Fix the LMS base URL"""
    if not domain_name:
        return ''

    lms_root_parts = urlparse(settings.LMS_ROOT_URL)

    if not (domain_name.startswith('http://') or domain_name.startswith('https://')):
        domain_name = f'{lms_root_parts.scheme}://{domain_name}'
    domain_name_parts = urlparse(domain_name)

    port = f':{domain_name_parts.port}' if domain_name_parts.port else ''

    if not port:
        port = f':{lms_root_parts.port}' if lms_root_parts.port else ''

    return f'{domain_name_parts.scheme}://{domain_name_parts.hostname}{port}'


@cache_dict(timeout='FX_CACHE_TIMEOUT_TENANTS_INFO', key_generator_or_name=cs.CACHE_NAME_ALL_TENANTS_INFO)
def get_all_tenants_info() -> Dict[str, str | dict | List[int]]:
    """
    Get all tenants in the system that are exposed in the route table, and with a valid config

    Note: a tenant is a TenantConfig object

    :return: Dictionary of tenant IDs and Sites
    :rtype: Dict[str, Any]
    """
    tenant_ids = list(get_all_tenants().values_list('id', flat=True))
    info = TenantConfig.objects.filter(id__in=tenant_ids).values('id', 'route__domain', 'lms_configs')
    return {
        'tenant_ids': tenant_ids,
        'sites': {
            tenant['id']: tenant['route__domain'] for tenant in info
        },
        'info': {
            tenant['id']: {
                'lms_root_url': get_first_not_empty_item([
                    (tenant['lms_configs'].get('LMS_ROOT_URL') or '').strip(),
                    fix_lms_base((tenant['lms_configs'].get('LMS_BASE') or '').strip()),
                ], default=''),
                'studio_root_url': settings.CMS_ROOT_URL,
                'platform_name': get_first_not_empty_item([
                    (tenant['lms_configs'].get('PLATFORM_NAME') or '').strip(),
                    (tenant['lms_configs'].get('platform_name') or '').strip(),
                ], default=''),
                'logo_image_url': (tenant['lms_configs'].get('logo_image_url') or '').strip(),
            } for tenant in info
        },
        'tenant_by_site': {
            tenant['route__domain']: tenant['id'] for tenant in info
        },
    }


def get_all_tenant_ids() -> List[int]:
    """
    Get list of IDs of all tenants in the system

    :return: List of all tenant IDs
    :rtype: List[int]
    """
    return get_all_tenants_info()['tenant_ids']


def get_tenants_info(tenant_ids: List[int]) -> Dict[int, Any]:
    """
    Get the information for the given tenant IDs

    :param tenant_ids: List of tenant IDs to get the information for
    :type tenant_ids: List[int]
    :return: Dictionary of tenant information
    :rtype: Dict[str, Any]
    """
    all_tenants_info = get_all_tenants_info()
    return {t_id: all_tenants_info['info'].get(t_id) for t_id in tenant_ids}


def get_tenant_site(tenant_id: int) -> str:
    """
    Get the site for a tenant

    :param tenant_id: The tenant ID
    :type tenant_id: int
    :return: The site for the tenant
    :rtype: str
    """
    return get_all_tenants_info()['sites'].get(tenant_id)


@cache_dict(timeout='FX_CACHE_TIMEOUT_TENANTS_INFO', key_generator_or_name=cs.CACHE_NAME_ALL_COURSE_ORG_FILTER_LIST)
def get_all_course_org_filter_list() -> Dict[int, List[str]]:
    """
    Get all course org filters for all tenants.

    :return: Dictionary of tenant IDs and their course org filters
    :rtype: Dict[int, List[str]]
    """
    tenant_configs = get_all_tenants().values_list('id', 'lms_configs')

    result = {}
    for t_id, config in tenant_configs:
        course_org_filter = config.get('course_org_filter', [])
        if isinstance(course_org_filter, str):
            course_org_filter = [course_org_filter]
        result[t_id] = sorted(list({org.strip().lower() for org in course_org_filter}))

    return result


def get_course_org_filter_list(tenant_ids: List[int], ignore_invalid_tenant_ids: bool = False) -> Dict[str, Any]:
    """
    Get the filters to use for course orgs.

    returns two information:
    {
        'course_org_filter_list': List of course org filters,
        'duplicates': Dictionary of tenant IDs and their duplicates,
        'invalid': List of invalid tenant IDs,
    }

    duplicates looks like this:
    {
        1: [2, 3],
        2: [1, 3],
        3: [1, 2],
        4: [],
        5: [],
    }

    :param tenant_ids: List of tenant IDs to get the filters for
    :type tenant_ids: List[int]
    :param ignore_invalid_tenant_ids: If True, don't raise an error if a tenant ID is invalid. Otherwise, raise an error
        with the list of invalid tenant IDs.
    :type ignore_invalid_tenant_ids: bool
    :return: Dictionary of course org filters and duplicates
    :rtype: Dict[str, List | Dict[str, List[int]]]
    """
    tenant_configs = get_all_course_org_filter_list()

    tenant_ids = tenant_ids or []
    orgs_list = []
    duplicate_trace = {}
    duplicates = {}
    invalid = []
    for tenant_id in tenant_ids:
        course_org_filter = tenant_configs.get(tenant_id, [])
        if not course_org_filter:
            invalid.append(tenant_id)
            continue

        for org in course_org_filter:
            if org not in orgs_list:
                orgs_list.append(org)
                duplicate_trace[org] = [tenant_id]
            else:
                for other_id in duplicate_trace[org]:
                    if other_id not in duplicates:
                        duplicates[other_id] = [tenant_id]
                    else:
                        duplicates[other_id].append(tenant_id)
                duplicates[tenant_id] = list(duplicate_trace[org])
                duplicate_trace[org].append(tenant_id)

    if invalid and not ignore_invalid_tenant_ids:
        raise ValueError(f'Invalid tenant IDs: {invalid}')

    return {
        'course_org_filter_list': orgs_list,
        'duplicates': duplicates,
        'invalid': invalid,
    }


@cache_dict(timeout='FX_CACHE_TIMEOUT_TENANTS_INFO', key_generator_or_name=cs.CACHE_NAME_ORG_TO_TENANT_MAP)
def get_org_to_tenant_map() -> Dict[str, List[int]]:
    """
    Get the map of orgs to tenant IDs

    {
        'org1': [1, 2, 3],
        'org2': [2, 3, 4],
        ....
    }

    :return: Dictionary of orgs and their tenant IDs
    :rtype: Dict[str, List[int]]
    """
    tenant_configs = get_all_course_org_filter_list()
    result: Dict[str, Any] = {}
    for t_id, course_org_filter in tenant_configs.items():
        for org in course_org_filter:
            if org not in result:
                result[org] = {t_id}
            else:
                result[org].add(t_id)

    for org, tenant_ids in result.items():
        result[org] = list(tenant_ids)

    return result


def get_tenants_by_org(org: str) -> List[int]:
    """
    Get the tenants that have <org> in their course org filter

    :param org: The org to check
    :type org: str
    :return: List of tenant IDs
    :rtype: List[int]
    """
    return get_org_to_tenant_map().get(org.lower(), [])


def get_tenants_sites(tenant_ids: List[int]) -> List[str]:
    """
    Get the sites for the given tenant IDs

    :param tenant_ids: List of tenant IDs
    :type tenant_ids: List[int]
    :return: List of sites
    :rtype: List[str]
    """
    if not tenant_ids:
        return []

    tenant_sites = []
    for tenant_id in tenant_ids:
        if site := get_tenant_site(tenant_id):
            tenant_sites.append(site)
    return tenant_sites
