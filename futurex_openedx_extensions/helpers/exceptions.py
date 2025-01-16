"""Custom exceptions for the FutureX Open edX Extensions app."""
from __future__ import annotations

from enum import Enum


class FXExceptionCodes(Enum):
    """Role types."""
    UNKNOWN_ERROR = 0

    USER_NOT_FOUND = 1001
    USER_IS_NOT_ACTIVE = 1002
    USER_EMAIL_CONFLICT = 1003
    USER_QUERY_NOT_PERMITTED = 1004

    ROLE_DELETE = 2001
    ROLE_CREATE = 2002
    ROLE_USELESS_ENTRY = 2003
    ROLE_UNSUPPORTED = 2004
    ROLE_INVALID_ENTRY = 2005
    ROLE_INACTIVE = 2006
    ROLE_UPDATE = 2007

    BAD_HASH_CODE = 3001

    INVALID_INPUT = 4001

    COURSE_CREATOR_NOT_FOUND = 5001
    COURSE_EFFORT_NOT_FOUND = 5002

    EXPORT_CSV_VIEW_RESPONSE_FAILURE = 6001
    EXPORT_CSV_MISSING_REQUIRED_PARAMS = 6002
    EXPORT_CSV_TASK_NOT_FOUND = 6003
    EXPORT_CSV_TASK_CHANGE_STATUS_NOT_POSSIBLE = 6004
    EXPORT_CSV_TASK_CANNOT_CHANGE_PROGRESS = 6005
    EXPORT_CSV_TASK_INVALID_PROGRESS_VALUE = 6006
    EXPORT_CSV_VIEW_INVALID_URL = 6007
    EXPORT_CSV_BAD_URL = 6008

    SERIALIZER_FILED_NAME_DOES_NOT_EXIST = 7001

    QUERY_SET_BAD_OPERATION = 8001
    QUERY_SET_DB_VENDOR_NOT_SUPPORTED = 8002

    CUSTOM_ROLE_DUPLICATE_DECLARATION = 9001


class FXCodedException(Exception):
    """Exception with a code."""
    def __init__(self, code: FXExceptionCodes | int, message: str) -> None:
        """Initialize the exception."""
        super().__init__(message)
        if isinstance(code, FXExceptionCodes):
            self.code = code.value
        # check if integer that is part of the FXExceptionCodes enum
        elif isinstance(code, int):
            if code in [e.value for e in FXExceptionCodes]:
                self.code = code
            else:
                self.code = FXExceptionCodes.UNKNOWN_ERROR.value
        else:
            self.code = FXExceptionCodes.UNKNOWN_ERROR.value
