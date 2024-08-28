"""Test permissions helper classes"""
# pylint: disable=too-many-lines
from unittest.mock import Mock, patch

import pytest
from common.djangoapps.student.models import CourseAccessRole
from deepdiff import DeepDiff
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DatabaseError
from django.test import override_settings
from opaque_keys.edx.django.models import CourseKeyField

from futurex_openedx_extensions.helpers import constants as cs
from futurex_openedx_extensions.helpers.exceptions import FXCodedException, FXExceptionCodes
from futurex_openedx_extensions.helpers.extractors import DictHashcode
from futurex_openedx_extensions.helpers.models import ViewAllowedRoles
from futurex_openedx_extensions.helpers.roles import (
    FXViewRoleInfoMetaClass,
    FXViewRoleInfoMixin,
    RoleType,
    _clean_course_access_roles,
    add_course_access_roles,
    cache_name_user_course_access_roles,
    cache_refresh_course_access_roles,
    check_tenant_access,
    delete_course_access_roles,
    get_course_access_roles_queryset,
    get_fx_view_with_roles,
    get_user_course_access_roles,
    get_usernames_with_access_roles,
    is_view_exist,
    is_view_support_write,
    update_course_access_roles,
    validate_course_access_role,
)
from futurex_openedx_extensions.helpers.tenants import get_all_tenant_ids
from tests.fixture_helpers import (
    get_all_orgs,
    get_test_data_dict,
    get_test_data_dict_without_course_roles,
    get_test_data_dict_without_course_roles_org3,
)


class FXViewRoleInfoMetaClassTestView(metaclass=FXViewRoleInfoMetaClass):  # pylint: disable=too-few-public-methods
    """Mock class to use FXViewRoleInfoMetaClass."""


@pytest.fixture(autouse=True)
def reset_fx_views_with_roles():
    """Reset the _fx_views_with_roles dictionary before each test."""
    FXViewRoleInfoMetaClass._fx_views_with_roles = {'_all_view_names': {}}  # pylint: disable=protected-access


@pytest.mark.parametrize('update_course_access_role, error_msg, error_code', [
    ({'role': 'bad_role'}, 'invalid role ({role})!', FXExceptionCodes.ROLE_INVALID_ENTRY),
    ({'role': cs.COURSE_ACCESS_ROLES_UNSUPPORTED[0]}, None, FXExceptionCodes.ROLE_UNSUPPORTED),
    (
        {'role': cs.COURSE_ACCESS_ROLES_COURSE_ONLY[0]},
        'role {role} must have both course_id and org!',
        FXExceptionCodes.ROLE_INVALID_ENTRY,
    ),
    (
        {'role': cs.COURSE_ACCESS_ROLES_COURSE_ONLY[0], 'org': 'org1'},
        'role {role} must have both course_id and org!',
        FXExceptionCodes.ROLE_INVALID_ENTRY,
    ),
    (
        {'role': cs.COURSE_ACCESS_ROLES_COURSE_ONLY[0], 'course_id': 'course_v1:course'},
        'role {role} must have both course_id and org!',
        FXExceptionCodes.ROLE_INVALID_ENTRY,
    ),
    (
        {'role': cs.COURSE_ACCESS_ROLES_TENANT_ONLY[0]},
        'role {role} must have an org!',
        FXExceptionCodes.ROLE_INVALID_ENTRY,
    ),
    (
        {'role': cs.COURSE_ACCESS_ROLES_TENANT_OR_COURSE[0]},
        'role {role} must have at least an org, it can also have a course_id!',
        FXExceptionCodes.ROLE_INVALID_ENTRY,
    ),
    (
        {'role': cs.COURSE_ACCESS_ROLES_TENANT_OR_COURSE[0], 'course_id': 'course_v1:course'},
        'role {role} must have at least an org, it can also have a course_id!',
        FXExceptionCodes.ROLE_INVALID_ENTRY,
    ),
    (
        {'role': cs.COURSE_ACCESS_ROLES_COURSE_ONLY[0], 'org': 'org1', 'course_id': 'an id', 'course_org': 'org2'},
        'expected org value to be (org2), but got (org1)!',
        FXExceptionCodes.ROLE_INVALID_ENTRY,
    ),
])
def test_validate_course_access_role_invalid(update_course_access_role, error_msg, error_code):
    """Verify that validate_course_access_role raises FXCodedException when the access role record is invalid."""
    bad_course_access_role = {
        'id': 99,
        'user_id': 33,
        'org': '',
        'course_id': '',
        'course_org': '',
    }
    bad_course_access_role.update(update_course_access_role)
    if error_msg and '{role}' in error_msg:
        error_msg = error_msg.format(role=update_course_access_role['role'])

    with patch('futurex_openedx_extensions.helpers.roles.logger.error') as mock_logger:
        with pytest.raises(FXCodedException) as exc_info:
            validate_course_access_role(bad_course_access_role)

    assert exc_info.value.code == error_code.value
    if error_msg:
        mock_logger.assert_called_with(*('Invalid course access role: %s (id: %s)', error_msg, 99))
    else:
        mock_logger.assert_not_called()


def _remove_course_access_roles_causing_error_logs():
    """Remove bad course access roles."""
    CourseAccessRole.objects.filter(course_id=CourseKeyField.Empty, org='').delete()


@pytest.mark.django_db
def test_get_user_course_access_roles(base_data):  # pylint: disable=unused-argument
    """Verify that get_user_course_access_roles returns the expected structure."""
    user_id = 4
    _remove_course_access_roles_causing_error_logs()
    expected_result = {
        'roles': {
            'instructor': {
                'global_role': False,
                'orgs_full_access': ['org1', 'org2', 'org3'],
                'course_limited_access': [],
                'orgs_of_courses': []
            },
            'staff': {
                'global_role': False,
                'orgs_full_access': [],
                'course_limited_access': ['course-v1:ORG1+4+4', 'course-v1:ORG3+1+1'],
                'orgs_of_courses': ['org1', 'org3']
            },
        },
        'useless_entries_exist': False,
    }
    assert get_user_course_access_roles(user_id) == expected_result

    CourseAccessRole.objects.create(
        user_id=user_id,
        role='support',
        org='org8',
        course_id='course-v1:ORG8+1+1',
    )
    expected_result['roles']['support'] = {
        'global_role': True,
        'orgs_full_access': [],
        'course_limited_access': [],
        'orgs_of_courses': []
    }
    expected_result['useless_entries_exist'] = True

    CourseAccessRole.objects.create(
        user_id=user_id,
        role='org_course_creator_group',
        org='org8',
        course_id='course-v1:ORG8+1+1',
    )
    expected_result['roles']['org_course_creator_group'] = {
        'global_role': False,
        'orgs_full_access': ['org8'],
        'course_limited_access': [],
        'orgs_of_courses': []
    }

    CourseAccessRole.objects.create(
        user_id=user_id,
        role='staff',
        org='org2',
        course_id='course-v1:ORG8+1+1',
    )  # This should not be included in the result because the course is not in the org

    CourseAccessRole.objects.create(
        user_id=user_id,
        role='staff',
        org='org2',
        course_id='course-v1:ORG2+2+2',
    )
    expected_result['roles']['staff']['orgs_of_courses'].append('org2')
    expected_result['roles']['staff']['course_limited_access'].append('course-v1:ORG2+2+2')

    result = get_user_course_access_roles(user_id)
    print(result)
    print(expected_result)
    assert not DeepDiff(result, expected_result, ignore_order=True)


