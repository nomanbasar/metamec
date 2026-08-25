import math

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.core.mail import send_mail
from authentication.utils import build_response
from loan_applications.models import LoanApplication
from user_notifications.events import (
    notify_appointment_booked,
    notify_appointment_status_changed,
    notify_chat_message,
)
import json
import secrets
import string
from django.db import transaction

from .models import (
    AgentAvailability,
    ChatConversation,
    ChatMessage,
    SupportAgent,
    SupportAppointment,
    ChatTemplateFolder,
    ChatTemplate,
)

from .ai_chat_service import (
    is_ai_user,
    maybe_generate_ai_reply,
)
from datetime import datetime, timedelta
from django.conf import settings

User = get_user_model()

def _truthy(value):
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    return str(value).strip().lower() in ["true", "1", "yes", "y", "on"]


def _normalize_call_types(value):
    if value is None or value == "":
        return [SupportAppointment.CALL_PHONE, SupportAppointment.CALL_LIVE_CHAT]

    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        text = value.strip()

        if text.startswith("[") and text.endswith("]"):
            text = text.replace("[", "").replace("]", "").replace('"', "").replace("'", "")

        items = [item.strip() for item in text.split(",") if item.strip()]
    else:
        items = []

    allowed = [SupportAppointment.CALL_PHONE, SupportAppointment.CALL_LIVE_CHAT]

    return [item for item in items if item in allowed] or allowed


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

def _is_support_staff(user):
    if not user or not user.is_authenticated:
        return False

    if str(getattr(user, "role", "")).lower() != "support_staff":
        return False

    try:
        return bool(
            user.support_agent_profile
            and user.support_agent_profile.is_active
        )
    except SupportAgent.DoesNotExist:
        return False



def _generate_temporary_password(length=12):
    alphabet = string.ascii_letters + string.digits + "@#$%"

    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))

        if (
            any(char.islower() for char in password)
            and any(char.isupper() for char in password)
            and any(char.isdigit() for char in password)
            and any(char in "@#$%" for char in password)
        ):
            return password


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
        "isSupportStaff": _is_support_staff(user),
        "isAI": is_ai_user(user),
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
        return file_field.url
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


def _can_access_chat_templates(user):
    return _is_admin_user(user) or _is_support_staff(user)


def _template_folder_payload(folder):
    if not folder:
        return None

    return {
        "id": folder.id,
        "name": folder.name,
        "parent": (
            {
                "id": folder.parent.id,
                "name": folder.parent.name,
            }
            if folder.parent
            else None
        ),
        "templateCount": folder.templates.count(),
        "subfolderCount": folder.subfolders.count(),
        "createdBy": _user_payload(folder.created_by),
        "createdAt": folder.created_at,
        "updatedAt": folder.updated_at,
    }


def _template_payload(request, template):
    return {
        "id": template.id,
        "name": template.name,
        "category": template.category,
        "language": template.language,
        "message": template.message,
        "headerType": template.header_type,
        "headerText": template.header_text,
        "headerFile": _file_url(request, template.header_file),
        "footerText": template.footer_text,
        "buttons": template.buttons,
        "folder": (
            {
                "id": template.folder.id,
                "name": template.folder.name,
            }
            if template.folder
            else None
        ),
        "status": template.status,
        "createdBy": _user_payload(template.created_by),
        "createdAt": template.created_at,
        "updatedAt": template.updated_at,
    }


def _parse_template_buttons(value):
    if value is None or value == "":
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed
        except (json.JSONDecodeError, TypeError):
            return None

    return None


def _validate_template_buttons(buttons):
    if not isinstance(buttons, list):
        return "Buttons must be a valid list."

    if len(buttons) > 10:
        return "Maximum 10 buttons are allowed."

    for button in buttons:
        if not isinstance(button, dict):
            return "Each button must be an object."

        if not str(button.get("type") or "").strip():
            return "Each button requires a type."

        if not str(button.get("label") or "").strip():
            return "Each button requires a label."

    return None


# def _unread_count_for_user(conversation, user):
#     if _is_admin_user(user):
#         last_read = conversation.admin_last_read_at
#     else:
#         last_read = conversation.customer_last_read_at

#     queryset = conversation.messages.exclude(sender=user)

#     if last_read:
#         queryset = queryset.filter(created_at__gt=last_read)

#     return queryset.count()

def _unread_count_for_user(conversation, user):
    if _is_admin_user(user) or _is_support_staff(user):
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


# def _can_access_conversation(user, conversation):
#     if _is_admin_user(user):
#         return True

#     return conversation.customer_id == user.id

def _can_access_conversation(user, conversation):
    if not user or not user.is_authenticated:
        return False

    # Main admin can monitor every conversation
    if _is_admin_user(user):
        return True

    # Support staff can access only assigned conversations
    if _is_support_staff(user):
        return conversation.admin_id == user.id

    # Customer can access only own conversations
    return conversation.customer_id == user.id


# class ChatConversationListCreateView(APIView):
#     permission_classes = [IsAuthenticated]
#     parser_classes = [JSONParser, MultiPartParser, FormParser]

#     def get(self, request):
#         search = request.query_params.get("search", "").strip()
#         status_filter = request.query_params.get("status", "").strip()
#         page = _to_int(request.query_params.get("page"), 1)
#         limit = _to_int(request.query_params.get("limit"), 20)

#         queryset = ChatConversation.objects.select_related(
#             "customer",
#             "admin",
#             "application",
#             "application__loan_type",
#         ).all()

#         if not _is_admin_user(request.user):
#             queryset = queryset.filter(customer=request.user)

#         if search:
#             queryset = queryset.filter(
#                 Q(title__icontains=search)
#                 | Q(customer__full_name__icontains=search)
#                 | Q(customer__email_address__icontains=search)
#                 | Q(admin__full_name__icontains=search)
#                 | Q(admin__email_address__icontains=search)
#                 | Q(application__application_number__icontains=search)
#             )

#         if status_filter:
#             queryset = queryset.filter(status=status_filter)

#         total = queryset.count()
#         start = (page - 1) * limit
#         end = start + limit

#         items = [
#             _conversation_payload(request, conversation)
#             for conversation in queryset.order_by("-last_message_at", "-created_at")[start:end]
#         ]

