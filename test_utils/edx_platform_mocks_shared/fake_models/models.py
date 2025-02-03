"""edx-platform models mocks for testing purposes."""
import re

from django import forms
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.fields import AutoField
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from opaque_keys.edx.django.models import CourseKeyField, LearningContextKeyField, UsageKeyField


class Organization(models.Model):
    """Mock"""
    short_name = models.CharField(max_length=255, unique=True, db_collation='NOCASE')

    def clean(self):
        if not re.match('^[a-zA-Z0-9._-]*$', self.short_name):
            raise ValueError('Short name must be alphanumeric and may contain periods, underscores, and hyphens.')


class CourseOverview(models.Model):
    """Mock"""
    id = CourseKeyField(db_index=True, primary_key=True, max_length=255)  # pylint: disable=invalid-name
    org = models.CharField(max_length=255, db_collation='NOCASE')
    catalog_visibility = models.TextField(null=True)
    start = models.DateTimeField(null=True)
    end = models.DateTimeField(null=True)
    display_name = models.TextField(null=True)
    enrollment_start = models.DateTimeField(null=True)
    enrollment_end = models.DateTimeField(null=True)
    self_paced = models.BooleanField(default=False)
    course_image_url = models.TextField()
    visible_to_staff_only = models.BooleanField(default=False)
    effort = models.TextField(null=True)

    class Meta:
        app_label = 'fake_models'
        db_table = 'course_overviews_courseoverview'


class CourseAccessRole(models.Model):
    """Mock"""
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    role = models.CharField(max_length=255)
    org = models.CharField(blank=True, max_length=255, db_collation='NOCASE')
    course_id = CourseKeyField(max_length=255, db_index=True, blank=True)

    class Meta:
        app_label = 'fake_models'
        db_table = 'student_courseaccessrole'
        unique_together = ('user', 'org', 'course_id', 'role')


class CourseEnrollment(models.Model):
    """Mock"""
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    course = models.ForeignKey(CourseOverview, on_delete=models.CASCADE)
    is_active = models.BooleanField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'fake_models'
        db_table = 'student_courseenrollment'


class UserSignupSource(models.Model):
    """Mock"""
    site = models.CharField(max_length=255)
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)

    class Meta:
        app_label = 'fake_models'
        db_table = 'student_usersignupsource'


class GeneratedCertificate(models.Model):
    """Mock"""
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, blank=True, default=None)
    status = models.CharField(max_length=32, default='unavailable')
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('user', 'course_id'),)
        app_label = 'fake_models'
        db_table = 'certificates_generatedcertificate'


class UserProfile(models.Model):
    """Mock"""
    user = models.OneToOneField(
        get_user_model(), unique=True, db_index=True, related_name='profile', on_delete=models.CASCADE
    )
    name = models.CharField(blank=True, max_length=255, db_index=True)
    year_of_birth = models.IntegerField(blank=True, null=True, db_index=True)
    GENDER_CHOICES = (
        ('m', 'Male'),
        ('f', 'Female'),
    )
    gender = models.CharField(
        blank=True, null=True, max_length=6, db_index=True, choices=GENDER_CHOICES
    )
    profile_image_uploaded_at = models.DateTimeField(null=True, blank=True)
    phone_number = models.CharField(blank=True, null=True, max_length=50)
    bio = models.CharField(blank=True, null=True, max_length=3000, db_index=False)
    level_of_education = models.CharField(blank=True, null=True, max_length=6, db_index=True)
    city = models.TextField(blank=True, null=True)

    @property
    def has_profile_image(self):
        """
        Convenience method that returns a boolean indicating whether or not
        this user has uploaded a profile image.
        """
        return self.profile_image_uploaded_at is not None

    @property
    def gender_display(self):
        """ Convenience method that returns the human readable gender. """
        if self.gender:
            return 'Male' if self.gender == 'm' else 'Female'
        return None

    @property
    def level_of_education_display(self):
        """ Convenience method that returns the human readable level of education. """
        return self.level_of_education

    class Meta:
        app_label = 'fake_models'
        db_table = 'auth_userprofile'


class SocialLink(models.Model):
    """Mock"""
    user_profile = models.ForeignKey(UserProfile, db_index=True, related_name='social_links', on_delete=models.CASCADE)
    platform = models.CharField(max_length=30)
    social_link = models.CharField(max_length=100, blank=True)

    class Meta:
        app_label = 'fake_models'
        db_table = 'student_social_link'


class BaseFeedback(models.Model):
    """Mock"""
    RATING_OPTIONS = [
        (0, '0'),
        (1, '1'),
        (2, '2'),
        (3, '3'),
        (4, '4'),
        (5, '5')
    ]
    author = models.ForeignKey(get_user_model(), null=True, on_delete=models.SET_NULL)
    rating_content = models.IntegerField(blank=True, null=True, choices=RATING_OPTIONS)
    feedback = models.CharField(max_length=500, blank=True, null=True)
    public = models.BooleanField(null=True, default=False)
    course_id = models.ForeignKey(CourseOverview, null=True, on_delete=models.SET_NULL)

    class Meta:
        """Set model abstract"""
        abstract = True