@pytest.mark.django_db
@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
def test_get_user_course_access_roles_being_cached():
    """Verify that get_user_course_access_roles is being cached."""
    cache_name = cache_name_user_course_access_roles(3)
    assert cache.get(cache_name) is None
    result = get_user_course_access_roles(3)
    assert cache.get(cache_name)['data'] == result
    cache.set(cache_name, None)


@pytest.mark.django_db
@pytest.mark.parametrize('user_id, ids_to_check, expected', [
    (1, '1,2,3,7', (True, {'tenant_ids': [1, 2, 3, 7]})),
    (2, '1,2,3,7', (True, {'tenant_ids': [1, 2, 3, 7]})),
    (3, '1,2,3,7', (
        False, {
            'details': {'tenant_ids': [2, 3, 7]},
            'reason': 'User does not have access to these tenants'
        }
    )),
    (1, '1,7,9', (
        False, {
            'details': {'tenant_ids': [9]},
            'reason': 'Invalid tenant IDs provided'
        }
    )),
    (1, '1,2,E,7', (
        False, {
            'details': {'error': 'invalid literal for int() with base 10: \'E\''},
            'reason': 'Invalid tenant IDs provided. It must be a comma-separated list of integers'
        }
    )),
])
def test_check_tenant_access(base_data, user_id, ids_to_check, expected):  # pylint: disable=unused-argument
    """Verify check_tenant_access function."""
    user = get_user_model().objects.get(id=user_id)
    result = check_tenant_access(user, ids_to_check)
    assert result == expected


def test_fx_view_role_metaclass__view_name_missing():
    """Verify that an error is logged if the view name is not defined."""
    with patch('futurex_openedx_extensions.helpers.roles.logger') as mock_logger:
        class TestView(FXViewRoleInfoMetaClassTestView):  # pylint: disable=too-few-public-methods, unused-variable
            fx_view_name = ''
            fx_view_description = 'A test view'
            fx_default_read_only_roles = ['role1', 'role2']

    mock_logger.error.assert_called_with('fx_view_name is not defined for view (%s)', 'TestView')


def test_fx_view_role_metaclass_view_name_length_exceeded():
    """Verify that an error is logged if the view name length exceeds 255 characters."""
    long_name = 'x' * 256
    with patch('futurex_openedx_extensions.helpers.roles.logger') as mock_logger:
        class TestView(FXViewRoleInfoMetaClassTestView):  # pylint: disable=too-few-public-methods, unused-variable
            fx_view_name = long_name
            fx_view_description = 'A test view'
            fx_default_read_only_roles = ['role1', 'role2']

    mock_logger.error.assert_called_with(
        'fx_view_name and fx_view_description length must be below 256 characters (%s)', 'TestView')


def test_fx_view_role_metaclass_view_description_length_exceeded():
    """Verify that an error is logged if the view description length exceeds 255 characters."""
    long_description = 'x' * 256
    with patch('futurex_openedx_extensions.helpers.roles.logger') as mock_logger:
        class TestView(FXViewRoleInfoMetaClassTestView):  # pylint: disable=too-few-public-methods, unused-variable
            fx_view_name = 'TestView'
            fx_view_description = long_description
            fx_default_read_only_roles = ['role1', 'role2']

    mock_logger.error.assert_called_with(
        'fx_view_name and fx_view_description length must be below 256 characters (%s)', 'TestView',
    )


def test_fx_view_role_metaclass_view_name_duplicate():
    """Verify that an error is logged if the view name is a duplicate."""
    class FirstView(FXViewRoleInfoMetaClassTestView):  # pylint: disable=too-few-public-methods, unused-variable
        fx_view_name = 'TestView'
        fx_view_description = 'First test view'
        fx_default_read_only_roles = ['role1']

    with patch('futurex_openedx_extensions.helpers.roles.logger') as mock_logger:
        class SecondView(FXViewRoleInfoMetaClassTestView):  # pylint: disable=too-few-public-methods, unused-variable
            fx_view_name = 'TestView'
            fx_view_description = 'Second test view'
            fx_default_read_only_roles = ['role2']

    mock_logger.error.assert_called_with('fx_view_name duplicate between (%s) and another view', 'SecondView')


def test_fx_view_role_metaclass_adding_view_to_fx_views_with_roles():
    """Verify that the view is added to the _fx_views_with_roles dictionary."""
    class TestView(FXViewRoleInfoMetaClassTestView):  # pylint: disable=too-few-public-methods
        """Test view class."""
        fx_view_name = 'UniqueView'
        fx_view_description = 'A unique test view'
        fx_default_read_only_roles = ['role1', 'role2']

    assert 'TestView' in TestView._fx_views_with_roles  # pylint: disable=protected-access
    assert TestView._fx_views_with_roles['TestView'] == {  # pylint: disable=protected-access
        'name': 'UniqueView',
        'description': 'A unique test view',
        'default_read_only_roles': ['role1', 'role2'],
        'default_read_write_roles': [],
    }
    assert 'UniqueView' in TestView._fx_views_with_roles['_all_view_names']  # pylint: disable=protected-access


def test_fx_view_role_metaclass_bad_duplicate_class_definition():
    """Verify that duplicate class definitions are logged as errors, and included in get_fx_view_with_roles result."""
    class DuplicateClassDefinition(
        FXViewRoleInfoMetaClassTestView
    ):  # pylint: disable=too-few-public-methods, missing-class-docstring
        fx_view_name = 'TestView_1'
        fx_view_description = 'A test view'
        fx_default_read_only_roles = ['role1', 'role2']

    expected_result = {
        'DuplicateClassDefinition': {
            'name': 'TestView_1',
            'description': 'A test view',
            'default_read_only_roles': ['role1', 'role2'],
            'default_read_write_roles': [],
        },
        '_all_view_names': {'TestView_1': DuplicateClassDefinition},
    }

    with patch('futurex_openedx_extensions.helpers.roles.logger') as mock_logger:
        class DuplicateClassDefinition(
            FXViewRoleInfoMetaClassTestView
        ):  # pylint: disable=function-redefined, too-few-public-methods, missing-class-docstring
            fx_view_name = 'TestView_2'
            fx_view_description = 'A test view'
            fx_default_read_only_roles = ['role1', 'role5']

    assert get_fx_view_with_roles() == expected_result
    mock_logger.error.assert_called_with(
        'FXViewRoleInfoMetaClass error: Unexpected class redefinition (%s)', 'DuplicateClassDefinition'
    )


def test_fx_view_role_metaclass_get_fx_view_with_roles():
    """Verify that get_fx_view_with_roles returns the expected dictionary."""
    class TestView1(FXViewRoleInfoMetaClassTestView):  # pylint: disable=too-few-public-methods
        fx_view_name = 'TestView_1'
        fx_view_description = 'A test view'
        fx_default_read_only_roles = ['role1', 'role2']

    class TestView2(FXViewRoleInfoMetaClassTestView):  # pylint: disable=too-few-public-methods
        fx_view_name = 'TestView_2'
        fx_view_description = 'A test view'
        fx_default_read_only_roles = ['role1', 'role5']

    assert get_fx_view_with_roles() == {
        'TestView1': {
            'name': 'TestView_1',
            'description': 'A test view',
            'default_read_only_roles': ['role1', 'role2'],
            'default_read_write_roles': [],
        },
        'TestView2': {
            'name': 'TestView_2',
            'description': 'A test view',
            'default_read_only_roles': ['role1', 'role5'],
            'default_read_write_roles': [],
        },
        '_all_view_names': {'TestView_1': TestView1, 'TestView_2': TestView2},
    }


def test_fx_view_role_metaclass_get_methods():
    """Verify that the get_read_methods and get_write_methods methods return the expected values."""
    assert FXViewRoleInfoMetaClass.get_read_methods() == ['GET', 'HEAD', 'OPTIONS']
    assert FXViewRoleInfoMetaClass.get_write_methods() == ['POST', 'PUT', 'PATCH', 'DELETE']


