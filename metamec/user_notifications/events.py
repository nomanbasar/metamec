from .models import UserNotification
from .utils import create_notification, notify_admins


def _str_id(value):
    return str(value) if value else None


def _user_name(user):
    if not user:
        return "Customer"

    return (
        getattr(user, "full_name", None)
        or getattr(user, "name", None)
        or getattr(user, "email_address", None)
        or getattr(user, "email", None)
        or str(user)
    )


def _app_number(application):
    return getattr(application, "application_number", None) or _str_id(getattr(application, "id", None))


def _loan_type_name(application):
    try:
        return application.loan_type.name if application.loan_type else None
    except Exception:
        return None


def _application_metadata(application):
    return {
        "applicationId": _str_id(getattr(application, "id", None)),
        "applicationNumber": _app_number(application),
        "loanType": _loan_type_name(application),
        "status": getattr(application, "status", None),
        "customerId": _str_id(getattr(application, "user_id", None)),
    }


def notify_application_submitted(application):
    try:
        app_no = _app_number(application)

        create_notification(
            user=application.user,
            title="Application Submitted!",
            message=f"Your loan application {app_no} has been submitted successfully.",
            notification_type=UserNotification.TYPE_APPLICATION_RECEIVED,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="loan_detail",
            action_api=f"/api/customer/my-loans/{application.id}/",
            object_id=application.id,
            object_type="loan_application",
            metadata=_application_metadata(application),
        )

        notify_admins(
            title="New Loan Application",
            message=f"{_user_name(application.user)} submitted loan application {app_no}.",
            notification_type=UserNotification.TYPE_APPLICATION_RECEIVED,
            priority=UserNotification.PRIORITY_HIGH,
            action_screen="admin_application_detail",
            action_api=f"/api/admin/applications/{application.id}/",
            object_id=application.id,
            object_type="loan_application",
            metadata=_application_metadata(application),
        )
    except Exception:
        pass


def notify_application_status_changed(application, new_status, note=None):
    try:
        app_no = _app_number(application)

        mapping = {
            "submitted": {
                "title": "Application Submitted",
                "message": f"Your application {app_no} has been submitted.",
                "type": UserNotification.TYPE_APPLICATION_RECEIVED,
                "priority": UserNotification.PRIORITY_NORMAL,
            },
            "under_review": {
                "title": "Application Under Review",
                "message": f"Your application {app_no} is now under review.",
                "type": UserNotification.TYPE_GENERAL,
                "priority": UserNotification.PRIORITY_NORMAL,
            },
            "pending_documents": {
                "title": "Additional Documents Required",
                "message": f"Additional documents are required for application {app_no}.",
                "type": UserNotification.TYPE_DOCUMENT_REQUIRED,
                "priority": UserNotification.PRIORITY_HIGH,
            },
            "kyc_required": {
                "title": "KYC Required",
                "message": f"Please complete KYC verification for application {app_no}.",
                "type": UserNotification.TYPE_KYC_SUBMITTED,
                "priority": UserNotification.PRIORITY_HIGH,
            },
            "approved": {
                "title": "Application Approved!",
                "message": f"Congratulations! Your application {app_no} has been approved.",
                "type": UserNotification.TYPE_APPLICATION_APPROVED,
                "priority": UserNotification.PRIORITY_HIGH,
            },
            "rejected": {
                "title": "Application Rejected",
                "message": f"Your application {app_no} has been rejected.",
                "type": UserNotification.TYPE_APPLICATION_REJECTED,
                "priority": UserNotification.PRIORITY_HIGH,
            },
            "completed": {
                "title": "Application Completed",
                "message": f"Your application {app_no} has been completed.",
                "type": UserNotification.TYPE_GENERAL,
                "priority": UserNotification.PRIORITY_NORMAL,
            },
        }

        config = mapping.get(new_status)

        if not config:
            return

        metadata = _application_metadata(application)
        metadata["adminNote"] = note or ""

        create_notification(
            user=application.user,
            title=config["title"],
            message=config["message"],
            notification_type=config["type"],
            priority=config["priority"],
            action_screen="loan_detail",
            action_api=f"/api/customer/my-loans/{application.id}/",
            object_id=application.id,
            object_type="loan_application",
            metadata=metadata,
        )
    except Exception:
        pass