class FeedbackCourse(BaseFeedback):
    """Mock"""
    rating_instructors = models.IntegerField(blank=True, null=True, choices=BaseFeedback.RATING_OPTIONS)
    recommended = models.BooleanField(null=True, default=True)

    class Meta:
        """Set constrain for author an course id"""
        unique_together = [['author', 'course_id']]
        db_table = 'eox_nelp_feedbackcourse'


class BlockCompletion(models.Model):
    """Mock"""
    id = models.BigAutoField(primary_key=True)  # pylint: disable=invalid-name
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    context_key = models.CharField(max_length=255, null=False, blank=False, db_column='course_key')
    modified = models.DateTimeField()


class CourseGradeFactory:  # pylint: disable=too-few-public-methods
    """Mock"""
    def read(self, *args, **kwargs):  # pylint: disable=no-self-use
        """Mock read"""
        class DummyGrade:
            """dummy grade class"""

            letter_grade = 'Fail'
            percent = 0.4
            passed = False

            def update(self, *args, **kwargs):  # pylint: disable=no-self-use
                """update"""
                return None

        return DummyGrade()


class PersistentCourseGrade(models.Model):
    """Mock"""
    id = AutoField(primary_key=True)  # pylint: disable=invalid-name
    user_id = models.IntegerField(blank=False, db_index=True)
    course_id = CourseKeyField(blank=False, max_length=255)

    percent_grade = models.FloatField(blank=False)

    class Meta:
        app_label = 'fake_models'
        unique_together = [
            ('course_id', 'user_id'),
        ]
        db_table = 'persistentcoursegrade'


class PersistentSubsectionGrade(models.Model):
    """Mock"""
    id = AutoField(primary_key=True)  # pylint: disable=invalid-name
    user_id = models.IntegerField(blank=False)
    course_id = CourseKeyField(blank=False, max_length=255)
    usage_key = UsageKeyField(blank=False, max_length=255)
    earned_all = models.FloatField(blank=False)
    possible_all = models.FloatField(blank=False)
    earned_graded = models.FloatField(blank=False)
    possible_graded = models.FloatField(blank=False)
    first_attempted = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'fake_models'
        unique_together = [
            ('course_id', 'user_id', 'usage_key'),
        ]
        db_table = 'persistentsubsectiongrade'


class StudentModule(models.Model):
    """Mock"""
    id = AutoField(primary_key=True)  # pylint: disable=invalid-name
    student = models.ForeignKey(get_user_model(), db_index=True, db_constraint=False, on_delete=models.CASCADE)
    course_id = LearningContextKeyField(max_length=255, db_index=True)
    modified = models.DateTimeField(auto_now=True, db_index=True)
    module_state_key = UsageKeyField(max_length=255, db_column='module_id')

    class Meta:
        app_label = 'fake_models'
        unique_together = (('student', 'module_state_key', 'course_id'),)


class CourseCreator(models.Model):
    """Mock"""
    UNREQUESTED = 'unrequested'
    PENDING = 'pending'
    GRANTED = 'granted'
    DENIED = 'denied'

    STATES = (
        (UNREQUESTED, UNREQUESTED),
        (PENDING, UNREQUESTED),
        (GRANTED, UNREQUESTED),
        (DENIED, UNREQUESTED),
    )

    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE)
    state = models.CharField(max_length=24, blank=False, choices=STATES, default=UNREQUESTED)
    organizations = models.ManyToManyField(Organization, blank=True)
    all_organizations = models.BooleanField(default=True)

    class Meta:
        app_label = 'fake_models'
        db_table = 'course_creators_coursecreator'


@receiver(post_save, sender=CourseCreator)
def post_save_never_use_create_or_save(sender, **kwargs):
    """Mock"""
    raise ValueError(
        'This exception means that you have used `create` or `save` methods of the CourseCreator model. '
        'These methods trigger signals in CMS which is outside the scope of the Dashboard. Please use our '
        'add_org_course_creator function instead. It will use bulk_create to avoid triggering signals.'
    )


@receiver(m2m_changed, sender=CourseCreator.organizations.through)
def m2m_changed_never_use_set_add_remove_or_clear(sender, **kwargs):
    """Mock"""
    raise ValueError(
        'This exception means that you have used `set`, `add`, remove` or `clear` methods of '
        'CourseCreator.organizations. These methods trigger signals in CMS which is outside the scope of the '
        'Dashboard. Please use our add_orgs_to_course_creator_record function instead. It will use bulk_create '
        'to avoid triggering signals. You cal also use add_clear_org_to_course_creator in tests which will '
        'temporarily disable the signal.'
    )


class ExtraInfo(models.Model):
    """Mock"""
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE, null=True)
    arabic_name = models.CharField(max_length=255)
    arabic_first_name = models.CharField(max_length=30, blank=True)
    arabic_last_name = models.CharField(max_length=50, blank=True)
    national_id = models.CharField(max_length=20, blank=True)
    allow_newsletter_emails = models.BooleanField(default=False, blank=True)
    is_phone_validated = models.BooleanField(default=False)

    class Meta:
        app_label = 'fake_models'
        db_table = 'custom_reg_form_extra_info'


class CourseAccessRoleForm(forms.ModelForm):
    """Mock"""
    class Meta:
        model = CourseAccessRole
        fields = '__all__'

    COURSE_ACCESS_ROLES = []
    role = forms.ChoiceField(choices=COURSE_ACCESS_ROLES)