def test_fx_view_role_metaclass_check_allowed_read_methods(caplog):
    """Verify that check_allowed_read_methods returns the expected value."""
    error_message = 'fx_allowed_read_methods contains invalid methods (TestView)'

    with patch(
        'futurex_openedx_extensions.helpers.roles.FXViewRoleInfoMetaClass.get_read_methods',
        return_value=['GET']
    ):
        class TestView(FXViewRoleInfoMetaClass):
            fx_view_name = 'TestView'
            fx_view_description = 'A test view'
            fx_allowed_read_methods = ['GET']
        assert TestView.check_allowed_read_methods() is True

        assert error_message not in caplog.text
        TestView.fx_allowed_read_methods = ['POST']
        assert TestView.check_allowed_read_methods() is False
        assert error_message in caplog.text


def test_fx_view_role_metaclass_check_allowed_write_methods(caplog):
    """Verify that check_allowed_write_methods returns the expected value."""
    error_message = 'fx_allowed_write_methods contains invalid methods (TestView)'

    with patch(
        'futurex_openedx_extensions.helpers.roles.FXViewRoleInfoMetaClass.get_write_methods',
        return_value=['POST']
    ):
        class TestView(FXViewRoleInfoMetaClass):
            fx_view_name = 'TestView'
            fx_view_description = 'A test view'
            fx_allowed_write_methods = ['POST']
        assert TestView.check_allowed_write_methods() is True

        assert error_message not in caplog.text
        TestView.fx_allowed_write_methods = ['GET']
        assert TestView.check_allowed_write_methods() is False
        assert error_message in caplog.text


def test_fx_view_role_metaclass_is_write_supported():
    """Verify that is_write_supported returns the expected value."""
    class TestView(FXViewRoleInfoMetaClass):
        fx_view_name = 'TestView'
        fx_view_description = 'A test view'
    assert TestView.is_write_supported() is False

    TestView.fx_allowed_write_methods = ['ANYTHING']
    assert TestView.is_write_supported() is True


def test_is_view_exist():
    """Verify that is_view_exist returns the expected value."""
    assert is_view_exist('TestView') is False

    with patch(
        'futurex_openedx_extensions.helpers.roles.get_fx_view_with_roles',
        return_value={'_all_view_names': {'TestView': Mock()}}
    ):
        assert is_view_exist('TestView') is True


def test_is_view_support_write_nonexistent_view():
    """Verify that is_view_support_write returns the expected value for a nonexistent view."""
    assert is_view_support_write('non-existing_dummy_view') is False


@pytest.mark.parametrize('flag_value', [True, False])
def test_is_view_support_write(flag_value):
    """Verify that is_view_support_write returns the expected value."""
    class TestView(FXViewRoleInfoMetaClass):
        fx_view_name = 'TestView'
    with patch(
        'futurex_openedx_extensions.helpers.roles.get_fx_view_with_roles',
        return_value={'_all_view_names': {'TestView': TestView}}
    ):
        with patch.object(TestView, 'is_write_supported') as mock_is_write_supported:
            mock_is_write_supported.return_value = flag_value
            assert is_view_support_write('TestView') is flag_value


def _fill_default_fx_views_with_roles():
    """Fill the _fx_views_with_roles dictionary with default values."""
    FXViewRoleInfoMetaClass._fx_views_with_roles = {  # pylint: disable=protected-access
        '_all_view_names': {'View1': None, 'View2': None},
        'View1Class': {
            'name': 'View1',
            'description': 'Desc1',
            'default_read_only_roles': ['role1'],
            'default_read_write_roles': [],
        },
        'View2Class': {
            'name': 'View2',
            'description': 'Desc2',
            'default_read_only_roles': ['role1', 'role2'],
            'default_read_write_roles': [],
        }
    }


def test_fx_view_role_mixin_get_allowed_roles_no_existing_roles(db):  # pylint: disable=unused-argument
    """Verify that get_allowed_roles_all_views returns the expected dictionary and creates needed records."""
    _fill_default_fx_views_with_roles()
    assert ViewAllowedRoles.objects.count() == 0

    mixin = FXViewRoleInfoMixin()
    result = mixin.get_allowed_roles_all_views()

    assert result == {
        'View1': ['role1'],
        'View2': ['role1', 'role2'],
    }
    assert ViewAllowedRoles.objects.count() == 3
    assert ViewAllowedRoles.objects.filter(view_name='View1', allowed_role='role1').exists()
    assert ViewAllowedRoles.objects.filter(view_name='View2', allowed_role='role1').exists()
    assert ViewAllowedRoles.objects.filter(view_name='View2', allowed_role='role2').exists()


def test_fx_view_role_mixin_get_allowed_roles_with_existing_roles(db):  # pylint: disable=unused-argument
    """
    Verify that get_allowed_roles_all_views returns the expected dictionary without creating new records when
    records already exist.
    """
    _fill_default_fx_views_with_roles()
    assert ViewAllowedRoles.objects.count() == 0

    ViewAllowedRoles.objects.create(view_name='View1', view_description='Desc1', allowed_role='role1')
    ViewAllowedRoles.objects.create(view_name='View2', view_description='Desc2', allowed_role='role2')

    mixin = FXViewRoleInfoMixin()
    result = mixin.get_allowed_roles_all_views()

    assert result == {
        'View1': ['role1'],
        'View2': ['role2'],
    }
    assert ViewAllowedRoles.objects.count() == 2
    assert ViewAllowedRoles.objects.filter(view_name='View1', allowed_role='role1').exists()
    assert ViewAllowedRoles.objects.filter(view_name='View2', allowed_role='role2').exists()


def test_fx_view_role_mixin_get_allowed_roles_with_nonexistent_view(db):  # pylint: disable=unused-argument
    """
    Verify that get_allowed_roles_all_views returns the expected dictionary after removing records
    for nonexistent views.
    """
    FXViewRoleInfoMetaClass._fx_views_with_roles = {  # pylint: disable=protected-access
        '_all_view_names': {'View1': None, 'View2': None},
    }
    assert ViewAllowedRoles.objects.count() == 0

    ViewAllowedRoles.objects.create(view_name='View1', view_description='Desc1', allowed_role='role1')
    ViewAllowedRoles.objects.create(view_name='View1', view_description='Desc1', allowed_role='role4')
    ViewAllowedRoles.objects.create(view_name='View2', view_description='Desc2', allowed_role='role2')

    FXViewRoleInfoMetaClass._fx_views_with_roles['_all_view_names'] = {  # pylint: disable=protected-access
        'View1': None
    }

    mixin = FXViewRoleInfoMixin()
    result = mixin.get_allowed_roles_all_views()

    assert result == {
        'View1': ['role1', 'role4'],
    }
    assert ViewAllowedRoles.objects.count() == 2
    assert not ViewAllowedRoles.objects.filter(view_name='View2').exists()
    assert ViewAllowedRoles.objects.filter(view_name='View1', allowed_role='role1').exists()
    assert ViewAllowedRoles.objects.filter(view_name='View1', allowed_role='role4').exists()


def test_fx_view_role_mixin_fx_permission_info_not_available():
    """Verify that fx_permission_info returns the expected value."""
    def ensure_no_fx_permission_info():
        """Ensure that the request object has no fx_permission_info attribute."""
        delattr(mixin.request, 'fx_permission_info')  # pylint: disable=literal-used-as-attribute
    mixin = FXViewRoleInfoMixin()
    mixin.request = Mock()
    ensure_no_fx_permission_info()
    assert isinstance(mixin.fx_permission_info, dict)
    assert not mixin.fx_permission_info


