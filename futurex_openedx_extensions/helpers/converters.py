"""Type conversion helpers"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List
from urllib.parse import urljoin

from dateutil.relativedelta import relativedelta

from futurex_openedx_extensions.helpers import constants as cs


def ids_string_to_list(ids_string: str) -> List[int]:
    """Convert a comma-separated string of ids to a list of integers. Duplicate ids are not removed."""
    if not ids_string:
        return []
    return [int(id_value.strip()) for id_value in ids_string.split(',') if id_value.strip()]


def error_details_to_dictionary(reason: str, **details: Any) -> dict:
    """Constructing the dictionary for error details"""
    return {
        'reason': reason,
        'details': details,
    }


def relative_url_to_absolute_url(relative_url: str, request: Any) -> str | None:
    """Convert a relative URL to an absolute URL"""
    if request and hasattr(request, 'site') and request.site:
        return str(urljoin(request.site.domain, relative_url))

    return None


class DateMethods:
    """Date methods"""
    FMT = '%Y-%m-%d'
    ARG_SEPARATOR = ','
    DATE_METHODS = [
        'today', 'yesterday', 'tomorrow', 'month_start', 'month_end', 'year_start', 'year_end',
        'last_month_start', 'last_month_end', 'next_month_start', 'next_month_end',
        'last_year_start', 'last_year_end', 'next_year_start', 'next_year_end',
        f'days{ARG_SEPARATOR}', f'months{ARG_SEPARATOR}', f'years{ARG_SEPARATOR}',
    ]

    @staticmethod
    def _get_date_method(date_method_name: str) -> Callable:
        """
        Get the date method.

        :param date_method_name: The date method name to get.
        :type date_method_name: str
        :return: The date method.
        :rtype: Callable
        """
        if date_method_name not in DateMethods.DATE_METHODS:
            raise ValueError(f'Invalid date method: {date_method_name}')

        return getattr(DateMethods, date_method_name.split(DateMethods.ARG_SEPARATOR)[0])

    @staticmethod
    def parse_date_method(date_method_string: str) -> str:
        """
        Parse the date method.

        :param date_method_string: The date method to parse.
        :type date_method_string: str
        :return: The parsed date.
        :rtype: str
        """
        if not date_method_string:
            raise ValueError('Date method string is empty')
        date_method_string = date_method_string.strip().lower()

        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_method_string):
            return date_method_string

        splitter = DateMethods.ARG_SEPARATOR

        date_method = date_method_string.split(DateMethods.ARG_SEPARATOR)
        if len(date_method) == 2:
            method = date_method[0].strip()
            try:
                value = int(date_method[1].strip())
            except ValueError as exc:
                raise ValueError(f'Invalid integer given to method: {date_method_string}') from exc
            return DateMethods._get_date_method(f'{method}{splitter}')(value)

        if len(date_method) == 1:
            method = date_method[0]
            return DateMethods._get_date_method(method)()

        raise ValueError(f'Date method contains many separators: {date_method_string}')

    @staticmethod
    def today() -> str:
        """Get today's date"""
        return datetime.now().strftime(DateMethods.FMT)

    @staticmethod
    def yesterday() -> str:
        """Get yesterday's date"""
        return (datetime.now() - timedelta(days=1)).strftime(DateMethods.FMT)

    @staticmethod
    def tomorrow() -> str:
        """Get tomorrow's date"""
        return (datetime.now() + timedelta(days=1)).strftime(DateMethods.FMT)

    @staticmethod
    def month_start() -> str:
        """Get the start of the month"""
        return (datetime.now() + relativedelta(day=1)).strftime(DateMethods.FMT)

    @staticmethod
    def month_end() -> str:
        """Get the end of the month"""
        return (datetime.now() + relativedelta(months=1, day=1) + timedelta(days=-1)).strftime(DateMethods.FMT)

    @staticmethod
    def year_start() -> str:
        """Get the start of the year"""
        return (datetime.now() + relativedelta(month=1, day=1)).strftime(DateMethods.FMT)

    @staticmethod
    def year_end() -> str:
        """Get the end of the year"""
        return (datetime.now() + relativedelta(years=1, month=1, day=1) + timedelta(days=-1)).strftime(DateMethods.FMT)

    @staticmethod
    def last_month_start() -> str:
        """Get the start of the last month"""
        return (datetime.now() + relativedelta(months=-1, day=1)).strftime(DateMethods.FMT)

    @staticmethod
    def last_month_end() -> str:
        """Get the end of the last month"""
        return (datetime.now() + relativedelta(day=1) + timedelta(days=-1)).strftime(DateMethods.FMT)

    @staticmethod
    def next_month_start() -> str:
        """Get the start of the next month"""
        return (datetime.now() + relativedelta(months=1, day=1)).strftime(DateMethods.FMT)

    @staticmethod
    def next_month_end() -> str:
        """Get the end of the next month"""
        return (datetime.now() + relativedelta(months=2, day=1) + timedelta(days=-1)).strftime(DateMethods.FMT)

    @staticmethod
    def last_year_start() -> str:
        """Get the start of the last year"""
        return (datetime.now() + relativedelta(years=-1, month=1, day=1)).strftime(DateMethods.FMT)

    @staticmethod
    def last_year_end() -> str:
        """Get the end of the last year"""
        return (datetime.now() + relativedelta(month=1, day=1) + timedelta(days=-1)).strftime(DateMethods.FMT)

    @staticmethod
    def next_year_start() -> str:
        """Get the start of the next year"""
        return (datetime.now() + relativedelta(years=1, month=1, day=1)).strftime(DateMethods.FMT)

    @staticmethod
    def next_year_end() -> str:
        """Get the end of the next year"""
        return (datetime.now() + relativedelta(years=1, month=12, day=31)).strftime(DateMethods.FMT)

    @staticmethod
    def days(days: int) -> str:
        """Get the date after a number of days"""
        return (datetime.now() + timedelta(days=days)).strftime(DateMethods.FMT)

    @staticmethod
    def months(months: int) -> str:
        """Get the date after a number of months"""
        return (datetime.now() + relativedelta(months=months)).strftime(DateMethods.FMT)

    @staticmethod
    def years(years: int) -> str:
        """Get the date after a number of years"""
        return (datetime.now() + relativedelta(years=years)).strftime(DateMethods.FMT)


def get_allowed_roles(roles_filter: List[str] | None) -> Dict[str, List[str]]:
    """
    Get the refined roles.

    :param roles_filter: The roles to filter.
    :type roles_filter: List[str] | None
    :return: The refined roles.
    :rtype: Dict[str, List[str]]
    """
    allowed_roles = {
        'global': cs.COURSE_ACCESS_ROLES_GLOBAL,
        'tenant_only': cs.COURSE_ACCESS_ROLES_TENANT_ONLY,
        'course_only': cs.COURSE_ACCESS_ROLES_COURSE_ONLY,
        'tenant_or_course': cs.COURSE_ACCESS_ROLES_TENANT_OR_COURSE,
    }
    if roles_filter:
        for role in allowed_roles:
            allowed_roles[role] = list(set(allowed_roles[role]).intersection(roles_filter))

    return allowed_roles
