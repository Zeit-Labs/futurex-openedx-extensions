"""Tests for tenants helpers."""
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from eox_tenant.models import Route, TenantConfig

from futurex_openedx_extensions.helpers import constants as cs
from futurex_openedx_extensions.helpers import tenants
from futurex_openedx_extensions.helpers.exceptions import FXExceptionCodes


@pytest.fixture
def expected_exclusion():
    """Expected exclusion data."""
    return {
        4: [FXExceptionCodes.TENANT_HAS_NO_LMS_BASE.value],
        5: [FXExceptionCodes.TENANT_COURSE_ORG_FILTER_NOT_VALID.value],
        6: [FXExceptionCodes.TENANT_HAS_NO_SITE.value],
    }


@pytest.mark.django_db
def test_get_excluded_tenant_ids(
    base_data, expected_exclusion,
):  # pylint: disable=unused-argument, redefined-outer-name
    """Verify get_excluded_tenant_ids function."""
    result = tenants.get_excluded_tenant_ids()
    assert result == expected_exclusion


@pytest.mark.django_db
def test_get_excluded_tenant_ids_more_than_one_tenant(
    base_data, expected_exclusion,
):  # pylint: disable=unused-argument, redefined-outer-name
    """Verify get_excluded_tenant_ids function when there is more than one tenant."""
    Route.objects.create(config_id=1, domain='s1-new.sample.com')

    result = tenants.get_excluded_tenant_ids()
    expected_exclusion.update({1: [FXExceptionCodes.TENANT_HAS_MORE_THAN_ONE_SITE.value]})
    assert result == expected_exclusion


@pytest.mark.django_db
def test_get_excluded_tenant_ids_dashboard_disabled(
    base_data, expected_exclusion,
):  # pylint: disable=unused-argument, redefined-outer-name
    """Verify get_excluded_tenant_ids function when the dashboard is disabled."""
    assert tenants.get_excluded_tenant_ids() == expected_exclusion
    tenant1 = TenantConfig.objects.get(id=1)

    tenant1.lms_configs['IS_FX_DASHBOARD_ENABLED'] = False
    tenant1.save()
    expected_exclusion.update({1: [FXExceptionCodes.TENANT_DASHBOARD_NOT_ENABLED.value]})
    assert tenants.get_excluded_tenant_ids() == expected_exclusion

    tenant1.lms_configs.pop('IS_FX_DASHBOARD_ENABLED')
    tenant1.save()
    expected_exclusion.pop(1)
    assert tenants.get_excluded_tenant_ids() == expected_exclusion


@pytest.mark.django_db
def test_get_excluded_tenant_ids_lms_base_mismatch(
    base_data, expected_exclusion,
):  # pylint: disable=unused-argument, redefined-outer-name
    """Verify get_excluded_tenant_ids function when the LMS base is not the same as the related domain."""
    tenant1 = TenantConfig.objects.get(id=1)
    tenant1.lms_configs['LMS_BASE'] = 's1-different.sample.com'
    tenant1.save()

    result = tenants.get_excluded_tenant_ids()
    expected_exclusion.update({1: [FXExceptionCodes.TENANT_LMS_BASE_SITE_MISMATCH.value]})
    assert result == expected_exclusion


@pytest.mark.django_db
def test_get_all_tenants(base_data):  # pylint: disable=unused-argument
    """Verify get_all_tenants function."""
    result = tenants.get_all_tenants()
    assert TenantConfig.objects.count() == 8
    assert result.count() == 5
    assert result.exclude(id__in=[4, 5, 6]).count() == result.count()
    assert result.exclude(id__in=[4, 5, 6]).count() == TenantConfig.objects.exclude(id__in=[4, 5, 6]).count()


@pytest.mark.django_db
def test_get_all_tenant_ids(base_data):  # pylint: disable=unused-argument
    """Verify get_all_tenant_ids function."""
    result = tenants.get_all_tenant_ids()
    assert result == [1, 2, 3, 7, 8]


@pytest.mark.django_db
def test_get_all_course_org_filter_list(base_data):  # pylint: disable=unused-argument
    """Verify get_all_course_org_filter_list function."""
    result = tenants.get_all_course_org_filter_list()
    assert result == {
        1: ['org1', 'org2'],
        2: ['org3', 'org8'],
        3: ['org4', 'org5'],
        7: ['org3'],
        8: ['org8'],
    }


@pytest.mark.django_db
def test_get_all_course_org_filter_list_is_being_cached(cache_testing):  # pylint: disable=unused-argument
    """Verify that get_all_course_org_filter_list is being cached."""
    assert cache.get(cs.CACHE_NAME_ALL_COURSE_ORG_FILTER_LIST) is None
    result = tenants.get_all_course_org_filter_list()
    assert cache.get(cs.CACHE_NAME_ALL_COURSE_ORG_FILTER_LIST)['data'] == result
    cache.set(cs.CACHE_NAME_ALL_COURSE_ORG_FILTER_LIST, None)


