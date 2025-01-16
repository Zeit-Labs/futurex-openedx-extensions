"""functions for getting statistics about courses"""
from __future__ import annotations

from datetime import date
from typing import Dict

from common.djangoapps.student.models import CourseEnrollment
from django.db.models import Case, CharField, Count, Q, Sum, Value, When
from django.db.models.functions import Coalesce, Lower
from django.db.models.query import QuerySet
from django.utils.timezone import now

from futurex_openedx_extensions.dashboard.details.courses import annotate_courses_rating_queryset
from futurex_openedx_extensions.helpers.constants import COURSE_STATUSES
from futurex_openedx_extensions.helpers.extractors import get_valid_duration
from futurex_openedx_extensions.helpers.querysets import (
    annotate_period,
    check_staff_exist_queryset,
    get_base_queryset_courses,
)


def get_courses_count(
    fx_permission_info: dict, visible_filter: bool | None = True, active_filter: bool | None = None
) -> QuerySet:
    """
    Get the count of courses in the given tenants

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param visible_filter: Value to filter courses on catalog visibility. None means no filter.
    :type visible_filter: bool | None
    :param active_filter: Value to filter courses on active status. None means no filter.
    :type active_filter: bool | None
    :return: QuerySet of courses count per organization
    :rtype: QuerySet
    """
    q_set = get_base_queryset_courses(
        fx_permission_info, visible_filter=visible_filter, active_filter=active_filter
    )

    return q_set.values(org_lower_case=Lower('org')).annotate(
        courses_count=Count('id')
    ).order_by(Lower('org'))


def _get_enrollments_count(
    fx_permission_info: dict,
    visible_filter: bool | None = True,
    active_filter: bool | None = None,
    include_staff: bool = False,
) -> QuerySet:
    """
    Get the count of courses in the given tenants

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param visible_filter: Value to filter courses on catalog visibility. None means no filter.
    :type visible_filter: bool | None
    :param active_filter: Value to filter courses on active status. None means no filter.
    :type active_filter: bool | None
    :param include_staff: Value to include staff users in the count. False means exclude staff users.
    :type include_staff: bool
    :return: QuerySet of courses count per organization
    :rtype: QuerySet
    """
    q_set = CourseEnrollment.objects.filter(
        course_id__in=get_base_queryset_courses(
            fx_permission_info, visible_filter=visible_filter, active_filter=active_filter
        ).values_list('id', flat=True),
        is_active=True,
    ).exclude(
        Q(user__is_active=False) | Q(user__is_staff=True) | Q(user__is_superuser=True)
    )

    if not include_staff:
        q_set = q_set.exclude(check_staff_exist_queryset('user_id', 'course__org', 'course_id'))

    return q_set


def get_enrollments_count(
    fx_permission_info: dict,
    visible_filter: bool | None = True,
    active_filter: bool | None = None,
    include_staff: bool = False,
) -> QuerySet:
    """
    Get the count of courses in the given tenants

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param visible_filter: Value to filter courses on catalog visibility. None means no filter.
    :type visible_filter: bool | None
    :param active_filter: Value to filter courses on active status. None means no filter.
    :type active_filter: bool | None
    :param include_staff: Value to include staff users in the count. False means exclude staff users.
    :type include_staff: bool
    :return: QuerySet of courses count per organization
    :rtype: QuerySet
    """
    q_set = _get_enrollments_count(
        fx_permission_info, visible_filter=visible_filter, active_filter=active_filter, include_staff=include_staff,
    )

    return q_set.values(org_lower_case=Lower('course__org')).annotate(
        enrollments_count=Count('id')
    ).order_by(Lower('course__org'))


