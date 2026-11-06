from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import Course, InstructorProfile, Lecture, QRCodeUpload, StudentProfile

CDT = ZoneInfo("America/Chicago")


def time_view(request: HttpRequest) -> HttpResponse:
    """Return current Chicago time as HH:MM (24-hour), plain text."""
    now = datetime.now(tz=CDT)
    return HttpResponse(now.strftime("%H:%M"), content_type="text/plain")


def _decimal_to_str(x: Decimal) -> str:
    """Format Decimal without scientific notation and without trailing zeros."""
    s = format(x, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def sum_view(request: HttpRequest) -> HttpResponse:
    """Return n1 + n2 from query params as plain text."""
    n1_str = request.GET.get("n1", "0")
    n2_str = request.GET.get("n2", "0")

    try:
        val = Decimal(n1_str) + Decimal(n2_str)
    except (InvalidOperation, ValueError):
        return HttpResponse("Bad Request: n1 and n2 must be numbers", status=400, content_type="text/plain")

    return HttpResponse(_decimal_to_str(val), content_type="text/plain")


# ----------------------------------------------------------------------------
# HW4
# ----------------------------------------------------------------------------

def index(request: HttpRequest) -> HttpResponse:
    """Home page: app name, bio, logged-in user (or 'Not logged in.'), and time.

    The template gets two context values:
        time:      current Chicago time as HH:MM
        user_name: the logged-in user's username, or None if nobody is logged in
    """
    now = datetime.now(tz=CDT)
    context = {
        "time": now.strftime("%H:%M"),
        "user_name": request.user.get_username() if request.user.is_authenticated else None,
    }
    return render(request, "app/index.html", context)


@csrf_exempt
@require_GET
def new(request: HttpRequest) -> HttpResponse:
    """Sign-up form page. GET only; any other method gets 405."""
    return render(request, "app/new.html")


@csrf_exempt
@require_POST
def createUser(request: HttpRequest) -> JsonResponse:
    """API endpoint that creates a User plus a student or instructor profile.

    POST fields: user_name, email, password, is_student ("1" = student,
    anything else = instructor). POST only; any other method gets 405.

    Responses:
        200  user created and signed in
        400  a field is missing
        409  the email or user name is already taken
    """
    user_name = request.POST.get("user_name", "").strip()
    email = request.POST.get("email", "").strip()
    password = request.POST.get("password", "")
    is_student_raw = request.POST.get("is_student")

    if not user_name or not email or not password or is_student_raw is None:
        return JsonResponse(
            {"error": "user_name, email, password and is_student are required"}, status=400
        )

    if User.objects.filter(email__iexact=email).exists():
        return JsonResponse({"error": "That email is already registered"}, status=409)
    if User.objects.filter(username=user_name).exists():
        return JsonResponse({"error": "That user name is already taken"}, status=409)

    is_student = is_student_raw.strip().lower() in ("1", "true", "yes", "on")

    # atomic: if the profile fails, the User is not left behind half-created
    with transaction.atomic():
        user = User.objects.create_user(username=user_name, email=email, password=password)
        if is_student:
            # student_id is required and unique; use a placeholder built from
            # the user's id until a real school ID is collected.
            StudentProfile.objects.create(user=user, student_id=f"S{user.pk:06d}")
        else:
            InstructorProfile.objects.create(user=user)

    login(request, user)
    return JsonResponse(
        {"status": "ok", "user_name": user.username, "role": "student" if is_student else "instructor"}
    )


# ----------------------------------------------------------------------------
# HW5
# ----------------------------------------------------------------------------

def _unauthorized(message: str) -> JsonResponse:
    """The 401 response used by every role-protected endpoint."""
    return JsonResponse({"error": message}, status=401)


def _instructor_profile(user):
    """Return the user's InstructorProfile, or None if not a logged-in instructor."""
    if not user.is_authenticated:
        return None
    return InstructorProfile.objects.filter(user=user).first()


def _student_profile(user):
    """Return the user's StudentProfile, or None if not a logged-in student."""
    if not user.is_authenticated:
        return None
    return StudentProfile.objects.filter(user=user).first()


@require_GET
def new_course(request: HttpRequest) -> HttpResponse:
    """Form page for creating a course (submits to /app/createCourse)."""
    return render(request, "app/new_course.html")


@require_GET
def new_lecture(request: HttpRequest) -> HttpResponse:
    """Form page for creating a lecture. Lists existing courses to choose from."""
    return render(request, "app/new_lecture.html", {"courses": Course.objects.order_by("name")})


@require_GET
def new_qr_upload(request: HttpRequest) -> HttpResponse:
    """Form page for uploading a QR code photo (submits to /app/createQRCodeUpload)."""
    return render(request, "app/new_qr_upload.html")


@csrf_exempt
@require_POST
def createCourse(request: HttpRequest) -> JsonResponse:
    """Create a Course taught by the logged-in instructor.

    POST fields: course-name, start-time, end-time, and one or more of
    day-mon, day-tue, day-wed, day-thu, day-fri.
    Responses: 200 created, 400 bad input, 401 not an instructor, 409 name taken.
    """
    instructor = _instructor_profile(request.user)
    if instructor is None:
        return _unauthorized("Only logged-in instructors can create courses")

    name = request.POST.get("course-name", "").strip()
    start = request.POST.get("start-time", "").strip()
    end = request.POST.get("end-time", "").strip()
    days = [
        label
        for key, label in (("mon", "Mon"), ("tue", "Tue"), ("wed", "Wed"), ("thu", "Thu"), ("fri", "Fri"))
        if request.POST.get(f"day-{key}", "").strip().lower() not in ("", "0", "false", "off")
    ]

    if not name or not start or not end or not days:
        return JsonResponse(
            {"error": "course-name, start-time, end-time and at least one day are required"}, status=400
        )
    if len(name) > 100:
        return JsonResponse({"error": "course-name is too long (max 100 characters)"}, status=400)
    if Course.objects.filter(name=name).exists():
        return JsonResponse({"error": "A course with that name already exists"}, status=409)

    Course.objects.create(
        name=name,
        instructor=instructor,
        meeting_schedule=f"{'/'.join(days)} {start}-{end}",
    )
    return JsonResponse({"status": "ok", "course": name})


@csrf_exempt
@require_POST
def createLecture(request: HttpRequest) -> JsonResponse:
    """Create a Lecture (today's date, new random QR id) for the course named in `choice`.

    Responses: 200 created, 400 missing/unknown course, 401 not an instructor.
    """
    if _instructor_profile(request.user) is None:
        return _unauthorized("Only logged-in instructors can create lectures")

    course_name = request.POST.get("choice", "").strip()
    if not course_name:
        return JsonResponse({"error": "choice (a course name) is required"}, status=400)

    course = Course.objects.filter(name=course_name).first()
    if course is None:
        return JsonResponse({"error": "No course with that name"}, status=400)

    lecture = Lecture.objects.create(course=course, date=datetime.now(tz=CDT).date())
    return JsonResponse({"status": "ok", "course": course.name, "qr_identifier": str(lecture.qr_identifier)})


@csrf_exempt
@require_POST
def createQRCodeUpload(request: HttpRequest) -> JsonResponse:
    """Save a QR code photo uploaded by the logged-in student.

    POST file field: imageUpload. The student comes from the logged-in user and
    the upload time is set automatically.
    Responses: 200 saved, 400 no file, 401 not a student.
    """
    student = _student_profile(request.user)
    if student is None:
        return _unauthorized("Only logged-in students can upload QR codes")

    image = request.FILES.get("imageUpload")
    if image is None:
        return JsonResponse({"error": "imageUpload file is required"}, status=400)

    QRCodeUpload.objects.create(student=student, photo=image)
    return JsonResponse({"status": "ok"})


@require_GET
def dumpUploads(request: HttpRequest) -> JsonResponse:
    """Return every QR upload as JSON: [{"username": ..., "upload_time": ...}, ...].

    Responses: 200 list, 401 not an instructor.
    """
    if _instructor_profile(request.user) is None:
        return _unauthorized("Only logged-in instructors can view uploads")

    data = []
    for upload in QRCodeUpload.objects.select_related("student__user").order_by("uploaded_at"):
        when = upload.uploaded_at
        if timezone.is_aware(when):
            when = timezone.localtime(when)
        data.append(
            {
                "username": upload.student.user.username,
                "upload_time": when.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return JsonResponse(data, safe=False)