@pytest.mark.django_db
@pytest.mark.parametrize('tenant_ids, expected', [
    ([1, 2, 3, 7], {
        'course_org_filter_list': ['org1', 'org2', 'org3', 'org8', 'org4', 'org5'],
        'duplicates': {
            2: [7],
            7: [2],
        },
        'invalid': [],
    }),
    ([2, 3], {
        'course_org_filter_list': ['org3', 'org8', 'org4', 'org5'],
        'duplicates': {},
        'invalid': [],
    }),
    ([2, 3, 4], {
        'course_org_filter_list': ['org3', 'org8', 'org4', 'org5'],
        'duplicates': {},
        'invalid': [4],
    }),
    ([2, 3, 7, 8], {
        'course_org_filter_list': ['org3', 'org8', 'org4', 'org5'],
        'duplicates': {
            2: [7, 8],
            7: [2],
            8: [2],
        },
        'invalid': [],
    }),
    ([], {
        'course_org_filter_list': [],
        'duplicates': {},
        'invalid': [],
    }),
    (None, {
        'course_org_filter_list': [],
        'duplicates': {},
        'invalid': [],
    }),
])
def test_get_course_org_filter_list(base_data, tenant_ids, expected):  # pylint: disable=unused-argument
    """Verify get_course_org_filter_list function."""
    result = tenants.get_course_org_filter_list(tenant_ids, ignore_invalid_tenant_ids=True)
    assert result == expected
    if expected['invalid']:
        with pytest.raises(ValueError) as exc_info:
            tenants.get_course_org_filter_list(tenant_ids)
        assert str(exc_info.value) == f'Invalid tenant IDs: {expected["invalid"]}'


@pytest.mark.django_db
def test_get_all_tenants_info(base_data):  # pylint: disable=unused-argument
    """Verify get_all_tenants_info function."""
    result = tenants.get_all_tenants_info()
    assert result['tenant_ids'] == [1, 2, 3, 7, 8]
    assert result['sites'] == {
        1: 's1.sample.com',
        2: 's2.sample.com',
        3: 's3.sample.com',
        7: 's7.sample.com',
        8: 's8.sample.com',
    }


@pytest.mark.django_db
@pytest.mark.parametrize('config_key, info_key, test_value, expected_result', [
    ('LMS_BASE', 'lms_root_url', 'lms.example.com', 'https://lms.example.com'),
    ('LMS_ROOT_URL', 'lms_root_url', 'https://lms.example.com', 'https://lms.example.com'),
    ('PLATFORM_NAME', 'platform_name', 'Test Platform', 'Test Platform'),
    ('platform_name', 'platform_name', 'Test Platform', 'Test Platform'),
    ('logo_image_url', 'logo_image_url', 'https://img.example.com/dummy.jpg', 'https://img.example.com/dummy.jpg'),
])
@patch('futurex_openedx_extensions.helpers.tenants.get_excluded_tenant_ids', return_value=[])
def test_get_all_tenants_info_configs(
    base_data, config_key, info_key, test_value, expected_result
):  # pylint: disable=unused-argument
    """Verify get_all_tenants_info function returning the correct logo_url."""
    tenant_config = TenantConfig.objects.create()
    assert tenant_config.lms_configs.get(config_key) is None

    result = tenants.get_all_tenants_info()
    assert result['info'][tenant_config.id][info_key] == ''

    tenant_config.lms_configs[config_key] = test_value
    tenant_config.save()
    result = tenants.get_all_tenants_info()
    assert result['info'][tenant_config.id][info_key] == expected_result


@pytest.mark.django_db
@pytest.mark.parametrize('config_keys, data_prefix, call_index', [
    (['LMS_ROOT_URL', 'LMS_BASE'], 'https://', 0),
    (['PLATFORM_NAME', 'platform_name'], '', 1),
])
@patch(
    'futurex_openedx_extensions.helpers.tenants.get_excluded_tenant_ids',
    return_value=[1, 2, 3, 4, 5, 6, 7, 8]
)
@patch('futurex_openedx_extensions.helpers.tenants.get_first_not_empty_item')
@patch('futurex_openedx_extensions.helpers.tenants.fix_lms_base')
def test_get_all_tenants_info_config_priorities(
    mock_fix_lms_base, mock_get_first_not_empty_item, base_data, config_keys, data_prefix, call_index
):  # pylint: disable=unused-argument, too-many-arguments
    """Verify get_all_tenants_info is respecting the priority of the config keys."""
    assert not tenants.get_all_tenants_info()['tenant_ids']
    tenant_config = TenantConfig.objects.create()
    for config_key in config_keys:
        tenant_config.lms_configs[config_key] = f'{data_prefix}{config_key}_value'
    tenant_config.save()

    mock_fix_lms_base.side_effect = lambda x: x

    _ = tenants.get_all_tenants_info()
    assert mock_get_first_not_empty_item.call_args_list[call_index][0][0] == [
        f'{data_prefix}{config_key}_value' for config_key in config_keys
    ]


