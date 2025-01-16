"""Serializers for the dashboard details API."""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from common.djangoapps.student.models import CourseEnrollment
from django.contrib.auth import get_user_model
from django.utils.timezone import now
from lms.djangoapps.courseware.courses import get_course_blocks_completion_summary
from lms.djangoapps.grades.api import CourseGradeFactory
from lms.djangoapps.grades.context import grading_context_for_course
from lms.djangoapps.grades.models import PersistentSubsectionGrade
from opaque_keys.edx.locator import CourseLocator
from openedx.core.djangoapps.content.block_structure.api import get_block_structure_manager
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.user_api.accounts.serializers import AccountLegacyProfileSerializer
from openedx.core.lib.courses import get_course_by_id
from rest_framework import serializers
from rest_framework.fields import empty

from futurex_openedx_extensions.dashboard.custom_serializers import (
    ModelSerializerOptionalFields,
    SerializerOptionalMethodField,
)
from futurex_openedx_extensions.helpers.certificates import get_certificate_url
from futurex_openedx_extensions.helpers.constants import (
    COURSE_ACCESS_ROLES_GLOBAL,
    COURSE_STATUS_SELF_PREFIX,
    COURSE_STATUSES,
)
from futurex_openedx_extensions.helpers.converters import relative_url_to_absolute_url
from futurex_openedx_extensions.helpers.export_csv import get_exported_file_url
from futurex_openedx_extensions.helpers.models import DataExportTask
from futurex_openedx_extensions.helpers.roles import (
    RoleType,
    get_course_access_roles_queryset,
    get_user_course_access_roles,
)
from futurex_openedx_extensions.helpers.tenants import get_tenants_by_org

# class NoneFieldRemoverMixin:
#     """Mixin to remove None fields from the response."""
#
#     def to_representation(self, instance: Any) -> Any:
#         """Return the representation of the instance."""
#         representation = super().to_representation(instance)
#         return {key: value for key, value in representation.items() if value is not None}


class DataExportTaskSerializer(ModelSerializerOptionalFields):
    """Serializer for Data Export Task"""
    download_url = SerializerOptionalMethodField(field_tags=['download_url'])

    class Meta:
        model = DataExportTask
        fields = [
            'id',
            'user_id',
            'tenant_id',
            'status',
            'progress',
            'view_name',
            'related_id',
            'filename',
            'notes',
            'created_at',
            'started_at',
            'completed_at',
            'download_url',
            'error_message',
        ]
        read_only_fields = [
            field.name for field in DataExportTask._meta.fields if field.name not in ['notes']
        ]

    def validate_notes(self: Any, value: str) -> str:  # pylint: disable=no-self-use
        """Sanitize the notes field and escape HTML tags."""
        value = re.sub(r'<', '&lt;', value)
        value = re.sub(r'>', '&gt;', value)
        return value

    def get_download_url(self, obj: DataExportTask) -> Any:  # pylint: disable=no-self-use
        """Return download url."""
        return get_exported_file_url(obj)


