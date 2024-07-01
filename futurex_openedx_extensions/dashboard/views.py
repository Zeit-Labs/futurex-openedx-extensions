"""Views for the dashboard app"""
from common.djangoapps.student.models import get_user_by_username_or_email
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from futurex_openedx_extensions.dashboard import serializers
from futurex_openedx_extensions.dashboard.details.courses import get_courses_queryset, get_learner_courses_info_queryset
from futurex_openedx_extensions.dashboard.details.learners import (
    get_learner_info_queryset,
    get_learners_by_course_queryset,
    get_learners_queryset,
)
from futurex_openedx_extensions.dashboard.statistics.certificates import get_certificates_count
from futurex_openedx_extensions.dashboard.statistics.courses import get_courses_count, get_courses_count_by_status
from futurex_openedx_extensions.dashboard.statistics.learners import get_learners_count
from futurex_openedx_extensions.helpers.constants import COURSE_STATUS_SELF_PREFIX, COURSE_STATUSES
from futurex_openedx_extensions.helpers.converters import error_details_to_dictionary
from futurex_openedx_extensions.helpers.filters import DefaultOrderingFilter
from futurex_openedx_extensions.helpers.pagination import DefaultPagination
from futurex_openedx_extensions.helpers.permissions import (
    FXHasTenantCourseAccess,
    IsAnonymousOrSystemStaff,
    IsSystemStaff,
    get_tenant_limited_fx_permission_info,
)
from futurex_openedx_extensions.helpers.roles import FXViewRoleInfoMixin
from futurex_openedx_extensions.helpers.tenants import (
    get_accessible_tenant_ids,
    get_tenants_info,
    get_user_id_from_username_tenants,
)


class TotalCountsView(APIView, FXViewRoleInfoMixin):
    """
    View to get the total count statistics

    TODO: there is a better way to get info per tenant without iterating over all tenants
    """
    STAT_CERTIFICATES = 'certificates'
    STAT_COURSES = 'courses'
    STAT_HIDDEN_COURSES = 'hidden_courses'
    STAT_LEARNERS = 'learners'

    valid_stats = [STAT_CERTIFICATES, STAT_COURSES, STAT_HIDDEN_COURSES, STAT_LEARNERS]
    STAT_RESULT_KEYS = {
        STAT_CERTIFICATES: 'certificates_count',
        STAT_COURSES: 'courses_count',
        STAT_HIDDEN_COURSES: 'hidden_courses_count',
        STAT_LEARNERS: 'learners_count'
    }

    permission_classes = [FXHasTenantCourseAccess]
    fx_view_name = 'total_counts_statistics'
    fx_default_read_only_roles = ['staff', 'instructor', 'data_researcher', 'org_course_creator_group']
    fx_view_description = 'api/fx/statistics/v1/total_counts/: Get the total count statistics'

    @staticmethod
    def _get_certificates_count_data(one_tenant_permission_info):
        """Get the count of certificates for the given tenant"""
        collector_result = get_certificates_count(one_tenant_permission_info)
        return sum(certificate_count for certificate_count in collector_result.values())

    @staticmethod
    def _get_courses_count_data(one_tenant_permission_info, visible_filter):
        """Get the count of courses for the given tenant"""
        collector_result = get_courses_count(one_tenant_permission_info, visible_filter=visible_filter)
        return sum(org_count['courses_count'] for org_count in collector_result)

    @staticmethod
    def _get_learners_count_data(one_tenant_permission_info, tenant_id):
        """Get the count of learners for the given tenant"""
        collector_result = get_learners_count(one_tenant_permission_info)
        return collector_result[tenant_id]['learners_count'] + \
            collector_result[tenant_id]['learners_count_no_enrollment']

    def _get_stat_count(self, stat, tenant_id):
        """Get the count of the given stat for the given tenant"""
        one_tenant_permission_info = get_tenant_limited_fx_permission_info(self.fx_permission_info, tenant_id)
        if stat == self.STAT_CERTIFICATES:
            return self._get_certificates_count_data(one_tenant_permission_info)

        if stat == self.STAT_COURSES:
            return self._get_courses_count_data(one_tenant_permission_info, visible_filter=True)

        if stat == self.STAT_HIDDEN_COURSES:
            return self._get_courses_count_data(one_tenant_permission_info, visible_filter=False)

        return self._get_learners_count_data(one_tenant_permission_info, tenant_id)

    def get(self, request, *args, **kwargs):
        """
        GET /api/fx/statistics/v1/total_counts/?stats=<countTypesList>&tenant_ids=<tenantIds>

        <countTypesList> (required): a comma-separated list of the types of count statistics to include in the
            response. Available count statistics are:
        certificates: total number of issued certificates in the selected tenants
        courses: total number of courses in the selected tenants
        learners: total number of learners in the selected tenants
        <tenantIds> (optional): a comma-separated list of the tenant IDs to get the information for. If not provided,
            the API will assume the list of all accessible tenants by the user
        """
        stats = request.query_params.get('stats', '').split(',')
        invalid_stats = list(set(stats) - set(self.valid_stats))
        if invalid_stats:
            return Response(error_details_to_dictionary(reason="Invalid stats type", invalid=invalid_stats), status=400)

        tenant_ids = self.fx_permission_info['permitted_tenant_ids']

        result = dict({tenant_id: {} for tenant_id in tenant_ids})
        result.update({
            f'total_{self.STAT_RESULT_KEYS[stat]}': 0 for stat in stats
        })
        for tenant_id in tenant_ids:
            for stat in stats:
                count = self._get_stat_count(stat, tenant_id)
                result[tenant_id][self.STAT_RESULT_KEYS[stat]] = count
                result[f'total_{self.STAT_RESULT_KEYS[stat]}'] += count

        return JsonResponse(result)