@pytest.mark.django_db
def test_get_all_tenants_info_is_being_cached(cache_testing):  # pylint: disable=unused-argument
    """Verify that get_all_tenants_info is being cached."""
    assert cache.get(cs.CACHE_NAME_ALL_TENANTS_INFO) is None
    result = tenants.get_all_tenants_info()
    assert cache.get(cs.CACHE_NAME_ALL_TENANTS_INFO)['data'] == result
    cache.set(cs.CACHE_NAME_ALL_TENANTS_INFO, None)


@pytest.mark.django_db
@pytest.mark.parametrize('tenant_id, expected', [
    (1, 's1.sample.com'),
    (2, 's2.sample.com'),
    (3, 's3.sample.com'),
    (4, None),
    (5, None),
    (6, None),
    (7, 's7.sample.com'),
    (8, 's8.sample.com'),
])
def test_get_tenant_site(base_data, tenant_id, expected):  # pylint: disable=unused-argument
    """Verify get_tenant_site function."""
    assert expected == tenants.get_tenant_site(tenant_id)


@pytest.mark.django_db
@pytest.mark.parametrize('org, expected', [
    ('org1', [1]),
    ('org2', [1]),
    ('org3', [2, 7]),
    ('org4', [3]),
    ('org5', [3]),
    ('org8', [2, 8]),
])
def test_get_tenants_by_org(base_data, org, expected):  # pylint: disable=unused-argument
    """Verify get_tenants_by_org function."""
    assert len(expected) == len(tenants.get_tenants_by_org(org))
    assert set(expected) == set(tenants.get_tenants_by_org(org))


@pytest.mark.django_db
@pytest.mark.parametrize('tenant_ids, expected', [
    ([1], ['s1.sample.com']),
    ([2, 3], ['s2.sample.com', 's3.sample.com']),
    ([2, 3, 4], ['s2.sample.com', 's3.sample.com']),
    ([2, 3, 7, 8], ['s2.sample.com', 's3.sample.com', 's7.sample.com', 's8.sample.com']),
])
def test_get_tenants_sites(base_data, tenant_ids, expected):  # pylint: disable=unused-argument
    """Verify get_tenants_sites function."""
    assert expected == tenants.get_tenants_sites(tenant_ids)


@pytest.mark.django_db
@pytest.mark.parametrize('tenant_ids', [
    [],
    None,
    [99],
])
def test_get_tenants_sites_bad_tenants(base_data, tenant_ids):  # pylint: disable=unused-argument
    """Verify get_tenants_sites function."""
    result = tenants.get_tenants_sites(tenant_ids)
    assert result is not None and len(result) == 0


@pytest.mark.parametrize('lms_root_scheme, domain_name, expected_result', [
    ('http', 'example.com', 'http://example.com'),
    ('http', 'http://example.com', 'http://example.com'),
    ('http', 'https://example.com', 'https://example.com'),
    ('https', 'example.com', 'https://example.com'),
    ('https', 'http://example.com', 'http://example.com'),
    ('https', 'https://example.com', 'https://example.com'),
])
def test_fix_lms_base_scheme(lms_root_scheme, domain_name, expected_result):
    """Verify that fix_lms_base sets the correct scheme for the result."""
    with override_settings(LMS_ROOT_URL=f'{lms_root_scheme}://lms.example.com'):
        assert expected_result == tenants.fix_lms_base(domain_name)


@pytest.mark.parametrize('lms_root_port, domain_name, expected_result', [
    (None, 'example.com', 'https://example.com'),
    (None, 'example.com:8080', 'https://example.com:8080'),
    (3030, 'example.com', 'https://example.com:3030'),
    (3030, 'example.com:8080', 'https://example.com:8080'),
])
def test_fix_lms_base_port(lms_root_port, domain_name, expected_result):
    """Verify that fix_lms_base sets the correct port for the result."""
    port = f':{lms_root_port}' if lms_root_port else ''
    with override_settings(LMS_ROOT_URL=f'https://lms.example.com{port}'):
        assert expected_result == tenants.fix_lms_base(domain_name)


@pytest.mark.parametrize('domain_name', [
    None, '',
])
def test_fix_lms_base_empty_domain_name(domain_name):
    """Verify that fix_lms_base sets the correct port for the result."""
    assert tenants.fix_lms_base(domain_name) == ''
