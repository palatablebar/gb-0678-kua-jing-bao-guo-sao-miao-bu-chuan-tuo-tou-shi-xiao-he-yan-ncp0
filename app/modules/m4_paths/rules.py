"""路径裁决：先按物理包裹重建扫描路径，再按合箱关系归并为正式单元。

裁决口径：正式时效由母单统一承担。
- 一个母单及其子单只产出一条正式结论，子单不再单独成行，因此不会同时出现
  “母单待妥投、子单缺收件”两份并行结论。
- 组合开始取母单有效收件；母单缺少可采信收件时退回组合内最早收件，
  两者都记录依据。组合完成要求每个有采信扫描的成员都有不早于组合开始的
  有效妥投，组合妥投取各成员妥投中最晚一次；任一成员未妥投则整单待妥投，
  只保留一份结论，不按成员拆成多份。
- 商业承诺（时限、保价、申报）取母单收件扫描；母单缺少可采信扫描时退回
  组合内最早收件并记录依据，绝不因此另起一份子单结论。
- 成员扫描仍全部保留在 _sources、members 与隔离台账中；隔离只登记原因，
  不删除原始行。子单此前的申报额登记为 superseded_reported，不重复计赔。
"""
from decimal import Decimal
from app.values import instant
from app.reasons import reject,sources
from app.combos import normalize as normalize_combos
PRIORITY={"ACCEPT":0,"DEPART":1,"CUSTOMS":2,"DELIVERED":3}
def _event_key(row): return (instant(row["event_utc"]),PRIORITY[row["node"]],str(row["scan_id"]))
def _parcel_path(events):
    """单个物理包裹的路径重建；隔离只登记原因，不删除原始扫描。"""
    ordered=sorted(events,key=_event_key)
    seen={};valid=[];bad=[];last=-1
    for e in ordered:
        time=e["event_utc"]
        if time in seen and seen[time]!=e["node"]:bad.append(reject(e,"SIMULTANEOUS_CONFLICT","同刻扫描节点冲突"));continue
        seen[time]=e["node"]
        if PRIORITY[e["node"]]<last:bad.append(reject(e,"PATH_REGRESSION","扫描路径倒退"));continue
        last=PRIORITY[e["node"]];valid.append(e)
    return valid,bad
def _first(events,node):
    return min((e for e in events if e["node"]==node),key=_event_key,default=None)
def _reported(events):
    delivery=_first(events,"DELIVERED")
    return (delivery or min(events,key=_event_key))["reported"]
def _line_set(events): return sorted({line for e in events for line in sources(e)})
def _conflicts(terms,members):
    """子单与母单承诺不一致的字段，留在组合依据里供复核。"""
    conflicts=[]
    for parcel,events in sorted(members.items()):
        if not events:continue
        row=min(events,key=_event_key)
        changed={key:[str(row.get(key)),str(terms.get(key))] for key in ("destination","promised_hours","declared_value") if str(row.get(key))!=str(terms.get(key))}
        if changed:conflicts.append({"parcel":parcel,"fields":changed})
    return conflicts
