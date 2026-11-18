import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence"])
    meta=run["manifest"]
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    # 组合依据单独成行：页面与证据包都能追到母单、子单、承诺来源与逐成员妥投时刻。
    official={str(row.get("parcel")):row for row in run["stages"][3]["rows"] if row.get("combo")}
    for unit in run["stages"][3].get("combos",[]):
        row=official.get(str(unit.get("parent")))
        lines=sorted({line for member in (row or {}).get("members",[]) for line in member.get("source_lines",[])})
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"combo",json.dumps(lines),unit.get("status",""),json.dumps(unit,ensure_ascii=False,sort_keys=True)])
    return "﻿"+stream.getvalue()