class LearnersView(ListAPIView, FXViewRoleInfoMixin):
    """View to get the list of learners"""
    serializer_class = serializers.LearnerDetailsSerializer
    permission_classes = [FXHasTenantCourseAccess]
    pagination_class = DefaultPagination
    fx_view_name = 'learners_list'
    fx_default_read_only_roles = ['staff', 'instructor', 'data_researcher', 'org_course_creator_group']
    fx_view_description = 'api/fx/learners/v1/learners/: Get the list of learners'

    def get_queryset(self):
        """Get the list of learners"""
        search_text = self.request.query_params.get('search_text')
        return get_learners_queryset(
            fx_permission_info=self.fx_permission_info,
            search_text=search_text,
        )


class CoursesView(ListAPIView, FXViewRoleInfoMixin):
    """View to get the list of courses"""
    serializer_class = serializers.CourseDetailsSerializer
    permission_classes = [FXHasTenantCourseAccess]
    pagination_class = DefaultPagination
    filter_backends = [DefaultOrderingFilter]
    ordering_fields = [
        'id', 'self_paced', 'enrolled_count', 'active_count',
        'certificates_count', 'display_name', 'org',
    ]
    ordering = ['display_name']
    fx_view_name = 'courses_list'
    fx_default_read_only_roles = ['staff', 'instructor', 'data_researcher', 'org_course_creator_group']
    fx_view_description = 'api/fx/courses/v1/courses/: Get the list of courses'

    def get_queryset(self):
        """Get the list of learners"""
        search_text = self.request.query_params.get('search_text')
        return get_courses_queryset(
            fx_permission_info=self.fx_permission_info,
            search_text=search_text,
            visible_filter=None,
        )


class CourseStatusesView(APIView, FXViewRoleInfoMixin):
    """View to get the course statuses"""
    permission_classes = [FXHasTenantCourseAccess]
    fx_view_name = 'course_statuses'
    fx_default_read_only_roles = ['staff', 'instructor', 'data_researcher', 'org_course_creator_group']
    fx_view_description = 'api/fx/statistics/v1/course_statuses/: Get the course statuses'

    @staticmethod
    def to_json(result):
        """Convert the result to JSON format"""
        dict_result = {
            f"{COURSE_STATUS_SELF_PREFIX if self_paced else ''}{status}": 0
            for status in COURSE_STATUSES
            for self_paced in [False, True]
        }

        for item in result:
            status = f"{COURSE_STATUS_SELF_PREFIX if item['self_paced'] else ''}{item['status']}"
            dict_result[status] = item['courses_count']
        return dict_result

    def get(self, request, *args, **kwargs):
        """
        GET /api/fx/statistics/v1/course_statuses/?tenant_ids=<tenantIds>

        <tenantIds> (optional): a comma-separated list of the tenant IDs to get the information for. If not provided,
            the API will assume the list of all accessible tenants by the user
        """
        result = get_courses_count_by_status(fx_permission_info=self.fx_permission_info)

        return JsonResponse(self.to_json(result))