def notify_document_uploaded(document, replaced=False):
    try:
        application = document.application
        app_no = _app_number(application)
        document_label = document.get_document_type_display() if hasattr(document, "get_document_type_display") else document.document_type

        create_notification(
            user=application.user,
            title="Document Uploaded",
            message=f"{document_label} has been {'replaced' if replaced else 'uploaded'} for application {app_no}.",
            notification_type=UserNotification.TYPE_GENERAL,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="documents",
            action_api=f"/api/applications/{application.id}/documents/",
            object_id=document.id,
            object_type="loan_document",
            metadata={
                **_application_metadata(application),
                "documentId": _str_id(document.id),
                "documentType": document.document_type,
                "documentStatus": document.status,
                "replaced": bool(replaced),
            },
        )

        notify_admins(
            title="Document Uploaded",
            message=f"{_user_name(application.user)} uploaded {document_label} for application {app_no}.",
            notification_type=UserNotification.TYPE_GENERAL,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="admin_application_documents",
            action_api=f"/api/admin/applications/{application.id}/documents/",
            object_id=document.id,
            object_type="loan_document",
            metadata={
                **_application_metadata(application),
                "documentId": _str_id(document.id),
                "documentType": document.document_type,
                "documentStatus": document.status,
            },
        )
    except Exception:
        pass


def notify_documents_completed(application):
    try:
        app_no = _app_number(application)

        create_notification(
            user=application.user,
            title="Documents Submitted",
            message=f"All required documents for application {app_no} have been submitted for review.",
            notification_type=UserNotification.TYPE_GENERAL,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="loan_detail",
            action_api=f"/api/customer/my-loans/{application.id}/",
            object_id=application.id,
            object_type="loan_application",
            metadata=_application_metadata(application),
        )

        notify_admins(
            title="Documents Ready for Review",
            message=f"All required documents for application {app_no} are ready for admin review.",
            notification_type=UserNotification.TYPE_GENERAL,
            priority=UserNotification.PRIORITY_HIGH,
            action_screen="admin_application_documents",
            action_api=f"/api/admin/applications/{application.id}/documents/",
            object_id=application.id,
            object_type="loan_application",
            metadata=_application_metadata(application),
        )
    except Exception:
        pass


def notify_document_status_changed(document, new_status, note=None):
    try:
        application = document.application
        app_no = _app_number(application)
        document_label = document.get_document_type_display() if hasattr(document, "get_document_type_display") else document.document_type

        if new_status == "approved":
            title = "Document Approved"
            message = f"Your {document_label} for application {app_no} has been approved."
            notification_type = UserNotification.TYPE_DOCUMENT_APPROVED
            priority = UserNotification.PRIORITY_NORMAL

        elif new_status == "rejected":
            title = "Document Rejected"
            message = f"Your {document_label} for application {app_no} has been rejected. Please upload a correct document."
            notification_type = UserNotification.TYPE_DOCUMENT_REJECTED
            priority = UserNotification.PRIORITY_HIGH

        elif new_status == "pending":
            title = "Document Pending"
            message = f"Your {document_label} for application {app_no} is pending review."
            notification_type = UserNotification.TYPE_DOCUMENT_REQUIRED
            priority = UserNotification.PRIORITY_NORMAL

        else:
            return

        create_notification(
            user=application.user,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            action_screen="documents",
            action_api=f"/api/applications/{application.id}/documents/",
            object_id=document.id,
            object_type="loan_document",
            metadata={
                **_application_metadata(application),
                "documentId": _str_id(document.id),
                "documentType": document.document_type,
                "documentStatus": document.status,
                "adminNote": note or "",
            },
        )
    except Exception:
        pass


def notify_kyc_submitted(kyc):
    try:
        application = kyc.application
        app_no = _app_number(application) if application else None

        create_notification(
            user=kyc.user,
            title="KYC Submitted",
            message="Your KYC verification has been submitted and is under review.",
            notification_type=UserNotification.TYPE_KYC_SUBMITTED,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="kyc",
            action_api="/api/kyc/me/",
            object_id=kyc.id,
            object_type="kyc_verification",
            metadata={
                "kycId": _str_id(kyc.id),
                "applicationId": _str_id(getattr(application, "id", None)),
                "applicationNumber": app_no,
                "status": kyc.status,
            },
        )

        notify_admins(
            title="KYC Submitted",
            message=f"{_user_name(kyc.user)} submitted KYC verification.",
            notification_type=UserNotification.TYPE_KYC_SUBMITTED,
            priority=UserNotification.PRIORITY_HIGH,
            action_screen="admin_kyc_detail",
            action_api=f"/api/admin/kyc/{kyc.id}/",
            object_id=kyc.id,
            object_type="kyc_verification",
            metadata={
                "kycId": _str_id(kyc.id),
                "applicationId": _str_id(getattr(application, "id", None)),
                "applicationNumber": app_no,
                "status": kyc.status,
            },
        )
    except Exception:
        pass


