# =============================================================================
# LLM USED: Claude (Anthropic), model Claude Sonnet 5.5
#
# PROMPT GIVEN TO THE LLM:
#   "Write a Django models.py for an app called AttendanceChimp, which tracks
#    class attendance via QR codes. Users are students and instructors (two
#    roles), so use separate InstructorProfile and StudentProfile tables. Each
#    course has one instructor, and students can enroll in multiple courses
#    (use an Enrollment table). Lectures are individual class meetings, each
#    associated with a course, with a date and a QR identifier. QR code uploads
#    are photos uploaded by students, each associated with a student and
#    (optionally) a lecture. The design should be simple to use, support
#    attendance analytics, and be robust to cheating. Include docstrings."
# =============================================================================

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class InstructorProfile(models.Model):
    """Profile for a user who teaches courses.

    Linked one-to-one to Django's built-in User model, so login, password and
    name/email are handled by Django's authentication system.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="instructor_profile",
    )
    department = models.CharField(max_length=100, blank=True)
    office = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class StudentProfile(models.Model):
    """Profile for a user who attends courses.

    Linked one-to-one to Django's built-in User model.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    student_id = models.CharField(max_length=20, unique=True)
    graduation_year = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.student_id})"


class Course(models.Model):
    """A course taught by exactly one instructor, with a weekly schedule."""

    DAY_CHOICES = [
        ("MON", "Monday"),
        ("TUE", "Tuesday"),
        ("WED", "Wednesday"),
        ("THU", "Thursday"),
        ("FRI", "Friday"),
    ]

    code = models.CharField(max_length=20, unique=True)  # e.g. "DATA 13600"
    name = models.CharField(max_length=200)
    instructor = models.ForeignKey(
        InstructorProfile, on_delete=models.PROTECT, related_name="courses"
    )
    meeting_days = models.CharField(
        max_length=50, help_text="Comma-separated days, e.g. MON,WED"
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    students = models.ManyToManyField(
        StudentProfile, through="Enrollment", related_name="courses"
    )

    def __str__(self):
        return f"{self.code}: {self.name}"


class Enrollment(models.Model):
    """Links a student to a course (many-to-many through table)."""

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    enrolled_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("student", "course")

    def __str__(self):
        return f"{self.student} in {self.course}"


class Lecture(models.Model):
    """A single class meeting of a course.

    The qr_identifier is a random token embedded in the QR code shown in class.
    Because it is random and unique, students cannot guess it without being
    present, which helps prevent cheating.
    """

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="lectures"
    )
    date = models.DateField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    qr_identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ["-start_time"]

    def is_open(self, when=None):
        """Return True if `when` (default: now) falls inside the lecture window."""
        when = when or timezone.now()
        return self.start_time <= when <= self.end_time

    def __str__(self):
        return f"{self.course.code} on {self.date}"


class QRCodeUpload(models.Model):
    """A photo of a QR code uploaded by a student as proof of attendance.

    Anti-cheating fields:
        decoded_value: the text read from the QR code in the photo.
        is_valid: True if decoded_value matches the lecture's qr_identifier
                  and the upload happened while the lecture was open.
        ip_address: where the upload came from, for later review.
    """

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="qr_uploads"
    )
    lecture = models.ForeignKey(
        Lecture,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qr_uploads",
    )
    image = models.ImageField(upload_to="qr_uploads/%Y/%m/%d/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    decoded_value = models.CharField(max_length=255, blank=True)
    is_valid = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lecture"],
                condition=models.Q(is_valid=True),
                name="one_valid_upload_per_student_per_lecture",
            )
        ]

    def check_validity(self):
        """Mark this upload valid if it matches its lecture and arrived on time."""
        if self.lecture is None:
            self.is_valid = False
        else:
            matches = self.decoded_value == str(self.lecture.qr_identifier)
            self.is_valid = matches and self.lecture.is_open(self.uploaded_at)
        return self.is_valid

    def __str__(self):
        return f"Upload by {self.student} at {self.uploaded_at:%Y-%m-%d %H:%M}"
