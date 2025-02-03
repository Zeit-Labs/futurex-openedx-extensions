"""Helper functions for FutureX Open edX Extensions."""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List
from urllib.parse import urlparse

from dateutil.relativedelta import relativedelta
from django.conf import settings
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from xmodule.modulestore.django import modulestore

from futurex_openedx_extensions.helpers import constants as cs
from futurex_openedx_extensions.helpers.exceptions import FXCodedException, FXExceptionCodes


@dataclass
class DictHashcode:
    """Class for keeping track of a dictionary hashcode."""
    dict_item: dict
    separator: str = ','

    def __init__(self, dict_item: Dict[str, Any], separator: str = ',') -> None:
        """Accepts a dict and saves a hashcode"""
        if not isinstance(dict_item, dict):
            raise TypeError(f'DictHashcode accepts only dict type. Got: {type(dict_item).__name__}')
        self.dict_item = dict_item
        self.separator = separator

        self.hash_code = separator.join(str(item[1]) for item in sorted(dict_item.items()))

    def __hash__(self) -> int:
        """Enables the object is usable for hash based operations"""
        return hash(self.hash_code)

    def __eq__(self, other: Any) -> bool:
        """Enables the object is usable for equality based operations"""
        if isinstance(other, DictHashcode):
            return self.hash_code == other.hash_code

        return False


class DictHashcodeSet:
    """Class for keeping track of a set of dictionary hashcodes."""

    def __init__(self, dict_list: List[Dict[str, Any]], separator: str = ',') -> None:
        """Accepts a list of dicts and saves a set of hashcodes"""
        if not isinstance(dict_list, list):
            raise TypeError(f'DictHashcodeSet accepts only list type. Got: {type(dict_list).__name__}')

        self.separator = separator
        self._dict_hash_codes = set()
        for dict_item in dict_list:
            self._dict_hash_codes.add(DictHashcode(dict_item=dict_item, separator=separator))

    def __contains__(self, dict_item: Dict | DictHashcode) -> bool:
        """Check if the dict_item is in the hash_codes set."""
        if not isinstance(dict_item, (dict, DictHashcode)):
            return False

        if isinstance(dict_item, dict):
            dict_item = DictHashcode(dict_item=dict_item, separator=self.separator)

        return dict_item in self._dict_hash_codes

    def __eq__(self, other: Any) -> bool:
        """Check if the other object is equal to the hash_codes set."""
        if isinstance(other, DictHashcodeSet):
            return self._dict_hash_codes == other.dict_hash_codes

        if isinstance(other, set):
            return self._dict_hash_codes == other

        return False

    @property
    def dict_hash_codes(self) -> set:
        """Get the set of dictionary hashcodes."""
        return self._dict_hash_codes


def get_course_id_from_uri(uri: str) -> str | None:
    """
    Extract the course_id from the URI.

    :param uri: URI to extract the course_id from.
    :type uri: str
    :return: Course ID extracted from the URI.
    :rtype: str | None
    """
    path_parts = urlparse(uri).path.split('/')
    for part in path_parts:
        result = re.search(cs.COURSE_ID_REGX_EXACT, part)
        if result:
            return result.groupdict().get('course_id')

    return None


def get_first_not_empty_item(items: List, default: Any = None) -> Any:
    """
    Return the first item in the list that is not empty.

    :param items: List of items to check.
    :type items: List
    :param default: Default value to return if no item is found.
    :type default: Any
    :return: First item that is not empty.
    :rtype: Any
    """
    return next((item for item in items if item), default)


def verify_course_ids(course_ids: List[str]) -> None:
    """
    Verify that all course IDs in the list are in valid format. Raise an error if any course ID is invalid.

    :param course_ids: List of course IDs to verify.
    :type course_ids: List[str]
    """
    if course_ids is None:
        raise FXCodedException(
            code=FXExceptionCodes.INVALID_INPUT,
            message='course_ids must be a list of course IDs, but got None',
        )

    for course_id in course_ids:
        if not isinstance(course_id, str):
            raise FXCodedException(
                code=FXExceptionCodes.INVALID_INPUT,
                message=f'course_id must be a string, but got {type(course_id).__name__}',
            )
        if not re.search(cs.COURSE_ID_REGX_EXACT, course_id) and not re.search(cs.LIBRARY_ID_REGX_EXACT, course_id):
            raise FXCodedException(
                code=FXExceptionCodes.INVALID_INPUT,
                message=f'Invalid course ID format: {course_id}',
            )


