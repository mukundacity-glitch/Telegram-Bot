import pytest
from vortex.weekly_transfer_value import compare,legal
from vortex.editorial_inputs import RequiredInput


def test_budget_and_hit_are_applied_to_legal_lineups():
    positions=[1]*2+[2]*5+[3]*5+[4]*3
    players=[{"id":i+1,"element_type":pos,"team":i//3+1,"now_cost":50}
             for i,pos in enumerate(positions)]
    players.append({"id":16,"element_type":4,"team":6,"now_cost":60})
    values=[[2.,2.] for _ in range(15)]+[[5.,5.]]
    squad=list(range(15))
    selling={p["id"]:50 for p in players[:15]}
    assert legal(players[:15])
    assert not compare(players,values,squad,selling,0,0,4,[15])
    free=compare(players,values,squad,selling,10,1,4,[15])[0]
    hit=compare(players,values,squad,selling,10,0,4,[15])[0]
    assert free["net"]-hit["net"]==4
    assert hit["bank_after"]==0
    with pytest.raises(RequiredInput):
        compare(players,values,squad,{},10,0,4,[15])
