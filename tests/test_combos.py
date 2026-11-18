import csv,io
import pytest
from decimal import Decimal
from app import store
from app.errors import DomainError
from app.pipeline import calculate,execute,load_sample
from app.combos import normalize,parse_form
from app.modules.m4_paths.rules import evaluate as paths
from app.modules.m5_timeliness.rules import evaluate as timely
from app.modules.m6_compensation.rules import evaluate as settle
COMBOS=[{"parent":"0001","children":["0002"]}]
CHILD_COMBO=[{"parent":"M1","children":["C1"]}]
def scan(id,parcel,node,at,received="2026-11-09T00:00:00Z",reported="0",promised="24",value="200",destination="JP",zone="Asia/Tokyo",line=None):
    return {"scan_id":str(id),"parcel":parcel,"node":node,"event_time":at,"received_time":received,"destination":destination,"promised_hours":promised,"declared_value":value,"reported":reported,"_sources":[line or int(id)],"_line":line or int(id),"event_utc":at,"received_utc":received,"upload_lag_hours":"1","zone":zone}
def test_clock_starts_from_mother_accept_not_child():
    out=paths([scan(1,"M1","ACCEPT","2026-11-02T06:00:00Z",reported="10"),scan(2,"M1","DELIVERED","2026-11-03T01:00:00Z",reported="10"),scan(3,"C1","ACCEPT","2026-11-02T00:00:00Z",reported="99"),scan(4,"C1","DELIVERED","2026-11-03T03:00:00Z",reported="99")],{"parameters":{"combos":["M1:C1"]}})
    row=out["rows"][0]
    # 身份与起算都取母单收件：子单更早收件不把时钟拨前，也不把申报改成子单
    assert row["scan_id"]=="1" and row["accepted_at"]=="2026-11-02T06:00:00Z"
    assert row["combo"]["accepted_from"]=="M1" and row["reported"]=="10"
    assert row["delivered_at"]=="2026-11-03T03:00:00Z" and row["combo"]["delivered_from"]=="C1"
def test_delivery_before_combo_start_is_not_a_completion():
    out=paths([scan(1,"M1","ACCEPT","2026-11-02T06:00:00Z"),scan(2,"C1","ACCEPT","2026-11-02T00:00:00Z"),scan(3,"C1","DELIVERED","2026-11-02T03:00:00Z")],{"parameters":{"combos":["M1:C1"]}})
    assert out["rows"][0]["delivered_at"] is None and out["metrics"]["delivered"]==0
def test_combo_forms_are_equivalent():
    expected=normalize([{"parent":"M1","children":["C2","C1"]}])
    assert normalize({"M1":["C1","C2"]})==expected
    assert normalize(["M1:C1,C2"])==expected
    assert normalize({"C1":"M1","C2":"M1"})==expected
    assert normalize([{"parent":"M1","child":"C1"},{"parent":"M1","child":"C2"}])==expected
def test_combo_child_cannot_have_two_parents():
    with pytest.raises(DomainError) as e:normalize([{"parent":"M1","children":["C1"]},{"parent":"M2","children":["C1"]}])
    assert e.value.code=="BAD_COMBOS"
def test_combo_cycle_rejected():
    with pytest.raises(DomainError):normalize([{"parent":"M1","children":["M2"]},{"parent":"M2","children":["M1"]}])
def test_form_parsing_accepts_lines_and_json():
    assert parse_form("M1:C1,C2\nM2:C3")=={"combos":["M1:C1,C2","M2:C3"]}
    assert parse_form('{"M1":["C1"]}')=={"combos":{"M1":["C1"]}}
    assert parse_form("")=={}
def test_child_does_not_produce_its_own_row(result):
    combos=result["stages"][3]["combos"]
    assert combos==[]
    merged=calculate(load_sample("dirty.csv"),{"combos":COMBOS})["stages"][3]
    parcels=[r["parcel"] for r in merged["rows"]]
    assert "0002" not in parcels and parcels.count("0001")==1