class LearnerBasicDetailsSerializer(ModelSerializerOptionalFields):
    """Serializer for learner's basic details."""
    user_id = serializers.SerializerMethodField(help_text='User ID in edx-platform')
    full_name = serializers.SerializerMethodField(help_text='Full name of the user')
    alternative_full_name = serializers.SerializerMethodField(help_text='Arabic name (if available)')
    username = serializers.SerializerMethodField(help_text='Username of the user in edx-platform')
    national_id = serializers.SerializerMethodField(help_text='National ID of the user (if available)')
    email = serializers.SerializerMethodField(help_text='Email of the user in edx-platform')
    mobile_no = serializers.SerializerMethodField(help_text='Mobile number of the user (if available)')
    year_of_birth = serializers.SerializerMethodField(help_text='Year of birth of the user (if available)')
    gender = serializers.SerializerMethodField(help_text='Gender code of the user (if available)')
    gender_display = serializers.SerializerMethodField(help_text='Gender of the user (if available)')
    date_joined = serializers.SerializerMethodField(
        help_text='Date when the user was registered in the platform regardless of which tenant',
    )
    last_login = serializers.SerializerMethodField(help_text='Date when the user last logged in')

    class Meta:
        model = get_user_model()
        fields = [
            'user_id',
            'full_name',
            'alternative_full_name',
            'username',
            'national_id',
            'email',
            'mobile_no',
            'year_of_birth',
            'gender',
            'gender_display',
            'date_joined',
            'last_login',
        ]

    @staticmethod
    def _is_english(text: str) -> bool:
        """
        Checks if a string consists only of characters in the ASCII range (a-z, A-Z, 0-9, and common symbols).

        This method is very basic and may miss valid English text with non-ASCII characters.
        """
        return all(ord(char) < 128 for char in text)

    def _get_user(self, obj: Any = None) -> get_user_model | None:  # pylint: disable=no-self-use
        """
        Retrieve the associated user for the given object.

        This method can be overridden in child classes to provide a different
        implementation for accessing the user, depending on how the user is
        related to the object (e.g., `obj.user`, `obj.profile.user`, etc.).
        """
        return obj

    def _get_name(self, obj: Any, alternative: bool = False) -> str:
        """
        Calculate the full name and alternative full name. We have two issues in the data:
        1. The first and last names in auth.user contain many records with identical values (redundant data).
        2. The name field in the profile sometimes contains data while the first and last names are empty.

        :param obj: The user object.
        :type obj: Any
        :param alternative: Whether to return the alternative full name.
        :type alternative: bool
        :return: The full name or alternative full name.
        """
        first_name = self._get_user(obj).first_name.strip()  # type: ignore
        last_name = self._get_user(obj).last_name.strip()  # type: ignore

        full_name = first_name or last_name
        if first_name and last_name and not (first_name == last_name and ' ' in first_name):
            full_name = ' '.join(filter(None, (first_name, last_name)))

        profile_name = self._get_profile_field(obj, 'name')
        alt_name = profile_name.strip() if profile_name else ''

        if not full_name:
            full_name, alt_name = alt_name, ''

        if alt_name and not self._is_english(alt_name):
            full_name, alt_name = alt_name, full_name

        return alt_name if alternative else full_name

    def _get_arabic_name(self, obj: Any) -> str:
        """
        Get arabic name of user

        :param obj: The user object.
        :type obj: Any
        :return: The arabic name of user.
        """
        arabic_name = (self._get_extra_field(obj, 'arabic_name') or '').strip()
        if arabic_name:
            return arabic_name

        arabic_first_name = self._get_extra_field(obj, 'arabic_first_name')
        arabic_last_name = self._get_extra_field(obj, 'arabic_last_name')
        arabic_full_name = arabic_first_name or arabic_last_name
        if arabic_first_name and arabic_last_name and not arabic_first_name == arabic_last_name:
            arabic_full_name = ' '.join(filter(None, (arabic_first_name, arabic_last_name)))
        return (arabic_full_name or '').strip()

    def _get_profile_field(self: Any, obj: get_user_model, field_name: str) -> Any:
        """Get the profile field value."""
        user = self._get_user(obj)
        return getattr(user.profile, field_name) if hasattr(user, 'profile') and user.profile else None

    def _get_extra_field(self: Any, obj: get_user_model, field_name: str) -> Any:
        """Get the extra field value."""
        user = self._get_user(obj)
        return getattr(user.extrainfo, field_name) if hasattr(user, 'extrainfo') and user.extrainfo else None

    def get_user_id(self, obj: get_user_model) -> int:
        """Return user ID."""
        return self._get_user(obj).id  # type: ignore

    def get_email(self, obj: get_user_model) -> str:
        """Return user ID."""
        return self._get_user(obj).email  # type: ignore

    def get_username(self, obj: get_user_model) -> str:
        """Return user ID."""
        return self._get_user(obj).username  # type: ignore

    def get_date_joined(self, obj: Any) -> str | None:
        date_joined = self._get_user(obj).date_joined  # type: ignore
        return date_joined.isoformat() if date_joined else None

    def get_last_login(self, obj: Any) -> str | None:
        last_login = self._get_user(obj).last_login  # type: ignore
        return last_login.isoformat() if last_login else None

    def get_national_id(self, obj: get_user_model) -> Any:
        """Return national ID."""
        return self._get_extra_field(obj, 'national_id')

    def get_full_name(self, obj: get_user_model) -> Any:
        """Return full name."""
        return self._get_name(obj)

    def get_alternative_full_name(self, obj: get_user_model) -> Any:
        """Return alternative full name."""
        return self._get_arabic_name(obj) or self._get_name(obj, alternative=True)

    def get_mobile_no(self, obj: get_user_model) -> Any:
        """Return mobile number."""
        return self._get_profile_field(obj, 'phone_number')

    def get_gender(self, obj: get_user_model) -> Any:
        """Return gender."""
        return self._get_profile_field(obj, 'gender')

    def get_gender_display(self, obj: get_user_model) -> Any:
        """Return readable text for gender"""
        return self._get_profile_field(obj, 'gender_display')

    def get_year_of_birth(self, obj: get_user_model) -> Any:
        """Return year of birth."""
        return self._get_profile_field(obj, 'year_of_birth')