def evaluate(rows,context):
    context=context or {}
    combos=normalize_combos((context.get("parameters") or {}).get("combos"))
    parent_of={};children_of={}
    for combo in combos:
        children_of[combo["parent"]]=combo["children"]
        for child in combo["children"]:parent_of[child]=combo["parent"]
    rebuilt={}
    for row in rows:rebuilt.setdefault(row["parcel"],[]).append(row)
    for parcel,events in list(rebuilt.items()):
        valid,bad=_parcel_path(events);rebuilt[parcel]={"valid":valid,"bad":bad}
    quarantined={str(row.get("parcel")) for row in context.get("quarantine") or [] if isinstance(row,dict) and row.get("parcel")}
    good=[];bad=[];units=[];superseded_total=Decimal(0)
    # 正式单元只出现一次：母单及其子单归入母单，子单不再单独产出结论。
    # 组合完全未出现在输入中时也登记一行“组合依据”，避免关系被静默丢弃。
    bearers=sorted(({p for p in rebuilt if p not in parent_of})|set(children_of))
    for bearer in bearers:
        declared=children_of.get(bearer,[])
        present=[p for p in [bearer]+declared if p in rebuilt]
        for p in present:bad.extend(rebuilt[p]["bad"])
        members={p:rebuilt[p]["valid"] for p in present}
        valid=[e for p in present for e in members[p]]
        unresolved=[p for p in [bearer]+declared if p not in rebuilt and p in quarantined]
        missing=[p for p in [bearer]+declared if p not in rebuilt and p not in quarantined]
        if not valid:
            if bearer in children_of:
                units.append({"parent":bearer,"children":declared,"present":present,"missing":missing,"unresolved":unresolved,"status":"无采信扫描"})
            continue
        accepts=[e for e in valid if e["node"]=="ACCEPT"]
        if not accepts:
            bad.extend(reject(e,"MISSING_ACCEPT","缺少收件扫描") for e in valid)
            if bearer in children_of:
                units.append({"parent":bearer,"children":declared,"present":present,"missing":missing,"unresolved":unresolved,"status":"缺收件扫描"})
            continue
        accepted=min(accepts,key=_event_key)
        mother=members.get(bearer,[])
        # 客户只认母单的一份承诺：起算、时限与保价都以母单收件扫描为准。
        mother_accept=_first(mother,"ACCEPT") if mother else None
        if bearer in children_of and mother_accept:terms,terms_from,start_scan=mother_accept,"母单",mother_accept
        elif bearer in children_of:terms,terms_from,start_scan=accepted,"母单缺可采信扫描，沿用组合内最早收件",accepted
        else:terms,terms_from,start_scan=accepted,"本包裹",accepted
        start=instant(start_scan["event_utc"])
        per_member={};pending=[]
        for p in present:
            deliveries=[e for e in members[p] if e["node"]=="DELIVERED" and instant(e["event_utc"])>=start]
            if deliveries:per_member[p]=min(deliveries,key=_event_key)
            elif members[p]:pending.append(p)
        pending=sorted(set(pending)|set(missing)|set(unresolved))
        # 子单缺收件/缺妥投只作为组合内证据登记，不另起一份子单结论。
        incomplete=[{"parcel":p,"missing":[node for node in ("ACCEPT","DELIVERED") if not _first(members[p],node)]} for p in present if members[p] and (not _first(members[p],"ACCEPT") or not _first(members[p],"DELIVERED"))]
        # 同一时刻多成员妥投时以母单顺序靠前者为来源，保证重跑结论稳定。
        delivered=max(per_member.values(),key=lambda e:(instant(e["event_utc"]),-present.index(e["parcel"]))) if per_member and not pending else None
        reported_source=bearer if (bearer in children_of and mother) else terms["parcel"]
        superseded=[]
        for p in present:
            if p==reported_source or not members[p]:continue
            amount=_reported(members[p]);superseded.append({"parcel":p,"reported":amount});superseded_total+=Decimal(amount)
        evidence=[]
        for p in present:
            events=members[p]
            accept=_first(events,"ACCEPT");delivery=_first(events,"DELIVERED")
            state="（无采信扫描）" if not events else ("缺收件" if not accept else ("已妥投" if delivery else "待妥投"))
            evidence.append({"parcel":p,"role":"母单" if p==bearer else "子单","scan_ids":[str(e["scan_id"]) for e in events],"source_lines":_line_set(events),"path":" → ".join(e["node"] for e in events) if events else "（无采信扫描）","accepted_at":accept["event_utc"] if accept else None,"delivered_at":delivery["event_utc"] if delivery else None,"status":state})
        combo=None
        if bearer in children_of:
            combo={"parent":bearer,"children":declared,"present":present,"missing":missing,"unresolved":unresolved,"incomplete":incomplete,"parent_scanned":bool(mother),"terms_from":terms_from,"reported_from":reported_source,"accepted_from":start_scan["parcel"],"delivered_from":delivered["parcel"] if delivered else None,"delivery_state":"已妥投" if delivered else "待妥投","pending_members":pending,"deliveries":{p:{"at":e["event_utc"],"source_line":e.get("_line")} for p,e in sorted(per_member.items())},"conflicts":_conflicts(terms,members),"superseded_reported":superseded}
            units.append({**combo,"status":"已归并"})
        # 单件保持原有路径写法；合箱时把每个成员的路径并排展示，便于核对组合依据。
        path=evidence[0]["path"] if len(evidence)==1 else " ｜ ".join(f'{m["parcel"]} {m["path"]}' for m in evidence)
        # 正式行与起算使用同一扫描为身份：母单有收件时取母单收件，
        # 否则取组合内最早收件。商业字段整体取母单承诺，成员证据另列。
        official={**start_scan,"parcel":bearer,"destination":terms["destination"],"zone":terms["zone"],"promised_hours":terms["promised_hours"],"declared_value":terms["declared_value"],"_sources":_line_set(valid),"accepted_at":start_scan["event_utc"],"delivered_at":delivered["event_utc"] if delivered else None,"delivery_uploaded_at":delivered["received_utc"] if delivered else None,"scan_count":len(valid),"path":path,"reported":_reported(members[reported_source]),"role":"母单" if bearer in children_of else "单件","members_display":", ".join(m["parcel"] for m in evidence),"members":evidence,"terms_from":terms_from,"combo":combo}
        good.append(official)
    return {"rows":good,"quarantine":bad,"combos":units,"metrics":{"parcels":len(good),"delivered":sum(r["delivered_at"] is not None for r in good),"path_errors":len(bad),"combos":len(children_of),"combined_children":sum(1 for p in parent_of if p in rebuilt),"combined_units":sum(r.get("combo") is not None for r in good),"superseded_reported":str(superseded_total)}}
