"""Stories review steps 1 and 3 (library docs/superpowers/specs/2026-11-09-stories-review.md) · the one writer
for a new story, as `community/needs.py` is for the wishlist (D-S6-7).

- ST1 · the story and its photos commit together or not at all, and `story_posted` is emitted only after the
  commit, so a failed photo never leaves a published story with photos missing, and the event never counts a
  story that does not exist.
- ST3 / ST4 · a link is resolved here, not left to the foreign key (an unknown id was a 500), and it must be
  earned: the author is the poster or the adopter of a listing that was adopted, or the claimer or the reporter
  of a rescue that resolved. The type comes from the link; "adoption" and "rescue" are never the client's claim.
- SQ3 · one story per author per link, checked here and held by the two partial unique constraints.

Step 4 (ST5, ST23) · the feed pages by a keyset cursor over (created_at, story_id), newest first. An offset page would
repeat a row whenever a story is posted while someone scrolls; a cursor is a position, so it survives that, and survives
the story it points at being hidden. `next` is opaque to the app: it hands it back as `?cursor=` and nothing else.

Step 6 (ST7, SQ1) · an author edits the caption of, and deletes, their own story. A delete is SOFT for `REMOVED_RETENTION_DAYS`: the story
leaves the feed, the detail and "your stories" at once, the row and its photos are kept as moderation evidence, and `purge_removed_stories`
(nightly) then removes them for good, with their files. `removed` is a status of its own, so a moderation takedown can neither hide it back
into view nor a restore bring it back.

The photo rule (each must be this account's own `story_photo` upload, ST2) is the serializer's, beside the other
field checks.
"""
import base64
import binascii
import logging
import uuid
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from common.analytics import emit
from common.storage import PUBLIC, delete_object, delete_object_or_log, list_objects, object_url
from common.uploads import own_upload_url_error

from .models import StoryPhoto, StoryPost, StoryStatus, StoryType

# Stories review step 10 (ST18) · where a post came from. A closed list, so free text never reaches the log; anything else is "unknown".
# Add a value here in the same change that adds the entry point that sends it.
STORY_SOURCES = frozenset({"feed", "adoption_cta", "poster_prompt", "rescue_prompt"})


def clean_source(value):
    return value if isinstance(value, str) and value in STORY_SOURCES else "unknown"


# The fields a refusal may name. Anything else is just "invalid": a field name the client chose must not become a log dimension.
_REFUSAL_FIELDS = frozenset({"caption", "photos", "story_type", "adoption_listing_id", "rescue_case_id", "source"})


def refusal_reason(errors):
    """A coarse reason for a refused post, from a serializer's `errors`: invalid_<field>, or invalid."""
    field = next(iter(errors), None) if isinstance(errors, dict) else None
    return f"invalid_{field}" if field in _REFUSAL_FIELDS else "invalid"


def emit_refused(reason):
    emit("story_post_refused", reason=reason)


MAX_CAPTION = 2000    # SQ4 (owner, 2026-11-09)
MAX_PHOTOS = 6        # the app's compose screen takes up to this many (stories review step 8)