class LearnerInfoView(APIView, FXViewRoleInfoMixin):
    """View to get the information of a learner"""
    permission_classes = [FXHasTenantCourseAccess]
    fx_view_name = 'learner_detailed_info'
    fx_default_read_only_roles = ['staff', 'instructor', 'data_researcher', 'org_course_creator_group']
    fx_view_description = 'api/fx/learners/v1/learner/: Get the information of a learner'

    def get(self, request, username, *args, **kwargs):
        """
        GET /api/fx/learners/v1/learner/<username>/
        """
        tenant_ids = self.fx_permission_info['permitted_tenant_ids']
        user_id = get_user_id_from_username_tenants(username, tenant_ids)

        if not user_id:
            return Response(error_details_to_dictionary(reason=f"User not found {username}"), status=404)

        user = get_learner_info_queryset(self.fx_permission_info, user_id).first()

        return JsonResponse(
            serializers.LearnerDetailsExtendedSerializer(user, context={'request': request}).data
        )


class LearnerCoursesView(APIView, FXViewRoleInfoMixin):
    """View to get the list of courses for a learner"""
    permission_classes = [FXHasTenantCourseAccess]
    pagination_class = DefaultPagination
    fx_view_name = 'learner_courses'
    fx_default_read_only_roles = ['staff', 'instructor', 'data_researcher', 'org_course_creator_group']
    fx_view_description = 'api/fx/learners/v1/learner_courses/: Get the list of courses for a learner'

    def get(self, request, username, *args, **kwargs):
        """
        GET /api/fx/learners/v1/learner_courses/<username>/
        """
        tenant_ids = self.fx_permission_info['permitted_tenant_ids']
        user_id = get_user_id_from_username_tenants(username, tenant_ids)

        if not user_id:
            return Response(error_details_to_dictionary(reason=f"User not found {username}"), status=404)

        courses = get_learner_courses_info_queryset(
            fx_permission_info=self.fx_permission_info,
            user_id=user_id,
            visible_filter=None,
        )

        return Response(serializers.LearnerCoursesDetailsSerializer(
            courses, context={'request': request}, many=True
        ).data)


class VersionInfoView(APIView):
    """View to get the version information"""
    permission_classes = [IsSystemStaff]

    def get(self, request, *args, **kwargs):  # pylint: disable=no-self-use
        """
        GET /api/fx/version/v1/info/
        """
        import futurex_openedx_extensions  # pylint: disable=import-outside-toplevel
        return JsonResponse({
            'version': futurex_openedx_extensions.__version__,
        })


class AccessibleTenantsInfoView(APIView):
    """View to get the list of accessible tenants"""
    permission_classes = [IsAnonymousOrSystemStaff]

    def get(self, request, *args, **kwargs):  # pylint: disable=no-self-use
        """
        GET /api/fx/tenants/v1/accessible_tenants/?username_or_email=<usernameOrEmail>
        """
        username_or_email = request.query_params.get("username_or_email")
        try:
            user = get_user_by_username_or_email(username_or_email)
        except ObjectDoesNotExist:
            user = None

        if not user:
            return JsonResponse({})

        tenant_ids = get_accessible_tenant_ids(user)
        return JsonResponse(get_tenants_info(tenant_ids))


class LearnersDetailsForCourseView(ListAPIView, FXViewRoleInfoMixin):
    """View to get the list of learners for a course"""
    serializer_class = serializers.LearnerDetailsForCourseSerializer
    permission_classes = [FXHasTenantCourseAccess]
    pagination_class = DefaultPagination
    fx_view_name = 'learners_with_details_for_course'
    fx_default_read_only_roles = ['staff', 'instructor', 'data_researcher', 'org_course_creator_group']
    fx_view_description = 'api/fx/learners/v1/learners/<course-id>: Get the list of learners for a course'

    def get_queryset(self, *args, **kwargs):
        """Get the list of learners for a course"""
        search_text = self.request.query_params.get('search_text')
        course_id = self.kwargs.get('course_id')

        return get_learners_by_course_queryset(
            course_id=course_id,
            search_text=search_text,
        )