def get_enrollments_count_aggregated(  # pylint: disable=too-many-arguments
    fx_permission_info: dict,
    visible_filter: bool | None = True,
    active_filter: bool | None = None,
    include_staff: bool = False,
    aggregate_period: str = 'month',
    date_from: date | None = None,
    date_to: date | None = None,
) -> QuerySet:
    """
    Get the count of enrollments in the given tenants aggregated by period. The query will return a limited number of
    period values, depending on the date range and the period.

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param visible_filter: Value to filter courses on catalog visibility. None means no filter.
    :type visible_filter: bool | None
    :param active_filter: Value to filter courses on active status. None means no filter.
    :type active_filter: bool | None
    :param include_staff: Value to include staff users in the count. False means exclude staff users.
    :type include_staff: bool
    :param aggregate_period: Period to aggregate the count of enrollments. Possible values are 'day', 'week', 'month'.
    :type aggregate_period: str
    :param date_from: Start date to filter enrollments (inclusive). None means no filter.
    :type date_from: date | None
    :param date_to: End date to filter enrollments (inclusive). None means no filter.
    :type date_to: date | None
    """
    date_from, date_to = get_valid_duration(aggregate_period, date_from, date_to)

    q_set = _get_enrollments_count(
        fx_permission_info, visible_filter=visible_filter, active_filter=active_filter, include_staff=include_staff,
    )

    if date_from:
        q_set = q_set.filter(created__gte=date_from)
    if date_to:
        q_set = q_set.filter(created__lte=date_to)

    q_set = annotate_period(q_set, aggregate_period, 'created')

    q_set = q_set.values('period').annotate(
        enrollments_count=Count('id')
    ).order_by('period')

    return q_set


def get_courses_count_by_status(
    fx_permission_info: dict, visible_filter: bool | None = True, active_filter: bool | None = None
) -> QuerySet:
    """
    Get the count of courses in the given tenants by status

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param visible_filter: Value to filter courses on catalog visibility. None means no filter
    :type visible_filter: bool | None
    :param active_filter: Value to filter courses on active status. None means no filter (according to dates)
    :type active_filter: bool | None
    :return: QuerySet of courses count per organization and status
    :rtype: QuerySet
    """
    q_set = get_base_queryset_courses(
        fx_permission_info, visible_filter=visible_filter, active_filter=active_filter
    )

    q_set = q_set.annotate(
        status=Case(
            When(
                Q(end__isnull=False) & Q(end__lt=now()),
                then=Value(COURSE_STATUSES['archived'])
            ),
            When(
                Q(start__isnull=False) & Q(start__gt=now()),
                then=Value(COURSE_STATUSES['upcoming'])
            ),
            default=Value(COURSE_STATUSES['active']),
            output_field=CharField()
        )
    ).values('status', 'self_paced').annotate(
        courses_count=Count('id')
    ).values('status', 'self_paced', 'courses_count')

    return q_set


def get_courses_ratings(
    fx_permission_info: dict,
    visible_filter: bool | None = True,
    active_filter: bool | None = None,
) -> Dict[str, int]:
    """
    Get the average rating of courses in the given tenants

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param visible_filter: Value to filter courses on catalog visibility. None means no filter
    :type visible_filter: bool | None
    :param active_filter: Value to filter courses on active status. None means no filter (according to dates)
    :type active_filter: bool | None
    :return: Dictionary containing the total rating, courses count, and rating count per rating value
    :rtype: Dict[str, int]
    """
    q_set = get_base_queryset_courses(
        fx_permission_info, visible_filter=visible_filter, active_filter=active_filter
    )

    q_set = annotate_courses_rating_queryset(q_set).filter(rating_count__gt=0)

    q_set = q_set.annotate(**{
        f'course_rating_{rate_value}_count': Count(
            'feedbackcourse',
            filter=Q(feedbackcourse__rating_content=rate_value)
        ) for rate_value in range(1, 6)
    })

    return q_set.aggregate(
        total_rating=Coalesce(Sum('rating_total'), 0),
        courses_count=Coalesce(Count('id'), 0),
        **{
            f'rating_{rate_value}_count': Coalesce(Sum(f'course_rating_{rate_value}_count'), 0)
            for rate_value in range(1, 6)
        }
    )
