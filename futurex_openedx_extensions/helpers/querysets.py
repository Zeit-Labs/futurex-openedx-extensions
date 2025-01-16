"""Helper functions for working with Django querysets."""
from __future__ import annotations

from typing import Any, List

from common.djangoapps.student.models import CourseAccessRole, CourseEnrollment, UserSignupSource
from django.contrib.auth import get_user_model
from django.db.models import BooleanField, Case, CharField, Count, Exists, F, OuterRef, Q, Value, When
from django.db.models.functions import (
    Cast,
    Concat,
    ExtractDay,
    ExtractMonth,
    ExtractQuarter,
    ExtractWeek,
    ExtractYear,
    Right,
)
from django.db.models.query import QuerySet
from django.utils.timezone import now
from opaque_keys.edx.django.models import CourseKeyField
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

from futurex_openedx_extensions.helpers.converters import get_allowed_roles
from futurex_openedx_extensions.helpers.exceptions import FXCodedException, FXExceptionCodes
from futurex_openedx_extensions.helpers.extractors import get_partial_access_course_ids, verify_course_ids
from futurex_openedx_extensions.helpers.tenants import get_tenants_sites
from futurex_openedx_extensions.helpers.users import get_user_by_key


def verify_queryset_removable_annotations(queryset: QuerySet) -> None:
    """
    Verify that the queryset has the removable annotations set.

    :param queryset: QuerySet to verify
    :type queryset: QuerySet
    """
    if not hasattr(queryset, 'removable_annotations'):
        return

    for key in queryset.removable_annotations:
        if isinstance(queryset.query.annotations.get(key, None), Count):
            raise FXCodedException(
                code=FXExceptionCodes.QUERY_SET_BAD_OPERATION,
                message=(
                    f'Cannot set annotation `{key}` of type `Count` as removable. You must unset it from the '
                    f'removable annotations list, or replace the `Count` annotation with `Subquery`.'
                ),
            )


def update_removable_annotations(
    queryset: QuerySet,
    removable: set | List[str] | None = None,
    not_removable: set | List[str] | None = None,
) -> None:
    """
    Update the removable annotations on the given queryset.

    :param queryset: QuerySet to update
    :type queryset: QuerySet
    :param removable: Set of annotations to add to the removable annotations
    :type removable: set(str) | List[str] | None
    :param not_removable: Set of annotations to remove from the removable annotations
    :type not_removable: set(str) | List[str] | None
    """
    removable_annotations = queryset.removable_annotations if hasattr(queryset, 'removable_annotations') else set()
    removable_annotations = (removable_annotations | set(removable or [])) - set(not_removable or [])

    if not removable_annotations and hasattr(queryset, 'removable_annotations'):
        del queryset.removable_annotations

    elif removable_annotations:
        queryset.removable_annotations = removable_annotations
        verify_queryset_removable_annotations(queryset)


def clear_removable_annotations(queryset: QuerySet) -> None:
    """
    Clear the removable annotations on the given queryset.

    :param queryset: QuerySet to clear the removable annotations from
    :type queryset: QuerySet
    """
    if hasattr(queryset, 'removable_annotations'):
        del queryset.removable_annotations


def check_staff_exist_queryset(
    ref_user_id: str | Value,
    ref_org: str | Value | List | None,
    ref_course_id: str | Value | None,
    roles_filter: List[str] | None = None,
) -> Exists:
    """
    Get the queryset of users who are staff.

    :param ref_user_id: Reference to the user ID
    :type ref_user_id: str | Value
    :param ref_org: Reference to the organization
    :type ref_org: str | Value | List | None
    :param ref_course_id: Reference to the course ID
    :type ref_course_id: str | Value | None
    :param roles_filter: List of allowed roles
    :type roles_filter: List[str] | None
    :return: QuerySet of users
    :rtype: Exists
    """
    if isinstance(ref_user_id, str):
        ref_user_id = OuterRef(ref_user_id)
    elif not isinstance(ref_user_id, Value):
        raise ValueError(f'Invalid ref_user_id type ({type(ref_user_id).__name__})')

    if isinstance(ref_org, str):
        org_query = Q(org=OuterRef(ref_org))
    elif isinstance(ref_org, list):
        org_query = Q(org__in=ref_org)
    else:
        raise ValueError(f'Invalid ref_org type ({type(ref_org).__name__})')

    if isinstance(ref_course_id, str):
        course_query = Q(course_id=OuterRef(ref_course_id))
        course_empty_query = Q(course_id=CourseKeyField.Empty)
    elif isinstance(ref_course_id, Value):
        course_query = Q(course_id=ref_course_id)
        course_empty_query = Q(course_id=CourseKeyField.Empty)
    elif ref_course_id is None:
        course_query = Q(Value(True, output_field=BooleanField()))
        course_empty_query = course_query
    else:
        raise ValueError(f'Invalid ref_course_id type ({type(ref_course_id).__name__})')

    allowed_roles = get_allowed_roles(roles_filter)

    return Exists(
        CourseAccessRole.objects.filter(
            user_id=ref_user_id,
        ).filter(
            Q(role__in=allowed_roles['global']) |
            (
                Q(role__in=allowed_roles['tenant_only']) &
                org_query
            ) |
            (
                Q(role__in=allowed_roles['course_only']) &
                org_query & course_query
            ) |
            (
                Q(role__in=allowed_roles['tenant_or_course']) &
                org_query &
                (course_query | course_empty_query)
            ),
        ),
    )