def test_mother_bears_one_formal_conclusion():
    out=paths([scan(1,"M1","ACCEPT","2026-11-02T00:00:00Z",reported="10"),scan(2,"M1","DEPART","2026-11-02T12:00:00Z"),scan(3,"C1","ACCEPT","2026-11-02T06:00:00Z",reported="99",promised="48",value="999"),scan(4,"C1","DELIVERED","2026-11-04T00:00:00Z",reported="99")],{"parameters":{"combos":[{"parent":"M1","children":["C1"]}]}})
    assert len(out["rows"])==1
    row=out["rows"][0]
    assert row["parcel"]=="M1" and row["role"]=="母单"
    # 时限、保价、申报全部取母单，子单不另起一份正式结论
    assert (row["promised_hours"],row["declared_value"],row["reported"])==("24","200","10")
    assert row["combo"]["reported_from"]=="M1" and row["combo"]["terms_from"]=="母单"
    assert {c["parcel"]:c["reported"] for c in row["combo"]["superseded_reported"]}=={"C1":"99"}
    assert [m["parcel"] for m in row["members"]]==["M1","C1"]
    assert set(row["_sources"])=={1,2,3,4}
def test_mother_pending_and_child_missing_accept_give_one_pending_row():
    out=paths([scan(1,"M1","ACCEPT","2026-11-02T00:00:00Z"),scan(2,"M1","DEPART","2026-11-02T12:00:00Z"),scan(3,"C1","DELIVERED","2026-11-04T00:00:00Z")],{"parameters":{"combos":[{"parent":"M1","children":["C1"]}]}})
    assert len(out["rows"])==1
    row=out["rows"][0]
    assert row["parcel"]=="M1" and row["delivered_at"] is None
    assert row["combo"]["delivery_state"]=="待妥投"
    assert row["combo"]["pending_members"]==["M1"]
    assert row["combo"]["incomplete"]==[{"parcel":"M1","missing":["DELIVERED"]},{"parcel":"C1","missing":["ACCEPT"]}]
    assert out["metrics"]["delivered"]==0
def test_all_members_delivered_takes_latest_and_keeps_evidence():
    out=paths([scan(1,"M1","ACCEPT","2026-11-02T00:00:00Z"),scan(2,"M1","DELIVERED","2026-11-04T00:00:00Z"),scan(3,"C1","ACCEPT","2026-11-02T06:00:00Z"),scan(4,"C1","DELIVERED","2026-11-05T00:00:00Z")],{"parameters":{"combos":[{"parent":"M1","children":["C1"]}]}})
    row=out["rows"][0]
    assert row["delivered_at"]=="2026-11-05T00:00:00Z" and row["combo"]["delivered_from"]=="C1"
    assert row["combo"]["deliveries"]=={"C1":{"at":"2026-11-05T00:00:00Z","source_line":4},"M1":{"at":"2026-11-04T00:00:00Z","source_line":2}}
def test_regressed_child_scan_is_quarantined_not_deleted():
    out=paths([scan(1,"M1","ACCEPT","2026-11-02T00:00:00Z"),scan(2,"M1","DELIVERED","2026-11-04T00:00:00Z"),scan(3,"C1","ACCEPT","2026-11-02T00:00:00Z"),scan(4,"C1","DELIVERED","2026-11-04T00:00:00Z"),scan(5,"C1","CUSTOMS","2026-11-06T00:00:00Z")],{"parameters":{"combos":[{"parent":"M1","children":["C1"]}]}})
    assert [q["reason"] for q in out["quarantine"]]==["PATH_REGRESSION"]
    assert out["quarantine"][0]["_line"]==5
    # 退化的子单扫描不被静默删除：只登记隔离，原始行仍可从隔离台账追溯
    assert sorted(out["rows"][0]["_sources"])==[1,2,3,4]
    assert out["rows"][0]["delivered_at"]=="2026-11-04T00:00:00Z"
    assert out["rows"][0]["combo"]["pending_members"]==[]
def test_parent_absent_still_one_conclusion_under_parent_name():
    out=paths([scan(1,"C1","ACCEPT","2026-11-02T00:00:00Z"),scan(2,"C1","DELIVERED","2026-11-04T00:00:00Z")],{"parameters":{"combos":[{"parent":"M1","children":["C1"]}]}})
    assert len(out["rows"])==1 and out["rows"][0]["parcel"]=="M1"
    assert out["rows"][0]["combo"]["missing"]==["M1"]
    assert out["rows"][0]["combo"]["terms_from"]=="母单缺可采信扫描，沿用组合内最早收件"
