"""Test views for the dashboard app"""
# pylint: disable=too-many-lines
import json
from datetime import date
from unittest.mock import Mock, patch

import ddt
import pytest
from common.djangoapps.student.models import CourseAccessRole, CourseEnrollment
from deepdiff import DeepDiff
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage
from django.db.models import Q
from django.http import JsonResponse
from django.urls import resolve, reverse
from django.utils.timezone import now, timedelta
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from rest_framework import status as http_status
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, APITestCase

from futurex_openedx_extensions.dashboard import serializers, urls, views
from futurex_openedx_extensions.dashboard.views import UserRolesManagementView
from futurex_openedx_extensions.helpers import clickhouse_operations as ch
from futurex_openedx_extensions.helpers import constants as cs
from futurex_openedx_extensions.helpers.exceptions import FXCodedException, FXExceptionCodes
from futurex_openedx_extensions.helpers.filters import DefaultOrderingFilter
from futurex_openedx_extensions.helpers.models import DataExportTask, ViewAllowedRoles
from futurex_openedx_extensions.helpers.pagination import DefaultPagination
from futurex_openedx_extensions.helpers.permissions import (
    FXHasTenantAllCoursesAccess,
    FXHasTenantCourseAccess,
    IsAnonymousOrSystemStaff,
    IsSystemStaff,
)
from tests.fixture_helpers import d_t, get_all_orgs, get_test_data_dict, get_user1_fx_permission_info
from tests.test_dashboard.test_mixins import MockPatcherMixin


class BaseTestViewMixin(APITestCase):
    """Base test view mixin"""
    VIEW_NAME = 'view name is not set!'

    def setUp(self):
        """Setup"""
        self.view_name = self.VIEW_NAME
        self.url_args = []
        self.staff_user = 2

    @property
    def url(self):
        """Get the URL"""
        return reverse(self.view_name, args=self.url_args)

    def login_user(self, user_id):
        """Helper to login user"""
        self.client.force_login(get_user_model().objects.get(id=user_id))

    def _get_request(self):
        """Helper to get the request"""
        factory = APIRequestFactory()
        request = factory.get(self.url)
        request.query_params = {}
        request.user = get_user_model().objects.get(id=self.staff_user)
        request.fx_permission_info = get_user1_fx_permission_info()
        request.fx_permission_info['user'] = request.user
        return request