def test_fx_view_role_mixin_fx_permission_info_available():
    """Verify that fx_permission_info returns the expected value."""
    mixin = FXViewRoleInfoMixin()
    mixin.request = Mock(fx_permission_info={'dummy': ['data']})
    assert mixin.fx_permission_info == {'dummy': ['data']}


@pytest.mark.django_db
def test_get_usernames_with_access_roles(base_data):  # pylint: disable=unused-argument
    """Verify that get_usernames_with_access_roles returns the expected value."""
    user3 = get_user_model().objects.get(username='user3')
    assert user3.is_active is True
    expected_result = ['user1', 'user2', 'user3', 'user4', 'user8', 'user9', 'user60']

    assert set(get_usernames_with_access_roles(['org1', 'org2'])) == set(expected_result)

    user3.is_active = False
    user3.save()
    expected_result.remove('user3')
    assert set(get_usernames_with_access_roles(['org1', 'org2'], active_filter=True)) == set(expected_result)
    assert get_usernames_with_access_roles(['org1', 'org2'], active_filter=False) == ['user3']


def test_role_types():
    """Verify that the role types are as expected."""
    assert RoleType.ORG_WIDE == RoleType('org_wide')
    assert RoleType.COURSE_SPECIFIC == RoleType('course_specific')
    assert len(RoleType) == 2, 'Unexpected number of role types, if this class is updated, then the logic of ' \
                               'get_course_access_roles_queryset should be updated as well'


@pytest.mark.parametrize('bad_role_type, expected_error_message', [
    ('bad_name', 'Invalid exclude_role_type: bad_name'),
    ('', 'Invalid exclude_role_type: EmptyString'),
    (['not string and not RoleType'], 'Invalid exclude_role_type: [\'not string and not RoleType\']'),
])
def test_get_roles_for_users_queryset_bad_exclude(bad_role_type, expected_error_message):
    """Verify that get_roles_for_users_queryset raises an error if the exclude parameter is invalid."""
    with pytest.raises(TypeError) as exc_info:
        get_course_access_roles_queryset(
            orgs_filter=['org1', 'org2'],
            remove_redundant=False,
            exclude_role_type=bad_role_type,
        )
    assert str(exc_info.value) == expected_error_message


def test_get_roles_for_users_queryset_bad_course_id():
    """Verify that get_roles_for_users_queryset raises an error if the course_id parameter is invalid."""
    with pytest.raises(ValueError) as exc_info:
        get_course_access_roles_queryset(
            orgs_filter=['org1', 'org2'],
            remove_redundant=False,
            course_ids_filter=['course-v1:ORG1+999+999', 'course-v1:ORG1+bad_course_id', 'course-v1:ORG1+99+99'],
        )
    assert str(exc_info.value) == 'Invalid course ID format: course-v1:ORG1+bad_course_id'


def roles_records_to_dict(records):
    """Convert the roles records to a dictionary."""
    result = {
        record.user.username: {} for record in records
    }
    for record in records:
        result[record.user.username][record.org.lower()] = {}
    for record in records:
        result[record.user.username][record.org.lower()][str(record.course_id or 'None')] = []
    for record in records:
        result[record.user.username][record.org.lower()][str(record.course_id or 'None')].append(record.role)

    return result


@pytest.mark.django_db
def test_assert_roles_test_data():
    """Verify that the test data is as expected."""
    records = CourseAccessRole.objects.filter(user__is_superuser=False, user__is_staff=False).exclude(org='')

    assert roles_records_to_dict(records) == get_test_data_dict()


@pytest.mark.django_db
def test_get_roles_for_users_queryset_simple(base_data):  # pylint: disable=unused-argument
    """Verify that get_roles_for_users_queryset returns the expected queryset."""
    result = get_course_access_roles_queryset(orgs_filter=get_all_orgs(), remove_redundant=False)

    assert roles_records_to_dict(result) == get_test_data_dict()


@pytest.mark.django_db
def test_get_roles_for_users_queryset_search_text(base_data):  # pylint: disable=unused-argument
    """Verify that get_roles_for_users_queryset returns the expected queryset when search_text is used."""
    test_orgs = get_all_orgs()
    result = get_course_access_roles_queryset(orgs_filter=test_orgs, remove_redundant=False, search_text='user4')

    assert roles_records_to_dict(result) == {
        'user4': get_test_data_dict()['user4'],
        'user48': get_test_data_dict()['user48'],
    }


@pytest.mark.django_db
def test_get_roles_for_users_queryset_active(base_data):  # pylint: disable=unused-argument
    """Verify that get_roles_for_users_queryset returns the expected queryset when active_filter is used."""
    test_orgs = get_all_orgs()
    expected_data = get_test_data_dict()
    result = get_course_access_roles_queryset(orgs_filter=test_orgs, remove_redundant=False)
    assert roles_records_to_dict(result) == expected_data

    user3 = get_user_model().objects.get(username='user3')
    user3.is_active = False
    user3.save()

    result = get_course_access_roles_queryset(orgs_filter=test_orgs, remove_redundant=False, active_filter=True)
    expected_data.pop('user3')
    assert roles_records_to_dict(result) == expected_data


@pytest.mark.django_db
def test_get_roles_for_users_queryset_roles_filter(base_data):  # pylint: disable=unused-argument
    """Verify that get_roles_for_users_queryset returns the expected queryset when roles_filter is used."""
    result = get_course_access_roles_queryset(
        orgs_filter=get_all_orgs(), remove_redundant=False, roles_filter=['data_researcher']
    )

    expected_data = {
        'user9': {
            'org3': {
                'None': ['data_researcher'],
                'course-v1:ORG3+2+2': ['data_researcher'],
            },
        },
        'user10': {
            'org3': {'None': ['data_researcher']},
        },

    }
    assert roles_records_to_dict(result) == expected_data

    result = get_course_access_roles_queryset(
        orgs_filter=get_all_orgs(), remove_redundant=True, roles_filter=['data_researcher']
    )
    del expected_data['user9']['org3']['course-v1:ORG3+2+2']
    assert roles_records_to_dict(result) == expected_data


