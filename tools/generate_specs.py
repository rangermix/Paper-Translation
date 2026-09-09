"""Regenerate specifications and plans from reviewed v3 machine-readable contracts."""
from pathlib import Path
import json,csv,re
R=Path(__file__).resolve().parents[1]
reqs=json.loads((R/'contracts/requirements.json').read_text());tasks=json.loads((R/'contracts/implementation-backlog.json').read_text());gates=json.loads((R/'contracts/exit-gates.json').read_text())
phases={
'M0':dict(title='PDF 原件库与静态出版底座',goal='把PDF安全保存到单实例个人库，提供原件阅读与管理，并固定后续所有译文的静态出版契约。M0不调用翻译模型；出版能力用内部IR夹具和已知旧版种子证明。',entry='本v3约束和参考样式已经确认；能够在Docker+Compose干净环境运行测试；不得从旧原型的配对文本入口开始实现。',flow='上传PDF → 隔离有效性检查 → source_only原件条目 → 标签/收藏/预览；另外由受控内置种子/内部fixture → 校验 → 渲染 → 静态发布 → 导出。',notin='没有自动翻译、完整PDF语义解析、双语/JSON/HTML输入、账户/权限或反代。M0的新PDF不能被伪造译文标记为published。',screens=[('文档库','题名、原PDF、source_only/既有发布版、标签和收藏','不展示所有者、团队、访问权限'),('PDF上传','最多10个文件、大小、接收状态和明确错误','仅PDF；机器翻译尚未实现时必须可见'),('原件详情','真实页数、SHA、原文件、查重候选','浏览器刷新不丢服务端数据'),('静态阅读','原文后接译文、目录、字号、主题、PDF入口','内容在HTML中，无JS也可读'),('设置/运维','个人偏好、系统就绪、Compose说明','无登录设置、认证选项或反代配置')],demo='从空卷Compose启动，不创建账户；上传一份受控PDF并收藏，重建app后仍存在；原PDF字节不变。选择内置旧资料，离线导出且断网/禁JS可读。故障注入半写产物，当前版本不变；检测非PDF及文件路径攻击。'),
'M1':dict(title='真实 PDF 解析、翻译与发布',goal='把已保存PDF从真实解析带到可核验的双语静态网页；在付费调用前完成外发确认、预算、未知结果、重试和恢复机制。',entry='M0全部退出门完成，库/IR/Publisher/Compose迁移可复用；准备可控FakeProvider和有上限的真实调用测试预算。',flow='原PDF → 本地Docling → 页/块覆盖预检 → 确认来源+locale+profile+费用 → 逐unit翻译 → 结构/语义风险检查 → 必要时基础校对 → 封存并发表。',notin='OCR/加密PDF处理、其他格式、任意远程源、自动切供应商、不限次数自修复和多人权限均不实现。',screens=[('上传与原件','复用M0，批量PDF各自独立','不重新开放附件或网页入口'),('结构预检','页图、阅读顺序、块/区域覆盖、未解决问题、估价','正文缺页/扫描需求不能确认'),('翻译任务','stage、verified块/unit、请求数、actual/reserved/unknown费用','没有假百分比；断线后快照恢复'),('基础校对','源文只读、原PDF页图、目标编辑和重验','修改译文不改源；旧QA不能发布新稿'),('配置状态','profile/model/能力/价格/隐私版本','不在前端保存密钥；无Provider仍能读库')],demo='上传真实双栏PDF，确认全文覆盖与外发成本；使用已批准真实Provider完成小样本。中途重启worker和关闭浏览器，成功块不重复翻译；模拟已收费超时进入unknown且不自动重试；64→32错误被阻断、修复后生成新静态版。'),
'M2':dict(title='个人校对、多语言和版本管理',goal='将长期阅读和修订工作闭环：PDF来源定位、术语、局部候选、人工核对、多目标语言、回滚、检索与零模型模板重建。',entry='M0/M1全部退出证据有效；使用带未完成任务、旧artifact和费用预留的M1数据库快照测试升级；没有新增多人协作范围。',flow='打开已发表版 → 建草稿 → 对照PDF → 选择部分段落重译 → 比较候选 → 接受并确认 → 重验封存 → 新发布版；可新增语言、重建模板或回滚历史。',notin='实时协作、账号级同步、角色审批、更多文件格式、RAG问答、图中文字重绘和未经认证语言质量保证不在范围。',screens=[('PDF来源工作台','页码bbox、跨页高亮、机械清理与源码修订','不支持网页DOM/TXT locator；legacy不伪造'),('译文编辑器','逐段版本、保存/人工确认、QA问题、候选','候选异步返回不得覆盖当前人工修改'),('术语/记忆','个人全库与文档覆盖、词项修订、影响预览','没有组织范围或权限字段'),('版本与语言','每locale独立edition、差异、回滚、固定导出','版本不可变，模板升级不调用模型'),('全文搜索','CJK字面子串、当前已发布片段、阅读位置','无ACL过滤；仍检查当前generation和删除状态')],demo='在100段fixture仅重译2段，其余98段内容/确认记录不变；在候选运行时修改一段触发冲突。增加日语版不重解析；20篇换模板Provider调用0；A→B→A回滚generation递增；旧版离线导出和M1→M2恢复通过。')}
for m,p in phases.items():
 rr=[x for x in reqs if x['milestone']==m];tt=[x for x in tasks if x['milestone']==m];gg=[x for x in gates if x['milestone']==m]
 s=f"# {m} 产品 Spec · {p['title']}\n\n**版本3.0 · 个人PDF版 · 待实现**\n\n"
 s+=f"## 1. 产品目标与前提\n\n{p['goal']}\n\n**进入条件：**{p['entry']}\n\n本阶段只有一个使用者，不引入用户实体。规格依赖[产品基线](../00-product-baseline.md)、[共享数据契约](../shared/architecture-data.md)、[工作流和质量](../shared/workflow-quality-security.md)、[API](../shared/api-contract.md)、[Compose契约](../deployment/compose-contract.md)。\n\n"
 s+=f"## 2. 核心流程与明确排除\n\n{p['flow']}\n\n**排除范围：**{p['notin']}\n\n"
 s+='## 3. 页面及状态规格\n\n| 页面 | 必需信息与操作 | 边界 |\n|---|---|---|\n'+''.join('| '+' | '.join(x)+' |\n' for x in p['screens'])
 s+='\n输入错误留在当前页并保留有效选择；耗时操作返回job而不是锁住界面。操作完成显示真实已完成范围，失败给对应资源/错误码；不以人工按“继续演示”的结果作为正式成功。\n\n## 4. 编号需求与验收场景\n\n以下每个MUST是退出门的一部分；AT均为待执行产品测试，不是本包自检结果。\n\n'
 for q in rr:
  s+=f"### {q['id']} · {q['title']}\n\n**MUST：**{q['rule']}\n\n"
  for a in q['tests']:s+=f"**{a['id']}**（{'自动化' if a['mode']=='automated' else '自动化＋人工/环境验证'}，planned）\n\n{a['scenario']}\n\n"
 s+='## 5. 非功能、边界与失败要求\n\n'+('真实用户路径与内部fixture严格隔离。静态正文和资源字节确定，app容器重启不丢目录；失败的PDF检查不会建立成功source。\n' if m=='M0' else '延迟、费用与性能分阶段记录，不编造每篇耗时。多标签页与Worker竞争使用generation/fence；恢复不等同重新调用模型。\n')
 s+='\n没有登录不代表可以执行上传内容；PDF解析无网络/秘密且资源受限。仅支持Compose，不安排替代部署。阅读静态化不取消资源存在性和删除状态检查。配置、容量、完整性与无JS阅读要求继承产品基线。\n\n'
 s+='## 6. 退出门与可演示交付\n\n'+p['demo']+'\n\n| Gate | 名称 | 必需证据 |\n|---|---|---|\n'
 for g in gg:s+=f"| {g['id']} | {g['title']} | {g['evidence']} |\n"
 s+=f"\n全部gate初始状态not_evaluated。详见[{m} Plan]({m}-plan.md)；没有已执行证据不得标completed。\n"
 (R/f'milestones/{m}-spec.md').write_text(re.sub(r'(?<!\*)\*\*(\S(?:[^*\n]*?\S)?)\*\*(?=\S)',r'**\1** ',s))
 # Plan
 s=f"# {m} 实施 Plan · {p['title']}\n\n**版本3.0 · 对应[{m} Spec]({m}-spec.md) · 所有工作包not_started**\n\n"
 s+=f"## 1. 进入条件与实施策略\n\n{p['entry']}\n\n沿用既有设计和领域模型，先写退出测试，再按依赖实施。前端原型只提供交互参考，不将localStorage、固定译文或手动推进移植为正式后端。\n\n"
 s+='## 2. 工作包依赖总表\n\n| 工作包 | 工作内容 | 前置依赖 | 工程人日估算 |\n|---|---|---|---|\n'
 for t in tt:s+=f"| {t['id']} | {t['title']} | {', '.join(t['depends_on']) or '无'} | {t['engineering_days'][0]}–{t['engineering_days'][1]} |\n"
 total=[sum(t['engineering_days'][i] for t in tt) for i in [0,1]]
 s+=f"\n顺序相加估算为{total[0]}–{total[1]}工程人日，是包括测试/修复的规划量级，不是AI运行时间、日历工期或承诺。可并行工作按依赖图安排；原文核对、真实Provider、镜像构建与环境限制会影响实际时间。需求中的职责可由同一维护者/编码Agent执行，不要求建立多人团队。\n\n## 3. 逐包实施与完成检查\n\n"
 for t in tt:
  s+=f"### {t['id']} · {t['title']}\n\n**前置：**{', '.join(t['depends_on']) or '无'}。 **需求：**{', '.join(t['requirements'])}。\n\n**产出代码/文件位置（待实现，不是本包已提供模块）：**\n\n"+''.join(f'- `{z}`\n' for z in t['outputs'])+'\n**步骤：**\n\n'+''.join(f'{i+1}. {z}\n' for i,z in enumerate(t['steps']))
  at=[a['id'] for q in rr if q['id'] in t['requirements'] for a in q['tests']]
  s+=f"\n**完成检查：**{t['done']}\n\n**回归范围：**{', '.join(at)}。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。\n\n"
 s+='## 4. 数据迁移、故障与发布检查\n\n'
 s+=('M0从空库初始化，不创建Users或Workspace；受控旧资料只seed一次。迁移先测试空卷/已有卷/中断后重启，应用与数据库schema版本不匹配时readiness失败。\n' if m=='M0' else f'{m}先在上阶段快照上演练升级：保留原件/封存IR/产物hash，增加表而不改写历史版本。恢复先暂停外发，outcome_unknown不能当pending重发。\n')
 s+='\n每次正式候选发布需要所有本地依赖镜像就绪，Docker-only冷启成功、parser无运行期下载、单端口无反代、无身份页面/接口/数据表。环境缺失的Docker或真实模型测试标blocked，不能以YAML解析或FakeProvider代替。\n\n'
 s+='## 5. 退出演示脚本\n\n'+p['demo']+'\n\n对每个gate提供：关联需求/AT、运行环境、实际结果、证据路径、已知限制、决定。角色标签是实施职责，不是产品账号。保持不支持功能的测试为明确拒绝，而非悄悄接受。\n\n'
 s+='## 6. 编码 Agent 开始提示\n\n```text\n'
 s+=f'实施对照文库 v3 的 {m}。先完整读取 00-product-baseline.md、shared/*、deployment/compose-contract.md、milestones/{m}-spec.md 和本Plan；以最新五条用户约束为最高优先级。\n'
 s+=f'检查实际代码和上阶段证据，先为 {m} 的退出规格写自动化测试。按 contracts/implementation-backlog.json 的依赖领取工作包。\n'
 s+='只允许PDF来源；不要增加双语/IR/HTML导入，不创建用户/工作区/角色/登录，不交付反代。只支持Docker Compose且运行依赖随镜像提供。\n保留reader-v1样式和确定性出版；模型只能返回受限译文数据。失败/缺块不能假成功，外部付费调用先通过预算与外发确认。\n原型功能不等于生产实现。所有报告区分已运行、未运行和环境阻塞；禁止将mock测试当真实模型/Compose验收。\n完成一个工作包后保存代码、测试与证据再更新状态；跨包条件未满足不标完成。需要密钥或测试预算时报告精确阻塞，不跳过退出门。\n```\n'
 (R/f'milestones/{m}-plan.md').write_text(re.sub(r'(?<!\*)\*\*(\S(?:[^*\n]*?\S)?)\*\*(?=\S)',r'**\1** ',s))
# tracing from current canonical files
text='# 需求追踪矩阵 · v3\n\n65条需求、42个工作包、130个AT、24个退出门沿用编号但重新审阅。这里只表示覆盖映射，不表示测试已通过。\n\n| 需求 | 标题 | 实施工作包 | 验收场景 | 退出门 |\n|---|---|---|---|---|\n'
rows=[]
for q in reqs:
 row=[q['id'],q['title'],', '.join(t['id'] for t in tasks if q['id'] in t['requirements']),', '.join(a['id'] for a in q['tests']),', '.join(g['id'] for g in gates if q['id'] in g['requirements'])];rows.append(row);text+='| '+' | '.join(row)+' |\n'
(R/'shared/traceability.md').write_text(text)
with (R/'contracts/traceability.csv').open('w',encoding='utf-8-sig',newline='') as f:
 wr=csv.writer(f);wr.writerow(['requirement','title','tasks','tests','gates']);wr.writerows(rows)
print('Generated six phase documents and traceability')
