from datetime import datetime,timezone
import pytest
from vortex import weekly_green_arrow as w
from vortex.weekly_green_arrow_render import PALETTES


def test_scoring_is_per_match_not_per_multiple():
    history=[{"minutes":90,"defensive_contribution":20,"saves":6},
             {"minutes":90,"defensive_contribution":9,"saves":2}]
    assert w.defensive_metrics(2,history)["points_per_match"]==1
    assert w.defensive_metrics(1,history)["points_per_match"]==1
    with pytest.raises((ValueError,KeyError)):
        w.defensive_metrics(2,[{"minutes":90}])


def test_security_rejects_missing_and_cameo_before_ranking():
    fixtures=[{"id":i,"event":i,"team_h":1,"team_a":2,"finished":True,
               "kickoff_time":f"2026-11-{i:02}T15:00:00Z"} for i in (1,2,3)]
    rows=[{"fixture":i,"round":i,"minutes":64} for i in (1,2,3)]
    assert len(w.secure_history(rows,fixtures,1,[1,2,3]))==3
    assert not w.secure_history(rows[:-1],fixtures,1,[1,2,3])
    assert not w.secure_history(rows+rows[:1],fixtures,1,[1,2,3])
    rows[-1]["minutes"]=63
    assert not w.secure_history(rows,fixtures,1,[1,2,3])


def test_core_metrics_keep_observations_and_missing_distinct():
    data={"minutes":450,"xa":2.5,"assists":1,"chances_created":10}
    assert w.core_metrics(27,data)["chances90"]==2
    assert w.core_metrics(27,data)["assist_delta"]==-1.5
    with pytest.raises(ValueError):
        w.core_metrics(27,{**data,"incomplete_metrics":True})
    assert w.core_metrics(28,{"minutes":450,"xg":3,"goals":2,"total_shots":15,
                             "touches_opposition_box":25})["xg_per_shot"]==.2


def test_unique_palettes_and_closed_gate():
    assert set(PALETTES)==set(w.EDITIONS)=={26,27,28,29}
    assert len({v[0] for v in PALETTES.values()})==4
    assert not w.eligible(26,{},{"season":"2026-27","gw":12},{},
                          datetime.now(timezone.utc),[],{},inventory_verified=True,legacy_reconciled=True)