def notify_kyc_status_changed(kyc, new_status, note=None):
    try:
        if new_status == "approved":
            title = "KYC Approved"
            message = "Your KYC verification has been approved."
            notification_type = UserNotification.TYPE_KYC_APPROVED
            priority = UserNotification.PRIORITY_NORMAL

        elif new_status == "rejected":
            title = "KYC Rejected"
            message = "Your KYC verification has been rejected. Please review the reason and submit again."
            notification_type = UserNotification.TYPE_KYC_REJECTED
            priority = UserNotification.PRIORITY_HIGH

        elif new_status == "under_review":
            title = "KYC Under Review"
            message = "Your KYC verification is under review."
            notification_type = UserNotification.TYPE_KYC_SUBMITTED
            priority = UserNotification.PRIORITY_NORMAL

        else:
            return

        application = kyc.application

        create_notification(
            user=kyc.user,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            action_screen="kyc",
            action_api="/api/kyc/me/",
            object_id=kyc.id,
            object_type="kyc_verification",
            metadata={
                "kycId": _str_id(kyc.id),
                "applicationId": _str_id(getattr(application, "id", None)),
                "applicationNumber": _app_number(application) if application else None,
                "status": kyc.status,
                "adminNote": note or "",
                "rejectionReason": getattr(kyc, "rejection_reason", None),
            },
        )
    except Exception:
        pass


def notify_chat_message(message):
    try:
        conversation = message.conversation
        sender = message.sender

        if not conversation or not sender:
            return

        if conversation.customer_id == sender.id:
            if conversation.admin:
                create_notification(
                    user=conversation.admin,
                    title="New Chat Message",
                    message=f"{_user_name(conversation.customer)} sent a message.",
                    notification_type=UserNotification.TYPE_CHAT_MESSAGE,
                    priority=UserNotification.PRIORITY_NORMAL,
                    action_screen="chat_detail",
                    action_api=f"/api/chat/conversations/{conversation.id}/messages/",
                    object_id=conversation.id,
                    object_type="chat_conversation",
                    metadata={
                        "conversationId": _str_id(conversation.id),
                        "messageId": _str_id(message.id),
                        "senderId": _str_id(sender.id),
                    },
                )
            else:
                notify_admins(
                    title="New Chat Message",
                    message=f"{_user_name(conversation.customer)} sent a message.",
                    notification_type=UserNotification.TYPE_CHAT_MESSAGE,
                    priority=UserNotification.PRIORITY_NORMAL,
                    action_screen="admin_chat_detail",
                    action_api=f"/api/chat/conversations/{conversation.id}/messages/",
                    object_id=conversation.id,
                    object_type="chat_conversation",
                    metadata={
                        "conversationId": _str_id(conversation.id),
                        "messageId": _str_id(message.id),
                        "senderId": _str_id(sender.id),
                    },
                )
        else:
            create_notification(
                user=conversation.customer,
                title="New Message from Support",
                message=f"{_user_name(sender)} sent you a message.",
                notification_type=UserNotification.TYPE_CHAT_MESSAGE,
                priority=UserNotification.PRIORITY_NORMAL,
                action_screen="chat_detail",
                action_api=f"/api/chat/conversations/{conversation.id}/messages/",
                object_id=conversation.id,
                object_type="chat_conversation",
                metadata={
                    "conversationId": _str_id(conversation.id),
                    "messageId": _str_id(message.id),
                    "senderId": _str_id(sender.id),
                },
            )
    except Exception:
        pass


def notify_appointment_booked(appointment):
    try:
        create_notification(
            user=appointment.customer,
            title="Appointment Booked!",
            message=f"Your {appointment.get_call_type_display()} with {appointment.agent.name} is confirmed for {appointment.appointment_date} at {appointment.start_time.strftime('%I:%M %p')}.",
            notification_type=UserNotification.TYPE_APPOINTMENT_BOOKED,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="appointment_detail",
            action_api="/api/support/book-call/",
            object_id=appointment.id,
            object_type="support_appointment",
            metadata={
                "appointmentId": _str_id(appointment.id),
                "managerId": _str_id(appointment.agent_id),
                "managerName": appointment.agent.name,
                "date": appointment.appointment_date.isoformat(),
                "time": appointment.start_time.strftime("%H:%M"),
                "callType": appointment.call_type,
            },
        )

        notify_admins(
            title="New Appointment Booked",
            message=f"{_user_name(appointment.customer)} booked a {appointment.get_call_type_display()} with {appointment.agent.name}.",
            notification_type=UserNotification.TYPE_APPOINTMENT_BOOKED,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="admin_appointment_detail",
            action_api="/api/admin/support/appointments/",
            object_id=appointment.id,
            object_type="support_appointment",
            metadata={
                "appointmentId": _str_id(appointment.id),
                "customerId": _str_id(appointment.customer_id),
                "managerId": _str_id(appointment.agent_id),
                "managerName": appointment.agent.name,
                "date": appointment.appointment_date.isoformat(),
                "time": appointment.start_time.strftime("%H:%M"),
                "callType": appointment.call_type,
            },
        )
    except Exception:
        pass


