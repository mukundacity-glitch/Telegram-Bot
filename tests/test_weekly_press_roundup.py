from datetime import datetime, timedelta, timezone
from vortex import weekly_press_roundup as slot

UTC = timezone.utc
def at(h, m=0):
    return datetime(2026, 11, 27, h, m, tzinfo=UTC)


def sample():
    expected = {"season":"2026-27","gw":12,"deadline":at(18,30).isoformat(),
                "kickoff":at(20).isoformat(),"pairs":{"1":[2]},"fixture_ids":[1]}
    reports = {"1":[{"club":"Test club","opponent":2,"news":"Verified report",
                     "url":"https://example.com/report","published":at(11).isoformat(),
                     "manager":"","quote":""}]}
    proof = {"scope":expected,"research_at":at(11,58).isoformat(),
             "checked_at":at(12).isoformat(),"source_at":at(11,55).isoformat(),
             "post_at":at(15,13).isoformat(),"data_digest":slot.digest(reports)}
    return expected,reports,proof


def test_schedule_requires_complete_inventory_and_full_cutoff():
    assert slot.choose_schedule(at(18,30),[]) is None
    research,post=slot.choose_schedule(at(18,30),[],inventory_verified=True)
    assert post+slot.WINDOW <= at(15,30)
    assert post-research-slot.WINDOW >= timedelta(hours=3)
    assert slot.choose_schedule(at(18,30),[("busy",at(0)-timedelta(days=2),at(20))],
                                inventory_verified=True) is None


def test_proof_fail_closed_and_release_off():
    expected,reports,proof=sample()
    assert slot.proof_valid(proof,expected,reports,at(15,13),[],inventory_verified=True)
    assert not slot.proof_valid(proof,expected,reports,at(15,13),[])
    assert not slot.proof_valid(proof,expected,reports,at(15,23),[],inventory_verified=True)
    assert not slot.proof_valid(proof,expected,reports,at(15,13),
                                [("busy",at(12),at(12,5))],inventory_verified=True)
    assert not slot.proof_valid({**proof,"checked_at":at(12,9).isoformat()},expected,reports,
                                at(15,13),[],inventory_verified=True)
    assert not slot.proof_valid(proof,expected,{},at(15,13),[],inventory_verified=True)
    assert not slot.eligible(proof,expected,reports,at(15,13),[],{}, {},inventory_verified=True)


def test_legacy_receipt_and_unattributed_quote():
    expected,reports,proof=sample()
    assert slot.legacy_claimed({"2026:GW12":{"discord_sending":True}},expected)
    reports["1"][0]["quote"]="Unattributed statement"
    proof["data_digest"]=slot.digest(reports)
    assert not slot.proof_valid(proof,expected,reports,at(15,13),[],inventory_verified=True)
