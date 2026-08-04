import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from common import otp
from common.otp import CodeExpired, CodeInvalid, CodeLocked
from verifications.models import VerificationCode


@pytest.mark.django_db
def test_issue_code_persists_hashed_not_raw():
    acc = AccountFactory()
    raw = otp.issue_code(acc, channel="email", purpose="signup")
    assert len(raw) == 6 and raw.isdigit()
    row = VerificationCode.objects.get(account=acc, purpose="signup")
    assert row.code_hash and raw not in row.code_hash   # never stored raw


@pytest.mark.django_db
def test_verify_wrong_code_decrements_attempts_then_locks():
    acc = AccountFactory()
    otp.issue_code(acc, channel="email", purpose="signup")
    for expected_left in (4, 3, 2, 1, 0):
        with pytest.raises(CodeInvalid) as e:
            otp.verify_code(acc, purpose="signup", code="000000")
        assert e.value.attempts_left == expected_left
    with pytest.raises(CodeLocked):
        otp.verify_code(acc, purpose="signup", code="000000")


@pytest.mark.django_db
def test_verify_correct_code_consumes_it(monkeypatch):
    acc = AccountFactory()
    raw = otp.issue_code(acc, channel="email", purpose="signup")
    otp.verify_code(acc, purpose="signup", code=raw)          # no raise
    with pytest.raises(CodeInvalid):
        otp.verify_code(acc, purpose="signup", code=raw)      # single-use


@pytest.mark.django_db
def test_expired_code_raises_expired():
    acc = AccountFactory()
    raw = otp.issue_code(acc, channel="email", purpose="signup")
    row = VerificationCode.objects.get(account=acc, purpose="signup")
    row.expires_at = timezone.now() - timezone.timedelta(minutes=1)
    row.save()
    with pytest.raises(CodeExpired):
        otp.verify_code(acc, purpose="signup", code=raw)