@pytest.mark.usefixtures('base_data')
class TestTotalCountsView(BaseTestViewMixin):
    """Tests for TotalCountsView"""
    VIEW_NAME = 'fx_dashboard:total-counts'

    def test_unauthorized(self):
        """Test unauthorized access"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_invalid_stats(self):
        """Test invalid stats"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url + '?stats=invalid')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertEqual(str(response.data['detail']), "Invalid stats type: ['invalid']")

    def test_all_stats(self):
        """Test get method"""
        self.login_user(self.staff_user)
        response = self.client.get(
            self.url + '?stats=certificates,courses,hidden_courses,learners,enrollments,learning_hours,unique_learners'
        )
        self.assertTrue(isinstance(response, JsonResponse))
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertDictEqual(json.loads(response.content), {
            '1': {
                'certificates_count': 11, 'courses_count': 12, 'hidden_courses_count': 0,
                'learners_count': 16, 'enrollments_count': 26, 'learning_hours_count': 220
            },
            '2': {
                'certificates_count': 8, 'courses_count': 5, 'hidden_courses_count': 0,
                'learners_count': 21, 'enrollments_count': 21, 'learning_hours_count': 160
            },
            '3': {
                'certificates_count': 0, 'courses_count': 1, 'hidden_courses_count': 0,
                'learners_count': 6, 'enrollments_count': 4, 'learning_hours_count': 0
            },
            '7': {
                'certificates_count': 6, 'courses_count': 3, 'hidden_courses_count': 0,
                'learners_count': 17, 'enrollments_count': 14, 'learning_hours_count': 120
            },
            '8': {
                'certificates_count': 2, 'courses_count': 2, 'hidden_courses_count': 0,
                'learners_count': 9, 'enrollments_count': 7, 'learning_hours_count': 40
            },
            'total_certificates_count': 27, 'total_courses_count': 23, 'total_hidden_courses_count': 0,
            'total_learners_count': 69, 'total_enrollments_count': 72, 'total_learning_hours_count': 540,
            'total_unique_learners': 37, 'limited_access': False
        })

    def test_all_stats_with_include_staff(self):
        """Test get method"""
        self.login_user(self.staff_user)
        response = self.client.get(
            self.url + '?stats=certificates,courses,learners,enrollments&include_staff=1'
        )
        self.assertTrue(isinstance(response, JsonResponse))
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertDictEqual(json.loads(response.content), {
            '1': {'certificates_count': 14, 'courses_count': 12, 'learners_count': 18, 'enrollments_count': 32},
            '2': {'certificates_count': 9, 'courses_count': 5, 'learners_count': 26, 'enrollments_count': 25},
            '3': {'certificates_count': 0, 'courses_count': 1, 'learners_count': 6, 'enrollments_count': 4},
            '7': {'certificates_count': 7, 'courses_count': 3, 'learners_count': 20, 'enrollments_count': 17},
            '8': {'certificates_count': 2, 'courses_count': 2, 'learners_count': 10, 'enrollments_count': 8},
            'total_certificates_count': 32,
            'total_courses_count': 23,
            'total_learners_count': 80,
            'total_enrollments_count': 86,
            'limited_access': False
        })

    def test_limited_access(self):
        """Test get method with limited access"""
        self.login_user(9)
        response = self.client.get(self.url + '?tenant_ids=1&stats=certificates')  # we need at least one stat
        self.assertTrue(isinstance(response, JsonResponse))
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(json.loads(response.content)['limited_access'], True)

    def test_selected_tenants(self):
        """Test get method with selected tenants"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url + '?stats=certificates,courses,learners&tenant_ids=1,2')
        self.assertTrue(isinstance(response, JsonResponse))
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        expected_response = {
            '1': {'certificates_count': 11, 'courses_count': 12, 'learners_count': 16},
            '2': {'certificates_count': 8, 'courses_count': 5, 'learners_count': 21},
            'total_certificates_count': 19,
            'total_courses_count': 17,
            'total_learners_count': 37,
            'limited_access': False,
        }
        self.assertDictEqual(json.loads(response.content), expected_response)


@ddt.ddt
@pytest.mark.usefixtures('base_data')
class TestAggregatedCountsView(BaseTestViewMixin):
    """Tests for AggregatedCountsView"""
    VIEW_NAME = 'fx_dashboard:aggregated-counts'

    def setUp(self):
        """Setup"""
        super().setUp()
        self.view = views.AggregatedCountsView()
        self.view.request = self._get_request()

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_invalid_stats(self):
        """Test invalid stats"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url + '?stats=invalid')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertEqual(str(response.data['detail']), "Invalid stats type: ['invalid']")

    @patch('futurex_openedx_extensions.dashboard.views.AggregatedCountsView._construct_result')
    @ddt.data(
        (None, '2024-01-01', '2024-01-01', 'Invalid aggregate_period: None'),
        ('day', '2024-01-01', '2024-01-01', None),
        ('day', '2024-01-01', '2024-01-02', None),
        ('day', '2024-01-02', '2024-01-01', None),
        ('day', None, '2024-01-01', None),
        ('day', '2024-01-02', None, None),
        ('day', None, None, None),
        ('invalid', '2024-01-01', '2024-01-02', 'Invalid aggregate_period: invalid'),
        (
            'day',
            'invalid', '2024-01-02',
            'Invalid dates. You must provide a valid date_from and date_to formated as YYYY-MM-DD'
        ),
        (
            'day',
            '2024-01-01',
            'invalid',
            'Invalid dates. You must provide a valid date_from and date_to formated as YYYY-MM-DD'
        ),
        ('day', '2024-01-03', '2024-01-02', None),
    )
    @ddt.unpack
    def test_load_query_params(
        self, aggregate_period, date_from, date_to, error_message, mock_construct_result,
    ):  # pylint: disable=too-many-arguments
        """Verify that _load_query_params works as expected"""
        mock_construct_result.return_value = {
            'query_settings': {
                'aggregate_period': aggregate_period,
                'date_from': date_from,
                'date_to': date_to,
            },
            'by_tenant': [],
            'all_tenants': {
                'enrollments_count': [],
                'totals': {
                    'enrollments_count': 0,
                },
            },
            'limited_access': False,
        }
        self.login_user(self.staff_user)
        url = self.url + f'?stats=enrollments&aggregate_period={aggregate_period}'
        if date_from:
            url += f'&date_from={date_from}'
        if date_to:
            url += f'&date_to={date_to}'
        response = self.client.get(url)
        if error_message:
            self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
            self.assertEqual(str(response.data['detail']), error_message)
        else:
            self.assertEqual(response.status_code, http_status.HTTP_200_OK)

    @ddt.data(
        ('', 0, 'should be zero when max_period_chunks is not provided.'),
        ('44', 0, 'should be zero when max_period_chunks is greater than settings value.'),
        ('-1', 0, 'should be zero when max_period_chunks is negative.'),
        ('24', 24, 'should be the sam provided max_period_chunks value when it is less or equal settings value.'),
        ('0', 0, 'should be the sam provided max_period_chunks value when it is less or equal settings value.'),
        ('3', 3, 'should be the sam provided max_period_chunks value when it is less or equal settings value.'),
    )
    @ddt.unpack
    def test_load_query_params_max_period_chunks(
        self, max_period_chunks_query_params, expected_max_period_chunks, error_details,
    ):
        """Verify that _load_query_params works saves the correct value for max_period_chunks"""
        self.view.request.query_params = {
            'stats': 'enrollments',
            'aggregate_period': 'month',
        }
        if max_period_chunks_query_params:
            self.view.request.query_params['max_period_chunks'] = max_period_chunks_query_params

        assert self.view.max_period_chunks == 0, 'bad test data'
        self.view._load_query_params(request=self.view.request)  # pylint: disable=protected-access
        assert self.view.max_period_chunks == expected_max_period_chunks, error_details

    def test_load_query_params_max_period_chunks_not_int(self):
        """Verify that _load_query_params raises ParseError when max_period_chunks is not an integer"""
        self.view.request.query_params = {
            'stats': 'enrollments',
            'aggregate_period': 'month',
            'max_period_chunks': 'not_integer',
        }

        assert self.view.max_period_chunks == 0, 'bad test data'
        with pytest.raises(ParseError) as exc:
            self.view._load_query_params(request=self.view.request)  # pylint: disable=protected-access
        assert str(exc.value) == 'Invalid max_period_chunks. It must be an integer.'

    def _prepare_test_dates_for_aggregated_counts(self):
        """Prepare test dates for aggregated counts"""
        self.assertEqual(CourseEnrollment.objects.count(), 73)
        enrollments = CourseEnrollment.objects.filter(
            is_active=True,
            user_id__lt=30,
            user__is_superuser=False,
            user__is_staff=False,
            user__is_active=True,
            course__org='org2',
        )
        assert enrollments.count() == 16, 'bad test data'
        count = 7
        enrollment = enrollments.first()
        while enrollment and count > 0:
            enrollment.created = '2024-08-07' if count < 4 else '2024-12-26'
            enrollment.save()
            count -= 1
            enrollment = enrollments.filter(id__gt=enrollment.id).first()

        assert CourseEnrollment.objects.filter(created='2024-08-07').count() == 3, 'test data preparation failed!'
        assert CourseEnrollment.objects.filter(created='2024-12-26').count() == 4, 'test data preparation failed!'

        expected_result = {
            'query_settings': {
                'aggregate_period': 'day',
                'date_from': '2022-12-28T00:00:00Z',
                'date_to': '2024-12-26T23:59:59Z',
            },
            'all_tenants': {
                'enrollments_count': [
                    {'label': '2024-08-07', 'value': 3},
                    {'label': '2024-12-26', 'value': 4},
                ],
                'totals': {'enrollments_count': 7},
            },
            'by_tenant': [
                {
                    'enrollments_count': [
                        {'label': '2024-08-07', 'value': 3},
                        {'label': '2024-12-26', 'value': 4},
                    ],
                    'totals': {'enrollments_count': 7},
                    'tenant_id': 1,
                },
                {
                    'enrollments_count': [],
                    'totals': {'enrollments_count': 0},
                    'tenant_id': 2,
                },
            ],
            'limited_access': False,
        }
        return expected_result

    @patch('futurex_openedx_extensions.dashboard.views.AggregatedCountsView.get_data_with_missing_periods')
    @ddt.data(True, False)
    def test_all_stats(self, fill_missing_periods, mock_missing_periods):
        """Test get method"""
        mock_missing_periods.side_effect = lambda data, already_sorted: data
        expected_result = self._prepare_test_dates_for_aggregated_counts()

        self.login_user(self.staff_user)
        url = self.url + '?&tenant_ids=1,2&include_staff=1&stats=enrollments&date_to=2024-12-26&aggregate_period=day'
        if not fill_missing_periods:
            url += '&fill_missing_periods=0'
        response = self.client.get(url)
        self.assertTrue(isinstance(response, Response))
        self.assertEqual(
            response.status_code,
            http_status.HTTP_200_OK,
            f'{http_status}: {response.data.get("detail")}',
        )

        self.assertDictEqual(json.loads(response.content), expected_result)
        self.assertEqual(
            mock_missing_periods.call_count,
            len(expected_result['all_tenants']['enrollments_count']) if fill_missing_periods else 0,
        )

    @ddt.data('courses', 'learners', 'learning_hours', 'certificates')
    def test_unsupported_stats(self, stat):
        """Test unsupported stats"""
        with pytest.raises(NotImplementedError):
            self.view._get_stat_count(stat=stat, tenant_id=1)  # pylint: disable=protected-access

    @ddt.data(
        ('day', '2024-08-07'),
        ('month', '2024-08'),
        ('quarter', '2024-Q3'),
        ('year', '2024'),
    )
    @ddt.unpack
    def test_get_period_label(self, aggregate_period, expected_label):
        """Verify that get_period_label returns the correct result"""
        assert self.view.get_period_label(aggregate_period, date(2024, 8, 7)) == expected_label

    @ddt.data(
        ('day', d_t('2024-08-07'), d_t('2024-08-08')),
        ('day', d_t('2024-12-31'), d_t('2025-01-01')),
        ('month', d_t('2024-08-07'), d_t('2024-09-01')),
        ('month', d_t('2024-12-26'), d_t('2025-01-01')),
        ('quarter', d_t('2024-08-07'), d_t('2024-10-01')),
        ('quarter', d_t('2024-12-26'), d_t('2025-01-01')),
        ('year', d_t('2024-08-07'), d_t('2025-01-01')),
    )
    @ddt.unpack
    def test_get_next_period_date(self, aggregate_period, the_date, expected_next_date):
        """Verify that get_next_period_date returns the correct result"""
        assert self.view.get_next_period_date(aggregate_period, the_date) == expected_next_date

    @ddt.data(
        'get_period_label', 'get_next_period_date',
    )
    def test_extractors_bad_period(self, method_name):
        """Verify that extractor methods raise FXCodedException when the period is invalid"""
        with pytest.raises(FXCodedException) as exc_info:
            getattr(self.view, method_name)('invalid-period', date(2024, 8, 7))
        assert exc_info.value.code == FXExceptionCodes.INVALID_INPUT.value
        assert str(exc_info.value) == 'Invalid aggregate_period: invalid-period'

    @ddt.data(
        'get_period_label', 'get_next_period_date',
    )
    def test_get_period_label_bad_date(self, method_name):
        """Verify that extractor methods raise FXCodedException when the date is invalid"""
        with pytest.raises(ValidationError) as exc_info:
            getattr(self.view, method_name)('day', 'not-date-or-datetime')
        assert exc_info.value.message == 'the_date must be a date or datetime object. Got (str)'

    def test_get_data_with_missing_periods_no_data(self):
        """Verify that get_data_with_missing_periods returns an empty list when there is no data"""
        result = self.view.get_data_with_missing_periods([])
        assert not result
        assert isinstance(result, list)

    @ddt.data(
        (d_t('2024-08-07'), None),
        (None, d_t('2024-08-08')),
        (None, None),
    )
    @ddt.unpack
    def test_get_data_with_missing_periods_no_dates(self, date_from, date_to):
        """Verify that get_data_with_missing_periods returns the same data when there are no dates"""
        self.view.date_from = date_from
        self.view.date_to = date_to
        data = [{'label': '2024-12-26', 'value': 3}, {'label': '2024-08-08', 'value': 4}]
        sorted_data = [{'label': '2024-08-08', 'value': 4}, {'label': '2024-12-26', 'value': 3}]

        assert self.view.get_data_with_missing_periods(data) == sorted_data
        assert self.view.get_data_with_missing_periods(data, already_sorted=False) == sorted_data
        assert self.view.get_data_with_missing_periods(data, already_sorted=True) == data

    def test_get_data_with_missing_periods(self):
        """Verify that get_data_with_missing_periods returns the correct result"""
        self.view.date_from = d_t('2024-07-16')
        self.view.date_to = d_t('2025-02-14')
        self.view.aggregate_period = 'month'
        data = [{'label': '2024-12', 'value': 3}, {'label': '2024-08', 'value': 4}]

        assert self.view.get_data_with_missing_periods(data) == [
            {'label': '2024-07', 'value': 0},
            {'label': '2024-08', 'value': 4},
            {'label': '2024-09', 'value': 0},
            {'label': '2024-10', 'value': 0},
            {'label': '2024-11', 'value': 0},
            {'label': '2024-12', 'value': 3},
            {'label': '2025-01', 'value': 0},
            {'label': '2025-02', 'value': 0},
        ]

    def test_get_data_with_missing_periods_protection(self):
        """
        Verify that get_data_with_missing_periods is protected from infinite loops when the data is not sorted, and
        the caller passed already_sorted as True.
        """
        self.view.date_from = d_t('2024-07-16')
        self.view.date_to = d_t('2025-02-14')
        self.view.aggregate_period = 'month'
        data = [{'label': '2024-12', 'value': 3}, {'label': '2024-08', 'value': 4}]

        result = self.view.get_data_with_missing_periods(data, already_sorted=True)
        expected_added_zeros = ['2024-07', '2024-09', '2024-10', '2024-11', '2025-01', '2025-02']
        assert len(result) == 8
        for item in result:
            if item['label'] in expected_added_zeros:
                assert item['value'] == 0, f'{item["label"]} should be added as zero'
            if item['label'] == '2024-08':
                assert item['value'] == 0, '2024-08 should be set to zero because the data is not sorted'
            if item['label'] == '2024-12':
                assert item['value'] == 3, (
                    '2024-12 should be set to the correct value because it\' reached first, and any label less than'
                    ' 2024-12 will be set to zero. This is the correct behavior for a wrong data!'
                )