def get_orgs_of_courses(course_ids: List[str]) -> Dict[str, Any]:
    """
    Get the organization of the courses with the given course IDs.


    :param course_ids: List of course IDs to get the organization of.
    :type course_ids: List[str]
    :return: Dictionary containing the organization of each course ID.
    :rtype: Dict[str, Any]
    """
    verify_course_ids(course_ids)

    courses = CourseOverview.objects.filter(id__in=course_ids)

    result: Dict[str, Any] = {
        'courses': {str(course.id): course.org.lower() for course in courses},
    }

    result['courses'].update({
        str(lib_key): lib_key.org.lower()
        for lib_key in modulestore().get_library_keys()
        if str(lib_key) in course_ids
    })

    invalid_course_ids = [course_id for course_id in course_ids if course_id not in result['courses']]
    if invalid_course_ids:
        raise ValueError(f'Invalid course IDs provided: {invalid_course_ids}')

    return result


def get_partial_access_course_ids(fx_permission_info: dict) -> List[str]:
    """
    Get the course IDs that the user has partial access to according to the permission information.

    Note: remember that the user can have a course-specific role on one course, but that course is already
    accessible by another tenant-wide role. Therefore, that course is not considered as a partial access course.

    :param fx_permission_info: Dictionary containing permission information.
    :type fx_permission_info: dict
    :return: List of course IDs that the user has partial access to.
    :rtype: List[str]
    """
    if fx_permission_info['is_system_staff_user']:
        return []

    role_keys = set(fx_permission_info['view_allowed_roles']) & set(fx_permission_info['user_roles'])
    if role_keys & set(cs.COURSE_ACCESS_ROLES_GLOBAL):
        return []

    course_ids_to_check = set()
    for role_key in role_keys:
        course_ids_to_check.update(fx_permission_info['user_roles'][role_key]['course_limited_access'])

    only_limited_access = CourseOverview.objects.filter(
        id__in=list(course_ids_to_check),
        org__in=fx_permission_info['view_allowed_course_access_orgs'],
    ).values_list('id', flat=True)

    return [str(course_id) for course_id in only_limited_access]


def import_from_path(import_path: str) -> Any:
    """
    Import a class, function, or a variable from the given path. The path should be formatted as
    `module.module.module::class_or_method_or_variable_name`. The path should not contain any whitespace. Only one
    `module` is mandatory, but the rest is optional.

    :param import_path: Path to import the class, function, or variable from.
    :type import_path: str
    :return: Imported class, function, or variable.
    :rtype: Any
    """
    import_path_pattern = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*::[a-zA-Z_][a-zA-Z0-9_]*$')

    if not import_path_pattern.match(import_path):
        raise ValueError(
            'Invalid import path used with import_from_path. The path should be formatted as '
            '`module.module.module::class_or_method_or_variable_name`.'
        )

    module_path, target_object = import_path.split('::', 1)
    return getattr(importlib.import_module(module_path), target_object)


def get_optional_field_class() -> Any:
    return import_from_path(
        'futurex_openedx_extensions.dashboard.serializers::SerializerOptionalMethodField'
    )


def get_available_optional_field_tags(serializer_class_path: str) -> Dict[str, List[str]]:
    """
    Get the available optional field tags of the serializer class.

    :param serializer_class_path: Name of the serializer class. See `import_from_path` for the format.
    :type serializer_class_path: str
    :return: Available optional field tags of the serializer class.
    :rtype: Dict(str, List[str])
    """
    result: Dict[str, List[str]] = {}
    for field_name, field in import_from_path(serializer_class_path)().fields.items():
        if not issubclass(field.__class__, get_optional_field_class()):
            continue

        for tag in field.field_tags:
            if tag not in result:
                result[tag] = []
            result[tag].append(field_name)

    return result


def get_available_optional_field_tags_docs_table(serializer_class_path: str) -> str:
    """
    Get the available optional field tags of the serializer class in a markdown table format.

    :param serializer_class_path: Name of the serializer class. See `import_from_path` for the format.
    :type serializer_class_path: str
    :return: Available optional field tags of the serializer class in a markdown table format.
    :rtype: str
    """
    tags = get_available_optional_field_tags(serializer_class_path)
    tags = dict(sorted(tags.items()))
    result = ''
    for tag, fields in tags.items():
        tag = tag.replace('_', '\\_')
        result += f'| {tag} | {", ".join([f"`{field}`" for field in fields])} |\n'
    result += '----------------\n'

    return result