class StoryError(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


_EXISTS = StoryError("story_exists", "You've already shared a story about this.", 409)


def _listing_link(author, listing_id):
    from listings.models import AdoptionListing, ListingStatus
    listing = AdoptionListing.objects.filter(pk=listing_id).only("posted_by_id", "adopted_by_account_id",
                                                                 "status").first()
    if listing is None:
        raise StoryError("link_not_found", "We couldn't find that adoption.", 422)
    if author.pk not in (listing.posted_by_id, listing.adopted_by_account_id):
        raise StoryError("not_your_story", "Only the people in an adoption can share its story.", 403)
    if listing.status != ListingStatus.ADOPTED:
        raise StoryError("link_not_eligible", "You can share this story once the adoption is complete.", 422)
    return {"adoption_listing_id": listing.pk}, StoryType.ADOPTION


def _case_link(author, case_id):
    from sagip.models import RescueCase
    case = RescueCase.objects.select_related("report").filter(pk=case_id).first()
    if case is None:
        raise StoryError("link_not_found", "We couldn't find that rescue.", 422)
    if author.pk not in (case.claimed_by_account_id, case.report.reporter_account_id):
        raise StoryError("not_your_story", "Only the people in a rescue can share its story.", 403)
    if case.resolved_at is None or case.expired_at is not None:
        raise StoryError("link_not_eligible", "You can share this story once the rescue is resolved.", 422)
    return {"rescue_case_id": case.pk}, StoryType.RESCUE


def _resolve_link(author, story_type, adoption_listing_id, rescue_case_id):
    if adoption_listing_id and rescue_case_id:
        raise StoryError("one_link_only", "A story can be about one adoption or one rescue, not both.", 422)
    if adoption_listing_id:
        return _listing_link(author, adoption_listing_id)
    if rescue_case_id:
        return _case_link(author, rescue_case_id)
    if story_type in (StoryType.ADOPTION, StoryType.RESCUE):
        raise StoryError("link_required", "An adoption or rescue story needs the adoption or rescue it is about.", 422)
    return {}, StoryType.GENERAL


def create_story(author, *, photos, caption="", story_type=None, adoption_listing_id=None, rescue_case_id=None, source=None):
    """Write one story and its photos. Raises `StoryError` for a link that is unknown, not the author's, not yet
    eligible, or already has the author's story."""
    link, derived_type = _resolve_link(author, story_type, adoption_listing_id, rescue_case_id)
    if link and StoryPost.objects.filter(author_account=author, **link).exists():
        raise _EXISTS
    try:
        with transaction.atomic():
            story = StoryPost.objects.create(author_account=author, caption=caption, story_type=derived_type, **link)
            # Step 8 · each photo keeps the order it was sent in, and exactly one is primary: the marked one, else the first.
            primary = next((i for i, photo in enumerate(photos) if photo.get("is_primary")), 0)
            for position, photo in enumerate(photos):
                StoryPhoto.objects.create(story=story, url=photo["file_url"], is_primary=(position == primary), position=position)
    except IntegrityError:
        if link and StoryPost.objects.filter(author_account=author, **link).exists():
            raise _EXISTS from None           # a racing post on the same link won (uq_story_author_*)
        raise
    # Step 10 · account-free: the type, where it came from, whether it is about an adoption or rescue, and how many photos. After the commit.
    props = dict(story_type=derived_type, source=clean_source(source), linked=bool(link), photo_count=len(photos))
    transaction.on_commit(lambda: emit("story_posted", **props))
    return story


# --- step 4 · the feed's cursor --------------------------------------------------------------------------------------

PAGE_SIZE = 20
_MAX_CURSOR = 200      # a real cursor is ~60 characters; anything longer is refused before it is decoded
_BAD_CURSOR = StoryError("invalid_cursor", "That page link is no longer valid. Pull to refresh.", 400)


def encode_cursor(created_at, story_id):
    raw = f"{created_at.isoformat()}|{story_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor):
    """(created_at, story_id) from a cursor `encode_cursor` made. Raises `StoryError` (400) for anything else."""
    if not isinstance(cursor, str) or not 0 < len(cursor) <= _MAX_CURSOR:
        raise _BAD_CURSOR
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, sep, ident = raw.partition("|")
        created_at, story_id = datetime.fromisoformat(stamp), uuid.UUID(ident)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise _BAD_CURSOR from None
    if not sep or created_at.tzinfo is None:
        raise _BAD_CURSOR
    return created_at, story_id


def feed_page(stories, cursor=None):
    """(rows, next_cursor) · one page of `stories` (the caller's filtered queryset), newest first, after `cursor`.

    Fetches one row past the page to learn whether another follows, so the last page has `next = None` and an exactly full
    one never points at an empty page. `story_id` breaks a tie between two stories made in the same instant."""
    stories = stories.order_by("-created_at", "-story_id")
    if cursor:
        created_at, story_id = decode_cursor(cursor)
        stories = stories.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, story_id__lt=story_id))
    rows = list(stories[:PAGE_SIZE + 1])
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    return rows, (encode_cursor(rows[-1].created_at, rows[-1].pk) if more else None)


# --- step 5 · which stories link to something the viewer may open ------------------------------------------------------