@pytest.mark.usefixtures('base_data')
class TestLearnersView(BaseTestViewMixin):
    """Tests for LearnersView"""
    VIEW_NAME = 'fx_dashboard:learners'

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_no_tenants(self):
        """Verify that the view returns the result for all accessible tenants when no tenant IDs are provided"""
        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.dashboard.views.get_learners_queryset') as mock_queryset:
            self.client.get(self.url)
            mock_queryset.assert_called_once()
            assert mock_queryset.call_args_list[0][1]['fx_permission_info']['view_allowed_full_access_orgs'] \
                   == get_all_orgs()
            assert mock_queryset.call_args_list[0][1]['search_text'] is None

    def test_search(self):
        """Verify that the view filters the learners by search text"""
        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.dashboard.views.get_learners_queryset') as mock_queryset:
            self.client.get(self.url + '?tenant_ids=1&search_text=user')
            assert mock_queryset.call_args_list[0][1]['fx_permission_info']['view_allowed_tenant_ids_any_access'] == [1]
            assert mock_queryset.call_args_list[0][1]['search_text'] == 'user'

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 37)
        self.assertGreater(len(response.data['results']), 0)


@pytest.mark.usefixtures('base_data')
class TestCoursesView(BaseTestViewMixin):
    """Tests for CoursesView"""
    VIEW_NAME = 'fx_dashboard:courses'

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_no_tenants(self):
        """Verify that the view returns the result for all accessible tenants when no tenant IDs are provided"""
        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.dashboard.views.get_courses_queryset') as mock_queryset:
            self.client.get(self.url)
            assert mock_queryset.call_args_list[0][1]['fx_permission_info']['view_allowed_full_access_orgs'] \
                   == get_all_orgs()
            assert mock_queryset.call_args_list[0][1]['search_text'] is None
            assert mock_queryset.call_args_list[0][1]['visible_filter'] is None

    def test_search(self):
        """Verify that the view filters the courses by search text"""
        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.dashboard.views.get_courses_queryset') as mock_queryset:
            self.client.get(self.url + '?tenant_ids=1&search_text=course')
            assert mock_queryset.call_args_list[0][1]['fx_permission_info']['view_allowed_tenant_ids_any_access'] == [1]
            assert mock_queryset.call_args_list[0][1]['search_text'] == 'course'
            assert mock_queryset.call_args_list[0][1]['visible_filter'] is None

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 18)
        self.assertEqual(len(response.data['results']), 18)

    def test_sorting(self):
        """Verify that the view soring filter is set correctly"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.filter_backends, [DefaultOrderingFilter])


@pytest.mark.usefixtures('base_data')
class TestCourseCourseStatusesView(BaseTestViewMixin):
    """Tests for CourseStatusesView"""
    VIEW_NAME = 'fx_dashboard:course-statuses'

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_no_tenants(self):
        """Verify that the view returns the result for all accessible tenants when no tenant IDs are provided"""
        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.dashboard.views.get_courses_count_by_status') as mock_queryset:
            self.client.get(self.url)
            assert mock_queryset.call_args_list[0][1]['fx_permission_info']['view_allowed_full_access_orgs'] \
                   == get_all_orgs()

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        data = json.loads(response.content)
        self.assertDictEqual(data, {
            'active': 12,
            'archived': 3,
            'upcoming': 2,
            'self_active': 1,
            'self_archived': 0,
            'self_upcoming': 0,
        })


def _mock_get_by_key(username_or_email):
    """Mock get_user_by_key"""
    return get_user_model().objects.get(Q(username=username_or_email) | Q(email=username_or_email))


class PermissionsTestOfLearnerInfoViewMixin:
    """Tests for CourseStatusesView"""
    patching_config = {
        'get_by_key': ('futurex_openedx_extensions.helpers.users.get_user_by_username_or_email', {
            'side_effect': _mock_get_by_key,
        }),
    }

    def setUp(self):
        """Setup"""
        super().setUp()
        self.url_args = ['user10']

    def _get_view_class(self):
        """Helper to get the view class"""
        view_func, _, _ = resolve(self.url)
        return view_func.view_class

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        self.assertEqual(self._get_view_class().permission_classes, [FXHasTenantCourseAccess])

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_user_not_found(self):
        """Verify that the view returns 404 when the user is not found"""
        user_name = 'user10x'
        self.url_args = [user_name]
        assert not get_user_model().objects.filter(username=user_name).exists(), 'bad test data'

        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data, {
            'reason': 'User with username/email (user10x) does not exist!', 'details': {}
        })

    def _get_test_users(self, org3_admin_id, org3_learner_id):
        """Helper to get test users for the test_not_staff_user test"""
        admin_user = get_user_model().objects.get(id=org3_admin_id)
        learner_user = get_user_model().objects.get(id=org3_learner_id)

        self.assertFalse(admin_user.is_staff, msg='bad test data')
        self.assertFalse(admin_user.is_superuser, msg='bad test data')
        self.assertFalse(learner_user.is_staff, msg='bad test data')
        self.assertFalse(learner_user.is_superuser, msg='bad test data')
        self.assertFalse(CourseAccessRole.objects.filter(user_id=org3_learner_id).exists(), msg='bad test data')

        self.login_user(org3_admin_id)
        self.url_args = [f'user{org3_learner_id}']

    def test_org_admin_user_with_allowed_learner(self):
        """Verify that the view returns 200 when the user is an admin on the learner's organization"""
        self._get_test_users(4, 45)
        view_class = self._get_view_class()
        ViewAllowedRoles.objects.create(
            view_name=view_class.fx_view_name,
            view_description=view_class.fx_view_description,
            allowed_role='instructor',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)

    def test_org_admin_user_with_allowed_learner_same_tenant_diff_org(self):
        """
        Verify that the view returns 200 when the user is an admin on the learner's organization, where the user is
        in the same tenant but in an organization that is not included in course_access_roles
        for the admin's organization
        """
        self._get_test_users(4, 52)
        view_class = self._get_view_class()
        ViewAllowedRoles.objects.create(
            view_name=view_class.fx_view_name,
            view_description=view_class.fx_view_description,
            allowed_role='instructor',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)

    def test_org_admin_user_with_not_allowed_learner(self):
        """Verify that the view returns 404 when the user is an org admin but the learner belongs to another org"""
        self._get_test_users(4, 16)
        view_class = self._get_view_class()
        ViewAllowedRoles.objects.create(
            view_name=view_class.fx_view_name,
            view_description=view_class.fx_view_description,
            allowed_role='instructor',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)