class CourseScoreAndCertificateSerializer(ModelSerializerOptionalFields):
    """
    Course Score and Certificate Details Serializer

    Handles data for multiple courses, but exam_scores is included only for a single course when course_id is
    provided in the context. Otherwise, exam_scores is excluded, even if requested in requested_optional_field_tags.
    """
    exam_scores = SerializerOptionalMethodField(field_tags=['exam_scores', 'csv_export'])
    certificate_available = serializers.BooleanField()
    course_score = serializers.FloatField()
    active_in_course = serializers.BooleanField()
    progress = SerializerOptionalMethodField(field_tags=['progress', 'csv_export'])
    certificate_url = SerializerOptionalMethodField(field_tags=['certificate_url', 'csv_export'])

    class Meta:
        fields = [
            'certificate_available',
            'course_score',
            'active_in_course',
            'progress',
            'certificate_url',
            'exam_scores',
        ]

    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize the serializer."""
        super().__init__(*args, **kwargs)
        self._is_exam_name_in_header = self.context.get('omit_subsection_name', '0') != '1'
        self._grading_info: Dict[str, Any] = {}
        self._subsection_locations: Dict[str, Any] = {}

        if self.context.get('course_id'):
            self.collect_grading_info()

    def collect_grading_info(self) -> None:
        """
        Collect the grading info.
        """
        course_id = CourseLocator.from_string(self.context.get('course_id'))
        self._grading_info = {}
        self._subsection_locations = {}
        if not self.is_optional_field_requested('exam_scores'):
            return

        grading_context = grading_context_for_course(get_course_by_id(course_id))
        index = 0
        for assignment_type_name, subsection_infos in grading_context['all_graded_subsections_by_type'].items():
            for subsection_index, subsection_info in enumerate(subsection_infos, start=1):
                header_enum = f' {subsection_index}' if len(subsection_infos) > 1 else ''
                header_name = f'{assignment_type_name}{header_enum}'
                if self.is_exam_name_in_header:
                    header_name += f': {subsection_info["subsection_block"].display_name}'

                self._grading_info[str(index)] = {
                    'header_name': header_name,
                    'location': str(subsection_info['subsection_block'].location),
                }
                self._subsection_locations[str(subsection_info['subsection_block'].location)] = str(index)
                index += 1

    @property
    def is_exam_name_in_header(self) -> bool:
        """Check if the exam name is needed in the header."""
        return self._is_exam_name_in_header

    @property
    def grading_info(self) -> Dict[str, Any]:
        """Get the grading info."""
        return self._grading_info

    @property
    def subsection_locations(self) -> Dict[str, Any]:
        """Get the subsection locations."""
        return self._subsection_locations

    def _get_course_id(self, obj: Any = None) -> Any:
        """Get the course ID. Its helper method required for CourseScoreAndCertificateSerializer"""
        raise NotImplementedError('Child class must implement _get_user method.')

    def _get_user(self, obj: Any = None) -> Any:
        """Get the User. Its helper method required for CourseScoreAndCertificateSerializer"""
        raise NotImplementedError('Child class must implement _get_course_id method.')

    def get_certificate_url(self, obj: Any) -> Any:
        """Return the certificate URL."""
        return get_certificate_url(
            self.context.get('request'), self._get_user(obj), self._get_course_id(obj)
        )

    def get_progress(self, obj: Any) -> Any:
        """Return the certificate URL."""
        progress_info = get_course_blocks_completion_summary(
            self._get_course_id(obj), self._get_user(obj)
        )
        total = progress_info['complete_count'] + progress_info['incomplete_count'] + progress_info['locked_count']
        return round(progress_info['complete_count'] / total, 4) if total else 0.0

    def get_exam_scores(self, obj: Any) -> Dict[str, Tuple[float, float] | None]:
        """Return exam scores."""
        result: Dict[str, Tuple[float, float] | None] = {__index: None for __index in self.grading_info}
        grades = PersistentSubsectionGrade.objects.filter(
            user_id=self._get_user(obj).id,
            course_id=self._get_course_id(obj),
            usage_key__in=self.subsection_locations.keys(),
            first_attempted__isnull=False,
        ).values('usage_key', 'earned_all', 'possible_all')

        for grade in grades:
            result[self.subsection_locations[str(grade['usage_key'])]] = (grade['earned_all'], grade['possible_all'])

        return result

    def to_representation(self, instance: Any) -> Any:
        """Return the representation of the instance."""
        def _extract_exam_scores(representation_item: dict[str, Any]) -> None:
            exam_scores = representation_item.pop('exam_scores', {})
            for index, score in exam_scores.items():
                earned_key = f'earned - {self.grading_info[index]["header_name"]}'
                possible_key = f'possible - {self.grading_info[index]["header_name"]}'
                representation_item[earned_key] = score[0] if score else 'no attempt'
                representation_item[possible_key] = score[1] if score else 'no attempt'

        representation = super().to_representation(instance)

        _extract_exam_scores(representation)

        return representation


class LearnerDetailsSerializer(LearnerBasicDetailsSerializer):
    """Serializer for learner details."""
    enrolled_courses_count = serializers.SerializerMethodField(help_text='Number of courses the user is enrolled in')
    certificates_count = serializers.SerializerMethodField(help_text='Number of certificates the user has earned')

    class Meta:
        model = get_user_model()
        fields = LearnerBasicDetailsSerializer.Meta.fields + [
            'enrolled_courses_count',
            'certificates_count',
        ]

    def get_certificates_count(self, obj: get_user_model) -> Any:  # pylint: disable=no-self-use
        """Return certificates count."""
        return obj.certificates_count

    def get_enrolled_courses_count(self, obj: get_user_model) -> Any:  # pylint: disable=no-self-use
        """Return enrolled courses count."""
        return obj.courses_count


class LearnerDetailsForCourseSerializer(
    LearnerBasicDetailsSerializer, CourseScoreAndCertificateSerializer
):  # pylint: disable=too-many-ancestors
    """Serializer for learner details for a course."""

    class Meta:
        model = get_user_model()
        fields = LearnerBasicDetailsSerializer.Meta.fields + CourseScoreAndCertificateSerializer.Meta.fields

    def _get_course_id(self, obj: Any = None) -> CourseLocator:
        """Get the course ID. Its helper method required for CourseScoreAndCertificateSerializer"""
        return CourseLocator.from_string(self.context.get('course_id'))

    def _get_user(self, obj: Any = None) -> get_user_model:
        """Get the User. Its helper method required for CourseScoreAndCertificateSerializer"""
        return obj


class LearnerEnrollmentSerializer(
    LearnerBasicDetailsSerializer, CourseScoreAndCertificateSerializer
):  # pylint: disable=too-many-ancestors
    """Serializer for learner enrollments"""
    course_id = serializers.SerializerMethodField()

    class Meta:
        model = CourseEnrollment
        fields = (
            LearnerBasicDetailsSerializer.Meta.fields +
            CourseScoreAndCertificateSerializer.Meta.fields +
            ['course_id']
        )

    def _get_course_id(self, obj: Any = None) -> CourseLocator | None:
        """Get the course ID. Its helper method required for CourseScoreAndCertificateSerializer"""
        return obj.course_id if obj else None

    def _get_user(self, obj: Any = None) -> get_user_model | None:
        """
        Get the User. Its helper method required for CourseScoreAndCertificateSerializer. It also
        plays important role for LearnerBasicDetailsSerializer
        """
        return obj.user if obj else None

    def get_course_id(self, obj: Any) -> str:
        """Get course id"""
        return str(self._get_course_id(obj))


class LearnerDetailsExtendedSerializer(LearnerDetailsSerializer):  # pylint: disable=too-many-ancestors
    """Serializer for extended learner details."""
    city = serializers.SerializerMethodField()
    bio = serializers.SerializerMethodField()
    level_of_education = serializers.SerializerMethodField()
    social_links = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    profile_link = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = LearnerDetailsSerializer.Meta.fields + [
            'city',
            'bio',
            'level_of_education',
            'social_links',
            'image',
            'profile_link',
        ]

    def get_city(self, obj: get_user_model) -> Any:
        """Return city."""
        return self._get_profile_field(obj, 'city')

    def get_bio(self, obj: get_user_model) -> Any:
        """Return bio."""
        return self._get_profile_field(obj, 'bio')

    def get_level_of_education(self, obj: get_user_model) -> Any:
        """Return level of education."""
        return self._get_profile_field(obj, 'level_of_education_display')

    def get_social_links(self, obj: get_user_model) -> Any:  # pylint: disable=no-self-use
        """Return social links."""
        result = {}
        profile = obj.profile if hasattr(obj, 'profile') else None
        if profile:
            links = profile.social_links.all().order_by('platform')
            for link in links:
                result[link.platform] = link.social_link
        return result

    def get_image(self, obj: get_user_model) -> Any:
        """Return image."""
        if hasattr(obj, 'profile') and obj.profile:
            return AccountLegacyProfileSerializer.get_profile_image(
                obj.profile, obj, self.context.get('request')
            )['image_url_large']

        return None

    def get_profile_link(self, obj: get_user_model) -> Any:
        """Return profile link."""
        return relative_url_to_absolute_url(f'/u/{obj.username}/', self.context.get('request'))


class CourseDetailsBaseSerializer(serializers.ModelSerializer):
    """Serializer for course details."""
    status = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    start_enrollment_date = serializers.SerializerMethodField()
    end_enrollment_date = serializers.SerializerMethodField()
    display_name = serializers.CharField()
    image_url = serializers.SerializerMethodField()
    org = serializers.CharField()
    tenant_ids = serializers.SerializerMethodField()

    class Meta:
        model = CourseOverview
        fields = [
            'id',
            'status',
            'self_paced',
            'start_date',
            'end_date',
            'start_enrollment_date',
            'end_enrollment_date',
            'display_name',
            'image_url',
            'org',
            'tenant_ids',
        ]

    def get_status(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the course status."""
        now_time = now()
        if obj.end and obj.end < now_time:
            status = COURSE_STATUSES['archived']
        elif obj.start and obj.start > now_time:
            status = COURSE_STATUSES['upcoming']
        else:
            status = COURSE_STATUSES['active']

        return f'{COURSE_STATUS_SELF_PREFIX if obj.self_paced else ""}{status}'

    def get_start_enrollment_date(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the start enrollment date."""
        return obj.enrollment_start

    def get_end_enrollment_date(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the end enrollment date."""
        return obj.enrollment_end

    def get_image_url(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the course image URL."""
        return obj.course_image_url

    def get_tenant_ids(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the tenant IDs."""
        return get_tenants_by_org(obj.org)

    def get_start_date(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the start date."""
        return obj.start

    def get_end_date(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the end date."""
        return obj.end


class CourseDetailsSerializer(CourseDetailsBaseSerializer):
    """Serializer for course details."""
    rating = serializers.SerializerMethodField()
    enrolled_count = serializers.IntegerField()
    active_count = serializers.IntegerField()
    certificates_count = serializers.IntegerField()
    completion_rate = serializers.FloatField()

    class Meta:
        model = CourseOverview
        fields = CourseDetailsBaseSerializer.Meta.fields + [
            'rating',
            'enrolled_count',
            'active_count',
            'certificates_count',
            'completion_rate',
        ]

    def get_rating(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the course rating."""
        return round(obj.rating_total / obj.rating_count if obj.rating_count else 0, 1)


class LearnerCoursesDetailsSerializer(CourseDetailsBaseSerializer):
    """Serializer for learner's courses details."""
    enrollment_date = serializers.DateTimeField()
    last_activity = serializers.DateTimeField()
    certificate_url = serializers.SerializerMethodField()
    progress_url = serializers.SerializerMethodField()
    grades_url = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    grade = serializers.SerializerMethodField()

    class Meta:
        model = CourseOverview
        fields = CourseDetailsBaseSerializer.Meta.fields + [
            'enrollment_date',
            'last_activity',
            'certificate_url',
            'progress_url',
            'grades_url',
            'progress',
            'grade',
        ]

    def get_certificate_url(self, obj: CourseOverview) -> Any:
        """Return the certificate URL."""
        user = get_user_model().objects.get(id=obj.related_user_id)
        return get_certificate_url(self.context.get('request'), user, obj.id)

    def get_progress_url(self, obj: CourseOverview) -> Any:
        """Return the certificate URL."""
        return relative_url_to_absolute_url(
            f'/learning/course/{obj.id}/progress/{obj.related_user_id}/',
            self.context.get('request')
        )

    def get_grades_url(self, obj: CourseOverview) -> Any:
        """Return the certificate URL."""
        return relative_url_to_absolute_url(
            f'/gradebook/{obj.id}/',
            self.context.get('request')
        )

    def get_progress(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the certificate URL."""
        user = get_user_model().objects.get(id=obj.related_user_id)
        return get_course_blocks_completion_summary(obj.id, user)

    def get_grade(self, obj: CourseOverview) -> Any:  # pylint: disable=no-self-use
        """Return the grade summary."""
        collected_block_structure = get_block_structure_manager(obj.id).get_collected()
        course_grade = CourseGradeFactory().read(
            get_user_model().objects.get(id=obj.related_user_id),
            collected_block_structure=collected_block_structure
        )

        return {
            'percent': course_grade.percent,
            'letter_grade': course_grade.letter_grade,
            'is_passing': course_grade.passed,
        }


class UserRolesSerializer(LearnerBasicDetailsSerializer):
    """Serializer for user roles."""
    tenants = serializers.SerializerMethodField()
    global_roles = serializers.SerializerMethodField()

    def __init__(self, instance: Any | None = None, data: Any = empty, **kwargs: Any):
        """Initialize the serializer."""
        self._org_tenant: dict[str, list[int]] = {}
        self._roles_data: dict[Any, Any] = {}

        permission_info = kwargs['context']['request'].fx_permission_info
        self.orgs_filter = permission_info['view_allowed_any_access_orgs']
        self.permitted_tenant_ids = permission_info['view_allowed_tenant_ids_any_access']
        self.query_params = self.parse_query_params(kwargs['context']['request'].query_params)

        if instance:
            self.construct_roles_data(instance if isinstance(instance, list) else [instance])

        super().__init__(instance, data, **kwargs)

    @staticmethod
    def parse_query_params(query_params: dict[str, Any]) -> dict[str, Any]:
        """
        Parse the query parameters.

        :param query_params: The query parameters.
        :type query_params: dict[str, Any]
        """
        result = {
            'search_text': query_params.get('search_text', ''),
            'course_ids_filter': query_params[
                'only_course_ids'
            ].split(',') if query_params.get('only_course_ids') else [],
            'roles_filter': query_params.get('only_roles', '').split(',') if query_params.get('only_roles') else [],
        }

        if query_params.get('active_users_filter') is not None:
            result['active_filter'] = query_params['active_users_filter'] == '1'
        else:
            result['active_filter'] = None

        excluded_role_types = query_params.get('excluded_role_types', '').split(',') \
            if query_params.get('excluded_role_types') else []

        result['excluded_role_types'] = []
        if 'global' in excluded_role_types:
            result['excluded_role_types'].append(RoleType.GLOBAL)

        if 'tenant' in excluded_role_types:
            result['excluded_role_types'].append(RoleType.ORG_WIDE)

        if 'course' in excluded_role_types:
            result['excluded_role_types'].append(RoleType.COURSE_SPECIFIC)

        return result

    def get_org_tenants(self, org: str) -> list[int]:
        """
        Get the tenants for an organization.

        :param org: The organization to get the tenants for.
        :type org: str
        :return: The tenants.
        :rtype: list[int]
        """
        result = self._org_tenant.get(org)
        if not result:
            result = get_tenants_by_org(org)
            self._org_tenant[org] = result

        return result or []

    def construct_roles_data(self, users: list[get_user_model]) -> None:
        """
        Construct the roles data.

        {
            "<userID>": {
                "<tenantID>": {
                    "tenant_roles": ["<roleName>", "<roleName>"],
                    "course_roles": {
                        "<courseID>": ["<roleName>", "<roleName>"],
                        "<courseID>": ["<roleName>", "<roleName>"],
                    },
                },
                ....
            },
            ....
        }

        :param users: The user instances.
        :type users: list[get_user_model]
        """
        self._roles_data = {}
        for user in users:
            self._roles_data[user.id] = {}

        records = get_course_access_roles_queryset(
            self.orgs_filter,
            remove_redundant=True,
            users=users,
            search_text=self.query_params['search_text'],
            roles_filter=self.query_params['roles_filter'],
            active_filter=self.query_params['active_filter'],
            course_ids_filter=self.query_params['course_ids_filter'],
            excluded_role_types=self.query_params['excluded_role_types'],
        )

        for record in records or []:
            usr_data = self._roles_data[record.user_id]
            for tenant_id in self.get_org_tenants(record.org):
                if tenant_id not in self.permitted_tenant_ids:
                    continue

                if tenant_id not in usr_data:
                    usr_data[tenant_id] = {
                        'tenant_roles': [],
                        'course_roles': {},
                    }

                course_id = str(record.course_id) if record.course_id else None
                if course_id and course_id not in usr_data[tenant_id]['course_roles']:
                    usr_data[tenant_id]['course_roles'][course_id] = []

                if course_id:
                    usr_data[tenant_id]['course_roles'][course_id].append(record.role)
                elif record.role not in usr_data[tenant_id]['tenant_roles']:
                    usr_data[tenant_id]['tenant_roles'].append(record.role)

    @property
    def roles_data(self) -> dict[Any, Any] | None:
        """Get the roles data."""
        return self._roles_data

    def get_tenants(self, obj: get_user_model) -> Any:
        """Return the tenants."""
        return self.roles_data.get(obj.id, {}) if self.roles_data else {}

    def get_global_roles(self, obj: get_user_model) -> Any:  # pylint:disable=no-self-use
        """Return the global roles."""
        roles_dict = get_user_course_access_roles(obj)['roles']
        return [role for role in roles_dict if role in COURSE_ACCESS_ROLES_GLOBAL]

    class Meta:
        model = get_user_model()
        fields = [
            'user_id',
            'email',
            'username',
            'national_id',
            'full_name',
            'alternative_full_name',
            'global_roles',
            'tenants',
        ]


class ReadOnlySerializer(serializers.Serializer):
    """A serializer that is only used for read operations and does not require create/update methods."""

    def create(self, validated_data: Any) -> Any:
        """Not implemented: Create a new object."""
        raise ValueError('This serializer is read-only and does not support object creation.')

    def update(self, instance: Any, validated_data: Any) -> Any:
        """Not implemented: Update an existing object."""
        raise ValueError('This serializer is read-only and does not support object updates.')


class AggregatedCountsQuerySettingsSerializer(ReadOnlySerializer):
    """Serializer for aggregated counts settings."""
    aggregate_period = serializers.CharField()
    date_from = serializers.DateField()
    date_to = serializers.DateField()


class AggregatedCountsTotalsSerializer(ReadOnlySerializer):
    enrollments_count = serializers.IntegerField(required=False, allow_null=True)


class AggregatedCountsValuesSerializer(ReadOnlySerializer):
    label = serializers.CharField()
    value = serializers.IntegerField()


class AggregatedCountsAllTenantsSerializer(ReadOnlySerializer):
    enrollments_count = AggregatedCountsValuesSerializer(required=False, allow_null=True, many=True)
    totals = AggregatedCountsTotalsSerializer()


class AggregatedCountsOneTenantSerializer(AggregatedCountsAllTenantsSerializer):
    tenant_id = serializers.IntegerField()


class AggregatedCountsSerializer(ReadOnlySerializer):
    query_settings = AggregatedCountsQuerySettingsSerializer()
    all_tenants = AggregatedCountsAllTenantsSerializer()
    by_tenant = AggregatedCountsOneTenantSerializer(many=True)
    limited_access = serializers.BooleanField()
