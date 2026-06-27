import random
import string

from django.conf import settings
from django.utils import timezone

from .models import ReferralProfile, ReferralRecord


def get_user_email(user):
    return (
        getattr(user, "email_address", None)
        or getattr(user, "email", None)
        or ""
    )


def get_user_name(user):
    return (
        getattr(user, "full_name", None)
        or getattr(user, "name", None)
        or get_user_email(user)
        or str(user)
    )


def make_initials(name):
    name = (name or "User").strip()
    parts = [p for p in name.split() if p]

    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()

    return name[:2].upper()


def make_referral_code(user):
    name = get_user_name(user).upper()
    clean_name = "".join(ch for ch in name if ch.isalnum())

    prefix = clean_name[:4] if clean_name else "LSRF"
    alphabet = string.ascii_uppercase + string.digits

    while True:
        suffix = "".join(random.choice(alphabet) for _ in range(4))
        code = f"{prefix}{suffix}"[:12]

        if not ReferralProfile.objects.filter(referral_code=code).exists():
            return code


def get_or_create_profile(user):
    profile = ReferralProfile.objects.filter(user=user).first()

    if profile:
        return profile

    return ReferralProfile.objects.create(
        user=user,
        referral_code=make_referral_code(user),
        is_active=True,
    )


def build_referral_link(profile):
    base_url = getattr(
        settings,
        "REFERRAL_FRONTEND_BASE_URL",
        "https://loansphere.app/ref",
    )

    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}code={profile.referral_code}"


def get_referral_profile_by_code(referral_code):
    code = (referral_code or "").strip().upper()

    if not code:
        return None

    return ReferralProfile.objects.select_related("user").filter(
        referral_code__iexact=code,
        is_active=True,
    ).first()


def create_referral_record(user, referral_profile):

    try:
        if not user or not referral_profile:
            return None

        if referral_profile.user_id == user.id:
            return None

        existing_record = ReferralRecord.objects.filter(
            referred_user=user,
        ).first()

        if existing_record:
            return existing_record

        is_verified = bool(getattr(user, "is_email_verified", False))

        record = ReferralRecord.objects.create(
            referrer=referral_profile.user,
            referred_user=user,
            status=(
                ReferralRecord.STATUS_JOINED_ACTIVE
                if is_verified
                else ReferralRecord.STATUS_PENDING
            ),
            referral_code_snapshot=referral_profile.referral_code,
            referral_link_snapshot=build_referral_link(referral_profile),
            joined_at=timezone.now() if is_verified else None,
        )

        return record

    except Exception:
        return None


def mark_referral_joined_active(user):
    """
    Email verify success হলে pending referral কে joined_active করবে।
    """
    try:
        record = ReferralRecord.objects.filter(
            referred_user=user,
        ).first()

        if not record:
            return None

        if record.status == ReferralRecord.STATUS_JOINED_ACTIVE:
            return record

        record.status = ReferralRecord.STATUS_JOINED_ACTIVE
        record.joined_at = record.joined_at or timezone.now()
        record.save(
            update_fields=[
                "status",
                "joined_at",
                "updated_at",
            ]
        )

        return record

    except Exception:
        return None


def sync_referral_records_for_user(user):
    records = ReferralRecord.objects.filter(
        referrer=user,
    ).select_related("referred_user")

    for record in records:
        if (
            getattr(record.referred_user, "is_email_verified", False)
            and record.status != ReferralRecord.STATUS_JOINED_ACTIVE
        ):
            record.status = ReferralRecord.STATUS_JOINED_ACTIVE
            record.joined_at = record.joined_at or timezone.now()
            record.save(
                update_fields=[
                    "status",
                    "joined_at",
                    "updated_at",
                ]
            )


def record_payload(record):
    referred_user = record.referred_user
    name = get_user_name(referred_user)

    date_value = record.joined_at or record.signup_at or record.created_at

    return {
        "id": str(record.id),
        "name": name,
        "email": get_user_email(referred_user),
        "initials": make_initials(name),
        "status": record.status,
        "statusLabel": record.get_status_display(),
        "date": date_value.isoformat() if date_value else None,
        "dateLabel": date_value.strftime("%b %d, %Y") if date_value else None,
        "referredUserId": str(referred_user.id),
    }


def dashboard_payload(user):
    profile = get_or_create_profile(user)
    referral_link = build_referral_link(profile)

    sync_referral_records_for_user(user)

    records = ReferralRecord.objects.filter(
        referrer=user,
    ).select_related("referred_user").order_by("-created_at")

    total_invited = records.count()
    joined_active = records.filter(
        status=ReferralRecord.STATUS_JOINED_ACTIVE
    ).count()
    pending = records.filter(
        status=ReferralRecord.STATUS_PENDING
    ).count()

    goal = 5
    percentage = int((joined_active / goal) * 100) if goal else 0
    percentage = min(percentage, 100)

    return {
        "screenTitle": "Refer a Friend",
        "hero": {
            "programTitle": "Referral Program",
            "title": f"{total_invited}-Invited",
            "subtitle": "Please recommend us to your friends, family & colleagues.",
            "totalInvited": total_invited,
        },
        "referral": {
            "code": profile.referral_code,
            "link": referral_link,
            "copyText": referral_link,
        },
        "shareVia": {
            "whatsapp": f"https://wa.me/?text={referral_link}",
            "email": f"mailto:?subject=Join LoanSphere&body={referral_link}",
            "shareText": referral_link,
        },
        "progress": {
            "title": "Referral Progress",
            "goal": goal,
            "joined": joined_active,
            "pending": pending,
            "invited": 0,
            "percentage": percentage,
            "remainingText": f"{max(goal - joined_active, 0)} more joined",
        },
        "stats": {
            "totalInvited": total_invited,
            "joinedActive": joined_active,
            "pending": pending,
            "invited": 0,
            "goal": goal,
            "progressPercentage": percentage,
            "remainingToGoal": max(goal - joined_active, 0),
        },
        "referrals": [
            record_payload(record)
            for record in records
        ],
    }