from rest_framework.views import exception_handler


def error_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response
    detail = response.data
    code = getattr(exc, "default_code", "error")
    message = ""
    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
        code = getattr(detail["detail"], "code", code)
    elif isinstance(detail, dict):
        field, msgs = next(iter(detail.items()))
        message = msgs[0] if isinstance(msgs, list) else str(msgs)
        details = {
            f: (m if isinstance(m, list) else [m])
            for f, m in detail.items()
        }
        response.data = {
            "error": {
                "code": code,
                "message": message,
                "field": field,
                "details": details,
            }
        }
        return response
    response.data = {"error": {"code": code, "message": message}}
    return response
