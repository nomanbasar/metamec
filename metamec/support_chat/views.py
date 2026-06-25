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

from .models import ChatConversation, ChatMessage


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