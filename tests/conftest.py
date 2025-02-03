"""PyTest fixtures for tests."""
import datetime
from unittest.mock import patch

import pytest
from cms.djangoapps.course_creators.models import CourseCreator
from common.djangoapps.student.models import CourseAccessRole, CourseEnrollment, UserSignupSource
from custom_reg_form.models import ExtraInfo
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from eox_tenant.models import Route, TenantConfig
from lms.djangoapps.certificates.models import GeneratedCertificate
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from organizations.models import Organization

from futurex_openedx_extensions.helpers import constants as cs
from tests.base_test_data import _base_data
from tests.fixture_helpers import get_tenants_of_org, get_user1_fx_permission_info


@pytest.fixture
def empty_course_creator():
    """Create a CourseCreator record for user 33 with no organizations."""
    CourseCreator.objects.bulk_create([CourseCreator(
        user_id=33, all_organizations=False, state=CourseCreator.GRANTED,
    )])
    for org_index in range(1, 5):
        org_name = f'org{org_index}'
        Organization.objects.create(short_name=org_name)
    return CourseCreator.objects.get(user_id=33)


@pytest.fixture
def cache_testing():
    """Fixture for temporary enabling cache for testing."""
    with override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}):
        yield
        cache.clear()  # Clear the cache after each test


@pytest.fixture
def fx_permission_info():
    """Fixture for permission information."""
    return {
        'is_system_staff_user': True,
        'user': get_user_model().objects.get(id=1),
        'view_allowed_full_access_orgs': ['org1', 'org2'],
        'view_allowed_course_access_orgs': [],
        'view_allowed_any_access_orgs': ['org1', 'org2'],
        'view_allowed_tenant_ids_full_access': [1],
        'view_allowed_tenant_ids_any_access': [1],
        'view_allowed_tenant_ids_partial_access': [0],
    }


@pytest.fixture
def support_user():
    """Fixture for support user."""
    user_id = 55
    assert CourseAccessRole.objects.filter(user_id=user_id).count() == 0, 'Bad test data'
    user = get_user_model().objects.get(id=user_id)
    assert not user.is_staff, 'staff users not allowed in this test'
    assert not user.is_superuser, 'staff users not allowed in this test'
    CourseAccessRole.objects.create(user_id=user_id, role=cs.COURSE_SUPPORT_ROLE_GLOBAL)
    return user


@pytest.fixture
def user1_fx_permission_info():
    """Fixture for permission information for user1."""
    return get_user1_fx_permission_info()


@pytest.fixture
def roles_authorize_caller():
    """Fixture for temporary enabling cache for testing."""
    with patch('futurex_openedx_extensions.helpers.roles._verify_can_add_course_access_roles'):
        with patch('futurex_openedx_extensions.helpers.roles._verify_can_add_org_course_creator'):
            with patch('futurex_openedx_extensions.helpers.roles._verify_can_delete_course_access_roles'):
                with patch('futurex_openedx_extensions.helpers.roles._verify_can_delete_course_access_roles_partial'):
                    yield


@pytest.fixture
def view_data():
    """Fixture for a default view data."""
    return {
        'query_params': {},
        'kwargs': {},
        'path': '/',
        'url': 'http://example.com',
        'page_size': 2,
        'start_page': 1,
        'end_page': None,
    }