def get_base_queryset_courses(
    fx_permission_info: dict,
    visible_filter: bool | None = True,
    active_filter: bool | None = None,
) -> QuerySet:
    """
    Get the default course queryset for the given filters.

    include_staff flag is not needed, because we're dealing with courses here, not users.

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param visible_filter: Value to filter courses on catalog visibility. None means no filter.
    :type visible_filter: bool | None
    :param active_filter: Value to filter courses on active status. None means no filter.
    :type active_filter: bool | None
    :return: QuerySet of courses
    :rtype: QuerySet
    """
    now_time = now()
    course_is_active_queryset = (
        (Q(start__isnull=True) | Q(start__lte=now_time)) &
        (Q(end__isnull=True) | Q(end__gte=now_time))
    )

    course_is_visible_queryset = Q(catalog_visibility__in=['about', 'both']) & Q(visible_to_staff_only=False)

    q_set = CourseOverview.objects.filter(org__in=fx_permission_info['view_allowed_any_access_orgs'])

    if not fx_permission_info['is_system_staff_user']:
        q_set = q_set.filter(check_staff_exist_queryset(
            ref_user_id=Value(fx_permission_info['user'].id),
            ref_org='org',
            ref_course_id='id',
            roles_filter=fx_permission_info['view_allowed_roles'],
        ))

    q_set = q_set.annotate(
        course_is_active=Case(
            When(course_is_active_queryset, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
    ).annotate(
        course_is_visible=Case(
            When(course_is_visible_queryset, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
    )

    update_removable_annotations(q_set, removable=['course_is_active', 'course_is_visible'])

    if active_filter is not None:
        q_set = q_set.filter(course_is_active=active_filter)
        update_removable_annotations(q_set, not_removable=['course_is_active'])

    if visible_filter is not None:
        q_set = q_set.filter(course_is_visible=visible_filter)
        update_removable_annotations(q_set, not_removable=['course_is_visible'])

    return q_set


def get_learners_search_queryset(  # pylint: disable=too-many-arguments
    search_text: str | None = None,
    superuser_filter: bool | None = False,
    staff_filter: bool | None = False,
    active_filter: bool | None = True,
    user_ids: List[int] | None = None,
    usernames: List[str] | None = None,
) -> QuerySet:
    """
    Get the learners queryset for the given search text.

    :param search_text: Search text to filter the learners by
    :type search_text: str | None
    :param superuser_filter: Value to filter superusers. None means no filter
    :type superuser_filter: bool | None
    :param staff_filter: Value to filter staff users. None means no filter
    :type staff_filter: bool | None
    :param active_filter: Value to filter active users. None means no filter
    :type active_filter: bool | None
    :return: QuerySet of learners
    :rtype: QuerySet
    """
    queryset = get_user_model().objects.all()

    if superuser_filter is not None:
        queryset = queryset.filter(is_superuser=superuser_filter)
    if staff_filter is not None:
        queryset = queryset.filter(is_staff=staff_filter)
    if active_filter is not None:
        queryset = queryset.filter(is_active=active_filter)

    search_text = (search_text or '').strip()
    if search_text:
        queryset = queryset.filter(
            Q(username__icontains=search_text) |
            Q(extrainfo__national_id__icontains=search_text) |
            Q(email__icontains=search_text) |
            Q(profile__name__icontains=search_text)
        )

    user_filter = Q()
    if user_ids:
        invalid_user_ids = [user_id for user_id in user_ids if not isinstance(user_id, int)]
        if invalid_user_ids:
            raise FXCodedException(
                code=FXExceptionCodes.INVALID_INPUT,
                message=f'Invalid user ids: {invalid_user_ids}',
            )
        user_filter |= Q(id__in=user_ids)
    if usernames:
        invalid_usernames = [username for username in usernames if not isinstance(username, str)]
        if invalid_usernames:
            raise FXCodedException(
                code=FXExceptionCodes.INVALID_INPUT,
                message=f'Invalid usernames: {invalid_usernames}',
            )
        user_filter |= Q(username__in=usernames)

    queryset = queryset.filter(user_filter)

    return queryset


def get_course_search_queryset(
    fx_permission_info: dict,
    search_text: str | None = None,
    course_ids: List[str] | None = None,
) -> QuerySet:
    """
    Get the courses queryset for the given search text.

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param search_text: Search text to filter the courses by
    :type search_text: str | None
    :return: QuerySet of courses
    :rtype: QuerySet
    """
    queryset = CourseOverview.objects.filter(
        Q(id__in=get_partial_access_course_ids(fx_permission_info)) |
        Q(org__in=fx_permission_info['view_allowed_full_access_orgs'])
    )
    if course_ids:
        verify_course_ids(course_ids)
        queryset = queryset.filter(id__in=course_ids)

    course_search = (search_text or '').strip()
    if course_search:
        queryset = queryset.filter(
            Q(display_name__icontains=course_search) |
            Q(id__icontains=course_search),
        )

    return queryset


def get_permitted_learners_queryset(
    queryset: QuerySet,
    fx_permission_info: dict,
    include_staff: bool = False,
) -> QuerySet:
    """
    Get the learners queryset after applying permissions from fx_permission_info.

    :param queryset: QuerySet of learners
    :type queryset: QuerySet
    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param include_staff: flag to include staff users
    :type include_staff: bool
    :return: QuerySet of learners
    :rtype: QuerySet
    """
    tenant_sites = get_tenants_sites(fx_permission_info['view_allowed_tenant_ids_full_access'])

    if not include_staff:
        queryset = queryset.exclude(
            check_staff_exist_queryset(
                ref_user_id='id',
                ref_org=fx_permission_info['view_allowed_any_access_orgs'],
                ref_course_id=None
            )
        )

    users_filter = Exists(
        UserSignupSource.objects.filter(user_id=OuterRef('id'), site__in=tenant_sites)
    )
    if fx_permission_info['view_allowed_tenant_ids_partial_access']:
        users_filter |= Exists(
            CourseEnrollment.objects.filter(
                user_id=OuterRef('id'),
                course_id__in=get_partial_access_course_ids(fx_permission_info),
            )
        )

    queryset = queryset.filter(users_filter)

    return queryset


def get_one_user_queryset(
    fx_permission_info: dict, user_key: get_user_model | int | str, include_staff: bool = False,
) -> QuerySet:
    """
    Get the queryset of one user by the given user key.

    :param fx_permission_info: Dictionary containing permission information
    :type fx_permission_info: dict
    :param user_key: User key to get the user by
    :type user_key: get_user_model | int | str
    :param include_staff: flag to include staff users
    :type include_staff: bool
    :return: QuerySet of users (filtered on one user)
    :rtype: QuerySet
    """
    user_key_info = get_user_by_key(user_key, fail_if_inactive=True)
    user: get_user_model = user_key_info['user']
    if user_key_info['error_code'] is not None:
        raise FXCodedException(user_key_info['error_code'], str(user_key_info['error_message']))

    queryset = get_permitted_learners_queryset(
        queryset=get_user_model().objects.filter(id=user.id),
        fx_permission_info=fx_permission_info,
        include_staff=include_staff,
    )

    if not queryset.exists():
        raise FXCodedException(
            code=FXExceptionCodes.USER_QUERY_NOT_PERMITTED,
            message=(
                f'Caller ({fx_permission_info["user"].username}) is not permitted to query user '
                f'({user.username}).'
            )
        )

    return queryset


def annotate_period(query_set: QuerySet, period: str, field_name: str) -> QuerySet:
    """
    Annotate the queryset with the given period.

    :param query_set: QuerySet to annotate
    :type query_set: QuerySet
    :param period: Period to annotate by
    :type period: str
    :param field_name: Field name to annotate
    :type field_name: str
    :return: Annotated queryset
    """
    def _zero_pad(field: Any) -> Any:
        """Ensures extracted integers (day, month, week) are zero-padded to 2 digits."""
        return Right(Concat(Value('0'), Cast(field, CharField())), 2)

    match period:
        case 'day':
            period_function = Concat(
                Cast(ExtractYear(F(field_name)), CharField()),
                Value('-'),
                _zero_pad(ExtractMonth(F(field_name))),
                Value('-'),
                _zero_pad(ExtractDay(F(field_name))),
                output_field=CharField(),
            )
        case 'week':
            period_function = Concat(
                Cast(ExtractYear(F(field_name)), CharField()),
                Value('-W'),
                _zero_pad(ExtractWeek(F(field_name))),
                output_field=CharField(),
            )
        case 'month':
            period_function = Concat(
                Cast(ExtractYear(F(field_name)), CharField()),
                Value('-'),
                _zero_pad(ExtractMonth(F(field_name))),
                output_field=CharField(),
            )
        case 'quarter':
            period_function = Concat(
                Cast(ExtractYear(F(field_name)), CharField()),
                Value('-Q'),
                Cast(ExtractQuarter(F(field_name)), CharField()),
                output_field=CharField(),
            )
        case 'year':
            period_function = Cast(ExtractYear(F(field_name)), CharField())
        case _:
            raise FXCodedException(
                code=FXExceptionCodes.INVALID_INPUT,
                message=f'Invalid aggregate_period ({period})',
            )

    return query_set.annotate(
        period=period_function,
    )