def notify_appointment_status_changed(appointment, new_status, note=None):
    try:
        title_map = {
            "scheduled": "Appointment Scheduled",
            "completed": "Appointment Completed",
            "cancelled": "Appointment Cancelled",
            "missed": "Appointment Missed",
            "rescheduled": "Appointment Rescheduled",
        }

        title = title_map.get(new_status)

        if not title:
            return

        create_notification(
            user=appointment.customer,
            title=title,
            message=f"Your appointment with {appointment.agent.name} is now {new_status}.",
            notification_type=UserNotification.TYPE_APPOINTMENT_BOOKED,
            priority=UserNotification.PRIORITY_NORMAL if new_status != "cancelled" else UserNotification.PRIORITY_HIGH,
            action_screen="appointment_detail",
            action_api="/api/support/book-call/",
            object_id=appointment.id,
            object_type="support_appointment",
            metadata={
                "appointmentId": _str_id(appointment.id),
                "status": appointment.status,
                "reason": note or getattr(appointment, "cancel_reason", None),
            },
        )
    except Exception:
        pass


def notify_agreement_signed(agreement):
    try:
        application = agreement.application

        create_notification(
            user=agreement.borrower,
            title="Agreement Signed",
            message=f"Your loan agreement for application {_app_number(application)} has been signed successfully.",
            notification_type=UserNotification.TYPE_E_SIGN_COMPLETED,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="agreement_detail",
            action_api=f"/api/agreements/{application.id}/",
            object_id=agreement.id,
            object_type="loan_agreement",
            metadata={
                **_application_metadata(application),
                "agreementId": _str_id(agreement.id),
                "signedAt": agreement.signed_at.isoformat() if agreement.signed_at else None,
            },
        )

        notify_admins(
            title="Agreement Signed",
            message=f"{_user_name(agreement.borrower)} signed agreement for application {_app_number(application)}.",
            notification_type=UserNotification.TYPE_E_SIGN_COMPLETED,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="admin_application_detail",
            action_api=f"/api/admin/applications/{application.id}/",
            object_id=agreement.id,
            object_type="loan_agreement",
            metadata={
                **_application_metadata(application),
                "agreementId": _str_id(agreement.id),
            },
        )
    except Exception:
        pass


def notify_co_applicant_invited(invite):
    try:
        agreement = invite.agreement
        application = agreement.application

        create_notification(
            user=agreement.borrower,
            title="Co-applicant Invited",
            message=f"{invite.name} has been invited as co-applicant for application {_app_number(application)}.",
            notification_type=UserNotification.TYPE_CO_APPLICANT_INVITE,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="agreement_detail",
            action_api=f"/api/agreements/{application.id}/",
            object_id=invite.id,
            object_type="co_applicant_invitation",
            metadata={
                **_application_metadata(application),
                "invitationId": _str_id(invite.id),
                "coApplicantName": invite.name,
                "coApplicantEmail": invite.email,
                "inviteLink": invite.invite_link,
            },
        )

        notify_admins(
            title="Co-applicant Invited",
            message=f"{_user_name(agreement.borrower)} invited {invite.name} as co-applicant.",
            notification_type=UserNotification.TYPE_CO_APPLICANT_INVITE,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="admin_application_detail",
            action_api=f"/api/admin/applications/{application.id}/",
            object_id=invite.id,
            object_type="co_applicant_invitation",
            metadata={
                **_application_metadata(application),
                "invitationId": _str_id(invite.id),
                "coApplicantName": invite.name,
                "coApplicantEmail": invite.email,
            },
        )
    except Exception:
        pass


def notify_co_applicant_responded(invite, action):
    try:
        agreement = invite.agreement
        application = agreement.application

        create_notification(
            user=agreement.borrower,
            title=f"Co-applicant {action.title()}ed",
            message=f"{invite.name} has {action}ed the co-applicant invitation for application {_app_number(application)}.",
            notification_type=UserNotification.TYPE_CO_APPLICANT_INVITE,
            priority=UserNotification.PRIORITY_NORMAL,
            action_screen="agreement_detail",
            action_api=f"/api/agreements/{application.id}/",
            object_id=invite.id,
            object_type="co_applicant_invitation",
            metadata={
                **_application_metadata(application),
                "invitationId": _str_id(invite.id),
                "coApplicantName": invite.name,
                "coApplicantEmail": invite.email,
                "action": action,
            },
        )
    except Exception:
        pass