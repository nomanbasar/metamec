from rest_framework.response import Response


def build_response(request, success=True, message="", data=None, meta=None, status_code=200):
    return Response(
        {
            "success": success,
            "message": message,
            "meta": meta if meta is not None else {},
            "data": data if data is not None else {},
            "requestId": getattr(request, "request_id", ""),
        },
        status=status_code,
    )