@pytest.mark.usefixtures('base_data')
class TestLearnerInfoView(
    PermissionsTestOfLearnerInfoViewMixin, MockPatcherMixin, BaseTestViewMixin,
):  # pylint: disable=too-many-ancestors
    """Tests for CourseStatusesView"""
    VIEW_NAME = 'fx_dashboard:learner-info'

    def test_success(self):
        """Verify that the view returns the correct response"""
        user = get_user_model().objects.get(username='user10')
        user.courses_count = 3
        user.certificates_count = 1
        self.url_args = [user.username]
        self.assertFalse(())

        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.dashboard.views.get_learner_info_queryset') as mock_get_info:
            mock_get_info.return_value = Mock(first=Mock(return_value=user))
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        data = json.loads(response.content)
        self.assertDictEqual(data, serializers.LearnerDetailsExtendedSerializer(user).data)

    @patch('futurex_openedx_extensions.dashboard.views.serializers.LearnerDetailsExtendedSerializer')
    def test_request_in_context(self, mock_serializer):
        """Verify that the view calls the serializer with the correct context"""
        request = self._get_request()
        view_class = self._get_view_class()
        mock_serializer.return_value = Mock(data={})

        with patch('futurex_openedx_extensions.dashboard.views.get_learner_info_queryset') as mock_get_info:
            mock_get_info.return_value = Mock()
            view = view_class()
            view.request = request
            view.get(request, 'user10')

        mock_serializer.assert_called_once_with(
            mock_get_info.return_value.first(),
            context={'request': request},
        )


@patch.object(
    serializers.LearnerCoursesDetailsSerializer,
    'get_grade',
    lambda self, obj: {'letter_grade': 'Pass', 'percent': 0.7, 'is_passing': True}
)
@pytest.mark.usefixtures('base_data')
class TestLearnerCoursesDetailsView(
    PermissionsTestOfLearnerInfoViewMixin, MockPatcherMixin, BaseTestViewMixin,
):  # pylint: disable=too-many-ancestors
    """Tests for LearnerCoursesView"""
    VIEW_NAME = 'fx_dashboard:learner-courses'

    def test_success(self):
        """Verify that the view returns the correct response"""
        user = get_user_model().objects.get(username='user10')
        self.url_args = [user.username]

        courses = CourseOverview.objects.filter(courseenrollment__user=user)
        for course in courses:
            course.enrollment_date = now() - timedelta(days=10)
            course.last_activity = now() - timedelta(days=2)
            course.related_user_id = user.id
            course.save()

        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.dashboard.views.get_learner_courses_info_queryset') as mock_get_info:
            mock_get_info.return_value = courses
            response = self.client.get(self.url)

        assert mock_get_info.call_args_list[0][1]['fx_permission_info']['view_allowed_full_access_orgs'] \
               == get_all_orgs()
        assert mock_get_info.call_args_list[0][1]['user_key'] == 'user10'
        assert mock_get_info.call_args_list[0][1]['visible_filter'] is None
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        data = json.loads(response.content)
        self.assertEqual(len(data), 2)
        self.assertEqual(list(data), list(serializers.LearnerCoursesDetailsSerializer(courses, many=True).data))

    @patch('futurex_openedx_extensions.dashboard.views.serializers.LearnerCoursesDetailsSerializer')
    def test_request_in_context(self, mock_serializer):
        """Verify that the view uses the correct serializer"""
        request = self._get_request()
        view_class = self._get_view_class()

        with patch('futurex_openedx_extensions.dashboard.views.get_learner_courses_info_queryset') as mock_get_info:
            mock_get_info.return_value = Mock()
            view = view_class()
            view.request = request
            view.get(request, 'user10')

        mock_serializer.assert_called_once_with(
            mock_get_info.return_value,
            context={'request': request},
            many=True,
        )


class TestVersionInfoView(BaseTestViewMixin):
    """Tests for VersionInfoView"""
    VIEW_NAME = 'fx_dashboard:version-info'

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.permission_classes, [IsSystemStaff])

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.__version__', new='0.1.dummy'):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(json.loads(response.content), {'version': '0.1.dummy'})