@pytest.mark.django_db
@pytest.mark.parametrize('course_ids, remove_redundant, exclude_role_type, expected_result', [
    ([], False, None, get_test_data_dict()),
    ([], True, None, {
        'user3': {
            'org1': {
                'None': ['staff'],
                'course-v1:ORG1+3+3': ['instructor'],
                'course-v1:ORG1+4+4': ['instructor'],
            }
        },
        'user8': {
            'org2': {'None': ['staff'], 'course-v1:ORG2+3+3': ['instructor']}
        },
        'user9': {
            'org3': {
                'None': ['staff', 'data_researcher'],
                'course-v1:ORG3+3+3': ['instructor'],
            },
            'org2': {'course-v1:ORG2+1+1': ['staff'], 'course-v1:ORG2+3+3': ['staff']},
        },
        'user18': {'org3': {'None': ['staff']}},
        'user10': {
            'org4': {'None': ['staff']},
            'org3': {'None': ['data_researcher']},
        },
        'user23': {
            'org4': {'None': ['staff', 'instructor']},
            'org5': {'None': ['staff', 'instructor']},
            'org8': {'None': ['instructor']},
        },
        'user4': {
            'org1': {'None': ['instructor'], 'course-v1:ORG1+4+4': ['staff']},
            'org2': {'None': ['instructor']},
            'org3': {
                'None': ['instructor'],
                'course-v1:ORG3+1+1': ['staff'],
            },
        },
        'user11': {
            'org3': {
                'course-v1:ORG3+2+2': ['instructor'],
            }
        },
        'user48': {'org4': {'None': ['instructor']}},
    }),
    ([], False, RoleType.ORG_WIDE, {
        'user3': {
            'org1': {
                'course-v1:ORG1+3+3': ['staff', 'instructor'],
                'course-v1:ORG1+4+4': ['instructor'],
            }
        },
        'user8': {
            'org2': {'course-v1:ORG2+3+3': ['instructor']}
        },
        'user9': {
            'org3': {
                'course-v1:ORG3+2+2': ['data_researcher'],
                'course-v1:ORG3+3+3': ['instructor'],
            },
            'org2': {'course-v1:ORG2+1+1': ['staff'], 'course-v1:ORG2+3+3': ['staff']},
        },
        'user18': {'org3': {'course-v1:ORG3+3+3': ['staff']}},
        'user4': {
            'org1': {'course-v1:ORG1+4+4': ['staff']},
            'org3': {
                'course-v1:ORG3+1+1': ['staff', 'instructor'],
            },
        },
        'user11': {
            'org3': {
                'course-v1:ORG3+2+2': ['instructor'],
            }
        },
    }),
    ([], True, RoleType.ORG_WIDE, {
        'user3': {
            'org1': {
                'course-v1:ORG1+3+3': ['instructor'],
                'course-v1:ORG1+4+4': ['instructor'],
            }
        },
        'user8': {
            'org2': {'course-v1:ORG2+3+3': ['instructor']}
        },
        'user9': {
            'org3': {
                'course-v1:ORG3+3+3': ['instructor'],
            },
            'org2': {'course-v1:ORG2+1+1': ['staff'], 'course-v1:ORG2+3+3': ['staff']},
        },
        'user4': {
            'org1': {'course-v1:ORG1+4+4': ['staff']},
            'org3': {
                'course-v1:ORG3+1+1': ['staff'],
            },
        },
        'user11': {
            'org3': {
                'course-v1:ORG3+2+2': ['instructor'],
            }
        },
    }),
    ([], False, RoleType.COURSE_SPECIFIC, get_test_data_dict_without_course_roles()),
    ([], True, RoleType.COURSE_SPECIFIC, get_test_data_dict_without_course_roles()),
    (['course-v1:ORG3+2+2'], False, None, {
        'user9': {
            'org3': {
                'None': ['staff', 'data_researcher'],
                'course-v1:ORG3+2+2': ['data_researcher'],
            },
        },
        'user18': {'org3': {'None': ['staff']}},
        'user10': {
            'org3': {'None': ['data_researcher']},
        },
        'user23': {
            'org8': {'None': ['instructor']},
        },
        'user4': {
            'org3': {
                'None': ['instructor'],
            },
        },
        'user11': {
            'org3': {
                'course-v1:ORG3+2+2': ['instructor'],
            }
        },
    }),
    (['course-v1:ORG3+2+2'], True, None, {
        'user9': {
            'org3': {
                'None': ['staff', 'data_researcher'],
            },
        },
        'user18': {'org3': {'None': ['staff']}},
        'user10': {
            'org3': {'None': ['data_researcher']},
        },
        'user23': {
            'org8': {'None': ['instructor']},
        },
        'user4': {
            'org3': {
                'None': ['instructor'],
            },
        },
        'user11': {
            'org3': {
                'course-v1:ORG3+2+2': ['instructor'],
            }
        },
    }),
    (['course-v1:ORG3+2+2'], False, RoleType.ORG_WIDE, {
        'user9': {
            'org3': {
                'course-v1:ORG3+2+2': ['data_researcher'],
            },
        },
        'user11': {
            'org3': {
                'course-v1:ORG3+2+2': ['instructor'],
            }
        },
    }),
    (['course-v1:ORG3+2+2'], True, RoleType.ORG_WIDE, {
        'user11': {
            'org3': {
                'course-v1:ORG3+2+2': ['instructor'],
            }
        },
    }),
    (['course-v1:ORG3+2+2'], False, RoleType.COURSE_SPECIFIC, get_test_data_dict_without_course_roles_org3()),
    (['course-v1:ORG3+2+2'], True, RoleType.COURSE_SPECIFIC, get_test_data_dict_without_course_roles_org3()),
])
def test_get_roles_for_users_queryset(
    base_data, course_ids, remove_redundant, exclude_role_type, expected_result,
):  # pylint: disable=unused-argument
    """Verify that get_roles_for_users_queryset returns the expected queryset."""
    result = get_course_access_roles_queryset(
        orgs_filter=get_all_orgs(),
        course_ids_filter=course_ids,
        remove_redundant=remove_redundant,
        exclude_role_type=exclude_role_type,
    )
    assert roles_records_to_dict(result) == expected_result

    result = get_course_access_roles_queryset(
        orgs_filter=get_all_orgs(),
        course_ids_filter=course_ids,
        remove_redundant=remove_redundant,
        exclude_role_type=exclude_role_type,
        user_id_distinct=True,
    )
    user_ids = [record['user_id'] for record in result]
    expected_user_ids = [int(username[4:]) for username in expected_result.keys()]
    assert set(user_ids) == set(expected_user_ids)


@pytest.mark.django_db
def test_get_roles_for_users_queryset_superuser(base_data):  # pylint: disable=unused-argument
    """Verify that get_roles_for_users_queryset does not include superusers."""
    test_orgs = ['org1', 'org2']
    user = get_user_model().objects.get(username='user1')
    assert user.is_superuser is True

    users = get_user_model().objects.all()
    result = get_course_access_roles_queryset(orgs_filter=test_orgs, remove_redundant=False, users=users)

    assert CourseAccessRole.objects.filter(user_id=user.id, org__in=test_orgs).exists()
    assert not any(record.user_id == user.id for record in result)


@pytest.mark.django_db
def test_get_roles_for_users_queryset_staff(base_data):  # pylint: disable=unused-argument
    """Verify that get_roles_for_users_queryset does not include staff user."""
    test_orgs = ['org1', 'org2']
    user = get_user_model().objects.get(username='user2')
    assert user.is_superuser is False
    assert user.is_staff is True

    users = get_user_model().objects.all()
    result = get_course_access_roles_queryset(orgs_filter=test_orgs, remove_redundant=False, users=users)

    assert CourseAccessRole.objects.filter(user_id=user.id, org__in=test_orgs).exists()
    assert result.count() > 0
    assert user.id not in [record.user_id for record in result]


def assert_roles_result(result, expected):
    """Assert that the roles result is as expected."""
    expected_length = len(expected)
    assert result.count() == expected_length
    result = result.order_by('user_id', 'role', 'org', 'course_id')
    for index in range(expected_length):
        assert result[index].user_id == expected[index]['user_id']
        assert result[index].role == expected[index]['role']
        assert result[index].org.lower() == expected[index]['org'].lower()
        assert str(result[index].course_id) == expected[index]['course_id']


