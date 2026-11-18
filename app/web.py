from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app import store
COLUMNS=[['scan_id', 'parcel', 'node', 'event_time', 'received_time'], ['scan_id', 'parcel', 'node', 'destination', 'zone'], ['scan_id', 'parcel', 'node', 'event_utc', 'received_utc', 'upload_lag_hours'], ['parcel', 'role', 'members_display', 'accepted_at', 'delivered_at', 'scan_count', 'path'], ['parcel', 'role', 'members_display', 'working_hours', 'promised_hours', 'late_hours', 'expected', 'sla'], ['parcel', 'role', 'members_display', 'expected', 'reported', 'difference', 'status'], ['parcel', 'role', 'members_display', 'delivered_at', 'sla', 'expected', 'status']]
LABELS={'scan_id': '扫描号', 'parcel': '包裹号', 'node': '节点', 'event_time': '发生时间', 'received_time': '上传时间', 'destination': '目的地', 'zone': '时区', 'event_utc': '发生 UTC', 'received_utc': '上传 UTC', 'upload_lag_hours': '补传时差 / h', 'accepted_at': '收件 UTC', 'delivered_at': '妥投 UTC', 'delivery_uploaded_at': '妥投上传 UTC', 'scan_count': '扫描数', 'path': '节点路径', 'working_hours': '计时 / h', 'promised_hours': '承诺 / h', 'late_hours': '超时 / h', 'expected': '赔付 / 元', 'sla': '时效结论', 'reported': '申报 / 元', 'difference': '差额 / 元', 'status': '对账结论', 'accepted': '采纳扫描', 'late_uploads': '迟到上传', 'parcels': '包裹数', 'late_parcels': '超时包裹', 'compensation': '赔付合计', 'delivered': '妥投数', 'path_errors': '路径异常', 'records': '归档数', 'source_lines': '源行数', 'sha256': '摘要', 'ready': '可归档', 'differences': '差异数',
 'accepted_inputs': '采纳来源行', 'quarantine_inputs': '隔离来源行', 'output_records': '结果记录', 'input': '输入行', 'excluded': '排除行', 'balanced': '行数平衡', 'expected_total': '预期合计', 'reported_total': '申报合计', 'differences': '差异项', 'blank': '空行', 'repeated_headers': '分段表头', 'encoding': '编码', 'duplicate': '重复行', 'quarantine': '隔离行', 'accepted': '采纳行', 'sha256': '校验摘要',
 'role': '正式角色', 'members_display': '组合成员', 'combos': '合箱组合', 'combined_children': '已并入子单', 'combined_units': '已归并单元', 'superseded_reported': '已归并申报 / 元', 'claim_basis': '计赔口径'}
def combo_basis(row):
    """把组合依据压成一行：页面与证据包都能追到同一份正式结论。"""
    combo=row.get("combo")
    if not combo:return ""
    parts=[f'母单 {combo["parent"]}',f'子单 {", ".join(combo["children"])}',f'承诺 {combo["terms_from"]}',f'申报来源 {combo["reported_from"]}',f'收件来源 {combo["accepted_from"]}']
    parts.append(f'妥投来源 {combo["delivered_from"]}' if combo.get("delivered_from") else "组合待妥投")
    if combo.get("pending_members"):parts.append(f'待妥投 {" / ".join(combo["pending_members"])}')
    if combo.get("incomplete"):parts.append("成员缺节点 " + " / ".join(f'{c["parcel"]} 缺{",".join(c["missing"])}' for c in combo["incomplete"]))
    if combo.get("missing"):parts.append(f'未导入 {" / ".join(combo["missing"])}')
    if combo.get("unresolved"):parts.append(f'已隔离 {" / ".join(combo["unresolved"])}')
    if combo.get("superseded_reported"):parts.append("子单申报 " + " / ".join(f'{c["parcel"]} {c["reported"]}' for c in combo["superseded_reported"]))
    if combo.get("conflicts"):parts.append("承诺差异 " + " / ".join(f'{c["parcel"]} {",".join(c["fields"])}' for c in combo["conflicts"]))
    return "；".join(parts)
def combo_text(parameters):
    """把已生效的组合声明还原成表单文本，页面可直接核对与重算。"""
    combos=(parameters or {}).get("combos") or []
    if isinstance(combos,dict):
        return "\n".join(f"{parent}:{','.join(children) if isinstance(children,list) else children}" for parent,children in combos.items())
    return "\n".join(f'{c["parent"]}:{",".join(c["children"])}' for c in combos)
def register_pages(app):
    def page(index):
        run=store.latest() or execute(load_sample("dirty.csv"))
        stage=run["stages"][index]
        rows=[{**row,"combo_basis":combo_basis(row)} for row in stage["rows"]]
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=rows,columns=COLUMNS[index][:12],history=store.history(),labels=LABELS,combos=run["stages"][3].get("combos",[]),combo_text=combo_text(run.get("parameters")))
    app.add_url_rule("/",view_func=lambda:page(4))
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))