class TestDataExportTasksView(BaseTestViewMixin):
    """Tests for DataExportTasksView"""
    view_actions = ['detail', 'list']

    def set_action(self, action, task_id=1):
        """Set the viewname and client method"""
        self.view_name = f'fx_dashboard:data-export-tasks-{action}'
        self.url_args = []
        if action == 'detail':
            self.url_args = [task_id]

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        registry = {}
        for _, viewset, basename in urls.export_router.registry:
            registry[basename] = viewset

        for action in self.view_actions:
            self.set_action(action)
            view_class = registry['data-export-tasks']
            self.assertEqual(view_class.permission_classes, [FXHasTenantCourseAccess])

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        for action in self.view_actions:
            self.set_action(action)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_non_staff_user(self):
        """Verify that user without required role can not access view."""
        for action in self.view_actions:
            self.set_action(action)
            learner_user = get_user_model().objects.get(id=45)
            self.login_user(learner_user.id)
            response = self.client.get(self.url, {})
            self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_list_success(self):
        """Verify view for list"""
        self.set_action('list')
        request = self._get_request()
        self.login_user(request.user.id)
        task = DataExportTask.objects.create(
            user=request.user,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test.csv',
            progress=1.0,
            tenant_id=1
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], task.id)

    def test_list_user_can_only_view_own_tasks(self):
        """Verify view for list - that the user can only view his tasks"""
        self.set_action('list')
        user1 = get_user_model().objects.get(id=4)
        user2 = get_user_model().objects.get(id=10)
        self.login_user(user1.id)
        user1_task1 = DataExportTask.objects.create(
            user=user1,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test1.csv',
            progress=1.0,
            tenant_id=1
        )
        user1_task2 = DataExportTask.objects.create(
            user=user1,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test2.csv',
            progress=1.0,
            tenant_id=1
        )
        # user1 shouldnt have access to the following task as it is created by user2
        DataExportTask.objects.create(
            user=user2,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test3.csv',
            progress=1.0,
            tenant_id=1
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        self.assertEqual(response.data['results'][0]['id'], user1_task2.id)
        self.assertEqual(response.data['results'][1]['id'], user1_task1.id)

    def test_patch_success(self):
        """Verify view for update"""
        user = get_user_model().objects.get(id=4)
        self.login_user(user.id)
        task = DataExportTask.objects.create(
            user=user,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test.csv',
            progress=1.0,
            notes='dummy',
            tenant_id=1
        )
        self.set_action('detail', task.id)
        new_notes = 'dummy new'
        response = self.client.patch(
            self.url,
            data={'notes': new_notes},
            format='json',
        )
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertEqual(task.notes, new_notes)
        self.assertEqual(response.data['id'], task.id)
        self.assertEqual(response.data['notes'], new_notes)

    def test_patch_user_can_only_edit_own_tasks(self):
        """Verify that the user can only update his tasks"""
        user1 = get_user_model().objects.get(id=4)
        user2 = get_user_model().objects.get(id=10)
        self.login_user(user1.id)
        user1_task = DataExportTask.objects.create(
            user=user1,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test1.csv',
            progress=1.0,
            tenant_id=1
        )
        self.assertEqual(user1_task.notes, '')
        self.set_action('detail', user1_task.id)
        response = self.client.patch(
            self.url,
            data={'notes': 'new notes'},
            format='json',
        )
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        user1_task.refresh_from_db()
        self.assertEqual(user1_task.notes, 'new notes')

        # user1 shouldnt be able to update following as it is created by user2
        user2_task = DataExportTask.objects.create(
            user=user2,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test3.csv',
            progress=1.0,
            tenant_id=1
        )
        self.set_action('detail', user2_task.id)
        response = self.client.patch(
            self.url,
            data={'notes': 'new notes update'},
            format='json',
        )
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_patch_for_non_writable_fields(self):
        """Verify view for non writable fields."""
        user = get_user_model().objects.get(id=4)
        self.login_user(user.id)
        task = DataExportTask.objects.create(
            user=user,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test.csv',
            progress=1.0,
            notes='dummy',
            tenant_id=1
        )
        self.set_action('detail', task.id)
        response = self.client.patch(
            self.url,
            data={'filename': 'newname.csv', 'user': 45},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], task.id)
        # verify filename and user didn't update.
        self.assertEqual(response.data['filename'], 'test.csv')
        self.assertEqual(response.data['user_id'], user.id)

    def test_retrieve_success(self):
        """Verify view for retrieve"""
        user = get_user_model().objects.get(id=4)
        self.login_user(user.id)
        task = DataExportTask.objects.create(
            user=user,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test.csv',
            progress=1.0,
            notes='dummy',
            tenant_id=1
        )
        self.set_action('detail', task.id)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['id'], task.id)

    def test_not_allowed_methods(self):
        """Verify view for not allowed methods."""
        user = get_user_model().objects.get(id=4)
        self.login_user(user.id)
        task = DataExportTask.objects.create(
            user=user,
            status=DataExportTask.STATUS_COMPLETED,
            view_name='exported_files_data',
            filename='test.csv',
            progress=1.0,
            notes='dummy',
            tenant_id=1
        )
        self.set_action('detail', task.id)
        response = self.client.put(
            self.url,
            data={'notes': 'new'},
            format='json',
        )
        self.assertEqual(response.status_code, 405)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 405)
        self.set_action('list', task.id)
        response = self.client.post(self.url, data={
            'user': 1,
            'view_name': 'fake',
            'filename': 'fake.csv',
            'notes': 'fake notes',
            'tenant_id': 1
        })
        self.assertEqual(response.status_code, 405)


