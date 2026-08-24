from shelter.permissions import IsShelter


class IsShiftOwner(IsShelter):
    """User+type=shelter AND the shelter that posted this shift. Ownership is checked in
    the view against the URL's shift, since DRF object permissions don't see it here."""

    message = "Only the shelter that posted this activity can manage it."
