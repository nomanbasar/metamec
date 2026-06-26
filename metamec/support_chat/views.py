import math

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from authentication.utils import build_response
from loan_applications.models import LoanApplication

from .models import (
    AgentAvailability,
    ChatConversation,
    ChatMessage,
    SupportAgent,
    SupportAppointment,
)
from datetime import datetime, timedelta
from django.conf import settings

User = get_user_model()


def _is_admin_user(user):
    if not user or not user.is_authenticated:
        return False

    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True

    return str(getattr(user, "role", "")).lower() in [
        "admin",
        "super_admin",
        "administrator",
    ]


def _to_int(value, default):
    try:
        value = int(value)
        return value if value > 0 else default
    except Exception:
        return default


def _meta(page, limit, total, filters=None):
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "totalPage": math.ceil(total / limit) if limit else 1,
        "filters": filters or {},
    }


def _user_name(user):
    return getattr(user, "full_name", None) or getattr(user, "email_address", None) or "User"


def _user_email(user):
    return getattr(user, "email_address", None) or getattr(user, "email", None) or ""


def _user_initials(user):
    name = _user_name(user)
    parts = name.replace("@", " ").replace(".", " ").split()

    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()

    if parts:
        return parts[0][:2].upper()

    return "U"


def _user_payload(user):
    if not user:
        return None

    return {
        "id": user.id,
        "name": _user_name(user),
        "email": _user_email(user),
        "initials": _user_initials(user),
        "role": getattr(user, "role", None),
        "isAdmin": _is_admin_user(user),
    }


def _get_default_admin():
    admin = User.objects.filter(is_superuser=True, is_active=True).first()

    if admin:
        return admin

    admin = User.objects.filter(is_staff=True, is_active=True).first()

    if admin:
        return admin

    return User.objects.filter(role="admin", is_active=True).first()


def _file_url(request, file_field):
    if not file_field:
        return None

    try:
        return request.build_absolute_uri(file_field.url)
    except Exception:
        return None


def _message_payload(request, message):
    return {
        "id": message.id,
        "conversationId": message.conversation_id,
        "sender": _user_payload(message.sender),
        "messageType": message.message_type,
        "message": message.message,
        "attachmentUrl": _file_url(request, message.attachment),
        "readAt": message.read_at,
        "createdAt": message.created_at,
    }


def _unread_count_for_user(conversation, user):
    if _is_admin_user(user):
        last_read = conversation.admin_last_read_at
    else:
        last_read = conversation.customer_last_read_at

    queryset = conversation.messages.exclude(sender=user)

    if last_read:
        queryset = queryset.filter(created_at__gt=last_read)

    return queryset.count()


def _conversation_payload(request, conversation):
    return {
        "id": conversation.id,
        "title": conversation.title,
        "status": conversation.status,
        "customer": _user_payload(conversation.customer),
        "admin": _user_payload(conversation.admin),
        "application": {
            "id": conversation.application.id,
            "applicationNumber": conversation.application.application_number,
            "loanType": conversation.application.loan_type.name if conversation.application.loan_type else None,
            "status": conversation.application.status,
        } if conversation.application else None,
        "lastMessage": conversation.last_message,
        "lastMessageAt": conversation.last_message_at,
        "unreadCount": _unread_count_for_user(conversation, request.user),
        "websocketUrl": f"/ws/chat/conversations/{conversation.id}/?token=<ACCESS_TOKEN>",
        "messagesApi": f"/api/chat/conversations/{conversation.id}/messages/",
        "markReadApi": f"/api/chat/conversations/{conversation.id}/read/",
        "createdAt": conversation.created_at,
        "updatedAt": conversation.updated_at,
    }


def _can_access_conversation(user, conversation):
    if _is_admin_user(user):
        return True

    return conversation.customer_id == user.id


class ChatConversationListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        status_filter = request.query_params.get("status", "").strip()
        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 20)

        queryset = ChatConversation.objects.select_related(
            "customer",
            "admin",
            "application",
            "application__loan_type",
        ).all()

        if not _is_admin_user(request.user):
            queryset = queryset.filter(customer=request.user)

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(customer__full_name__icontains=search)
                | Q(customer__email_address__icontains=search)
                | Q(admin__full_name__icontains=search)
                | Q(admin__email_address__icontains=search)
                | Q(application__application_number__icontains=search)
            )

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        total = queryset.count()
        start = (page - 1) * limit
        end = start + limit

        items = [
            _conversation_payload(request, conversation)
            for conversation in queryset.order_by("-last_message_at", "-created_at")[start:end]
        ]

        summary_queryset = ChatConversation.objects.all()

        if not _is_admin_user(request.user):
            summary_queryset = summary_queryset.filter(customer=request.user)

        return build_response(
            request,
            success=True,
            message="Chat conversations fetched successfully",
            meta=_meta(
                page,
                limit,
                total,
                {
                    "search": search,
                    "status": status_filter,
                },
            ),
            data={
                "summary": {
                    "total": summary_queryset.count(),
                    "open": summary_queryset.filter(status=ChatConversation.STATUS_OPEN).count(),
                    "closed": summary_queryset.filter(status=ChatConversation.STATUS_CLOSED).count(),
                },
                "conversations": items,
            },
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        application_id = request.data.get("application_id") or request.data.get("applicationId")
        title = str(request.data.get("title") or "Live Chat").strip()
        initial_message = str(request.data.get("message") or request.data.get("initial_message") or "").strip()

        application = None

        if application_id:
            application = LoanApplication.objects.filter(id=application_id, user=request.user).first()

            if not application and not _is_admin_user(request.user):
                return build_response(
                    request,
                    success=False,
                    message="Loan application not found",
                    data={},
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        if _is_admin_user(request.user):
            customer_id = request.data.get("customer_id") or request.data.get("customerId")

            if not customer_id:
                return build_response(
                    request,
                    success=False,
                    message="customer_id is required when admin creates a chat",
                    data={},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            customer = User.objects.filter(id=customer_id, is_active=True).first()

            if not customer:
                return build_response(
                    request,
                    success=False,
                    message="Customer not found",
                    data={},
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            admin = request.user

        else:
            customer = request.user
            admin = _get_default_admin()

        conversation = ChatConversation.objects.create(
            customer=customer,
            admin=admin,
            application=application,
            title=title,
        )

        if initial_message:
            message = ChatMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                message_type=ChatMessage.MESSAGE_TEXT,
                message=initial_message,
            )
            conversation.last_message = initial_message[:500]
            conversation.last_message_at = message.created_at
            conversation.save(update_fields=["last_message", "last_message_at", "updated_at"])

        return build_response(
            request,
            success=True,
            message="Chat conversation created successfully",
            data=_conversation_payload(request, conversation),
            status_code=status.HTTP_201_CREATED,
        )


class ChatConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        conversation = ChatConversation.objects.select_related(
            "customer",
            "admin",
            "application",
            "application__loan_type",
        ).filter(id=conversation_id).first()

        if not conversation:
            return build_response(
                request,
                success=False,
                message="Chat conversation not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not _can_access_conversation(request.user, conversation):
            return build_response(
                request,
                success=False,
                message="You do not have access to this conversation",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        return build_response(
            request,
            success=True,
            message="Chat conversation fetched successfully",
            data=_conversation_payload(request, conversation),
            status_code=status.HTTP_200_OK,
        )


class ChatMessagesView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request, conversation_id):
        conversation = ChatConversation.objects.filter(id=conversation_id).first()

        if not conversation:
            return build_response(
                request,
                success=False,
                message="Chat conversation not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not _can_access_conversation(request.user, conversation):
            return build_response(
                request,
                success=False,
                message="You do not have access to this conversation",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 30)

        queryset = ChatMessage.objects.select_related("sender").filter(conversation=conversation)
        total = queryset.count()

        start = max(total - (page * limit), 0)
        end = total - ((page - 1) * limit)

        messages = queryset.order_by("created_at")[start:end]

        return build_response(
            request,
            success=True,
            message="Chat messages fetched successfully",
            meta=_meta(page, limit, total),
            data={
                "conversation": _conversation_payload(request, conversation),
                "messages": [_message_payload(request, message) for message in messages],
            },
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, conversation_id):
        conversation = ChatConversation.objects.filter(id=conversation_id).first()

        if not conversation:
            return build_response(
                request,
                success=False,
                message="Chat conversation not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not _can_access_conversation(request.user, conversation):
            return build_response(
                request,
                success=False,
                message="You do not have access to this conversation",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        message_text = str(request.data.get("message") or "").strip()
        attachment = request.FILES.get("attachment") or request.FILES.get("file")

        if not message_text and not attachment:
            return build_response(
                request,
                success=False,
                message="Message or attachment is required",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            message_type=ChatMessage.MESSAGE_FILE if attachment else ChatMessage.MESSAGE_TEXT,
            message=message_text or None,
            attachment=attachment,
        )

        conversation.last_message = message_text[:500] if message_text else "Attachment"
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=["last_message", "last_message_at", "updated_at"])

        return build_response(
            request,
            success=True,
            message="Chat message sent successfully",
            data=_message_payload(request, message),
            status_code=status.HTTP_201_CREATED,
        )


class ChatMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, conversation_id):
        conversation = ChatConversation.objects.filter(id=conversation_id).first()

        if not conversation:
            return build_response(
                request,
                success=False,
                message="Chat conversation not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not _can_access_conversation(request.user, conversation):
            return build_response(
                request,
                success=False,
                message="You do not have access to this conversation",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        now = timezone.now()

        if _is_admin_user(request.user):
            conversation.admin_last_read_at = now
        else:
            conversation.customer_last_read_at = now

        conversation.save(update_fields=["admin_last_read_at", "customer_last_read_at", "updated_at"])

        updated_count = (
            ChatMessage.objects
            .filter(conversation=conversation, read_at__isnull=True)
            .exclude(sender=request.user)
            .update(read_at=now)
        )

        return build_response(
            request,
            success=True,
            message="Chat messages marked as read",
            data={
                "conversationId": conversation.id,
                "readAt": now,
                "updatedCount": updated_count,
            },
            status_code=status.HTTP_200_OK,
        )


class ChatAssignAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, conversation_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        conversation = ChatConversation.objects.filter(id=conversation_id).first()

        if not conversation:
            return build_response(
                request,
                success=False,
                message="Chat conversation not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        admin_id = request.data.get("admin_id") or request.data.get("adminId")

        if admin_id:
            admin = User.objects.filter(id=admin_id, is_active=True).first()

            if not admin:
                return build_response(
                    request,
                    success=False,
                    message="Admin user not found",
                    data={},
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        else:
            admin = request.user

        conversation.admin = admin
        conversation.save(update_fields=["admin", "updated_at"])

        return build_response(
            request,
            success=True,
            message="Chat conversation assigned successfully",
            data=_conversation_payload(request, conversation),
            status_code=status.HTTP_200_OK,
        )
    


def _parse_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_time(value):
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except Exception:
        try:
            return datetime.strptime(str(value), "%H:%M:%S").time()
        except Exception:
            return None


def _format_time(value):
    if not value:
        return None
    return value.strftime("%I:%M %p")


def _format_date(value):
    if not value:
        return None
    return value.strftime("%a, %B %d, %Y")


def _add_minutes_to_time(base_date, base_time, minutes):
    return (datetime.combine(base_date, base_time) + timedelta(minutes=minutes)).time()


def _make_datetime(base_date, base_time):
    naive_dt = datetime.combine(base_date, base_time)

    if getattr(settings, "USE_TZ", False):
        return timezone.make_aware(naive_dt, timezone.get_current_timezone())

    return naive_dt


def _agent_avatar_url(request, agent):
    if not agent.avatar:
        return None

    try:
        return request.build_absolute_uri(agent.avatar.url)
    except Exception:
        return None


def _agent_initials(agent):
    name = agent.name or "Agent"
    parts = name.split()

    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()

    return name[:2].upper()


def _agent_payload(request, agent):
    return {
        "id": agent.id,
        "name": agent.name,
        "email": agent.email,
        "phoneNumber": agent.phone_number,
        "initials": _agent_initials(agent),
        "title": agent.title,
        "speciality": agent.speciality,
        "rating": str(agent.rating),
        "reviewsCount": agent.reviews_count,
        "avatarUrl": _agent_avatar_url(request, agent),
        "availableCallTypes": agent.available_call_types or [],
        "isActive": agent.is_active,
        "slotsApi": f"/api/support/case-managers/{agent.id}/slots/?date=YYYY-MM-DD&call_type=phone_call",
    }


def _availability_payload(availability):
    return {
        "id": availability.id,
        "weekday": availability.weekday,
        "weekdayLabel": availability.get_weekday_display(),
        "startTime": availability.start_time.strftime("%H:%M"),
        "endTime": availability.end_time.strftime("%H:%M"),
        "slotDurationMinutes": availability.slot_duration_minutes,
        "breakStartTime": availability.break_start_time.strftime("%H:%M") if availability.break_start_time else None,
        "breakEndTime": availability.break_end_time.strftime("%H:%M") if availability.break_end_time else None,
        "isActive": availability.is_active,
    }


def _appointment_payload(request, appointment):
    starts_at = _make_datetime(appointment.appointment_date, appointment.start_time)
    ends_at = _make_datetime(appointment.appointment_date, appointment.end_time)

    return {
        "id": appointment.id,
        "status": appointment.status,
        "statusLabel": appointment.get_status_display(),
        "callType": appointment.call_type,
        "callTypeLabel": appointment.get_call_type_display(),
        "date": appointment.appointment_date.isoformat(),
        "dateLabel": _format_date(appointment.appointment_date),
        "time": appointment.start_time.strftime("%H:%M"),
        "timeLabel": _format_time(appointment.start_time),
        "startsAt": starts_at.isoformat(),
        "endsAt": ends_at.isoformat(),
        "note": appointment.note,
        "cancelReason": appointment.cancel_reason,
        "reminder": {
            "enabled": True,
            "minutesBefore": appointment.reminder_minutes_before,
            "message": f"You'll receive a reminder notification {appointment.reminder_minutes_before} minutes before your appointment.",
        },
        "manager": _agent_payload(request, appointment.agent),
        "customer": _user_payload(appointment.customer),
        "application": {
            "id": appointment.application.id,
            "applicationNumber": appointment.application.application_number,
            "loanType": appointment.application.loan_type.name if appointment.application.loan_type else None,
            "status": appointment.application.status,
        } if appointment.application else None,
        "actions": {
            "canCancel": appointment.status in [
                SupportAppointment.STATUS_SCHEDULED,
                SupportAppointment.STATUS_RESCHEDULED,
            ],
            "canReschedule": appointment.status in [
                SupportAppointment.STATUS_SCHEDULED,
                SupportAppointment.STATUS_RESCHEDULED,
            ],
            "cancelApi": f"/api/support/appointments/{appointment.id}/cancel/",
            "rescheduleApi": f"/api/support/appointments/{appointment.id}/reschedule/",
        },
        "createdAt": appointment.created_at,
        "updatedAt": appointment.updated_at,
    }


def _call_type_valid_for_agent(agent, call_type):
    available_types = agent.available_call_types or []
    return call_type in available_types


def _slot_is_inside_break(slot_start, slot_end, availability):
    if not availability.break_start_time or not availability.break_end_time:
        return False

    return slot_start < availability.break_end_time and slot_end > availability.break_start_time


def _get_generated_slots(agent, selected_date, call_type):
    weekday = selected_date.weekday()

    availability_rules = AgentAvailability.objects.filter(
        agent=agent,
        weekday=weekday,
        is_active=True,
    ).order_by("start_time")

    booked_times = set(
        SupportAppointment.objects.filter(
            agent=agent,
            appointment_date=selected_date,
            status__in=[
                SupportAppointment.STATUS_SCHEDULED,
                SupportAppointment.STATUS_RESCHEDULED,
            ],
        ).values_list("start_time", flat=True)
    )

    slots = []

    now = timezone.localtime()

    for availability in availability_rules:
        current_time = availability.start_time
        duration = availability.slot_duration_minutes

        while True:
            slot_end = _add_minutes_to_time(selected_date, current_time, duration)

            if slot_end > availability.end_time:
                break

            slot_start_dt = _make_datetime(selected_date, current_time)

            is_past = slot_start_dt <= now
            is_break = _slot_is_inside_break(current_time, slot_end, availability)
            is_booked = current_time in booked_times

            is_available = (
                not is_past
                and not is_break
                and not is_booked
                and _call_type_valid_for_agent(agent, call_type)
            )

            reason = None

            if is_past:
                reason = "Past time"
            elif is_break:
                reason = "Break time"
            elif is_booked:
                reason = "Already booked"
            elif not _call_type_valid_for_agent(agent, call_type):
                reason = "Call type not supported"

            slots.append({
                "time": current_time.strftime("%H:%M"),
                "label": _format_time(current_time),
                "durationMinutes": duration,
                "startsAt": slot_start_dt.isoformat(),
                "endsAt": _make_datetime(selected_date, slot_end).isoformat(),
                "isAvailable": is_available,
                "reason": reason,
            })

            current_time = slot_end

    return slots


def _find_slot(slots, time_value):
    for slot in slots:
        if slot["time"] == time_value.strftime("%H:%M"):
            return slot
    return None


def _get_application_for_appointment(user, application_id):
    if not application_id:
        return None

    return LoanApplication.objects.filter(id=application_id, user=user).first()


class SupportCaseManagerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        agents = SupportAgent.objects.filter(is_active=True).order_by("sort_order", "name")

        return build_response(
            request,
            success=True,
            message="Case managers fetched successfully",
            data=[_agent_payload(request, agent) for agent in agents],
            status_code=status.HTTP_200_OK,
        )


class SupportCaseManagerSlotsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, manager_id):
        agent = SupportAgent.objects.filter(id=manager_id, is_active=True).first()

        if not agent:
            return build_response(
                request,
                success=False,
                message="Case manager not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        selected_date = _parse_date(request.query_params.get("date"))
        call_type = request.query_params.get("call_type") or SupportAppointment.CALL_PHONE

        if not selected_date:
            return build_response(
                request,
                success=False,
                message="Valid date is required. Format: YYYY-MM-DD",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if call_type not in [SupportAppointment.CALL_PHONE, SupportAppointment.CALL_LIVE_CHAT]:
            return build_response(
                request,
                success=False,
                message="Invalid call_type. Use phone_call or live_chat.",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        slots = _get_generated_slots(agent, selected_date, call_type)

        return build_response(
            request,
            success=True,
            message="Available slots fetched successfully",
            data={
                "manager": _agent_payload(request, agent),
                "date": selected_date.isoformat(),
                "dateLabel": _format_date(selected_date),
                "callType": call_type,
                "callTypeLabel": dict(SupportAppointment.CALL_TYPE_CHOICES).get(call_type),
                "slots": slots,
            },
            status_code=status.HTTP_200_OK,
        )


class SupportAppointmentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        manager_id = request.data.get("manager_id") or request.data.get("managerId")
        application_id = request.data.get("application_id") or request.data.get("applicationId")
        call_type = request.data.get("call_type") or request.data.get("callType")
        date_value = request.data.get("date")
        time_value = request.data.get("time")
        note = request.data.get("note") or ""

        agent = SupportAgent.objects.filter(id=manager_id, is_active=True).first()

        if not agent:
            return build_response(
                request,
                success=False,
                message="Case manager not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        selected_date = _parse_date(date_value)
        selected_time = _parse_time(time_value)

        errors = {}

        if not selected_date:
            errors["date"] = ["Valid date is required. Format: YYYY-MM-DD"]

        if not selected_time:
            errors["time"] = ["Valid time is required. Format: HH:MM"]

        if call_type not in [SupportAppointment.CALL_PHONE, SupportAppointment.CALL_LIVE_CHAT]:
            errors["call_type"] = ["Use phone_call or live_chat."]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not _call_type_valid_for_agent(agent, call_type):
            return build_response(
                request,
                success=False,
                message="This case manager does not support the selected call type",
                data={
                    "availableCallTypes": agent.available_call_types,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        application = _get_application_for_appointment(request.user, application_id)

        if application_id and not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        slots = _get_generated_slots(agent, selected_date, call_type)
        selected_slot = _find_slot(slots, selected_time)

        if not selected_slot:
            return build_response(
                request,
                success=False,
                message="Selected time is outside case manager availability",
                data={"slots": slots},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not selected_slot["isAvailable"]:
            return build_response(
                request,
                success=False,
                message="Selected slot is not available",
                data={
                    "reason": selected_slot["reason"],
                    "slots": slots,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        end_time = _parse_time(selected_slot["endsAt"].split("T")[1][:5])

        appointment = SupportAppointment.objects.create(
            customer=request.user,
            agent=agent,
            application=application,
            call_type=call_type,
            appointment_date=selected_date,
            start_time=selected_time,
            end_time=end_time,
            status=SupportAppointment.STATUS_SCHEDULED,
            note=note,
        )

        return build_response(
            request,
            success=True,
            message="Appointment booked successfully",
            data=_appointment_payload(request, appointment),
            status_code=status.HTTP_201_CREATED,
        )


class MySupportAppointmentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = SupportAppointment.objects.select_related(
            "customer",
            "agent",
            "application",
            "application__loan_type",
        )

        if _is_admin_user(request.user):
            queryset = queryset.all()
        else:
            queryset = queryset.filter(customer=request.user)

        status_filter = request.query_params.get("status")

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        appointments = queryset.order_by("-appointment_date", "-start_time")

        return build_response(
            request,
            success=True,
            message="Appointments fetched successfully",
            data=[_appointment_payload(request, appointment) for appointment in appointments],
            status_code=status.HTTP_200_OK,
        )


class SupportAppointmentCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, appointment_id):
        appointment = SupportAppointment.objects.select_related(
            "customer",
            "agent",
            "application",
            "application__loan_type",
        ).filter(id=appointment_id).first()

        if not appointment:
            return build_response(
                request,
                success=False,
                message="Appointment not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not _is_admin_user(request.user) and appointment.customer_id != request.user.id:
            return build_response(
                request,
                success=False,
                message="You do not have permission to cancel this appointment",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        if appointment.status == SupportAppointment.STATUS_CANCELLED:
            return build_response(
                request,
                success=False,
                message="Appointment is already cancelled",
                data=_appointment_payload(request, appointment),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        appointment.status = SupportAppointment.STATUS_CANCELLED
        appointment.cancel_reason = request.data.get("reason") or request.data.get("cancel_reason") or ""
        appointment.cancelled_at = timezone.now()
        appointment.save(update_fields=["status", "cancel_reason", "cancelled_at", "updated_at"])

        return build_response(
            request,
            success=True,
            message="Appointment cancelled successfully",
            data=_appointment_payload(request, appointment),
            status_code=status.HTTP_200_OK,
        )


class SupportAppointmentRescheduleView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, appointment_id):
        appointment = SupportAppointment.objects.select_related(
            "customer",
            "agent",
            "application",
            "application__loan_type",
        ).filter(id=appointment_id).first()

        if not appointment:
            return build_response(
                request,
                success=False,
                message="Appointment not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not _is_admin_user(request.user) and appointment.customer_id != request.user.id:
            return build_response(
                request,
                success=False,
                message="You do not have permission to reschedule this appointment",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        selected_date = _parse_date(request.data.get("date"))
        selected_time = _parse_time(request.data.get("time"))

        errors = {}

        if not selected_date:
            errors["date"] = ["Valid date is required. Format: YYYY-MM-DD"]

        if not selected_time:
            errors["time"] = ["Valid time is required. Format: HH:MM"]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        slots = _get_generated_slots(appointment.agent, selected_date, appointment.call_type)
        selected_slot = _find_slot(slots, selected_time)

        if not selected_slot or not selected_slot["isAvailable"]:
            return build_response(
                request,
                success=False,
                message="Selected slot is not available",
                data={
                    "reason": selected_slot["reason"] if selected_slot else "Outside availability",
                    "slots": slots,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        appointment.appointment_date = selected_date
        appointment.start_time = selected_time
        appointment.end_time = _parse_time(selected_slot["endsAt"].split("T")[1][:5])
        appointment.status = SupportAppointment.STATUS_RESCHEDULED
        appointment.rescheduled_at = timezone.now()
        appointment.save(update_fields=[
            "appointment_date",
            "start_time",
            "end_time",
            "status",
            "rescheduled_at",
            "updated_at",
        ])

        return build_response(
            request,
            success=True,
            message="Appointment rescheduled successfully",
            data=_appointment_payload(request, appointment),
            status_code=status.HTTP_200_OK,
        )


class AdminSupportCaseManagerListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        agents = SupportAgent.objects.all().order_by("sort_order", "name")

        return build_response(
            request,
            success=True,
            message="Case managers fetched successfully",
            data=[_agent_payload(request, agent) for agent in agents],
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        user_id = request.data.get("user_id") or request.data.get("userId")
        linked_user = None

        if user_id:
            linked_user = User.objects.filter(id=user_id, is_active=True).first()

            if not linked_user:
                return build_response(
                    request,
                    success=False,
                    message="User not found",
                    data={},
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        name = request.data.get("name") or (_user_name(linked_user) if linked_user else "")
        email = request.data.get("email") or (_user_email(linked_user) if linked_user else "")

        if not name:
            return build_response(
                request,
                success=False,
                message="Name is required",
                data={"name": ["Name is required."]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        available_call_types = request.data.get("available_call_types") or request.data.get("availableCallTypes")

        if isinstance(available_call_types, str):
            available_call_types = [item.strip() for item in available_call_types.split(",") if item.strip()]

        if not available_call_types:
            available_call_types = [SupportAppointment.CALL_PHONE, SupportAppointment.CALL_LIVE_CHAT]

        agent = SupportAgent.objects.create(
            user=linked_user,
            name=name,
            email=email,
            phone_number=request.data.get("phone_number") or request.data.get("phoneNumber"),
            title=request.data.get("title") or "Senior Loan Advisor",
            speciality=request.data.get("speciality") or "Homeowner Loans",
            rating=request.data.get("rating") or 4.9,
            reviews_count=request.data.get("reviews_count") or request.data.get("reviewsCount") or 312,
            available_call_types=available_call_types,
            is_active=_truthy(request.data.get("is_active", True)),
            sort_order=request.data.get("sort_order") or request.data.get("sortOrder") or 0,
        )

        return build_response(
            request,
            success=True,
            message="Case manager created successfully",
            data=_agent_payload(request, agent),
            status_code=status.HTTP_201_CREATED,
        )


class AdminSupportAgentAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, manager_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        agent = SupportAgent.objects.filter(id=manager_id).first()

        if not agent:
            return build_response(
                request,
                success=False,
                message="Case manager not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        availability = AgentAvailability.objects.filter(agent=agent).order_by("weekday", "start_time")

        return build_response(
            request,
            success=True,
            message="Availability rules fetched successfully",
            data={
                "manager": _agent_payload(request, agent),
                "availability": [_availability_payload(item) for item in availability],
            },
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, manager_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        agent = SupportAgent.objects.filter(id=manager_id).first()

        if not agent:
            return build_response(
                request,
                success=False,
                message="Case manager not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        weekdays = request.data.get("weekdays")

        if weekdays is None:
            weekday = request.data.get("weekday")
            weekdays = [weekday] if weekday is not None else []

        start_time = _parse_time(request.data.get("start_time") or request.data.get("startTime"))
        end_time = _parse_time(request.data.get("end_time") or request.data.get("endTime"))

        break_start_time = _parse_time(request.data.get("break_start_time") or request.data.get("breakStartTime"))
        break_end_time = _parse_time(request.data.get("break_end_time") or request.data.get("breakEndTime"))

        slot_duration_minutes = _to_int(
            request.data.get("slot_duration_minutes") or request.data.get("slotDurationMinutes"),
            30,
        )

        errors = {}

        if not weekdays:
            errors["weekdays"] = ["weekdays is required. Example: [0,1,2,3,4]"]

        if not start_time:
            errors["start_time"] = ["Valid start_time is required. Format: HH:MM"]

        if not end_time:
            errors["end_time"] = ["Valid end_time is required. Format: HH:MM"]

        if start_time and end_time and end_time <= start_time:
            errors["end_time"] = ["end_time must be greater than start_time."]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        created_items = []

        for weekday in weekdays:
            try:
                weekday_int = int(weekday)
            except Exception:
                continue

            if weekday_int < 0 or weekday_int > 6:
                continue

            availability = AgentAvailability.objects.create(
                agent=agent,
                weekday=weekday_int,
                start_time=start_time,
                end_time=end_time,
                slot_duration_minutes=slot_duration_minutes,
                break_start_time=break_start_time,
                break_end_time=break_end_time,
                is_active=_truthy(request.data.get("is_active", True)),
            )
            created_items.append(availability)

        return build_response(
            request,
            success=True,
            message="Availability rules created successfully",
            data={
                "manager": _agent_payload(request, agent),
                "availability": [_availability_payload(item) for item in created_items],
            },
            status_code=status.HTTP_201_CREATED,
        )


class AdminSupportAppointmentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        queryset = SupportAppointment.objects.select_related(
            "customer",
            "agent",
            "application",
            "application__loan_type",
        )

        status_filter = request.query_params.get("status")
        manager_id = request.query_params.get("manager_id") or request.query_params.get("managerId")
        date_value = _parse_date(request.query_params.get("date"))

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if manager_id:
            queryset = queryset.filter(agent_id=manager_id)

        if date_value:
            queryset = queryset.filter(appointment_date=date_value)

        appointments = queryset.order_by("-appointment_date", "-start_time")

        return build_response(
            request,
            success=True,
            message="Admin appointments fetched successfully",
            data=[_appointment_payload(request, appointment) for appointment in appointments],
            status_code=status.HTTP_200_OK,
        )


class AdminSupportAppointmentStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, appointment_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        appointment = SupportAppointment.objects.select_related(
            "customer",
            "agent",
            "application",
            "application__loan_type",
        ).filter(id=appointment_id).first()

        if not appointment:
            return build_response(
                request,
                success=False,
                message="Appointment not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        new_status = request.data.get("status")

        allowed_statuses = [
            SupportAppointment.STATUS_SCHEDULED,
            SupportAppointment.STATUS_COMPLETED,
            SupportAppointment.STATUS_CANCELLED,
            SupportAppointment.STATUS_MISSED,
            SupportAppointment.STATUS_RESCHEDULED,
        ]

        if new_status not in allowed_statuses:
            return build_response(
                request,
                success=False,
                message="Invalid appointment status",
                data={
                    "allowedStatus": allowed_statuses,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        appointment.status = new_status

        if new_status == SupportAppointment.STATUS_COMPLETED:
            appointment.completed_at = timezone.now()

        if new_status == SupportAppointment.STATUS_CANCELLED:
            appointment.cancelled_at = timezone.now()
            appointment.cancel_reason = request.data.get("reason") or appointment.cancel_reason

        appointment.save()

        return build_response(
            request,
            success=True,
            message="Appointment status updated successfully",
            data=_appointment_payload(request, appointment),
            status_code=status.HTTP_200_OK,
        )