@pytest.mark.usefixtures('base_data')
class TestAccessibleTenantsInfoView(BaseTestViewMixin):
    """Tests for AccessibleTenantsInfoView"""
    VIEW_NAME = 'fx_dashboard:accessible-info'

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.permission_classes, [IsAnonymousOrSystemStaff])

    @patch('futurex_openedx_extensions.dashboard.views.get_user_by_username_or_email')
    def test_success(self, mock_get_user):
        """Verify that the view returns the correct response"""
        mock_get_user.return_value = get_user_model().objects.get(username='user4')
        response = self.client.get(self.url, data={'username_or_email': 'dummy, the user loader function is mocked'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertDictEqual(json.loads(response.content), {
            '1': {
                'lms_root_url': 'https://s1.sample.com',
                'studio_root_url': 'https://studio.example.com',
                'platform_name': '', 'logo_image_url': ''
            },
            '2': {
                'lms_root_url': 'https://s2.sample.com',
                'studio_root_url': 'https://studio.example.com',
                'platform_name': '', 'logo_image_url': ''
            },
            '7': {
                'lms_root_url': 'https://s7.sample.com',
                'studio_root_url': 'https://studio.example.com',
                'platform_name': '', 'logo_image_url': ''
            },
        })

    @patch('futurex_openedx_extensions.dashboard.views.get_user_by_username_or_email')
    def test_no_username_or_email(self, mock_get_user):
        """Verify that the view returns the correct response"""
        mock_get_user.side_effect = get_user_model().DoesNotExist()
        response = self.client.get(self.url)
        mock_get_user.assert_called_once_with(None)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertDictEqual(json.loads(response.content), {})

    def test_not_existing_username_or_email(self):
        """Verify that the view returns the correct response"""
        response = self.client.get(self.url, data={'username_or_email': 'dummy'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertDictEqual(json.loads(response.content), {})


@pytest.mark.usefixtures('base_data')
class TestAccessibleTenantsInfoViewV2(BaseTestViewMixin):
    """Tests for AccessibleTenantsInfoViewv2"""
    VIEW_NAME = 'fx_dashboard:accessible-info-v2'

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.permission_classes, [FXHasTenantCourseAccess])

    @patch('futurex_openedx_extensions.dashboard.views.get_user_by_username_or_email')
    def test_success(self, mock_get_user):
        """Verify that the view returns the correct response"""
        mock_get_user.return_value = get_user_model().objects.get(username='user4')
        self.login_user(self.staff_user)
        response = self.client.get(self.url, data={'username_or_email': 'dummy, the user loader function is mocked'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertDictEqual(json.loads(response.content), {
            '1': {
                'lms_root_url': 'https://s1.sample.com',
                'studio_root_url': 'https://studio.example.com',
                'platform_name': '', 'logo_image_url': ''
            },
            '2': {
                'lms_root_url': 'https://s2.sample.com',
                'studio_root_url': 'https://studio.example.com',
                'platform_name': '', 'logo_image_url': ''
            },
            '7': {
                'lms_root_url': 'https://s7.sample.com',
                'studio_root_url': 'https://studio.example.com',
                'platform_name': '', 'logo_image_url': ''
            },
        })

        self.login_user(5)
        response = self.client.get(self.url, data={'username_or_email': 'dummy'})
        self.assertEqual(
            response.status_code,
            http_status.HTTP_403_FORBIDDEN,
            f'Expected 403 for non staf users, but got {response.status_code}'
        )

    @patch('futurex_openedx_extensions.dashboard.views.get_user_by_username_or_email')
    def test_no_username_or_email(self, mock_get_user):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        mock_get_user.side_effect = get_user_model().DoesNotExist()
        response = self.client.get(self.url)
        mock_get_user.assert_called_once_with(None)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertDictEqual(json.loads(response.content), {})

    def test_not_existing_username_or_email(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url, data={'username_or_email': 'dummy'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertDictEqual(json.loads(response.content), {})


@pytest.mark.usefixtures('base_data')
class TestLearnersDetailsForCourseView(BaseTestViewMixin):
    """Tests for LearnersDetailsForCourseView"""
    VIEW_NAME = 'fx_dashboard:learners-course'

    def setUp(self):
        """Setup"""
        super().setUp()
        self.url_args = ['course-v1:ORG1+5+5']

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.permission_classes, [FXHasTenantCourseAccess])

    def test_get_related_id(self):
        """Verify get_related_id returns course_id"""
        view_func, _, kwargs = resolve(self.url)
        view = view_func.view_class()
        view.kwargs = kwargs
        expected_related_id = 'course-v1:ORG1+5+5'
        related_id = view.get_related_id()
        assert expected_related_id == related_id

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        self.assertGreater(len(response.data['results']), 0)


@pytest.mark.usefixtures('base_data')
class TestLearnersEnrollmentView(BaseTestViewMixin):
    """Tests for LearnersEnrollmentView"""
    VIEW_NAME = 'fx_dashboard:learners-enrollements'

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.permission_classes, [FXHasTenantCourseAccess])

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)

        user_id = 15
        course_id = 'course-v1:ORG1+5+5'
        response = self.client.get(self.url, data={'course_ids': course_id, 'user_ids': user_id})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['user_id'], user_id)
        self.assertEqual(response.data['results'][0]['course_id'], course_id)

    def test_success_for_user_ids_and_usernames(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url, data={
            'user_ids': 15,
            'usernames': 'user21, user15',
        })
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 6)
        self.assertEqual(
            set(user_data['user_id'] for user_data in response.data['results']),
            {15, 21}
        )


class MockClickhouseQuery:
    """Mock ClickhouseQuery"""
    def __init__(
        self, query, slug, version, scope, enabled, params_config, paginated
    ):  # pylint: disable=too-many-arguments
        self.query = query
        self.slug = slug
        self.version = version
        self.scope = scope
        self.enabled = enabled
        self.params_config = params_config
        self.paginated = paginated

    def fix_param_types(self, *args, **kwargs):
        """Mock parse_query"""
        return self.query

    @classmethod
    def get_query_record(cls, scope, version, slug):
        """Mock get_query_record"""
        if slug == 'non-existing-query':
            return None

        paginated = not slug.endswith('-nop')

        enabled = 'disabled' not in slug

        query = 'SELECT * FROM table'
        if 'ca-users' in slug:
            query += f' WHERE user_id IN {{{{{cs.CLICKHOUSE_FX_BUILTIN_CA_USERS_OF_TENANTS}}}}}'

        return MockClickhouseQuery(
            query=query,
            slug=slug,
            version=version,
            scope=scope,
            enabled=enabled,
            params_config={},
            paginated=paginated,
        )


class TestGlobalRatingView(BaseTestViewMixin):
    """Tests for GlobalRatingView"""
    VIEW_NAME = 'fx_dashboard:statistics-rating'

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.permission_classes, [FXHasTenantCourseAccess])

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        test_data = {
            'total_rating': 50,
            'courses_count': 2,
            'rating_1_count': 3,
            'rating_2_count': 5,
            'rating_3_count': 2,
            'rating_4_count': 1,
            'rating_5_count': 4,
        }
        expected_result = {
            'total_rating': 50,
            'total_count': 15,
            'courses_count': 2,
            'rating_counts': {
                '1': 3,
                '2': 5,
                '3': 2,
                '4': 1,
                '5': 4,
            },
        }
        for value in range(1, 6):
            assert expected_result['rating_counts'][str(value)] == test_data[f'rating_{value}_count']
        assert expected_result['total_count'] == sum(expected_result['rating_counts'].values())

        with patch('futurex_openedx_extensions.dashboard.views.get_courses_ratings') as mocked_calc:
            mocked_calc.return_value = test_data
            response = self.client.get(self.url)
        data = json.loads(response.content)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(data, expected_result)

    def test_success_no_rating(self):
        """Verify that the view returns the correct response when there are no ratings"""
        self.login_user(self.staff_user)
        with patch('futurex_openedx_extensions.dashboard.views.get_courses_ratings') as mocked_calc:
            mocked_calc.return_value = {
                'total_rating': 0,
                'courses_count': 0,
                'rating_1_count': 0,
                'rating_2_count': 0,
                'rating_3_count': 0,
                'rating_4_count': 0,
                'rating_5_count': 0,
            }
            response = self.client.get(self.url)
        data = json.loads(response.content)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(data, {
            'total_rating': 0,
            'total_count': 0,
            'courses_count': 0,
            'rating_counts': {
                '1': 0,
                '2': 0,
                '3': 0,
                '4': 0,
                '5': 0,
            },
        })


@ddt.ddt
class TestMyRolesView(BaseTestViewMixin):
    """Tests for MyRolesView"""
    VIEW_NAME = 'fx_dashboard:my-roles'

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.permission_classes, [FXHasTenantCourseAccess])

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(3)
        expected_result = {
            'user_id': 3,
            'email': 'user3@example.com',
            'username': 'user3',
            'national_id': '11223344556677',
            'full_name': '',
            'alternative_full_name': '',
            'is_system_staff': False,
            'global_roles': [],
            'tenants': {
                '1': {
                    'tenant_roles': ['staff'],
                    'course_roles': {
                        'course-v1:ORG1+3+3': ['instructor'],
                        'course-v1:ORG1+4+4': ['instructor'],
                    },
                },
            },
        }
        response = self.client.get(self.url)
        data = json.loads(response.content)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertFalse(DeepDiff(data, expected_result))


