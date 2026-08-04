from rest_framework.exceptions import ValidationError

from common.errors import error_handler


def test_multi_field_validation_error_keeps_all_fields():
    exc = ValidationError({"email": ["required"], "password": ["too short"]})
    context = {"view": None, "request": None}

    response = error_handler(exc, context)

    error = response.data["error"]
    assert error["field"] == "email"
    assert error["message"] == "required"
    assert error["details"] == {
        "email": ["required"],
        "password": ["too short"],
    }