#         summary_queryset = ChatConversation.objects.all()

#         if not _is_admin_user(request.user):
#             summary_queryset = summary_queryset.filter(customer=request.user)

#         return build_response(
#             request,
#             success=True,
#             message="Chat conversations fetched successfully",
#             meta=_meta(
#                 page,
#                 limit,
#                 total,
#                 {
#                     "search": search,
#                     "status": status_filter,
#                 },
#             ),
#             data={
#                 "summary": {
#                     "total": summary_queryset.count(),
#                     "open": summary_queryset.filter(status=ChatConversation.STATUS_OPEN).count(),
#                     "closed": summary_queryset.filter(status=ChatConversation.STATUS_CLOSED).count(),
#                 },
#                 "conversations": items,
#             },
#             status_code=status.HTTP_200_OK,
#         )

#     def post(self, request):
#         application_id = request.data.get("application_id") or request.data.get("applicationId")
#         title = str(request.data.get("title") or "Live Chat").strip()
#         initial_message = str(request.data.get("message") or request.data.get("initial_message") or "").strip()

#         application = None

#         if application_id:
#             application = LoanApplication.objects.filter(id=application_id, user=request.user).first()

#             if not application and not _is_admin_user(request.user):
#                 return build_response(
#                     request,
#                     success=False,
#                     message="Loan application not found",
#                     data={},
#                     status_code=status.HTTP_404_NOT_FOUND,
#                 )

#         if _is_admin_user(request.user):
#             customer_id = request.data.get("customer_id") or request.data.get("customerId")

#             if not customer_id:
#                 return build_response(
#                     request,
#                     success=False,
#                     message="customer_id is required when admin creates a chat",
#                     data={},
#                     status_code=status.HTTP_400_BAD_REQUEST,
#                 )

#             customer = User.objects.filter(id=customer_id, is_active=True).first()

#             if not customer:
#                 return build_response(
#                     request,
#                     success=False,
#                     message="Customer not found",
#                     data={},
#                     status_code=status.HTTP_404_NOT_FOUND,
#                 )

#             admin = request.user

#         else:
#             customer = request.user
#             admin = _get_default_admin()

#         conversation = ChatConversation.objects.create(
#             customer=customer,
#             admin=admin,
#             application=application,
#             title=title,
#         )

#         if initial_message:
#             message = ChatMessage.objects.create(
#                 conversation=conversation,
#                 sender=request.user,
#                 message_type=ChatMessage.MESSAGE_TEXT,
#                 message=initial_message,
#             )
#             conversation.last_message = initial_message[:500]
#             conversation.last_message_at = message.created_at
#             conversation.save(update_fields=["last_message", "last_message_at", "updated_at"])
            
#             notify_chat_message(message)