@ddt.ddt
class TestUserRolesManagementView(BaseTestViewMixin):
    """Tests for UserRolesManagementView for GET list"""
    def set_action(self, action):
        """Set the action"""
        self.view_name = f'fx_dashboard:user-roles-{action}'
        if action == 'detail':
            self.url_args = ['user4']

    def test_dispatch_is_non_atomic(self):
        """Verify that the view has the correct dispatch method"""
        dispatch_method = UserRolesManagementView.dispatch
        is_non_atomic = getattr(dispatch_method, '_non_atomic_requests', False)
        self.assertTrue(
            is_non_atomic,
            'dispatch method should be decorated with non_atomic_requests. atomic is used internally when needed'
        )

    @ddt.data('list', 'detail')
    def test_permission_classes(self, action):
        """Verify that the view has the correct permission classes"""
        self.set_action(action)

        registry = {}
        for _, viewset, basename in urls.roles_router.registry:
            registry[basename] = viewset
        view_class = registry['user-roles']
        self.assertEqual(view_class.permission_classes, [FXHasTenantAllCoursesAccess])

    @ddt.data('list', 'detail')
    def test_unauthorized(self, action):
        """Verify that the view returns 403 when the user is not authenticated"""
        self.set_action(action)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_bad_course_id(self):
        """Verify that the view returns 400 when the course ID is invalid"""
        self.set_action('list')

        self.login_user(self.staff_user)
        response = self.client.get(self.url, data={'only_course_ids': 'course-v1:ORG1+4+4,invalid-course-id'})
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid course ID format: invalid-course-id', response.data['detail'])

    def test_success_list(self):
        """Verify that the view returns the correct response when list action is used"""
        self.set_action('list')

        self.login_user(self.staff_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)

        test_data = get_test_data_dict()
        assert len(response.data['results']) == len(test_data)
        for user_roles in response.data['results']:
            username = user_roles['username']
            assert username in test_data
            del test_data[username]

        assert not test_data

    def test_success_detail(self):
        """Verify that the view returns the correct response when detail action is used"""
        self.set_action('detail')

        self.login_user(self.staff_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)

        assert response.data['tenants'] == {
            1: {'tenant_roles': ['instructor'], 'course_roles': {'course-v1:ORG1+4+4': ['staff']}},
            2: {'tenant_roles': ['instructor'], 'course_roles': {'course-v1:ORG3+1+1': ['staff']}},
            7: {'tenant_roles': ['instructor'], 'course_roles': {'course-v1:ORG3+1+1': ['staff']}}
        }

    @patch('futurex_openedx_extensions.dashboard.views.add_course_access_roles')
    def test_post_success(self, mock_add_users):
        """Verify that the view returns 201 for POST"""
        self.set_action('list')

        self.login_user(self.staff_user)
        mock_add_users.return_value = {
            'failed': [],
            'added': ['shadinaif', 'ahmad@gmail.com'],
            'updated': [10098765],
            'not_updated': [],
        }
        response = self.client.post(
            self.url,
            data={
                'tenant_ids': [9],
                'users': ['shadinaif', 'ahmad@gmail.com', 10098765],
                'role': 'staff',
                'tenant_wide': False,
                'course_ids': ['course-v1:ORG1+TOPIC+2024', 'course-v1:ORG1+TOPIC2+2024'],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.content), mock_add_users.return_value)

    @patch('futurex_openedx_extensions.dashboard.views.add_course_access_roles')
    @ddt.data(
        ('tenant_ids', 'not list', True, 'tenant_ids must be a list of integers'),
        ('tenant_ids', [1, 'not int'], True, 'tenant_ids must be a list of integers'),
        ('users', 'not list', True, 'users must be a list'),
        ('role', ['not str'], True, 'role must be a string'),
        ('tenant_wide', 'not int', True, 'tenant_wide must be an integer flag'),
        ('course_ids', 'not list', False, 'course_ids must be a list'),
    )
    @ddt.unpack
    def test_post_validation_error(
        self, key, value, is_required, error_message, mock_add_users
    ):  # pylint: disable=too-many-arguments
        """Verify that the view returns 400 for POST when the payload is invalid"""
        error_message = f'({FXExceptionCodes.INVALID_INPUT.value}) {error_message}'
        self.set_action('list')
        self.login_user(self.staff_user)
        data = {
            'tenant_ids': [9],
            'users': ['shadinaif', 'ahmad@gmail.com', 10098765],
            'role': 'staff',
            'tenant_wide': False,
            'course_ids': ['course-v1:ORG1+TOPIC+2024', 'course-v1:ORG1+TOPIC2+2024'],
        }

        data.pop(key)
        mock_add_users.return_value = {}
        response = self.client.post(self.url, data=data, format='json')
        if is_required:
            self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data, {
                'reason': f"Missing required parameter: '{key}'", 'details': {}
            })
        else:
            self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)

        data.update({key: value})
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {'reason': error_message, 'details': {}})

    @patch('futurex_openedx_extensions.dashboard.views.add_course_access_roles')
    def test_post_add_validation_error(self, mock_add_users):
        """Verify that the view returns 400 for POST when the payload is invalid"""
        self.set_action('list')
        self.login_user(self.staff_user)
        data = {
            'tenant_ids': [9],
            'users': ['shadinaif', 'ahmad@gmail.com', 10098765],
            'role': 'staff',
            'tenant_wide': False,
            'course_ids': ['course-v1:ORG1+TOPIC+2024', 'course-v1:ORG1+TOPIC2+2024'],
        }

        mock_add_users.side_effect = FXCodedException(
            code=FXExceptionCodes.INVALID_INPUT,
            message='an internal validation error!'
        )
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {'reason': f'({FXExceptionCodes.INVALID_INPUT.value}) an internal validation error!', 'details': {}}
        )

    def test_put_bad_username(self):
        """Verify that the view returns 404 when the given username is invalid"""
        self.set_action('detail')
        self.url_args = ['invalid_username']

        self.login_user(self.staff_user)
        response = self.client.put(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data, {
            'reason': '(1001) User with username/email (invalid_username) does not exist!', 'details': {}
        })

    @patch('futurex_openedx_extensions.dashboard.views.update_course_access_roles')
    @patch('futurex_openedx_extensions.dashboard.views.UserRolesManagementView.verify_username')
    def test_put_failed(self, mock_verify_username, mock_update_users):
        """Verify that the view returns 400 when the fails for any reason"""
        self.set_action('detail')

        self.login_user(self.staff_user)
        mock_verify_username.return_value = {
            'user': get_user_model().objects.get(id=4),
            'key_type': cs.USER_KEY_TYPE_USERNAME,
            'error_code': None,
            'error_message': None,
        }
        mock_update_users.return_value = {
            'error_code': '999',
            'error_message': 'the error message',
        }
        response = self.client.put(self.url)

        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {
            'reason': '(999) the error message', 'details': {}
        })

    @patch('futurex_openedx_extensions.dashboard.views.update_course_access_roles')
    @patch('futurex_openedx_extensions.dashboard.views.UserRolesManagementView.verify_username')
    def test_put_success(self, mock_verify_username, mock_update_users):
        """Verify that the view returns 204 for PUT"""
        self.set_action('detail')

        self.login_user(self.staff_user)
        mock_update_users.return_value = {
            'error_code': None,
            'error_message': None,
        }
        mock_verify_username.return_value = {
            'user': get_user_model().objects.get(id=4),
            'key_type': cs.USER_KEY_TYPE_USERNAME,
            'error_code': None,
            'error_message': None,
        }
        response = self.client.put(self.url, data={'the data': 'whatever, the function is mocked'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['user_id'], 4)

    @patch('futurex_openedx_extensions.dashboard.views.get_user_by_key')
    def test_delete_bad_username(self, mock_get_user):
        """Verify that the view returns 400 when the user tries to delete their own roles"""
        self.set_action('detail')

        mock_get_user.return_value = {
            'user': None,
            'key_type': cs.USER_KEY_TYPE_NOT_ID,
            'error_code': '999',
            'error_message': 'the error message',
        }
        self.url_args = ['invalid_username']

        self.login_user(self.staff_user)
        response = self.client.delete(self.url + '?tenant_ids=1,2')
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data, {'reason': '(999) the error message', 'details': {}})

    @patch('futurex_openedx_extensions.dashboard.views.get_user_by_key')
    def test_delete_missing_required_parameter(self, _):
        """Verify that the view returns 400 when there is a missing required-parameter"""
        self.set_action('detail')

        self.login_user(self.staff_user)
        response = self.client.delete(self.url + '?tenant_ids_not_sent_in_query_params=x')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {'reason': "Missing required parameter: 'tenant_ids'", 'details': {}})

    @patch('futurex_openedx_extensions.dashboard.views.get_user_by_key')
    @patch('futurex_openedx_extensions.dashboard.views.delete_course_access_roles')
    def test_delete_success(self, mock_delete_user, mock_get_user):
        """Verify that the view returns 400 when the user tries to delete their own roles"""
        self.set_action('detail')

        mock_get_user.return_value = {
            'user': get_user_model().objects.get(id=4),
            'key_type': cs.USER_KEY_TYPE_ID,
            'error_code': None,
            'error_message': None,
        }

        self.login_user(self.staff_user)
        response = self.client.delete(self.url + '?tenant_ids=1,2')
        self.assertEqual(response.status_code, http_status.HTTP_204_NO_CONTENT)
        self.assertIsNone(response.data)
        mock_delete_user.call_args_list[0][1].pop('caller')
        mock_delete_user.assert_called_once_with(tenant_ids=[1, 2], user=mock_get_user.return_value['user'])

    @patch('futurex_openedx_extensions.dashboard.views.get_user_by_key')
    @patch('futurex_openedx_extensions.dashboard.views.delete_course_access_roles')
    def test_delete_no_roles_found_for_user(self, mock_delete_user, mock_get_user):
        """Verify that the view returns 404 when no roles are found for the user"""
        self.set_action('detail')

        mock_get_user.return_value = {
            'user': get_user_model().objects.get(id=3),
            'key_type': cs.USER_KEY_TYPE_ID,
            'error_code': None,
            'error_message': None,
        }
        mock_delete_user.side_effect = FXCodedException(999, 'the error message')
        self.login_user(self.staff_user)
        response = self.client.delete(self.url + '?tenant_ids=1')
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertDictEqual(response.data, {'reason': 'the error message', 'details': {}})