def story_links(stories, viewer):
    """{story_id: {"type", "id"}} for the stories in `stories` whose adoption or rescue `viewer` could open, by the same rules as
    the screens it opens (D-S6-4: context goes through the gated detail screens, so the link is offered only when they would
    answer). A fixed number of queries however many stories there are.

    An adoption: the poster always; anyone else only while the listing is not taken down, its poster is publicly visible and a
    Verified Member or verified shelter (`listing_is_public`), and the viewer has not blocked the poster, either way round.
    A rescue: the public report, unless it was taken down, which only its reporter and the case's claimer can still open. The id
    is the REPORT's, because that is what the report screen takes."""
    from accounts.visibility import public_account_q
    from listings.models import AdoptionListing, ListingStatus
    from listings.visibility import public_poster_q
    from moderation.blocks import hidden_from
    from sagip.models import RescueCase

    stories = list(stories)
    listing_ids = {s.adoption_listing_id for s in stories if s.adoption_listing_id}
    case_ids = {s.rescue_case_id for s in stories if s.rescue_case_id}
    me = viewer.pk if viewer is not None and getattr(viewer, "is_authenticated", False) else None

    open_listings = set()
    if listing_ids:
        public = (AdoptionListing.objects.filter(pk__in=listing_ids, hidden_at__isnull=True)
                  .exclude(status=ListingStatus.DRAFT).filter(public_account_q("posted_by__")).filter(public_poster_q())
                  .exclude(posted_by_id__in=hidden_from(viewer)))
        open_listings = set(public.values_list("pk", flat=True))
        if me:
            open_listings |= set(AdoptionListing.objects.filter(pk__in=listing_ids, posted_by_id=me)
                                 .exclude(status=ListingStatus.DRAFT).values_list("pk", flat=True))

    open_reports = {}
    if case_ids:
        for case_id, report_id, hidden, reporter_id, claimer_id in RescueCase.objects.filter(pk__in=case_ids).values_list(
                "pk", "report_id", "report__hidden_at", "report__reporter_account_id", "claimed_by_account_id"):
            if hidden is None or (me is not None and me in (reporter_id, claimer_id)):
                open_reports[case_id] = report_id

    links = {}
    for s in stories:
        if s.adoption_listing_id in open_listings:
            links[s.pk] = {"type": "adoption", "id": s.adoption_listing_id}
        elif s.rescue_case_id in open_reports:
            links[s.pk] = {"type": "rescue", "id": open_reports[s.rescue_case_id]}
    return links


# --- step 6 · the author's own controls -------------------------------------------------------------------------------

REMOVED_RETENTION_DAYS = 30        # SQ1 (owner, 2026-11-09): soft for 30 days, then hard with the files


def _own_story_for_update(story_id, author):
    """The author's story, locked, or a 404 `StoryError`: a stranger's, a deleted one and an unknown id all read the same, so a delete or
    an edit never confirms that someone else's story exists."""
    story = StoryPost.objects.select_for_update().filter(pk=story_id, author_account=author).exclude(status=StoryStatus.REMOVED).first()
    if story is None:
        raise StoryError("not_found", "No such story.", 404)
    return story


@transaction.atomic
def remove_story(story_id, author):
    """Delete the author's story: gone from every surface at once, kept for `REMOVED_RETENTION_DAYS`. A story moderation hid may be
    deleted too (the author's own choice, and the row stays as evidence all the same); it can then no longer be restored."""
    story = _own_story_for_update(story_id, author)
    was_hidden = story.status == StoryStatus.HIDDEN
    story.status, story.removed_at = StoryStatus.REMOVED, timezone.now()
    story.save(update_fields=["status", "removed_at"])
    transaction.on_commit(lambda: emit("story_deleted", story_type=story.story_type, was_hidden=was_hidden))
    return story


@transaction.atomic
def edit_caption(story_id, author, caption):
    """Change the caption of the author's own published story. Nothing else about a story is editable (the photo and the link are what
    was shared), and one moderation hid cannot be edited: that would let the person rewrite what is under review."""
    story = _own_story_for_update(story_id, author)
    if story.status == StoryStatus.HIDDEN:
        raise StoryError("story_hidden", "Moderators hid this story, so it can't be edited. You can ask for a second look from Support.", 409)
    story.caption = caption
    story.save(update_fields=["caption"])
    transaction.on_commit(lambda: emit("story_edited", story_type=story.story_type))
    return story