#         return build_response(
#             request,
#             success=True,
#             message="Chat conversation created successfully",
#             data=_conversation_payload(request, conversation),
#             status_code=status.HTTP_201_CREATED,
#         )

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

        if _is_admin_user(request.user):
            # Main admin can see every conversation
            pass

        elif _is_support_staff(request.user):
            # Support staff sees only assigned conversations
            queryset = queryset.filter(admin=request.user)

        else:
            # Customer sees only own conversations
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
            for conversation in queryset.order_by(
                "-last_message_at",
                "-created_at",
            )[start:end]
        ]

        summary_queryset = ChatConversation.objects.all()

        if _is_admin_user(request.user):
            pass
        elif _is_support_staff(request.user):
            summary_queryset = summary_queryset.filter(
                admin=request.user
            )
        else:
            summary_queryset = summary_queryset.filter(
                customer=request.user
            )

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
                    "open": summary_queryset.filter(
                        status=ChatConversation.STATUS_OPEN
                    ).count(),
                    "closed": summary_queryset.filter(
                        status=ChatConversation.STATUS_CLOSED
                    ).count(),
                },
                "conversations": items,
            },
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        if _is_support_staff(request.user):
            return build_response(
                request,
                success=False,
                message="Support staff cannot create a customer conversation",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        application_id = (
            request.data.get("application_id")
            or request.data.get("applicationId")
        )

        case_manager_id = (
            request.data.get("case_manager_id")
            or request.data.get("caseManagerId")
            or request.data.get("manager_id")
            or request.data.get("managerId")
        )

        title = str(
            request.data.get("title")
            or "Live Chat"
        ).strip()

        initial_message = str(
            request.data.get("message")
            or request.data.get("initial_message")
            or ""
        ).strip()

        application = None

        if application_id:
            application_queryset = LoanApplication.objects.filter(
                id=application_id
            )

            if not _is_admin_user(request.user):
                application_queryset = application_queryset.filter(
                    user=request.user
                )

            application = application_queryset.first()

            if not application:
                return build_response(
                    request,
                    success=False,
                    message="Loan application not found",
                    data={},
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        if _is_admin_user(request.user):
            customer_id = (
                request.data.get("customer_id")
                or request.data.get("customerId")
            )

            if not customer_id:
                return build_response(
                    request,
                    success=False,
                    message="customer_id is required when admin creates a chat",
                    data={},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            customer = User.objects.filter(
                id=customer_id,
                role="customer",
                is_active=True,
            ).first()

            if not customer:
                return build_response(
                    request,
                    success=False,
                    message="Customer not found",
                    data={},
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            assigned_staff = request.user

            if case_manager_id:
                case_manager = SupportAgent.objects.select_related(
                    "user"
                ).filter(
                    id=case_manager_id,
                    is_active=True,
                    user__is_active=True,
                    user__role="support_staff",
                ).first()

                if not case_manager or not case_manager.user:
                    return build_response(
                        request,
                        success=False,
                        message="Active case manager not found",
                        data={},
                        status_code=status.HTTP_404_NOT_FOUND,
                    )

                assigned_staff = case_manager.user

        else:
            customer = request.user

            if case_manager_id:
                # case_manager = SupportAgent.objects.select_related(
                #     "user"
                # ).filter(
                #     id=case_manager_id,
                #     is_active=True,
                #     user__is_active=True,
                #     user__role="support_staff",
                #     available_call_types__contains=[
                #         SupportAppointment.CALL_LIVE_CHAT
                #     ],
                # ).first()

                # if not case_manager or not case_manager.user:
                #     return build_response(
                #         request,
                #         success=False,
                #         message="This case manager is not available for live chat",
                #         data={},
                #         status_code=status.HTTP_404_NOT_FOUND,
                #     )
                case_manager = SupportAgent.objects.select_related(
                    "user"
                ).filter(
                    id=case_manager_id,
                    is_active=True,
                    user__is_active=True,
                    user__role="support_staff",
                ).first()

                if (
                    not case_manager
                    or not case_manager.user
                    or SupportAppointment.CALL_LIVE_CHAT
                    not in (case_manager.available_call_types or [])
                ):
                    return build_response(
                        request,
                        success=False,
                        message="This case manager is not available for live chat",
                        data={},
                        status_code=status.HTTP_404_NOT_FOUND,
                    )

                assigned_staff = case_manager.user
            else:
                # Existing behaviour remains unchanged
                assigned_staff = _get_default_admin()

        conversation = ChatConversation.objects.create(
            customer=customer,
            admin=assigned_staff,
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
            conversation.save(
                update_fields=[
                    "last_message",
                    "last_message_at",
                    "updated_at",
                ]
            )

            notify_chat_message(message)

            maybe_generate_ai_reply(
                conversation=conversation,
                sender=request.user,
                message_text=initial_message,
                current_message_id=message.id,
                has_attachment=False,
                broadcast=True,
            )

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

        maybe_generate_ai_reply(
            conversation=conversation,
            sender=request.user,
            message_text=message_text,
            current_message_id=message.id,
            has_attachment=bool(attachment),
            broadcast=True,
        )

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

        # if _is_admin_user(request.user):
        if _is_admin_user(request.user) or _is_support_staff(request.user):
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
            # admin = User.objects.filter(id=admin_id, is_active=True).first()
            admin = User.objects.filter(
                Q(id=admin_id),
                Q(is_active=True),
                Q(role="admin") | Q(role="support_staff"),
            ).first()

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
    parser_classes = [JSONParser, MultiPartParser, FormParser]

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

        agent = SupportAgent.objects.create(
            user=linked_user,
            name=name,
            email=email,
            phone_number=request.data.get("phone_number") or request.data.get("phoneNumber"),
            title=request.data.get("title") or "Loan Advisor",
            speciality=request.data.get("speciality") or "",
            rating=request.data.get("rating") or 0,
            reviews_count=_to_int(
                request.data.get("reviews_count") or request.data.get("reviewsCount"),
                0,
            ),
            available_call_types=_normalize_call_types(
                request.data.get("available_call_types") or request.data.get("availableCallTypes")
            ),
            is_active=_truthy(request.data.get("is_active", True)),
            sort_order=_to_int(
                request.data.get("sort_order") or request.data.get("sortOrder"),
                0,
            ),
        )

        avatar = request.FILES.get("avatar")
        if avatar:
            agent.avatar = avatar
            agent.save(update_fields=["avatar", "updated_at"])

        return build_response(
            request,
            success=True,
            message="Case manager created successfully",
            data=_agent_payload(request, agent),
            status_code=status.HTTP_201_CREATED,
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

        name = str(request.data.get("name") or "").strip()
        email = str(request.data.get("email") or "").strip().lower()

        if not name:
            return build_response(
                request,
                success=False,
                message="Name is required",
                data={
                    "name": ["Name is required."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not email and not user_id:
            return build_response(
                request,
                success=False,
                message="Email is required",
                data={
                    "email": ["Email is required."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        linked_user = None
        temporary_password = None
        credentials_email_sent = False

        try:
            with transaction.atomic():
                # Keep old user_id linking support unchanged
                if user_id:
                    linked_user = User.objects.filter(
                        id=user_id,
                        is_active=True,
                    ).first()

                    if not linked_user:
                        return build_response(
                            request,
                            success=False,
                            message="User not found",
                            data={},
                            status_code=status.HTTP_404_NOT_FOUND,
                        )

                    if SupportAgent.objects.filter(user=linked_user).exists():
                        return build_response(
                            request,
                            success=False,
                            message="This user is already registered as a case manager",
                            data={
                                "user_id": [
                                    "This user already has a case manager profile."
                                ]
                            },
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )

                    email = email or _user_email(linked_user)
                    name = name or _user_name(linked_user)

                    linked_user.role = "support_staff"
                    linked_user.is_email_verified = True
                    linked_user.save(
                        update_fields=[
                            "role",
                            "is_email_verified",
                            "updated_at",
                        ]
                    )

                else:
                    if User.objects.filter(email_address__iexact=email).exists():
                        return build_response(
                            request,
                            success=False,
                            message="A user with this email already exists",
                            data={
                                "email": [
                                    "A user account with this email already exists."
                                ]
                            },
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )

                    if SupportAgent.objects.filter(email__iexact=email).exists():
                        return build_response(
                            request,
                            success=False,
                            message="A case manager with this email already exists",
                            data={
                                "email": [
                                    "A case manager with this email already exists."
                                ]
                            },
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )

                    temporary_password = _generate_temporary_password()

                    account_is_active = _truthy(
                        request.data.get("is_active", True)
                    )

                    linked_user = User.objects.create_user(
                        email_address=email,
                        password=temporary_password,
                        full_name=name,
                        phone_number=(
                            request.data.get("phone_number")
                            or request.data.get("phoneNumber")
                        ),
                        role="support_staff",
                        is_active=account_is_active,
                        is_staff=False,
                        is_email_verified=True,
                    )

                agent = SupportAgent.objects.create(
                    user=linked_user,
                    name=name,
                    email=email,
                    phone_number=(
                        request.data.get("phone_number")
                        or request.data.get("phoneNumber")
                    ),
                    title=request.data.get("title") or "Loan Advisor",
                    speciality=request.data.get("speciality") or "",
                    rating=request.data.get("rating") or 0,
                    reviews_count=_to_int(
                        request.data.get("reviews_count")
                        or request.data.get("reviewsCount"),
                        0,
                    ),
                    available_call_types=_normalize_call_types(
                        request.data.get("available_call_types")
                        or request.data.get("availableCallTypes")
                    ),
                    is_active=_truthy(
                        request.data.get("is_active", True)
                    ),
                    sort_order=_to_int(
                        request.data.get("sort_order")
                        or request.data.get("sortOrder"),
                        0,
                    ),
                )

                avatar = request.FILES.get("avatar")

                if avatar:
                    agent.avatar = avatar
                    agent.save(
                        update_fields=[
                            "avatar",
                            "updated_at",
                        ]
                    )

                # Email is sent only for a newly created account
                if temporary_password:
                    login_url = getattr(
                        settings,
                        "FRONTEND_ADMIN_LOGIN_URL",
                        getattr(
                            settings,
                            "SITE_BASE_URL",
                            "http://127.0.0.1:8011",
                        ),
                    )

                    send_mail(
                        subject="Your Metamec Gold Support Account",
                        message=(
                            f"Hello {name},\n\n"
                            f"Your Metamec Gold support account has been created.\n\n"
                            f"Login email: {email}\n"
                            f"Temporary password: {temporary_password}\n"
                            f"Login URL: {login_url}\n\n"
                            f"After logging in, please update your profile "
                            f"from the Settings/Profile section.\n\n"
                            f"Regards,\n"
                            f"Metamec Gold Team"
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[email],
                        fail_silently=False,
                    )

                    credentials_email_sent = True

        except Exception:
            return build_response(
                request,
                success=False,
                message="Case manager account could not be created or credentials email could not be sent",
                data={
                    "email": [
                        "Please check the email configuration and try again."
                    ]
                },
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response_data = _agent_payload(request, agent)
        response_data["userId"] = linked_user.id
        response_data["role"] = linked_user.role
        response_data["credentialsEmailSent"] = credentials_email_sent

        return build_response(
            request,
            success=True,
            message="Case manager created and login credentials sent successfully",
            data=response_data,
            status_code=status.HTTP_201_CREATED,
        )



class AdminSupportCaseManagerDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self, manager_id):
        return SupportAgent.objects.filter(id=manager_id).first()

    def get(self, request, manager_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        agent = self.get_object(manager_id)

        if not agent:
            return build_response(
                request,
                success=False,
                message="Case manager not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return build_response(
            request,
            success=True,
            message="Case manager fetched successfully",
            data=_agent_payload(request, agent),
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, manager_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        agent = self.get_object(manager_id)

        if not agent:
            return build_response(
                request,
                success=False,
                message="Case manager not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if "name" in request.data:
            agent.name = request.data.get("name") or agent.name

        if "email" in request.data:
            agent.email = request.data.get("email") or None

        if "phone_number" in request.data or "phoneNumber" in request.data:
            agent.phone_number = request.data.get("phone_number") or request.data.get("phoneNumber") or None

        if "title" in request.data:
            agent.title = request.data.get("title") or ""

        if "speciality" in request.data:
            agent.speciality = request.data.get("speciality") or ""

        if "rating" in request.data:
            agent.rating = request.data.get("rating") or 0

        if "reviews_count" in request.data or "reviewsCount" in request.data:
            agent.reviews_count = _to_int(
                request.data.get("reviews_count") or request.data.get("reviewsCount"),
                0,
            )

        if "available_call_types" in request.data or "availableCallTypes" in request.data:
            agent.available_call_types = _normalize_call_types(
                request.data.get("available_call_types") or request.data.get("availableCallTypes")
            )

        if "is_active" in request.data or "isActive" in request.data:
            agent.is_active = _truthy(request.data.get("is_active", request.data.get("isActive")))

        if "sort_order" in request.data or "sortOrder" in request.data:
            agent.sort_order = _to_int(
                request.data.get("sort_order") or request.data.get("sortOrder"),
                0,
            )

        avatar = request.FILES.get("avatar")
        if avatar:
            agent.avatar = avatar

        if _truthy(request.data.get("remove_avatar", False)) or _truthy(request.data.get("removeAvatar", False)):
            if agent.avatar:
                agent.avatar.delete(save=False)
            agent.avatar = None

        agent.save()

        return build_response(
            request,
            success=True,
            message="Case manager updated successfully",
            data=_agent_payload(request, agent),
            status_code=status.HTTP_200_OK,
        )

    # def delete(self, request, manager_id):
    #     if not _is_admin_user(request.user):
    #         return build_response(
    #             request,
    #             success=False,
    #             message="Admin permission required",
    #             data={},
    #             status_code=status.HTTP_403_FORBIDDEN,
    #         )

    #     agent = self.get_object(manager_id)

    #     if not agent:
    #         return build_response(
    #             request,
    #             success=False,
    #             message="Case manager not found",
    #             data={},
    #             status_code=status.HTTP_404_NOT_FOUND,
    #         )

    #     agent.is_active = False
    #     agent.save(update_fields=["is_active", "updated_at"])

    #     return build_response(
    #         request,
    #         success=True,
    #         message="Case manager disabled successfully",
    #         data=_agent_payload(request, agent),
    #         status_code=status.HTTP_200_OK,
    #     )

    def delete(self, request, manager_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        agent = self.get_object(manager_id)

        if not agent:
            return build_response(
                request,
                success=False,
                message="Case manager not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        agent.is_active = False
        agent.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

        if agent.user:
            agent.user.is_active = False
            agent.user.save(
                update_fields=[
                    "is_active",
                    "updated_at",
                ]
            )

        return build_response(
            request,
            success=True,
            message="Case manager disabled successfully",
            data=_agent_payload(request, agent),
            status_code=status.HTTP_200_OK,
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


class AdminSupportAvailabilityDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, availability_id):
        return AgentAvailability.objects.select_related("agent").filter(id=availability_id).first()

    def patch(self, request, availability_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        availability = self.get_object(availability_id)

        if not availability:
            return build_response(
                request,
                success=False,
                message="Availability rule not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if "weekday" in request.data:
            try:
                weekday = int(request.data.get("weekday"))
                if weekday < 0 or weekday > 6:
                    raise ValueError()
                availability.weekday = weekday
            except Exception:
                return build_response(
                    request,
                    success=False,
                    message="Invalid weekday. Use 0-6.",
                    data={},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        if "start_time" in request.data or "startTime" in request.data:
            start_time = _parse_time(request.data.get("start_time") or request.data.get("startTime"))
            if not start_time:
                return build_response(
                    request,
                    success=False,
                    message="Invalid start_time. Format: HH:MM",
                    data={},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            availability.start_time = start_time

        if "end_time" in request.data or "endTime" in request.data:
            end_time = _parse_time(request.data.get("end_time") or request.data.get("endTime"))
            if not end_time:
                return build_response(
                    request,
                    success=False,
                    message="Invalid end_time. Format: HH:MM",
                    data={},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            availability.end_time = end_time

        if availability.end_time <= availability.start_time:
            return build_response(
                request,
                success=False,
                message="end_time must be greater than start_time.",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if "slot_duration_minutes" in request.data or "slotDurationMinutes" in request.data:
            availability.slot_duration_minutes = _to_int(
                request.data.get("slot_duration_minutes") or request.data.get("slotDurationMinutes"),
                30,
            )

        if "break_start_time" in request.data or "breakStartTime" in request.data:
            availability.break_start_time = _parse_time(
                request.data.get("break_start_time") or request.data.get("breakStartTime")
            )

        if "break_end_time" in request.data or "breakEndTime" in request.data:
            availability.break_end_time = _parse_time(
                request.data.get("break_end_time") or request.data.get("breakEndTime")
            )

        if "is_active" in request.data or "isActive" in request.data:
            availability.is_active = _truthy(request.data.get("is_active", request.data.get("isActive")))

        availability.save()

        return build_response(
            request,
            success=True,
            message="Availability rule updated successfully",
            data={
                "manager": _agent_payload(request, availability.agent),
                "availability": _availability_payload(availability),
            },
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, availability_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        availability = self.get_object(availability_id)

        if not availability:
            return build_response(
                request,
                success=False,
                message="Availability rule not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        availability.delete()

        return build_response(
            request,
            success=True,
            message="Availability rule deleted successfully",
            data={},
            status_code=status.HTTP_200_OK,
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
        notify_appointment_status_changed(
            appointment,
            new_status,
            request.data.get("reason") or "",
        )

        return build_response(
            request,
            success=True,
            message="Appointment status updated successfully",
            data=_appointment_payload(request, appointment),
            status_code=status.HTTP_200_OK,
        )
    


class SupportBookCallView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_agent(self, manager_id=None, call_type=None):
        queryset = SupportAgent.objects.filter(is_active=True).order_by("sort_order", "name")

        if manager_id:
            return queryset.filter(id=manager_id).first()

        agents = list(queryset)

        if call_type:
            for agent in agents:
                if call_type in (agent.available_call_types or []):
                    return agent

        return agents[0] if agents else None

    def get(self, request):
        manager_id = request.query_params.get("manager_id") or request.query_params.get("managerId")
        call_type = (
            request.query_params.get("call_type")
            or request.query_params.get("callType")
            or SupportAppointment.CALL_PHONE
        )
        date_value = request.query_params.get("date")

        if call_type not in [SupportAppointment.CALL_PHONE, SupportAppointment.CALL_LIVE_CHAT]:
            return build_response(
                request,
                success=False,
                message="Invalid call_type. Use phone_call or live_chat.",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        selected_date = _parse_date(date_value) if date_value else timezone.localdate()

        if not selected_date:
            return build_response(
                request,
                success=False,
                message="Valid date is required. Format: YYYY-MM-DD",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        agent = self._get_agent(manager_id=manager_id, call_type=call_type)

        if not agent:
            return build_response(
                request,
                success=False,
                message="No active case manager configured. Admin must create a case manager first.",
                data={
                    "adminApis": {
                        "createCaseManager": "/api/admin/support/case-managers/",
                        "createAvailability": "/api/admin/support/case-managers/{manager_id}/availability/"
                    }
                },
                status_code=status.HTTP_404_NOT_FOUND,
            )

        has_availability = AgentAvailability.objects.filter(
            agent=agent,
            weekday=selected_date.weekday(),
            is_active=True,
        ).exists()

        slots = _get_generated_slots(agent, selected_date, call_type) if has_availability else []

        return build_response(
            request,
            success=True,
            message="Book a call data fetched successfully",
            data={
                "caseManager": _agent_payload(request, agent),
                "callTypes": [
                    {
                        "value": SupportAppointment.CALL_PHONE,
                        "label": "Phone Call",
                        "description": "Direct call to your number",
                        "isAvailable": SupportAppointment.CALL_PHONE in (agent.available_call_types or []),
                    },
                    {
                        "value": SupportAppointment.CALL_LIVE_CHAT,
                        "label": "Live Chat",
                        "description": "Text chat in-app",
                        "isAvailable": SupportAppointment.CALL_LIVE_CHAT in (agent.available_call_types or []),
                    },
                ],
                "selected": {
                    "managerId": agent.id,
                    "date": selected_date.isoformat(),
                    "dateLabel": _format_date(selected_date),
                    "callType": call_type,
                    "callTypeLabel": dict(SupportAppointment.CALL_TYPE_CHOICES).get(call_type),
                },
                "slots": slots,
                "availabilityConfigured": has_availability,
                "note": {
                    "enabled": True,
                    "placeholder": "Tell your advisor what you'd like to discuss..."
                },
                "reminder": {
                    "enabled": True,
                    "minutesBefore": 30,
                    "message": "A reminder will be sent to your registered email 30 minutes before the appointment.",
                },
                "actions": {
                    "confirmApi": "/api/support/book-call/",
                },
            },
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        manager_id = request.data.get("manager_id") or request.data.get("managerId")
        application_id = request.data.get("application_id") or request.data.get("applicationId")
        call_type = (
            request.data.get("call_type")
            or request.data.get("callType")
            or SupportAppointment.CALL_PHONE
        )
        date_value = request.data.get("date")
        time_value = request.data.get("time")
        note = request.data.get("note") or ""

        if call_type not in [SupportAppointment.CALL_PHONE, SupportAppointment.CALL_LIVE_CHAT]:
            return build_response(
                request,
                success=False,
                message="Invalid call_type. Use phone_call or live_chat.",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        agent = self._get_agent(manager_id=manager_id, call_type=call_type)

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

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if call_type not in (agent.available_call_types or []):
            return build_response(
                request,
                success=False,
                message="This case manager does not support the selected call type.",
                data={
                    "availableCallTypes": agent.available_call_types or []
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
                message="Selected time is outside case manager availability.",
                data={"slots": slots},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not selected_slot["isAvailable"]:
            return build_response(
                request,
                success=False,
                message="Selected slot is not available.",
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
            reminder_minutes_before=30,
        )
        notify_appointment_booked(appointment)

        return build_response(
            request,
            success=True,
            message="Appointment booked successfully",
            data={
                "screenTitle": "Appointment Booked!",
                "screenSubtitle": f"Your {appointment.get_call_type_display()} with {appointment.agent.name} is confirmed.",
                "appointment": _appointment_payload(request, appointment),
                "actions": {
                    "backToDashboard": True,
                },
            },
            status_code=status.HTTP_201_CREATED,
        )
    

class StaffProfileView(APIView):

    permission_classes = [IsAuthenticated]
    parser_classes = [
        JSONParser,
        MultiPartParser,
        FormParser,
    ]

    def _get_agent(self, user):
        return SupportAgent.objects.filter(
            user=user,
            is_active=True,
        ).first()

    def _profile_payload(
        self,
        request,
        user,
        agent,
    ):
        return {
            "id": user.id,
            "fullName": user.full_name,
            "emailAddress": user.email_address,
            "phoneNumber": user.phone_number,
            "department": user.department,
            "location": user.location,
            "role": user.role,
            "roleLabel": "Support Staff",
            "isActive": user.is_active,
            "isEmailVerified": user.is_email_verified,
            "profileImageUrl": _file_url(
                request,
                user.profile_image,
            ),
            "agent": _agent_payload(
                request,
                agent,
            ),
        }

    def get(self, request):
        if not _is_support_staff(request.user):
            return build_response(
                request,
                success=False,
                message="Support staff permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        agent = self._get_agent(
            request.user,
        )

        if not agent:
            return build_response(
                request,
                success=False,
                message="Active support staff profile not found",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        return build_response(
            request,
            success=True,
            message="Staff profile fetched successfully",
            data=self._profile_payload(
                request,
                request.user,
                agent,
            ),
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request):
        if not _is_support_staff(request.user):
            return build_response(
                request,
                success=False,
                message="Support staff permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        user = request.user

        agent = self._get_agent(user)

        if not agent:
            return build_response(
                request,
                success=False,
                message="Active support staff profile not found",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        full_name = request.data.get(
            "full_name"
        )

        if full_name is None:
            full_name = request.data.get(
                "fullName"
            )

        phone_number = request.data.get(
            "phone_number"
        )

        if phone_number is None:
            phone_number = request.data.get(
                "phoneNumber"
            )

        department = request.data.get(
            "department"
        )

        location = request.data.get(
            "location"
        )

        profile_image = (
            request.FILES.get("profile_image")
            or request.FILES.get("profileImage")
            or request.FILES.get("image")
            or request.FILES.get("avatar")
        )

        remove_profile_image = _truthy(
            request.data.get(
                "remove_profile_image"
            )
            or request.data.get(
                "removeProfileImage"
            )
        )

        errors = {}

        if (
            full_name is not None
            and not str(full_name).strip()
        ):
            errors["full_name"] = [
                "Full name cannot be empty."
            ]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user_update_fields = []
        agent_update_fields = []

        if full_name is not None:
            clean_name = str(
                full_name
            ).strip()

            user.full_name = clean_name
            agent.name = clean_name

            user_update_fields.append(
                "full_name"
            )

            agent_update_fields.append(
                "name"
            )

        if phone_number is not None:
            clean_phone = (
                str(phone_number).strip()
                or None
            )

            user.phone_number = clean_phone
            agent.phone_number = clean_phone

            user_update_fields.append(
                "phone_number"
            )

            agent_update_fields.append(
                "phone_number"
            )

        if department is not None:
            user.department = (
                str(department).strip()
                or None
            )

            user_update_fields.append(
                "department"
            )

        if location is not None:
            user.location = (
                str(location).strip()
                or None
            )

            user_update_fields.append(
                "location"
            )

        if remove_profile_image:
            if user.profile_image:
                user.profile_image.delete(
                    save=False
                )

            user.profile_image = None

            user_update_fields.append(
                "profile_image"
            )

        if profile_image:
            if user.profile_image:
                user.profile_image.delete(
                    save=False
                )

            user.profile_image = profile_image

            user_update_fields.append(
                "profile_image"
            )

        if user_update_fields:
            user_update_fields.append(
                "updated_at"
            )

            user.save(
                update_fields=list(
                    dict.fromkeys(
                        user_update_fields
                    )
                )
            )

        if agent_update_fields:
            agent_update_fields.append(
                "updated_at"
            )

            agent.save(
                update_fields=list(
                    dict.fromkeys(
                        agent_update_fields
                    )
                )
            )

        return build_response(
            request,
            success=True,
            message="Staff profile updated successfully",
            data=self._profile_payload(
                request,
                user,
                agent,
            ),
            status_code=status.HTTP_200_OK,
        )



class ChatTemplateFolderListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        if not _can_access_chat_templates(request.user):
            return build_response(
                request,
                success=False,
                message="You do not have permission to access template folders",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        folders = (
            ChatTemplateFolder.objects
            .select_related("parent", "created_by")
            .all()
            .order_by("name")
        )

        parent_id = request.query_params.get("parent")
        search = str(
            request.query_params.get("search") or ""
        ).strip()

        if parent_id:
            folders = folders.filter(
                parent_id=parent_id
            )

        if search:
            folders = folders.filter(
                name__icontains=search
            )

        return build_response(
            request,
            success=True,
            message="Template folders fetched successfully",
            data=[
                _template_folder_payload(folder)
                for folder in folders
            ],
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

        name = str(request.data.get("name") or "").strip()
        parent_id = request.data.get("parent")

        if not name:
            return build_response(
                request,
                success=False,
                message="Folder name is required",
                data={
                    "name": ["Folder name is required."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        parent = None

        if parent_id:
            parent = ChatTemplateFolder.objects.filter(
                id=parent_id
            ).first()

            if not parent:
                return build_response(
                    request,
                    success=False,
                    message="Parent folder not found",
                    data={
                        "parent": ["Invalid parent folder."]
                    },
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        folder = ChatTemplateFolder.objects.create(
            name=name,
            parent=parent,
            created_by=request.user,
        )

        return build_response(
            request,
            success=True,
            message="Template folder created successfully",
            data=_template_folder_payload(folder),
            status_code=status.HTTP_201_CREATED,
        )


class ChatTemplateFolderDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_object(self, folder_id):
        return (
            ChatTemplateFolder.objects
            .select_related("parent", "created_by")
            .filter(id=folder_id)
            .first()
        )

    def get(self, request, folder_id):
        if not _can_access_chat_templates(request.user):
            return build_response(
                request,
                success=False,
                message="You do not have permission to access template folders",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        folder = self.get_object(folder_id)

        if not folder:
            return build_response(
                request,
                success=False,
                message="Template folder not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return build_response(
            request,
            success=True,
            message="Template folder fetched successfully",
            data=_template_folder_payload(folder),
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, folder_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        folder = self.get_object(folder_id)

        if not folder:
            return build_response(
                request,
                success=False,
                message="Template folder not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if "name" in request.data:
            name = str(request.data.get("name") or "").strip()

            if not name:
                return build_response(
                    request,
                    success=False,
                    message="Folder name cannot be empty",
                    data={
                        "name": ["Folder name cannot be empty."]
                    },
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            folder.name = name

        if "parent" in request.data:
            parent_id = request.data.get("parent")

            if parent_id in [None, "", "null"]:
                folder.parent = None

            else:
                if str(parent_id) == str(folder.id):
                    return build_response(
                        request,
                        success=False,
                        message="A folder cannot be moved inside itself",
                        data={
                            "parent": [
                                "A folder cannot be its own parent."
                            ]
                        },
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )

                parent = ChatTemplateFolder.objects.filter(
                    id=parent_id
                ).first()

                if not parent:
                    return build_response(
                        request,
                        success=False,
                        message="Parent folder not found",
                        data={
                            "parent": ["Invalid parent folder."]
                        },
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )

                # Prevent moving folder into one of its own children
                current = parent

                while current:
                    if current.id == folder.id:
                        return build_response(
                            request,
                            success=False,
                            message="Cannot move folder inside its own subfolder",
                            data={
                                "parent": [
                                    "Invalid folder hierarchy."
                                ]
                            },
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )

                    current = current.parent

                folder.parent = parent

        folder.save()

        return build_response(
            request,
            success=True,
            message="Template folder updated successfully",
            data=_template_folder_payload(folder),
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, folder_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        folder = self.get_object(folder_id)

        if not folder:
            return build_response(
                request,
                success=False,
                message="Template folder not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if folder.subfolders.exists():
            return build_response(
                request,
                success=False,
                message="Folder contains subfolders. Move or delete them first.",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if folder.templates.exists():
            return build_response(
                request,
                success=False,
                message="Folder contains templates. Move or delete them first.",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        folder.delete()

        return build_response(
            request,
            success=True,
            message="Template folder deleted successfully",
            data={},
            status_code=status.HTTP_200_OK,
        )


class ChatTemplateListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        if not _can_access_chat_templates(request.user):
            return build_response(
                request,
                success=False,
                message="You do not have permission to access chat templates",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        templates = (
            ChatTemplate.objects
            .select_related("folder", "created_by")
            .all()
            .order_by("name")
        )

        folder_id = request.query_params.get("folder")
        category = request.query_params.get("category")
        template_status = request.query_params.get("status")
        search = str(
            request.query_params.get("search") or ""
        ).strip()

        if folder_id:
            templates = templates.filter(folder_id=folder_id)

        if category:
            templates = templates.filter(
                category=str(category).lower()
            )

        if template_status:
            templates = templates.filter(
                status=template_status
            )

        if search:
            templates = templates.filter(
                Q(name__icontains=search)
                | Q(message__icontains=search)
            )

        return build_response(
            request,
            success=True,
            message="Chat templates fetched successfully",
            data=[
                _template_payload(request, template)
                for template in templates
            ],
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

        name = str(request.data.get("name") or "").strip()
        category = str(
            request.data.get("category") or ""
        ).strip().lower()
        language = str(
            request.data.get("language") or ""
        ).strip()
        message = str(
            request.data.get("message") or ""
        ).strip()

        folder_id = request.data.get("folder")

        header_type = str(
            request.data.get("header_type") or ""
        ).strip().lower() or None

        header_text = str(
            request.data.get("header_text") or ""
        ).strip() or None

        header_file = request.FILES.get("header_file")

        footer_text = str(
            request.data.get("footer_text") or ""
        ).strip() or None

        action = str(
            request.data.get("action") or "draft"
        ).strip().lower()

        errors = {}

        if not name:
            errors["name"] = ["Template name is required."]

        allowed_categories = [
            ChatTemplate.CATEGORY_MARKETING,
            ChatTemplate.CATEGORY_UTILITY,
        ]

        if category not in allowed_categories:
            errors["category"] = [
                "Use marketing or utility."
            ]

        if not language:
            errors["language"] = [
                "Language is required."
            ]

        if not message:
            errors["message"] = [
                "Message is required."
            ]

        elif len(message) > 1024:
            errors["message"] = [
                "Message cannot exceed 1024 characters."
            ]

        folder = None

        if folder_id:
            folder = ChatTemplateFolder.objects.filter(
                id=folder_id
            ).first()

            if not folder:
                errors["folder"] = [
                    "Invalid folder."
                ]

        allowed_header_types = [
            ChatTemplate.HEADER_HEADLINE,
            ChatTemplate.HEADER_IMAGE,
            ChatTemplate.HEADER_VIDEO,
            ChatTemplate.HEADER_PDF,
        ]

        if header_type and header_type not in allowed_header_types:
            errors["header_type"] = [
                "Use headline, image, video or pdf."
            ]

        if (
            header_type == ChatTemplate.HEADER_HEADLINE
            and not header_text
        ):
            errors["header_text"] = [
                "Headline text is required."
            ]

        if (
            header_type
            in [
                ChatTemplate.HEADER_IMAGE,
                ChatTemplate.HEADER_VIDEO,
                ChatTemplate.HEADER_PDF,
            ]
            and not header_file
        ):
            errors["header_file"] = [
                "Attachment file is required."
            ]

        if footer_text and len(footer_text) > 60:
            errors["footer_text"] = [
                "Footer cannot exceed 60 characters."
            ]

        buttons = _parse_template_buttons(
            request.data.get("buttons", [])
        )

        button_error = _validate_template_buttons(buttons)

        if button_error:
            errors["buttons"] = [button_error]

        if action not in [
            "draft",
            "submit_for_review",
        ]:
            errors["action"] = [
                "Use draft or submit_for_review."
            ]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        template_status = (
            ChatTemplate.STATUS_PENDING_REVIEW
            if action == "submit_for_review"
            else ChatTemplate.STATUS_DRAFT
        )

        template = ChatTemplate.objects.create(
            name=name,
            category=category,
            language=language,
            message=message,
            header_type=header_type,
            header_text=header_text,
            header_file=header_file,
            footer_text=footer_text,
            buttons=buttons,
            folder=folder,
            status=template_status,
            created_by=request.user,
        )

        return build_response(
            request,
            success=True,
            message="Chat template created successfully",
            data=_template_payload(request, template),
            status_code=status.HTTP_201_CREATED,
        )


class ChatTemplateDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_object(self, template_id):
        return (
            ChatTemplate.objects
            .select_related("folder", "created_by")
            .filter(id=template_id)
            .first()
        )

    def get(self, request, template_id):
        if not _can_access_chat_templates(request.user):
            return build_response(
                request,
                success=False,
                message="You do not have permission to access chat templates",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        template = self.get_object(template_id)

        if not template:
            return build_response(
                request,
                success=False,
                message="Chat template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return build_response(
            request,
            success=True,
            message="Chat template fetched successfully",
            data=_template_payload(request, template),
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, template_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        template = self.get_object(template_id)

        if not template:
            return build_response(
                request,
                success=False,
                message="Chat template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        errors = {}

        if "name" in request.data:
            name = str(
                request.data.get("name") or ""
            ).strip()

            if not name:
                errors["name"] = [
                    "Template name cannot be empty."
                ]
            else:
                template.name = name

        if "category" in request.data:
            category = str(
                request.data.get("category") or ""
            ).strip().lower()

            if category not in [
                ChatTemplate.CATEGORY_MARKETING,
                ChatTemplate.CATEGORY_UTILITY,
            ]:
                errors["category"] = [
                    "Use marketing or utility."
                ]
            else:
                template.category = category

        if "language" in request.data:
            language = str(
                request.data.get("language") or ""
            ).strip()

            if not language:
                errors["language"] = [
                    "Language cannot be empty."
                ]
            else:
                template.language = language

        if "message" in request.data:
            message = str(
                request.data.get("message") or ""
            ).strip()

            if not message:
                errors["message"] = [
                    "Message cannot be empty."
                ]

            elif len(message) > 1024:
                errors["message"] = [
                    "Message cannot exceed 1024 characters."
                ]

            else:
                template.message = message

        if "folder" in request.data:
            folder_id = request.data.get("folder")

            if folder_id in [None, "", "null"]:
                template.folder = None

            else:
                folder = ChatTemplateFolder.objects.filter(
                    id=folder_id
                ).first()

                if not folder:
                    errors["folder"] = [
                        "Invalid folder."
                    ]
                else:
                    template.folder = folder

        if "header_type" in request.data:
            header_type = str(
                request.data.get("header_type") or ""
            ).strip().lower()

            if not header_type:
                template.header_type = None
                template.header_text = None

                if template.header_file:
                    template.header_file.delete(save=False)

                template.header_file = None

            elif header_type not in [
                ChatTemplate.HEADER_HEADLINE,
                ChatTemplate.HEADER_IMAGE,
                ChatTemplate.HEADER_VIDEO,
                ChatTemplate.HEADER_PDF,
            ]:
                errors["header_type"] = [
                    "Use headline, image, video or pdf."
                ]

            else:
                template.header_type = header_type

        if "header_text" in request.data:
            header_text = str(
                request.data.get("header_text") or ""
            ).strip()

            template.header_text = header_text or None

        new_header_file = request.FILES.get("header_file")

        if new_header_file:
            if template.header_file:
                template.header_file.delete(save=False)

            template.header_file = new_header_file

        remove_header_file = _truthy(
            request.data.get("remove_header_file", False)
        )

        if remove_header_file:
            if template.header_file:
                template.header_file.delete(save=False)

            template.header_file = None

        if "footer_text" in request.data:
            footer_text = str(
                request.data.get("footer_text") or ""
            ).strip()

            if len(footer_text) > 60:
                errors["footer_text"] = [
                    "Footer cannot exceed 60 characters."
                ]
            else:
                template.footer_text = footer_text or None

        if "buttons" in request.data:
            buttons = _parse_template_buttons(
                request.data.get("buttons")
            )

            button_error = _validate_template_buttons(
                buttons
            )

            if button_error:
                errors["buttons"] = [button_error]
            else:
                template.buttons = buttons

        if "action" in request.data:
            action = str(
                request.data.get("action") or ""
            ).strip().lower()

            if action == "draft":
                template.status = (
                    ChatTemplate.STATUS_DRAFT
                )

            elif action == "submit_for_review":
                template.status = (
                    ChatTemplate.STATUS_PENDING_REVIEW
                )

            else:
                errors["action"] = [
                    "Use draft or submit_for_review."
                ]

        # Final header validation after all patch values applied
        if (
            template.header_type
            == ChatTemplate.HEADER_HEADLINE
            and not template.header_text
        ):
            errors["header_text"] = [
                "Headline text is required."
            ]

        if (
            template.header_type
            in [
                ChatTemplate.HEADER_IMAGE,
                ChatTemplate.HEADER_VIDEO,
                ChatTemplate.HEADER_PDF,
            ]
            and not template.header_file
            and not new_header_file
        ):
            errors["header_file"] = [
                "Attachment file is required."
            ]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        template.save()

        return build_response(
            request,
            success=True,
            message="Chat template updated successfully",
            data=_template_payload(request, template),
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, template_id):
        if not _is_admin_user(request.user):
            return build_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        template = self.get_object(template_id)

        if not template:
            return build_response(
                request,
                success=False,
                message="Chat template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if template.header_file:
            template.header_file.delete(save=False)

        template.delete()

        return build_response(
            request,
            success=True,
            message="Chat template deleted successfully",
            data={},
            status_code=status.HTTP_200_OK,
        )