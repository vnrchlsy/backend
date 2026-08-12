import pytest

from accounts.factories import AccountFactory
from shelter.models import ShelterProfile
from verifications.models import VerificationDocument, VerificationRequest

CHANGE = "/admin/verifications/verificationrequest/{}/change/"


def _docs(vr, types):
    for t in types:
        VerificationDocument.objects.create(verification=vr, doc_type=t,
                                            file_url=f"https://example.invalid/{t}")


@pytest.mark.django_db
def test_decision_fields_are_read_only_so_edits_go_through_audited_actions():
    # A decision must be attributable and gate-correct, so it can only be made via the
    # approve/reject/needs_info actions — never by hand-editing the change form. The
    # decision-critical fields are therefore read-only on the detail page.
    from django.contrib import admin as dj
    ma = dj.site._registry[VerificationRequest]
    for field in ("account", "type", "status", "reviewed_by", "reviewed_at", "notes"):
        assert field in ma.readonly_fields


@pytest.mark.django_db
def test_detail_reports_deferred_bai_for_a_tier2_request_without_it(admin_client):
    acc = AccountFactory(account_type="shelter")
    ShelterProfile.objects.create(account=acc, org_name="Pasig NGO", org_type="shelter",
                                  tier="registered_ngo")
    vr = VerificationRequest.objects.create(account=acc, type="shelter_org")
    _docs(vr, ["gov_id", "proof_billing", "rescue_photos", "rescue_photos", "rescue_photos",
               "sec_dti"])
    content = admin_client.get(CHANGE.format(vr.pk)).content.decode()
    assert "Deferred" in content and "bai_cert" in content


@pytest.mark.django_db
def test_detail_reports_missing_for_an_incomplete_tier1_request(admin_client):
    acc = AccountFactory(account_type="shelter")
    ShelterProfile.objects.create(account=acc, org_name="Marikina Rescue", org_type="rescue",
                                  tier="community_rescue")
    vr = VerificationRequest.objects.create(account=acc, type="shelter_org")
    _docs(vr, ["gov_id"])  # no proof_billing, no photos
    content = admin_client.get(CHANGE.format(vr.pk)).content.decode()
    assert "Missing" in content
    assert "proof_billing" in content and "rescue_photos" in content


@pytest.mark.django_db
def test_detail_reports_all_present_for_a_complete_tier1_request(admin_client):
    acc = AccountFactory(account_type="shelter")
    ShelterProfile.objects.create(account=acc, org_name="Marikina Rescue", org_type="rescue",
                                  tier="community_rescue")
    vr = VerificationRequest.objects.create(account=acc, type="shelter_org")
    _docs(vr, ["gov_id", "proof_billing", "rescue_photos", "rescue_photos", "rescue_photos"])
    content = admin_client.get(CHANGE.format(vr.pk)).content.decode()
    assert "All required documents present" in content


@pytest.mark.django_db
def test_detail_line_is_not_applicable_for_a_member_request(admin_client):
    acc = AccountFactory(account_type="personal")
    vr = VerificationRequest.objects.create(account=acc, type="rescuer")
    _docs(vr, ["gov_id"])
    content = admin_client.get(CHANGE.format(vr.pk)).content.decode()
    # a member has no tier doc-set; the line must not fabricate a shelter checklist
    assert "Missing" not in content or "sec_dti" not in content
