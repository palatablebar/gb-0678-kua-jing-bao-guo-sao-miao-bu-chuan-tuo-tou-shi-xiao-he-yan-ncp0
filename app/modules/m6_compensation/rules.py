from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError
from app.combos import normalize as normalize_combos
def evaluate(rows,context):
    context=context or {}
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    # 正式结论只对应一份：子单不得再以自身名义出现在赔付行，同一正式单元不得出现两行。
    combos=normalize_combos((context.get("parameters") or {}).get("combos"))
    children={child for combo in combos for child in combo["children"]}
    leaked=sorted({str(r.get("parcel")) for r in rows if str(r.get("parcel")) in children})
    if leaked: raise DomainError("COMBINED_CHILD_LEAK","子单已并入母单，不能单独计赔："+", ".join(leaked))
    keys=[str(r.get("parcel")) for r in rows]
    repeated=sorted({key for key in keys if keys.count(key)>1})
    if repeated: raise DomainError("DUPLICATE_CLAIM","同一正式单元只允许一份赔付结论："+", ".join(repeated))
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    if accepted & rejected: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"output_records":len(rows)}
    if intake:
        excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"]
        m.update(input=intake["input"],excluded=excluded,balanced=intake["input"]==len(accepted)+len(rejected)+excluded)
    else:m.update(input=len(accepted)+len(rejected),excluded=0,balanced=True)
    output=[]
    for row in rows:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        output.append({**row,"difference":str(expected-reported),"status":"通过" if expected==reported else "差异"})
    m.update(expected_total=str(sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))),reported_total=str(sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))),differences=sum(r["status"]=="差异" for r in output))
    superseded=[claim for row in rows for claim in ((row.get("combo") or {}).get("superseded_reported") or [])]
    m["combined_units"]=sum(r.get("combo") is not None for r in rows)
    m["superseded_reported"]=str(sum((Decimal(str(claim.get("reported","0"))) for claim in superseded),Decimal(0)))
    return {"rows":output,"quarantine":[],"metrics":m}
