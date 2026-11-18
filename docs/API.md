# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。`/api/runs`使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。路径阶段额外返回`combos`组合依据，含母单/子单、承诺与申报来源、逐成员妥投时刻、待妥投与未导入成员。`/api/upload`接收multipart文件file，可附`combos`表单字段（每行`母单:子单,子单`或JSON）。`/api/runs/<id>/archive`只导出一份带清单与证据的CSV，`kind=combo`行给出组合依据。