@pytest.mark.django_db
def test_get_roles_for_users_queryset_remove_redundant(base_data):  # pylint: disable=unused-argument
    """
    Verify that get_roles_for_users_queryset returns the expected queryset, with or without redundant records.
    """
    test_orgs = ['org1', 'org2']
    user = get_user_model().objects.get(username='user3')
    assert CourseAccessRole.objects.filter(org__in=test_orgs, user__in=[user]).count() == 4

    result = get_course_access_roles_queryset(orgs_filter=test_orgs, remove_redundant=False, users=[user])
    assert_roles_result(result, [
        {'user_id': 3, 'role': 'instructor', 'org': 'org1', 'course_id': 'course-v1:ORG1+3+3'},
        {'user_id': 3, 'role': 'instructor', 'org': 'org1', 'course_id': 'course-v1:ORG1+4+4'},
        {'user_id': 3, 'role': 'staff', 'org': 'org1', 'course_id': 'None'},
        {'user_id': 3, 'role': 'staff', 'org': 'org1', 'course_id': 'course-v1:ORG1+3+3'},
    ])

    result = get_course_access_roles_queryset(orgs_filter=test_orgs, remove_redundant=True, users=[user])
    assert_roles_result(result, [
        {'user_id': 3, 'role': 'instructor', 'org': 'org1', 'course_id': 'course-v1:ORG1+3+3'},
        {'user_id': 3, 'role': 'instructor', 'org': 'org1', 'course_id': 'course-v1:ORG1+4+4'},
        {'user_id': 3, 'role': 'staff', 'org': 'org1', 'course_id': 'None'},
    ])


@pytest.mark.django_db
def test_delete_course_access_roles(base_data):  # pylint: disable=unused-argument
    """Verify that delete_course_access_roles deletes the expected records."""
    user3 = get_user_model().objects.get(username='user3')
    CourseAccessRole.objects.create(
        user=user3, org='', role='staff', course_id='course-v1:ORG1+3+3',
    )
    q_user3 = CourseAccessRole.objects.filter(user=user3)
    assert q_user3.filter(org='').count() > 0
    assert q_user3.exclude(org='').filter(course_id=CourseKeyField.Empty).count() > 0
    assert q_user3.exclude(org='', course_id=CourseKeyField.Empty).count() > 0
    delete_course_access_roles(get_all_tenant_ids(), user3)
    assert q_user3.count() == 0


@pytest.mark.django_db
def test_delete_course_access_roles_nothing_to_delete(base_data):  # pylint: disable=unused-argument
    """Verify that delete_course_access_roles does not raise an error when there are no records to delete."""
    user23 = get_user_model().objects.get(username='user23')
    assert CourseAccessRole.objects.filter(user_id=user23).exclude(
        org__in=['org1', 'org2']
    ).count() == 5, 'bad test data'
    assert CourseAccessRole.objects.filter(user_id=user23, org__in=['org1', 'org2']).count() == 0, 'bad test data'

    with pytest.raises(FXCodedException) as exc_info:
        delete_course_access_roles([1], user23)
    assert str(exc_info.value) == 'No role found to delete for the user (user23) within the given tenants [1]!'

    assert CourseAccessRole.objects.filter(user_id=user23).exclude(
        org__in=['org1', 'org2']
    ).count() == 5, 'bad test data'
    assert CourseAccessRole.objects.filter(user_id=user23, org__in=['org1', 'org2']).count() == 0, 'bad test data'


@pytest.mark.django_db
@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
@patch('futurex_openedx_extensions.helpers.roles.get_user_course_access_roles')
def test_cache_refresh_course_access_roles(mock_get_roles):
    """Verify that cache_refresh_course_access_roles calls the expected functions."""
    def mocked_get_user_course_access_roles(dummy):  # pylint: disable=unused-argument
        """Mocked get_user_course_access_roles function."""
        cache.set(cache_name, {'some': 'new data'}, timeout=None)

    user_id = 99
    cache_name = cache_name_user_course_access_roles(user_id)

    cache.set(cache_name, {'some': 'data'}, timeout=None)
    assert cache.get(cache_name) == {'some': 'data'}
    mock_get_roles.side_effect = mocked_get_user_course_access_roles
    cache_refresh_course_access_roles(user_id)
    assert cache.get(cache_name) == {'some': 'new data'}


@pytest.mark.django_db
@pytest.mark.parametrize('tenant_ids, expected_error_message', [
    ([], 'No valid tenant IDs provided'),
    (None, 'No valid tenant IDs provided'),
    ([1, 2, 999], 'Invalid tenant IDs: [999]'),
])
def test_add_course_access_roles_invalid_tenants(tenant_ids, expected_error_message):
    """Verify that add_course_access_roles raises an error if the tenant_ids parameter is invalid."""
    with pytest.raises(FXCodedException) as exc_info:
        add_course_access_roles(tenant_ids, ['user1'], 'staff', True, [])
    assert str(exc_info.value) == expected_error_message


@pytest.mark.django_db
def test_add_course_access_roles_users_count_limit():
    """Verify that add_course_access_roles raises an error when the number of users exceeds the limit"""
    limit = cs.COURSE_ACCESS_ROLES_MAX_USERS_PER_OPERATION
    with pytest.raises(FXCodedException) as exc_info:
        add_course_access_roles(
            tenant_ids=[1],
            user_keys=[f'user{i}' for i in range(1, limit + 2)],
            role='staff',
            tenant_wide=True,
            course_ids=[],
        )
    assert str(exc_info.value) == \
           f'add_course_access_roles cannot proces more than {limit} users at a time!'


@pytest.mark.django_db
def test_add_course_access_roles_invalid_role():
    """Verify that add_course_access_roles raises an error if the role parameter is invalid."""
    with pytest.raises(FXCodedException) as exc_info:
        add_course_access_roles([1, 2], ['user1'], 'superman', False, [])
    assert str(exc_info.value) == 'Invalid role: superman'


@pytest.mark.django_db
@pytest.mark.parametrize('tenant_wide, course_ids', [
    (True, ['course-v1:ORG1+3+3']),
    (False, []),
    (False, None),
])
def test_add_course_access_roles_conflict_tenant_wide(tenant_wide, course_ids):
    """Verify that add_course_access_roles raises an error if there is a conflict with tenant-wide roles."""
    with pytest.raises(FXCodedException) as exc_info:
        add_course_access_roles([1, 2], ['user1'], 'staff', tenant_wide, course_ids)
    assert str(exc_info.value) == 'Conflict between tenant_wide and course_ids'


@pytest.mark.django_db
def test_add_course_access_roles_invalid_course_ids():
    """Verify that add_course_access_roles raises an error if the course_ids parameter is invalid."""
    with pytest.raises(FXCodedException) as exc_info:
        add_course_access_roles(
            [1, 2], ['user1'], 'staff', False,
            ['course-v1:ORG1+3+3', 'course-v1:ORG1+bad_course_id+1', 'course-v1:ORG1+4+4'],
        )
    assert str(exc_info.value) == 'Invalid course IDs provided: [\'course-v1:ORG1+bad_course_id+1\']'


@pytest.mark.django_db
def test_add_course_access_roles_foreign_course_id():
    """Verify that add_course_access_roles raises an error if the course_id is not in the tenant."""
    with pytest.raises(FXCodedException) as exc_info:
        add_course_access_roles([1, 8], ['user1'], 'staff', False, ['course-v1:ORG3+1+1'])
    assert str(exc_info.value) == 'Course ID course-v1:ORG3+1+1 does not belong to the provided tenant IDs'


@pytest.mark.django_db
@pytest.mark.parametrize('user_keys, error_message', [
    (None, 'No users provided!'),
    ([], 'No users provided!'),
    ({'user1', 'not a list'}, 'Invalid user keys provided! must be a list'),
])
def test_add_course_access_roles_no_user_list(user_keys, error_message):
    """Verify that add_course_access_roles raises an error if no user is provided, or it's not a list."""
    with pytest.raises(FXCodedException) as exc_info:
        add_course_access_roles([1, 8], user_keys, 'staff', False, ['course-v1:ORG3+1+1'])
    assert str(exc_info.value) == error_message


