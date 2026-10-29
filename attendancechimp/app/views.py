from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import InstructorProfile, StudentProfile

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
