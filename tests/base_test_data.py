"""Base test data for the tests. dictionary instead of json file."""

_base_data = {
    'tenant_config': {
        1: {  # Organisations are duplicated with tenant 4 and 6
            'lms_configs': {
                'LMS_BASE': 's1.sample.com',
                'course_org_filter': ['ORG1', 'ORG2', 'Org1'],
                'IS_FX_DASHBOARD_ENABLED': True,
            },
        },
        2: {  # Organisation is duplicated with tenant 7 and 8
            'lms_configs': {
                'LMS_BASE': 's2.sample.com',
                'course_org_filter': ['ORG3', 'ORG8'],
                'IS_FX_DASHBOARD_ENABLED': True,
            },
        },
        3: {
            'lms_configs': {
                'LMS_BASE': 's3.sample.com',
                'course_org_filter': ['ORG4', 'ORG5'],
                'IS_FX_DASHBOARD_ENABLED': True,
            },
        },
        4: {  # This is a tenant with no LMS_BASE
            'lms_configs': {
                'LMS_BASE': None,
                'course_org_filter': ['ORG1', 'ORG2'],
                'IS_FX_DASHBOARD_ENABLED': True,
            },
        },
        5: {  # This is a tenant with no course_org_filter
            'lms_configs': {
                'LMS_BASE': 's5.sample.com',
                'course_org_filter': [],
                'IS_FX_DASHBOARD_ENABLED': True,
            },
        },
        6: {  # This is a tenant with no route
            'lms_configs': {
                'LMS_BASE': 's6.sample.com',
                'course_org_filter': ['ORG2'],
                'IS_FX_DASHBOARD_ENABLED': True,
            },
        },
        7: {
            'lms_configs': {
                'LMS_BASE': 's7.sample.com',
                'course_org_filter': 'ORG3',  # This a string, not a list, it should be fine too
                'IS_FX_DASHBOARD_ENABLED': True,
            },
        },
        8: {
            'lms_configs': {
                'LMS_BASE': 's8.sample.com',
                'course_org_filter': ['ORG8'],
                'IS_FX_DASHBOARD_ENABLED': True,
            },
        },
    },
    'routes': {
        1: {
            'domain': 's1.sample.com',
            'config_id': 1,
        },
        2: {
            'domain': 's2.sample.com',
            'config_id': 2,
        },
        3: {
            'domain': 's3.sample.com',
            'config_id': 3,
        },
        4: {
            'domain': 's4.sample.com',
            'config_id': 4,
        },
        5: {
            'domain': 's5.sample.com',
            'config_id': 5,
        },
        7: {
            'domain': 's7.sample.com',
            'config_id': 7,
        },
        8: {
            'domain': 's8.sample.com',
            'config_id': 8,
        },
    },
    'users_count': 70,
    'user_signup_source__users': {
        's1.sample.com': [1, 2, 3, 4, 5],
        's2.sample.com': [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
        's3.sample.com': [15, 16, 17, 18, 19, 20],
        's4.sample.com': [21, 22, 23, 24, 25, 26, 27],
        's5.sample.com': [21, 22, 23, 24, 25, 26, 27],
        's6.sample.com': [28, 29, 30, 31, 32, 33, 34, 35, 36, 37],
        's7.sample.com': [15, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50],
        's8.sample.com': [47, 48, 49, 50, 51, 52, 53, 54, 55],
        'dah.sample.com': [1, 2, 3, 4, 5],  # This is not a valid domain
    },
    'course_overviews': {  # count of courses per org
        'Org1': (1, 1),
        'ORG1': (2, 5),
        'ORG2': (1, 7),
        'ORG3': (1, 3),
        'ORG4': (1, 1),
        'ORG5': None,
        'ORG6': (1, 1),  # This is an org with no tenant
        'ORG8': (1, 2),
        'incompatible_org_case': {
            'course-v1:Org1+1+1': 'oRg1',
            'course-v1:ORG1+3+3': 'org1',
        },
    },
    'course_attributes': {  # org id, course id
        'course-v1:Org1+1+1': {
            'start': 'F',
        },
        'course-v1:ORG1+2+2': {
            'start': 'F',
            'end': 'F',
        },

        'course-v1:ORG2+3+3': {
            'end': 'P',
        },
        'course-v1:ORG2+4+4': {
            'end': 'P',
        },
        'course-v1:ORG2+5+5': {
            'start': 'P',
            'end': 'P',
        },

        'course-v1:ORG2+1+1': {
            'start': 'P',
        },
        'course-v1:ORG2+2+2': {
            'start': 'P',
            'end': 'F',
        },
        'course-v1:ORG1+3+3': {
            'end': 'F',
        },

        'course-v1:ORG1+4+4': {
            'self_paced': True,
        },
    },
    'course_enrollments': {  # org id, course id, user ids
        'Org1': {
            1: [4, 5],
        },
        'ORG1': {
            2: [3],
            3: [],
            4: [4],
            5: [1, 2, 3, 4, 15, 21, 40],
        },
        'ORG2': {
            1: [2],
            3: [1, 2, 3],
            4: [4, 5, 21, 22, 23, 24, 25],
            5: [21, 22, 23, 24, 25],
            6: [28, 29, 30, 31, 32],
            7: [15, 38, 39, 40, 41],
        },
        'ORG3': {
            1: [10, 40, 41, 42, 43, 44],
            2: [45, 46, 47, 48, 49],
            3: [7, 8, 9, 10, 11, 12],
        },
        'ORG4': {
            1: [1, 2, 15, 16, 17, 18],
        },
        'ORG6': {
            1: [30, 31, 32, 41, 42],
        },
        'ORG8': {
            1: [47, 48, 49, 52],
            2: [23, 52, 53, 54],
        },
    },
    'super_users': [1, 60],
    'staff_users': [2, 60],
    'inactive_users': [61, 62, 63],
    'user_extra_info': {  # user id, national id
        1: {
            'national_id': '123456700001',
        },
        2: {
            'national_id': '123456700002',
        },
        3: {
            'national_id': '11223344556677',
        },
        4: {
            'national_id': '123456700004',
        },
        5: {
            'national_id': '123456700005',
        },
    },
    'course_access_roles_org_wide': {  # roles, user ids per org
        'staff': {
            'Org1': [3],
            'Org2': [8],
            'Org3': [9, 18],
            'Org4': [10, 23],
            'Org5': [23],
        },
        'instructor': {
            'ORG1': [4],
            'ORG2': [1, 2, 4],
            'ORG3': [4],
            'ORG4': [23, 48],
            'ORG5': [23],
            'ORG8': [23],
        },
        'data_researcher': {
            'ORG3': [9, 10],
        },
    },
    'course_access_roles_course_specific': {  # org id, course id, roles, user ids
        'Org1': {
            'course-v1:Org1+1+1': {
                'staff': [1],
                'instructor': [1],
            },
            'course-v1:ORG1+2+2': {
                'staff': [1],
                'instructor': [2],
            },
            'course-v1:ORG1+3+3': {
                'staff': [3],
                'instructor': [3],
            },
            'course-v1:ORG1+4+4': {
                'staff': [4],
                'instructor': [3],
            },
        },
        'Org2': {
            'course-v1:ORG2+1+1': {
                'staff': [9],
                'instructor': [1],
            },
            'course-v1:ORG2+2+2': {
                'staff': [1],
                'instructor': [2],
            },
            'course-v1:ORG2+3+3': {
                'staff': [9],
                'instructor': [8],
            },
        },
        'Org3': {
            'course-v1:ORG3+1+1': {
                'staff': [4],
                'instructor': [4],
            },
            'course-v1:ORG3+2+2': {
                'data_researcher': [9],
                'instructor': [11],
            },
            'course-v1:ORG3+3+3': {
                'staff': [18],
                'instructor': [9],
                'sales_admin': [11],  # This is an unsupported role
            },
        },
    },
    'ignored_course_access_roles': {
        'no_org': {
            'staff': [10, 30, 40, 41],
            'org_course_creator_group': [24, 40, 42],
        },
    },
    'certificates': {  # org id, course id, user ids
        'ORG1': {
            5: [2, 3, 4, 40],
        },
        'ORG2': {
            4: [4, 5, 24, 25],
            5: [21, 24, 25],
            7: [15, 40, 41],
        },
        'ORG3': {
            1: [42, 43, 44],
            2: [48, 49],
            3: [8, 9],
        },
        'ORG4': {
        },
        'ORG6': {
            1: [30, 42],
        },
        'ORG8': {
            1: [49, 52],
        },
    },
}


expected_statistics = {
    '1': {
        'certificates_count': 14,
        'courses_count': 12,
        'enrollments_count': 26,
        'hidden_courses_count': 0,
        'learners_count': 16,
        'learning_hours_count': 14 * 20,
    },
    '2': {
        'certificates_count': 9,
        'courses_count': 5,
        'enrollments_count': 21,
        'hidden_courses_count': 0,
        'learners_count': 21,
        'learning_hours_count': 9 * 20,
    },
    '3': {
        'certificates_count': 0,
        'courses_count': 1,
        'enrollments_count': 4,
        'hidden_courses_count': 0,
        'learners_count': 6,
        'learning_hours_count': 0,

    },
    '7': {
        'certificates_count': 7,
        'courses_count': 3,
        'enrollments_count': 14,
        'hidden_courses_count': 0,
        'learners_count': 17,
        'learning_hours_count': 7 * 20,

    },
    '8': {
        'certificates_count': 2,
        'courses_count': 2,
        'enrollments_count': 7,
        'hidden_courses_count': 0,
        'learners_count': 9,
        'learning_hours_count': 2 * 20

    },
    'total_certificates_count': 32,
    'total_courses_count': 23,
    'total_enrollments_count': 72,
    'total_hidden_courses_count': 0,
    'total_learners_count': 69,
    'total_learning_hours_count': 640,
    'total_unique_learners': 37,
    'limited_access': False,
}