@pytest.mark.django_db
@patch('futurex_openedx_extensions.helpers.roles.cache_refresh_course_access_roles')
def test_add_course_access_roles_dry_run(mock_cache_refresh, base_data):  # pylint: disable=unused-argument
    """Verify that add_course_access_roles does not create records when dry_run is True."""
    user = get_user_model().objects.get(username='user43')
    expected_result = {'failed': [], 'added': [43], 'updated': [], 'not_updated': []}

    assert CourseAccessRole.objects.filter(user=user).count() == 0, 'Bad test data'
    assert add_course_access_roles(
        [1], [user], 'staff', True, [], dry_run=True
    ) == expected_result
    assert CourseAccessRole.objects.filter(user=user).count() == 0
    mock_cache_refresh.assert_not_called()

    mock_cache_refresh.reset_mock()
    assert add_course_access_roles(
        [1], [user], 'staff', True, [],
    ) == expected_result
    mock_cache_refresh.assert_called_once()
    assert CourseAccessRole.objects.filter(user=user).count() == 2
    org1 = org2 = False
    for record in CourseAccessRole.objects.filter(user=user):
        assert record.role == 'staff'
        assert record.course_id is None
        org1 |= record.org.lower() == 'org1'
        org2 |= record.org.lower() == 'org2'
    assert org1 and org2


@pytest.mark.django_db
def test_add_course_access_roles_bad_user_key(base_data):  # pylint: disable=unused-argument
    """Verify that add_course_access_roles raises an error if the user parameter is invalid."""
    result = add_course_access_roles([1], [999], 'staff', True, [])
    assert not any(result[data] for data in ('added', 'updated', 'not_updated'))

    assert len(result['failed']) == 1
    assert result['failed'][0]['reason_code'] == FXExceptionCodes.USER_NOT_FOUND.value
    assert result['failed'][0]['reason_message'] == 'User with ID (999) does not exist!'
    assert result['failed'][0]['user_id'] == 999
    assert result['failed'][0]['username'] is None
    assert result['failed'][0]['email'] is None


@pytest.mark.django_db
@pytest.mark.parametrize('user_key', ['user3@example.com', 'user3', 3])
@patch('futurex_openedx_extensions.helpers.users.get_user_by_username_or_email')
def test_add_course_access_roles_success_list_contains_user_key(
    mock_get_user, base_data, user_key
):  # pylint: disable=unused-argument
    """Verify that add_course_access_roles returns the expected result according to the user_key"""
    mock_get_user.return_value = get_user_model().objects.get(id=3)
    result = add_course_access_roles(
        [1], [user_key], 'beta_testers', False, ['course-v1:ORG1+3+3']
    )

    assert result == {
        'failed': [],
        'added': [],
        'updated': [user_key],
        'not_updated': [],
    }


@pytest.mark.django_db
def test_add_course_access_roles_success_user_key_same_as_id(base_data):  # pylint: disable=unused-argument
    """Verify that add_course_access_roles returns the expected result when the user_key is a User object."""
    user_key = get_user_model().objects.get(username='user3')
    result = add_course_access_roles(
        [1], [user_key], 'beta_testers', False, ['course-v1:ORG1+3+3']
    )

    assert result == {
        'failed': [],
        'added': [],
        'updated': [user_key.id],
        'not_updated': [],
    }


@pytest.mark.django_db
@patch('futurex_openedx_extensions.helpers.users.get_user_by_username_or_email')
def test_add_course_access_roles_data_cleaning(mocked_get_user, base_data):  # pylint: disable=unused-argument
    """
    Verify that add_course_access_roles returns the expected result when the data needs cleaning. The second call
    should not update since the data already cleaned
    """
    username = 'user3'
    staff_role = 'staff'
    mocked_get_user.return_value = get_user_model().objects.get(username=username)

    user3_org1_data = [
        (staff_role, CourseKeyField.Empty),
        ('instructor', 'course-v1:ORG1+3+3'),
        ('instructor', 'course-v1:ORG1+4+4'),
    ]
    user3_org1_redundant_data = [
        (staff_role, 'course-v1:ORG1+3+3'),
    ]
    assert all(CourseAccessRole.objects.filter(
        user__username=username, org='org1', role=data[0], course_id=data[1],
    ).exists() for data in user3_org1_data), 'Bad test data'
    assert all(CourseAccessRole.objects.filter(
        user__username=username, org='org1', role=data[0], course_id=data[1],
    ).exists() for data in user3_org1_redundant_data), 'Bad test data'

    assert not CourseAccessRole.objects.filter(user__username=username, org='org2').exists(), \
        'Bad test data. we need to test the case when an org role is missing from one org of the tenant'

    result = add_course_access_roles([1], [username], staff_role, True, [])
    assert result == {
        'failed': [],
        'added': [],
        'updated': [username],
        'not_updated': [],
    }
    assert all(CourseAccessRole.objects.filter(
        user__username=username, org='org1', role=data[0], course_id=data[1],
    ).exists() for data in user3_org1_data), 'Bad test data'
    assert not any(CourseAccessRole.objects.filter(
        user__username=username, org='org1', role=data[0], course_id=data[1],
    ).exists() for data in user3_org1_redundant_data), 'Bad test data'
    assert CourseAccessRole.objects.filter(user__username=username, org='org2').count() == 1

    second_call = add_course_access_roles([1], [username], staff_role, True, [])
    assert second_call == {
        'failed': [],
        'added': [],
        'updated': [],
        'not_updated': [username],
    }


@pytest.mark.django_db
@patch('futurex_openedx_extensions.helpers.users.get_user_by_username_or_email')
@patch('futurex_openedx_extensions.helpers.roles.CourseAccessRole.objects.bulk_create')
def test_add_course_access_roles_bulk_create_failed(
    mock_bulk_create, mocked_get_user, base_data
):  # pylint: disable=unused-argument
    """
    Verify that add_course_access_roles returns the expected result when the bulk_create fails.
    """
    username = 'user3'
    mocked_get_user.return_value = get_user_model().objects.get(username=username)
    mock_bulk_create.side_effect = DatabaseError('Some error')
    result = add_course_access_roles([1], [username], 'staff', True, [])

    assert result == {
        'failed': [{
            'user_id': 3,
            'username': 'user3',
            'email': 'user3@example.com',
            'reason_code': FXExceptionCodes.ROLE_CREATE.value,
            'reason_message': 'Database error while adding course access roles!'
        }],
        'added': [],
        'updated': [],
        'not_updated': [],
    }


@pytest.mark.django_db
def test_clean_course_access_roles_no_record_to_delete():
    """Verify that clean_course_access_roles returns the expected result when there are no records to delete."""
    hash_code = DictHashcode({'role': 'role1', 'org_lower_case': 'org1', 'course_id': None})
    with pytest.raises(FXCodedException) as exc_info:
        _clean_course_access_roles(
            {hash_code},
            get_user_model().objects.get(username='user3'),
        )
    assert exc_info.value.code == FXExceptionCodes.ROLE_DELETE.value
    assert str(exc_info.value) == f'No role found to delete! {hash_code}'


@pytest.mark.django_db
@patch('futurex_openedx_extensions.helpers.roles.CourseAccessRole.objects.filter')
def test_clean_course_access_roles_db_error_on_delete(mock_filter):
    """Verify that clean_course_access_roles returns the expected result when deletion failed for DB reasons."""
    mock_filter.return_value.delete.side_effect = DatabaseError('somthing!')
    hash_code = DictHashcode({'role': 'staff', 'org_lower_case': 'org1', 'course_id': None})
    with pytest.raises(FXCodedException) as exc_info:
        _clean_course_access_roles(
            {hash_code},
            get_user_model().objects.get(username='user3'),
        )
    assert exc_info.value.code == FXExceptionCodes.ROLE_DELETE.value
    assert str(exc_info.value) == f'Database error while deleting course access roles! {hash_code}. Error: somthing!'


