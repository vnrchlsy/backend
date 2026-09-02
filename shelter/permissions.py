from rest_framework.permissions import IsAuthenticated


class IsShelter(IsAuthenticated):
    """User+type=shelter. A signed-in account whose `account_type` is `shelter`."""

    message = "This action is only available to shelter accounts."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.account_type == "shelter"