def test_rerun_same_combo_is_one_batch_and_one_claim(sample):
    a=execute(sample,{"combos":COMBOS});b=execute(sample,{"combos":[{"parent":"0001","children":["0002"]}]})
    assert a["run_id"]==b["run_id"] and len(store.history())==1
    assert a["stages"][5]["metrics"]["output_records"]==7
    assert a["stages"][5]["metrics"]["expected_total"]=="0.00"
    assert len({r["parcel"] for r in a["stages"][5]["rows"]})==7
def test_rerun_with_reordered_combo_is_same_batch(sample):
    assert execute(sample,{"combos":["0001:0002,0003"]})["run_id"]==execute(sample,{"combos":["0001:0003,0002"]})["run_id"]
def test_different_combo_makes_different_batch(sample):
    assert execute(sample,{"combos":COMBOS})["run_id"]!=execute(sample,{})["run_id"]
def test_claim_stage_rejects_child_as_formal_row():
    child=scan(1,"C1","ACCEPT","2026-11-02T00:00:00Z")
    child.update(accepted_at="2026-11-02T00:00:00Z",working_hours="0",late_hours="0",expected="0.00",sla="达标")
    with pytest.raises(DomainError) as e:timely([child],{"parameters":{"combos":CHILD_COMBO}})
    assert e.value.code=="COMBINED_CHILD_LEAK"
    with pytest.raises(DomainError):settle([child],{"parameters":{"combos":CHILD_COMBO}})
def test_claim_stage_rejects_duplicate_formal_rows():
    row=scan(1,"M1","ACCEPT","2026-11-02T00:00:00Z")
    row.update(accepted_at="2026-11-02T00:00:00Z",working_hours="0",late_hours="0",expected="0.00",sla="达标")
    with pytest.raises(DomainError) as e:timely([row,dict(row)],{"parameters":{}})
    assert e.value.code=="DUPLICATE_CLOCK"
    with pytest.raises(DomainError) as e:settle([row,dict(row)],{})
    assert e.value.code=="DUPLICATE_CLAIM"
def test_combo_compensation_is_counted_once(sample):
    run=calculate(sample,{"combos":COMBOS})
    s5=run["stages"][5]
    assert s5["metrics"]["combined_units"]==1
    assert s5["metrics"]["superseded_reported"]=="0"
    assert s5["metrics"]["reported_total"]=="5.00"
    # 组合内逐成员申报不再叠加，正式结论只有母单一行
    assert sum(1 for r in s5["rows"] if r.get("combo"))==1
def test_combo_rows_reach_page(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv","parameters":{"combos":["0001:0002"]}}).get_json()
    for slug in ("paths","timeliness","compensation","archives"):
        html=client.get("/"+slug).get_data(as_text=True)
        assert "合箱裁决 · 母单统一承担" in html
        assert "母单 0001" in html and "承诺 母单" in html
def test_archive_carries_combo_basis_and_preserves_scans(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv","parameters":{"combos":["0001:0002"]}}).get_json()
    raw=client.get("/api/runs/"+p["run_id"]+"/archive").data.decode("utf-8-sig")
    rows=list(csv.reader(io.StringIO(raw)))
    combos=[r for r in rows[1:] if r[3]=="combo"]
    assert len(combos)==1
    evidence=__import__("json").loads(combos[0][6])
    assert evidence["parent"]=="0001" and evidence["children"]==["0002"]
    assert evidence["terms_from"]=="母单" and evidence["reported_from"]=="0001"
    assert evidence["deliveries"]["0002"]["source_line"]==10
    assert sorted(__import__("json").loads(combos[0][4]))==[3,4,5,6,7,8,9,10]
    # 原始扫描全部保留：采纳行与隔离行覆盖除重复/空行外的每个来源行，且互不重叠
    accepted=[__import__("json").loads(r[6]) for r in rows[1:] if r[3]=="accepted"]
    quarantine=[__import__("json").loads(r[6]) for r in rows[1:] if r[3]=="quarantine"]
    accepted_lines={line for row in accepted for line in row["_sources"]}
    quarantine_lines={line for row in quarantine for line in row["_sources"]}
    assert accepted_lines.isdisjoint(quarantine_lines)
    assert len(accepted_lines|quarantine_lines)==p["stages"][5]["metrics"]["accepted_inputs"]+p["stages"][5]["metrics"]["quarantine_inputs"]
    # 子单原始扫描仍在证据包中，可追到组合依据
    assert {7,8,9,10}<=accepted_lines