@pytest.mark.django_db
def test_clean_course_access_roles_kry_error_on_delete():
    """Verify that clean_course_access_roles returns the expected result when deletion failed for DB reasons."""
    hash_code = DictHashcode({'role': 'staff', 'missing_org_lower_case': 'org1', 'course_id': None})
    with pytest.raises(FXCodedException) as exc_info:
        _clean_course_access_roles(
            {hash_code},
            get_user_model().objects.get(username='user3'),
        )
    assert exc_info.value.code == FXExceptionCodes.ROLE_DELETE.value
    assert str(exc_info.value) == 'Unexpected internal error! \'org_lower_case\' is missing from the hashcode!'


@pytest.mark.django_db
@pytest.mark.parametrize('user', [
    None, '', 'must be a user object', 3,
])
def test_update_course_access_roles_invalid_user(user):
    """Verify that update_course_access_roles raises an error if the user parameter is invalid."""
    with pytest.raises(ValueError) as exc_info:
        update_course_access_roles(user, {})
    assert str(exc_info.value) == 'Invalid user provided!'


@pytest.mark.django_db
@pytest.mark.parametrize('key, value, expected_error_message', [
    ('tenant_id', 'not int', 'No valid tenant ID provided'),
    ('tenant_roles', 'not list', 'tenant_roles must be a list of strings, or an empty list'),
    ('tenant_roles', [1, 'not list of strings'], 'tenant_roles must be a list of strings, or an empty list'),
    ('course_roles', 'not dict', 'course_roles must be a dictionary of (roles: course_ids)'),
    ('course_roles', {'course': 'not list'}, 'roles of courses must be a list of strings'),
    ('course_roles', {'course': [1, 'not list of strings']}, 'roles of courses must be a list of strings'),
])
def test_update_course_access_roles_invalid_input(key, value, expected_error_message):
    """Verify that update_course_access_roles raises an error if the user parameter is invalid."""
    user = get_user_model().objects.get(username='user3')
    new_roles_details = {
        'tenant_id': 1,
        'tenant_roles': ['staff'],
        'course_roles': {
            'course-v1:ORG1+3+3': ['staff'],
        },
    }
    new_roles_details.update({key: value})
    result = update_course_access_roles(user, new_roles_details)
    assert result['error_code'] == FXExceptionCodes.INVALID_INPUT.value
    assert result['error_message'] == expected_error_message


def _run_update_roles(test_data_update, dry_run=False):
    """Helper function to run update_course_access_roles."""
    user = get_user_model().objects.get(username='user3')
    new_roles_details = {
        'tenant_id': 1,
        'tenant_roles': ['staff'],
        'course_roles': {
            'course-v1:ORG1+3+3': ['staff'],
        },
    }
    new_roles_details.update(test_data_update)
    return update_course_access_roles(user, new_roles_details, dry_run=dry_run)


@pytest.mark.django_db
@pytest.mark.parametrize('empty_data', [
    {'tenant_roles': [], 'course_roles': {}}, {'tenant_roles': [], 'course_roles': {'course': []}}
])
def test_update_course_access_roles_empty(empty_data):
    """Verify that update_course_access_roles returns an error when the update data is empty."""
    result = _run_update_roles(empty_data)
    assert result == {
        'error_code': FXExceptionCodes.INVALID_INPUT.value,
        'error_message': 'Cannot use empty data in roles update! use delete instead',
    }


@pytest.mark.django_db
@pytest.mark.parametrize('test_data_update', [
    {'tenant_roles': []}, {'course_roles': {}}
])
@patch('futurex_openedx_extensions.helpers.roles.delete_course_access_roles')
@patch('futurex_openedx_extensions.helpers.roles.add_course_access_roles')
def test_update_course_access_course_add_failed(mock_add, mock_delete, test_data_update):
    """Verify that update_course_access_roles returns an error when the add_course_access_roles fails."""
    mock_add.return_value = {'failed': [{
        'reason_code': FXExceptionCodes.ROLE_CREATE.value,
        'reason_message': 'Failed to create role for some reason!!',
    }]}

    result = _run_update_roles(test_data_update)
    mock_delete.assert_called_once()
    mock_add.assert_called_once()
    assert result == {
        'error_code': mock_add.return_value['failed'][0]['reason_code'],
        'error_message': mock_add.return_value['failed'][0]['reason_message'],
    }


@pytest.mark.django_db
@patch('futurex_openedx_extensions.helpers.roles.delete_course_access_roles')
def test_unexpected_error(mock_delete):
    """Verify that update_course_access_roles returns an error when an unexpected error occurs."""
    mock_delete.side_effect = Exception('Some unexpected error')
    result = _run_update_roles({})
    mock_delete.assert_called_once()
    assert result['error_code'] == FXExceptionCodes.UNKNOWN_ERROR.value
    assert result['error_message'] == 'Some unexpected error'


@pytest.mark.django_db
@patch('futurex_openedx_extensions.helpers.roles.cache_refresh_course_access_roles')
@patch('futurex_openedx_extensions.helpers.roles.delete_course_access_roles')
@patch('futurex_openedx_extensions.helpers.roles.add_course_access_roles')
def test_update_course_access_roles_dry_run(
    mock_add, mock_delete, mock_cache_refresh, base_data
):  # pylint: disable=unused-argument
    """Verify that update_course_access_roles does not update records when dry_run is True."""
    user = get_user_model().objects.get(username='user3')

    mock_add.return_value = {'failed': []}
    result = _run_update_roles({}, dry_run=True)
    mock_delete.assert_not_called()
    mock_add.assert_not_called()
    mock_cache_refresh.assert_not_called()
    assert result['error_code'] is None

    result = _run_update_roles({})
    mock_delete.assert_called_once_with([1], user)
    mock_add.assert_called_once_with(
        tenant_ids=[1],
        user_keys=[user],
        role='staff',
        tenant_wide=True,
        course_ids=None,
        dry_run=False,
    )
    mock_cache_refresh.assert_called_once()
    assert result['error_code'] is None


@pytest.mark.django_db
@patch('futurex_openedx_extensions.helpers.roles.delete_course_access_roles')
@patch('futurex_openedx_extensions.helpers.roles.add_course_access_roles')
def test_update_course_access_course_roles_grouping(mock_add, mock_delete):
    """Verify that update_course_access_roles groups the roles and course_ids correctly."""
    mock_add.return_value = {'failed': []}
    result = _run_update_roles({
        'tenant_roles': [],
        'course_roles': {
            'course-v1:ORG1+1+1': ['staff', 'org_course_creator_group'],
            'course-v1:ORG1+2+2': ['staff', 'org_course_creator_group'],
            'course-v1:ORG1+3+3': ['staff', 'org_course_creator_group'],
            'course-v1:ORG1+4+4': ['staff', 'org_course_creator_group'],
        }
    })
    mock_delete.assert_called_once()

    role_staff = False
    role_org_course_creator_group = False
    assert mock_add.call_count == 2
    for call_index in range(2):
        add_args = dict(mock_add.call_args_list[call_index].kwargs)
        role_staff |= 'staff' == add_args['role']
        role_org_course_creator_group |= 'org_course_creator_group' == add_args['role']
        add_args.pop('role')
        add_args['course_ids'] = sorted(add_args['course_ids'])
        assert add_args == {
            'tenant_ids': [1],
            'user_keys': [get_user_model().objects.get(username='user3')],
            'tenant_wide': False,
            'course_ids': [
                'course-v1:ORG1+1+1', 'course-v1:ORG1+2+2', 'course-v1:ORG1+3+3', 'course-v1:ORG1+4+4'
            ],
            'dry_run': False,
        }
    assert result['error_code'] is None
