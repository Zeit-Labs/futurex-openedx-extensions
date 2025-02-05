"""
URLs for dashboard.
"""
from django.conf import settings
from django.urls import include, re_path
from rest_framework.routers import DefaultRouter

from futurex_openedx_extensions.dashboard import views
from futurex_openedx_extensions.helpers.constants import CLICKHOUSE_QUERY_SLUG_PATTERN, COURSE_ID_REGX
from futurex_openedx_extensions.helpers.models import ClickhouseQuery

app_name = 'fx_dashboard'

QUERY_ALLOWED_SCOPES = '|'.join(ClickhouseQuery.allowed_scopes())

roles_router = DefaultRouter()
roles_router.register(r'user_roles', views.UserRolesManagementView, basename='user-roles')
export_router = DefaultRouter()
export_router.register(r'tasks', views.DataExportManagementView, basename='data-export-tasks')

urlpatterns = [
    re_path(r'^api/fx/accessible/v1/info/$', views.AccessibleTenantsInfoView.as_view(), name='accessible-info'),
    re_path(r'^api/fx/accessible/v2/info/$', views.AccessibleTenantsInfoViewV2.as_view(), name='accessible-info-v2'),
    re_path(r'^api/fx/courses/v1/courses/$', views.CoursesView.as_view(), name='courses'),
    re_path(r'^api/fx/learners/v1/learners/$', views.LearnersView.as_view(), name='learners'),
    re_path(
        fr'^api/fx/learners/v1/learners/{COURSE_ID_REGX}/$',
        views.LearnersDetailsForCourseView.as_view(), name='learners-course'),
    re_path(
        r'^api/fx/learners/v1/enrollments/$',
        views.LearnersEnrollmentView.as_view(), name='learners-enrollements'),
    re_path(
        r'^api/fx/learners/v1/learner/' + settings.USERNAME_PATTERN + '/$',
        views.LearnerInfoView.as_view(),
        name='learner-info'
    ),
    re_path(
        r'^api/fx/learners/v1/learner_courses/' + settings.USERNAME_PATTERN + '/$',
        views.LearnerCoursesView.as_view(),
        name='learner-courses'
    ),
    re_path(r'^api/fx/roles/v1/my_roles/$', views.MyRolesView.as_view(), name='my-roles'),
    re_path(r'^api/fx/roles/v1/', include(roles_router.urls)),
    re_path(r'^api/fx/export/v1/', include(export_router.urls)),
    re_path(r'^api/fx/statistics/v1/course_statuses/$', views.CourseStatusesView.as_view(), name='course-statuses'),
    re_path(r'^api/fx/statistics/v1/rating/$', views.GlobalRatingView.as_view(), name='statistics-rating'),
    re_path(r'^api/fx/statistics/v1/total_counts/$', views.TotalCountsView.as_view(), name='total-counts'),
    re_path(
        fr'^api/fx/query/v1/(?P<scope>{QUERY_ALLOWED_SCOPES})/(?P<slug>{CLICKHOUSE_QUERY_SLUG_PATTERN})/$',
        views.ClickhouseQueryView.as_view(),
        name='clickhouse-query'
    ),
    re_path(r'^api/fx/version/v1/info/$', views.VersionInfoView.as_view(), name='version-info'),
]