def get_valid_date_duration(
    period: str,
    date_point: date,
    target_forward: bool,
    max_chunks: int = 0,
) -> date | None:
    """
    Get the date point after/before the given period and date range. If max_chunks is 0, it will use the default value
    for the period from settings. If max_chunks is negative, it will return None.

    :param period: Period type to use. Possible values are 'day', 'week', 'month', 'quarter', and 'year'.
    :type period: str
    :param date_point: date point to start from or end to.
    :type date_point: date
    :param target_forward: True to get the date after date_point, False to get the date before it.
    :type target_forward: bool
    :param max_chunks: Maximum number of chunks to return. 0 means as default, negative means no limit.
    :type max_chunks: int | None
    :return: date_to for the given period and date range. Or None if no limit.
    :rtype: date | None
    """
    period = period.lower()
    if period not in ['day', 'week', 'month', 'quarter', 'year']:
        raise FXCodedException(
            code=FXExceptionCodes.INVALID_INPUT,
            message=f'Invalid period value: {period}',
        )

    if not isinstance(date_point, date):
        raise FXCodedException(
            code=FXExceptionCodes.INVALID_INPUT,
            message=f'get_valid_date_duration: invalid date type {date_point.__class__.__name__}',
        )

    if max_chunks == 0:
        max_chunks = settings.FX_MAX_PERIOD_CHUNKS.get(period, 0)

    if max_chunks > 0:
        match period:
            case 'day':
                delta_days = relativedelta(days=max_chunks)
            case 'week':
                delta_days = relativedelta(weeks=max_chunks)
            case 'month':
                delta_days = relativedelta(months=max_chunks)
            case 'quarter':
                delta_days = relativedelta(months=3 * max_chunks)
            case _:  # 'year'
                delta_days = relativedelta(years=max_chunks)

        if target_forward:
            target_date = date_point + delta_days
        else:
            target_date = date_point - delta_days
    else:
        target_date = None

    return target_date


def get_max_valid_date_to(
    period: str,
    date_from: date,
    max_chunks: int = 0,
) -> date | None:
    """
    Get the maximum possible date_to value for the given period and date range.

    :param period: Period type to use. Possible values are 'day', 'week', 'month', 'quarter', and 'year'.
    :type period: str
    :param date_from: date point to start from.
    :type date_from: date
    :param max_chunks: Maximum number of chunks to return. 0 means as default, negative means no limit.
    :type max_chunks: int | None
    :return: date_to for the given period and date range. Or None if no limit.
    :rtype: date | None
    """
    return get_valid_date_duration(period=period, date_point=date_from, target_forward=True, max_chunks=max_chunks)


def get_min_valid_date_from(
    period: str,
    date_to: date,
    max_chunks: int = 0,
) -> date | None:
    """
    Get the minimum possible date_from value for the given period and date range.

    :param period: Period type to use. Possible values are 'day', 'week', 'month', 'quarter', and 'year'.
    :type period: str
    :param date_to: date point to end to.
    :type date_to: date
    :param max_chunks: Maximum number of chunks to return. 0 means as default, negative means no limit.
    :type max_chunks: int | None
    :return: date_to for the given period and date range. Or None if no limit.
    :rtype: date | None
    """
    return get_valid_date_duration(period=period, date_point=date_to, target_forward=False, max_chunks=max_chunks)


def get_valid_duration(
    period: str,
    date_from: date | None,
    date_to: date | None,
    favours_backward: bool = True,
    max_chunks: int = 0,
) -> tuple[date | None, date | None]:
    """
    Get the valid date range for the given period and date range. If favours_forward is True, it will favour the
    forward direction. If max_chunks is 0, it will use the default value for the period from settings. If max_chunks is
    negative, it will return None.

    :param period: Period type to use. Possible values are 'day', 'week', 'month', 'quarter', and 'year'.
    :type period: str
    :param date_from: date point to start from.
    :type date_from: date | None
    :param date_to: date point to end to.
    :type date_to: date | None
    :param favours_backward: True to favour the backward direction, False to favour the forward direction.
    :type favours_backward: bool
    :param max_chunks: Maximum number of chunks to return. 0 means as default, negative means no limit.
    :type max_chunks: int | None
    :return: date_from and date_to for the given period and date range.
    :rtype: Tuple[date | None, date | None]
    """
    if date_from is None and date_to is None:
        date_to = date.today()

    if date_from is None:
        date_from = get_min_valid_date_from(period, date_to, max_chunks)  # type: ignore
    elif date_to is None:
        date_to = get_max_valid_date_to(period, date_from, max_chunks)
    else:
        if favours_backward:
            date_from = get_min_valid_date_from(period, date_to, max_chunks) or date_from
        else:
            date_to = get_max_valid_date_to(period, date_from, max_chunks) or date_to

    return date_from, date_to