@pytest.fixture(scope='session')
def base_data(django_db_setup, django_db_blocker):  # pylint: disable=unused-argument, too-many-statements
    """Create base data for tests."""
    def _get_course_id(org, course_index):
        """Get course ID."""
        return f'course-v1:{org}+{course_index}+{course_index}'

    def _create_users():
        """Create users."""
        user = get_user_model()
        for i in range(1, _base_data['users_count'] + 1):
            user.objects.create(
                id=i,
                username=f'user{i}',
                email=f'user{i}@example.com',
            )
        for user_id in _base_data['super_users']:
            user.objects.filter(id=user_id).update(is_superuser=True)
        for user_id in _base_data['staff_users']:
            user.objects.filter(id=user_id).update(is_staff=True)
        for user_id in _base_data['inactive_users']:
            user.objects.filter(id=user_id).update(is_active=False)
        for user_id, extra_info in _base_data['user_extra_info'].items():
            ExtraInfo.objects.create(
                user_id=user_id,
                national_id=extra_info.get('national_id'),
            )

    def _create_tenants():
        """Create tenants."""
        for tenant_id, tenant_config in _base_data['tenant_config'].items():
            TenantConfig.objects.create(
                id=tenant_id,
                lms_configs=tenant_config['lms_configs'],
            )

    def _create_routes():
        """Create routes."""
        for route_id in _base_data['routes']:
            Route.objects.create(
                id=route_id,
                domain=_base_data['routes'][route_id]['domain'],
                config_id=_base_data['routes'][route_id]['config_id'],
            )

    def _create_user_signup_sources():
        """Create user signup sources."""
        for site, users in _base_data['user_signup_source__users'].items():
            for user_id in users:
                UserSignupSource.objects.create(
                    site=site,
                    user_id=user_id,
                )

    def _create_course_access_roles():
        """Create course access roles."""
        for role, orgs in _base_data['course_access_roles_org_wide'].items():
            for org, users in orgs.items():
                for user_id in users:
                    CourseAccessRole.objects.bulk_create([CourseAccessRole(
                        user_id=user_id,
                        role=role,
                        org=org,
                    )])
        for org, courses in _base_data['course_access_roles_course_specific'].items():
            for course_id, roles in courses.items():
                for role, users in roles.items():
                    for user_id in users:
                        assert CourseOverview.objects.filter(id=course_id).exists(), \
                            f'Bad course_id in access roles testing data for org: {org}, course: {course_id}'
                        CourseAccessRole.objects.bulk_create([CourseAccessRole(
                            user_id=user_id,
                            role=role,
                            org=org,
                            course_id=course_id,
                        )])

    def _create_ignored_course_access_roles():
        """Create course access roles for records that will be ignored by our APIs."""
        for reason, orgs in _base_data['ignored_course_access_roles'].items():
            for role, users in orgs.items():
                for user_id in users:
                    assert reason in ['no_org'], f'Unknown reason for (ignored_course_access_roles) test data: {reason}'
                    params = {
                        'user_id': user_id,
                        'role': role,
                        'org': '',
                    }
                    CourseAccessRole.objects.bulk_create([CourseAccessRole(**params)])

    def _create_course_overviews():  # pylint: disable=too-many-branches
        """Create course overviews."""
        incompatible_org_case = _base_data['course_overviews'].pop('incompatible_org_case')
        for org, index_range in _base_data['course_overviews'].items():
            if index_range is None:
                continue
            for i in range(index_range[0], index_range[1] + 1):
                course_id = _get_course_id(org, i)
                CourseOverview.objects.create(
                    id=course_id,
                    org=org if course_id not in incompatible_org_case else incompatible_org_case[course_id],
                    catalog_visibility='both',
                    display_name=f'Course {i} of {org}',
                )
        for course_id in incompatible_org_case:
            assert CourseOverview.objects.filter(id=course_id).exists(), \
                f'Bad course_id in course_overviews testing data for incompatible_org_case: {course_id}'
        now_time = timezone.now()
        for course_id, data in _base_data['course_attributes'].items():
            course = CourseOverview.objects.get(id=course_id)
            for field, value in data.items():
                if field in ('start', 'end'):
                    assert value in ('F', 'P'), f'Bad value for {field} in course_attributes testing data: {value}'
                if field == 'start':
                    if value == 'F':
                        course.start = now_time + timezone.timedelta(days=1)
                    else:
                        course.start = now_time - timezone.timedelta(days=10)
                    continue
                if field == 'end':
                    if value == 'F':
                        course.end = now_time + timezone.timedelta(days=10)
                    else:
                        course.end = now_time - timezone.timedelta(days=1)
                    continue
                setattr(course, field, value)
            course.save()

    def _create_course_enrollments():
        """Create course enrollments."""
        for org, enrollments in _base_data['course_enrollments'].items():
            for course_index, users in enrollments.items():
                for user_id in users:
                    course_id = _get_course_id(org, course_index)
                    assert CourseOverview.objects.filter(id=course_id).exists(), \
                        f'Bad course_id in enrollment testing data for org: {org}, course: {course_id}'
                    assert 0 < user_id <= _base_data['users_count'], \
                        f'Bad user_id in enrollment testing data for org: {org}, user: {user_id}, course: {course_id}'
                    CourseEnrollment.objects.create(
                        user_id=user_id,
                        course_id=course_id,
                        is_active=True,
                    )
                    for _tenant_id in get_tenants_of_org(org, _base_data['tenant_config']):
                        assert 0 < _tenant_id < 9, f'Bad tenant_id in enrollment testing data for org: {org}'
                        if _tenant_id == 6:
                            continue
                        UserSignupSource.objects.get_or_create(
                            site=_base_data['routes'][_tenant_id]['domain'],
                            user_id=user_id,
                        )

    def _create_certificates():
        """Create certificates."""
        created_date = datetime.date(2024, 12, 26)
        for org, courses in _base_data['certificates'].items():
            for course_id, user_ids in courses.items():
                for user_id in user_ids:
                    certificate = GeneratedCertificate.objects.create(
                        user_id=user_id,
                        course_id=_get_course_id(org, course_id),
                        status='downloadable',
                    )
                    certificate.created_date = created_date
                    certificate.save()
                    if GeneratedCertificate.objects.count() % 2 == 0:
                        created_date -= datetime.timedelta(days=11)

    with django_db_blocker.unblock():
        _create_users()
        _create_tenants()
        _create_routes()
        _create_user_signup_sources()
        _create_course_overviews()
        _create_course_access_roles()
        _create_ignored_course_access_roles()
        _create_course_enrollments()
        _create_certificates()