def purge_removed_stories(now=None):
    """Remove for good every story deleted `REMOVED_RETENTION_DAYS` ago or more: the row, its photos and reactions (cascade), then the files.
    Returns how many. A storage error never stops it (the row is the person's right, a bucket hiccup must not hold it): the key is logged,
    never the URL, so the orphan can be found by hand. Only the author's OWN uploads are deleted (a legacy row can hold any URL, and the
    bucket key is derived from it), and never a file another story row still names."""
    cutoff = (now or timezone.now()) - timedelta(days=REMOVED_RETENTION_DAYS)
    purged = 0
    stories = (StoryPost.objects.filter(status=StoryStatus.REMOVED, removed_at__lte=cutoff)
               .select_related("author_account").prefetch_related("photos"))
    for story in stories:
        files = [p.url for p in story.photos.all() if own_upload_url_error(p.url, story.author_account, "story_photo") is None]
        story.delete()
        for url in dict.fromkeys(files):
            if not StoryPhoto.objects.filter(url=url).exists():
                delete_object_or_log(url, PUBLIC, why="a deleted story's photo", deleter=delete_object)
        purged += 1
    if purged:
        emit("story_purged", count=purged)
    return purged


# --- stories test plan F6 · the file nobody cites ---------------------------------------------------------------------------------

ORPHAN_GRACE_HOURS = 24         # an upload gets a day to be posted
ORPHAN_REFUSE_MIN = 50          # the valve below only judges a night with at least this many candidates ...
ORPHAN_REFUSE_FRACTION = 0.5    # ... and refuses when more than this share of what it found looks orphaned
_ORPHAN_BATCH = 200


def _cited_story_keys(keys):
    """Which of `keys` some story_photo row names. Matched on the KEY (the row's URL may carry another host: a CDN, an older bucket name)."""
    cited = set()
    for i in range(0, len(keys), _ORPHAN_BATCH):
        batch = keys[i:i + _ORPHAN_BATCH]
        q = Q()
        for k in batch:
            q |= Q(url__endswith="/" + k)
        for url in StoryPhoto.objects.filter(q).values_list("url", flat=True):
            cited.update(k for k in batch if url.endswith("/" + k))
    return cited


def sweep_orphan_story_uploads(now=None, lister=None, deleter=None):
    """Delete `story_photo/` files older than a day that no `story_photo` row cites: the upload that succeeded and the post that never did.

    Returns how many it deleted. Built so it cannot make things worse:
      - only the `story_photo/` prefix, and only files past `ORPHAN_GRACE_HOURS`, so a person who uploads and posts later is safe;
      - a file a row cites is kept whatever its story's state (a soft-deleted story's files are evidence for its 30 days);
      - a storage error on one file is logged by KEY and the sweep goes on;
      - if more than half of what it found looks orphaned (and there are enough to judge), it deletes NOTHING and logs an error: that shape means its idea of
        "cited" is wrong, not that the bucket is mostly litter.
    `lister` and `deleter` are for tests; the real ones are `common.storage.list_objects` and `delete_object`."""
    cutoff = (now or timezone.now()) - timedelta(hours=ORPHAN_GRACE_HOURS)
    old = [k for k, modified in (lister or list_objects)(PUBLIC, "story_photo/")
           if k.startswith("story_photo/") and not k.endswith("/") and modified < cutoff]
    cited = _cited_story_keys(old)
    orphans = [k for k in old if k not in cited]
    log = logging.getLogger("kupkop.storage")
    if len(orphans) >= ORPHAN_REFUSE_MIN and len(orphans) > ORPHAN_REFUSE_FRACTION * len(old):
        log.error("refusing to sweep story uploads: %d of %d old files look orphaned, which means the check is wrong; nothing deleted", len(orphans), len(old))
        return 0
    deleted = 0
    for k in orphans:
        try:
            (deleter or delete_object)(object_url(k, PUBLIC), PUBLIC)
        except Exception as exc:  # noqa: BLE001 — boto3 is prod-only, so its error types can't be named
            log.warning("could not delete orphaned story upload %s (%s); left for the next sweep", k, type(exc).__name__)
            continue
        deleted += 1
    if deleted:
        emit("story_orphans_swept", count=deleted)
    return deleted
