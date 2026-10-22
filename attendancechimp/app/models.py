"""
AttendanceChimp data model (HW3).

Six tables, matching app/docs/my-data-model.png:

    InstructorProfile  - the teachers (linked to a Django login account)
    StudentProfile     - the students (linked to a Django login account)
    Course             - a class, taught by exactly one instructor
    Enrollment         - which student is in which course (many-to-many link)
    Lecture            - one class meeting, belongs to one course
    QRCodeUpload       - a photo of a QR code uploaded by a student

Why separate Instructor and Student tables instead of one Users table?
Students and instructors store different information (students have a
student_id, instructors have a department), and a separate table means the
database itself stops a student from being set as a course's instructor.

Both profiles are linked one-to-one to Django's built-in User model, so every
student and instructor gets a login account (username, password, name, email)
for free instead of us rebuilding authentication.

Relationships (all made with foreign keys):
    InstructorProfile.user -> User            (one-to-one)
    StudentProfile.user    -> User            (one-to-one)
    Course.instructor  -> InstructorProfile   (one instructor, many courses)
    Enrollment.student -> StudentProfile      (one student, many enrollments)
    Enrollment.course  -> Course              (one course, many enrollments)
    Lecture.course     -> Course              (one course, many lectures)
    QRCodeUpload.student -> StudentProfile    (one student, many uploads)
    QRCodeUpload.lecture -> Lecture           (one lecture, many uploads; optional)
"""

import uuid

from django.contrib.auth.models import User
from django.db import models


class InstructorProfile(models.Model):
    """A teacher who can be assigned to courses.

    Fields:
        user:       the teacher's Django login account (one-to-one). Name and
                    email live on the User. Deleting the User deletes the
                    profile (CASCADE).
        department: the teacher's department (optional).
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="instructor_profile"
    )
    department = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class StudentProfile(models.Model):
    """A student who can enroll in courses and upload QR code photos.

    Fields:
        user:       the student's Django login account (one-to-one). Name and
                    email live on the User. Deleting the User deletes the
                    profile (CASCADE).
        student_id: the school ID number (unique), used to tell students apart.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="student_profile"
    )
    student_id = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.student_id})"


class Course(models.Model):
    """A class taught by exactly one instructor.

    Fields:
        name:             the course name, e.g. "DATA 13600".
        instructor:       who teaches it. on_delete=PROTECT means you cannot
                          delete an instructor who still has courses, so
                          courses are never lost by accident.
        meeting_schedule: when the class meets, e.g. "Mon/Wed 10:30-11:50".
    """

    name = models.CharField(max_length=100)
    instructor = models.ForeignKey(
        InstructorProfile, on_delete=models.PROTECT, related_name="courses"
    )
    meeting_schedule = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Enrollment(models.Model):
    """Links one student to one course (the many-to-many join table).

    A student can be in many courses and a course has many students, so we
    store one row per (student, course) pair. If the student or the course is
    deleted, their enrollment rows are deleted too (CASCADE).

    The unique constraint stops a student from enrolling in the same course
    twice, which keeps attendance counts correct.
    """

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"], name="unique_student_course"
            )
        ]

    def __str__(self):
        return f"{self.student} in {self.course.name}"


class Lecture(models.Model):
    """One class meeting of a course.

    Fields:
        course:        which course this lecture belongs to. If the course is
                       deleted, its lectures are deleted too (CASCADE).
        date:          the day of the lecture.
        qr_identifier: a random, unique, hard-to-guess code (a UUID) that is
                       shown on the lecture's QR code. Because it is random,
                       a student who skipped class cannot guess it. This is
                       the main protection against cheating.
    """

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="lectures"
    )
    date = models.DateField()
    qr_identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    def __str__(self):
        return f"{self.course.name} on {self.date}"


class QRCodeUpload(models.Model):
    """A photo of a QR code uploaded by a student to prove attendance.

    Fields:
        student:     who uploaded it. Deleted with the student (CASCADE).
        lecture:     which lecture the photo is for. Optional (null=True)
                     because we may not know the lecture until the QR code is
                     read. If the lecture is deleted, the upload is kept and
                     this field becomes empty (SET_NULL).
        photo:       the uploaded image file.
        uploaded_at: the time of upload, set automatically. Used to check the
                     photo was sent during class (anti-cheating) and for
                     attendance analytics.
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
    photo = models.FileField(upload_to="qr_uploads/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Upload by {self.student} at {self.uploaded_at}"
