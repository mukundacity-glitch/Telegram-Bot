"""Guard user-confirmed existing branded slide against silent replacement."""
import hashlib

from vortex.brand_footer import MASTER, APPROVED_MASTER_BLOB_SHA, verify_exact_master


def test_user_confirmed_telegram_stadium_slide_is_exactly_pinned():
    data = MASTER.read_bytes()
    digest = hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\\0" + data
    ).hexdigest()
    assert digest == APPROVED_MASTER_BLOB_SHA
    verify_exact_master()