@ddt.ddt
class TestClickhouseQueryView(MockPatcherMixin, BaseTestViewMixin):
    """Tests for ClickhouseQueryView"""
    VIEW_NAME = 'fx_dashboard:clickhouse-query'

    patching_config = {
        'get_query_record': ('futurex_openedx_extensions.dashboard.views.ClickhouseQuery.get_query_record', {
            'side_effect': MockClickhouseQuery.get_query_record,
        }),
        'parse_query': ('futurex_openedx_extensions.dashboard.views.ClickhouseQuery.fix_param_types', {
            'side_effect': MockClickhouseQuery.fix_param_types,
        }),
        'get_client': ('futurex_openedx_extensions.helpers.clickhouse_operations.get_client', {}),
        'execute_query': ('futurex_openedx_extensions.helpers.clickhouse_operations.execute_query', {
            'return_value': (100, 2, Mock(column_names=['col_name'], result_rows=[[1]])),
        }),
        'get_usernames_with_access_roles': (
            'futurex_openedx_extensions.dashboard.views.get_usernames_with_access_roles',
            {'return_value': []}
        ),
    }

    def setUp(self):
        """Setup"""
        super().setUp()
        self.url_args = ['course', 'test-query']

    def test_permission_classes(self):
        """Verify that the view has the correct permission classes"""
        view_func, _, _ = resolve(self.url)
        view_class = view_func.view_class
        self.assertEqual(view_class.permission_classes, [FXHasTenantCourseAccess])

    def test_unauthorized(self):
        """Verify that the view returns 403 when the user is not authenticated"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_success(self):
        """Verify that the view returns the correct response"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(json.loads(response.content), {
            'count': 100,
            'next': 'http://testserver/api/fx/query/v1/course/test-query/?page=2',
            'previous': None,
            'results': [{'col_name': 1}]
        })
        self.mocks['get_usernames_with_access_roles'].assert_not_called()

    def test_success_no_pagination(self):
        """Verify that the view returns the correct response when pagination is disabled"""
        self.url_args = ['course', 'test-query-nop']

        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(json.loads(response.content), [{'col_name': 1}])
        self.mocks['get_usernames_with_access_roles'].assert_not_called()

    def test_success_ca_users_needed(self):
        """Verify that the view gets the CA users when the query needs them"""
        self.url_args = ['course', 'test-query-ca-users-nop']
        all_orgs = ['org1', 'org2', 'org3', 'org8', 'org4', 'org5']

        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(json.loads(response.content), [{'col_name': 1}])
        self.mocks['get_usernames_with_access_roles'].assert_called_once_with(all_orgs)

    @ddt.data(
        ('?page=3', 5, '?page=5'),
        ('?page=3', 1, '?page=1'),
        ('?page=3&page_size=33', 5, '?page_size=33&page=5'),
        ('?page=3&whatever=any&page_size=33', 5, '?whatever=any&page_size=33&page=5'),
        ('?page=3&whatever=any&page_size=33', None, None),
    )
    @ddt.unpack
    def test_get_page_url_with_page(self, param_string, new_page_no, expected_result):
        """Verify that get_page_url_with_page returns the correct URL"""
        url = f'http://testserver/api/fx/query/v1/course/test-query/{param_string}'

        if expected_result:
            expected_result = f'http://testserver/api/fx/query/v1/course/test-query/{expected_result}'

        self.assertEqual(views.ClickhouseQueryView.get_page_url_with_page(url, new_page_no), expected_result)

    @ddt.data(
        ({}, True, (1, DefaultPagination.page_size)),
        ({'page': '4'}, True, (4, DefaultPagination.page_size)),
        ({'page': None}, True, (1, DefaultPagination.page_size)),
        ({'page': '2', 'page_size': '23'}, True, (2, 23)),
        ({'page_size': '23'}, True, (1, 23)),
        ({}, False, (None, DefaultPagination.page_size)),
        ({'page': '4'}, False, (None, DefaultPagination.page_size)),
        ({'page': None}, False, (None, DefaultPagination.page_size)),
        ({'page': '2', 'page_size': '23'}, False, (None, 23)),
        ({'page_size': '23'}, False, (None, 23)),
    )
    @ddt.unpack
    def test_pop_out_page_params(self, params, paginated, expected_result):
        """Verify that pop_out_page_params returns the correct page number and page size"""
        self.assertEqual(views.ClickhouseQueryView.pop_out_page_params(params, paginated), expected_result)

    def _assert_not_ok_response(self, status_code, reason):
        """Helper to assert that the response is not OK"""
        self.login_user(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status_code)
        self.assertEqual(response.data, {'details': {}, 'reason': reason})

    def test_query_does_no_exist(self):
        """Verify that the view returns 404 when the query does not exist"""
        self.url_args = ['course', 'non-existing-query']
        self._assert_not_ok_response(
            status_code=404,
            reason='Query not found course.v1.non-existing-query'
        )

    def test_query_not_enabled(self):
        """Verify that the view returns 400 when the query is not enabled"""
        self.url_args = ['course', 'test-query-disabled']
        self._assert_not_ok_response(
            status_code=400,
            reason='Query is disabled course.v1.test-query-disabled'
        )

    def test_empty_page(self):
        """Verify that the view returns 404 when the requested page is empty"""
        self.mocks['execute_query'].side_effect = EmptyPage('wrong page number!')
        self._assert_not_ok_response(
            status_code=404,
            reason='wrong page number!'
        )

    @ddt.data(
        ch.ClickhouseClientNotConfiguredError,
        ch.ClickhouseClientConnectionError,
    )
    def test_clickhouse_connection_error(self, side_effect):
        """Verify that the view returns 503 when there is a Clickhouse connection error"""
        self.mocks['get_client'].side_effect = side_effect('connection issue with clickhouse')
        self._assert_not_ok_response(
            status_code=503,
            reason='connection issue with clickhouse'
        )

    @ddt.data(
        ch.ClickhouseBaseError,
        ValueError,
        ValidationError,
    )
    def test_bad_use_of_arguments(self, side_effect):
        """Verify that the view returns 400 when there is a bad use of arguments"""
        self.mocks['execute_query'].side_effect = side_effect('bad use of arguments')
        self._assert_not_ok_response(
            status_code=400,
            reason='bad use of arguments'
        )
