<!-- checkpoint016 2026-10-07T22:20:22.796360+00:00 -->
最新恢复入口为 `checkpoints/CHECKPOINT_016_INTEGRATED.json`。完整目标 active，未完成。独立科学字段快照246/336；F3/F5两实际父进程仍运行，F7等待真正父进程释放。

历史118原因索引forwardv3已实际闭合不可变输入；F4 same/coarse/half各9原生帧观测与端帧独立解码完成，full2401无损归档完成；F6刚体CSV旋转约定仍UNKNOWN，不能消费旧quaternion作为已验证姿态。F2fine完整4秒实际801帧/20.23GB，175位置排除对应0.519%初质量，超过0.3%未知宽度，影响待定位。

Nativev4原始401帧重建→全帧typed对照→标签已实际启动，占用额外重I/O槽；v24 metadata probe修正root重复解释器argv后actual002因C49迁移目标被自身来源URI误判而失败；v23/C47与v24/C48/C49原失败保留，consumer继续forwardv25。以收据和PID/start_ticks为准，不从prepared/emptyreservation推断完成。

三个既有代理继续完整内部raw包、参考研究和遗漏影响/有界staticMK；未启动static59批或F7。原预算/期限/Home≥500GiB不重置，不运行模型、不公开发布。以下为历史记录。

<!-- checkpoint015 2026-10-07T21:46:02.186482+00:00 -->
最新恢复入口为 `checkpoints/CHECKPOINT_015_INTEGRATED.json`。完整目标 active，未完成。独立科学字段快照233/336（F1/F2/F4/F6各48，F3=21、F5=20）；F3/F5父进程的PID/start_ticks已核验，F7等待真实科学槽释放。

历史118例原生原因精确覆盖完成（F2=48、F4=22、F6=48），质量与物理去向/动力学信用分开。C41旧index实际53，旧checkpoint014的70应为72；新union003最终118。C44索引使用了两个正在变化的F3/F5批次收据，须forward不可变快照，不能用旧hash声称长期可重放。旧报告保留。

全336 effective lineage v15实际完成，286例GenCase输入与finish闭包完整，50未知；332例solver完整，4历史running缺finish。七cards仍PROVISIONAL_NOT_SPLIT_SAFE，科学资格未知。

F4原dp0实际SaveDt同/半CFL都完成2401原生帧。半CFL出现1384次DtMin钳制（同CFL为0），实际时间步不能直接视为严格减半；两者报告steps比日志行数多1，源码约定待核。查询[0,1.2]覆盖，半CFL最终时刻早于原始终点；没有积分/输出误差或收敛信用。

F2迁移v20实际C42失败保留；v21实际完整复制成功，metadata预审因C43 CURRENT生产者绑定与迁移目标关联未闭合而失败，401帧未读取。额外I/O槽已空闲，先等consumer forwardv22并跑真实copy+401+OStrace，再安排有界staticperMK、F4全窗losslessroundtrip或nativev2原生重建。Nativev2已集成且6项制造测试通过，完整源码闭包/逐帧对照准备中，未启动。

三个既有代理继续：consumer做v22及rawv2，reference做实际14研究状态与真实SaveDt语义/observer准备，forensics做不可变118索引、boundedcase staticMK与刚体标签。原预算/期限/500GiB下限不重置，无模型、无公开发布。下方是历史记录。

## 2026-10-07T21:17:03.764431+00:00：224例独立审计、336来源索引与F4真实成本

最新恢复入口为 `checkpoints/CHECKPOINT_014_INTEGRATED.json`，完整目标 active、未完成。独立字段快照224/336（F1/F2/F4/F6各48、F3=17、F5=15）；F3/F5两科学父进程已核对PID/start_ticks仍运行，F7等实际名额释放。

336例v14来源索引与七cards已实际guard完成并复制核验，但C35/C36/C37/C39使划分仍provisional；v15真实case210已修复来源接口并完成guard，不能外推其他335。v20搬迁mtime修复28测试通过，完整真实复制+401帧离线重放及OS openat审计待就绪请求；raw→typed→label完整产品仍未完成。

F4剩余19例46流体ID原生密度排除已独立核对；历史118目前根验证native case union70，余46 F6继续。新F4成本试验实际2401帧、3.40GiB、12.47GPU秒、零排除，覆盖0..1.2查询；末帧较原CURRENT末帧短23微秒，禁止外推。额外I/O槽已释放。四新F2粗GenCase质量全部硬失败，历史runner终态少算~2KB/例记录侧车，后续必须v4。

下一步：真实便携重放与最小336来源v15、F6原因台账、14匹配参考的空间/积分/输出误差、静态perMK分母、有效划分/七cards/无模型evaluator/完整内部包。Home空闲约753GiB，500GiB底线、累计父预算和2026-10-14截止不重置；Q-N/Q-E未知。以下历史记录保留。

## 2026-10-07T20:37:33.306126+00:00：200例独立字段审计、严格物理时间查询与118历史遗漏映射

最新恢复入口为 `checkpoints/CHECKPOINT_013_INTEGRATED.json`，完整目标 active、未完成。独立快照200/336；F1/F2/F4/F6各48、F3=7、F5=1。F1实际48完成且进程退出，名额已交F5；F3/F5实际各一worker继续，F7的48新v4请求等待真实名额释放。实时completed可高于独立快照，以JSON区分。

真实F2 coarse401/264357的0/1/2/3/4秒查询v4完成，动态九帧括号、输入H5 pre/post SHA、终态85101B一致；五种非法查询及两种canonical绑定篡改反例拒绝。连续盒质量18.876kg与离散源目标21.114kg明确分开。只是接口/结构信用，未赋QI/QN/QE。

新8+4 actual GenCase独立复核：F4 coarse .0123、F7 fine .01656、F2 fine .00855达到总质量1%准备目标；F2 fine .00855各源wholeinitial误差小于.03。但空间/积分/输出误差及实际科学资格仍未知，旧coarse材料不匹配保持失败，不重标质量、不放宽预算。

历史118精确成员来自E00007，旧转换路径/SHA与当前字段计数匹配；51个native join证据已索引，剩余F4=19/F6=46继续定位。26个F4 zero-native controls不属于历史118。13个MK分母目前仅producer metadata+scanner总质量一致，独立静态H5分组及历史导入库绑定尚未闭合。336小文件谱系已真实guard复跑，仍需修正GenCase输入/输出角色、控制CLI内容、recovery与七cards证据路径。portable16四测试仅小源迁移，完整离线重放待forward17。

336/118/14完整参考终态、合格标签、有效划分、七实质cards、无模型evaluator和完整内部重放包仍是必要交付；既有预算/期限不重置。以下历史检查点保持原记录。

## 2026-10-07T20:15:02.308464+00:00：191例独立审计、完整typed终态与净通量修正

最新恢复入口为 `checkpoints/CHECKPOINT_012_INTEGRATED.json`，完整目标active、未完成。独立快照191例：F2/F4/F6各48、F1=42、F3=5；以proof008实际JSON计数为准，前一提交标题190是文字计数疏漏。F1/F3实际一worker继续，F5/F7各48新v4请求已准备但未启动，在真实科学槽释放后接续。

v16 primary实际8测试PASS、正确总净通量区间[13.57200064463541,13.575000644777901]kg，原full401报告保持SHA/字节；只修正exactF2诊断半空间端点总量，gross/hiddenrecross未知。coarse401帧typed转换实际completed，H5685291008B，264357粒子/10692初始fluid/10681末帧fluid；完整405raw文件currentdigest与producer pre/post一致，终态tree/receipt/charge685731976B一致，预约释放。

C28：该coarse各材料初质量偏差−3.766%/−3.766%/+9.981%，总初质量1%通过掩盖第三材料占wholefluid差>.03；不能作为materialmatched reference。C29：原H5 inheritedcondition文字保留，forward控制/条件摘要待闭合。9项v2GenCase独立核对6totalmasspass/3hard；新per-source3%诊断不能替代已冻结wholeinitialtaskbudget。新queryv1预审发现nestedtime_values_s/未绑定H5content门禁，未启动，交新v2制造H5实际接口验证后再primary读取。

336/118/14实际参考终态/有效物理划分/七cards/无模型evaluator/完整内部可迁移重放均仍是必要完成条件，既有预算/期限不重置。以下历史检查点保留。

## 2026-10-07T20:07:49.304400+00:00：173例独立审计、完整回放与新转换启动

恢复入口为 `checkpoints/CHECKPOINT_011_INTEGRATED.json`，完整目标active、未完成。独立快照173例（F2/F4/F6各48、F1=29），字段/身份/来源完整性信用，不代表动力学或QN/QE。F6真实48/48 completed且父进程退出，F3已接续新v4一worker；F1继续，以实际PID/start_ticks及收据为准。

v15实际full401/21114回放completed、25测试PASS，冻结质量21.114001002861187kg，源H5pre/post SHA相同，finaltree/receipt/charge62410433B相同。结果C26净通量总区间漏已知13.572kg贡献，C27残留v14冲突字段；新forward sidecar待primary核对，原报告保留，任务产品仍未验收。ROT090=.9秒、实际rotation.5..1.4秒/table0..4秒为唯一正确解释。

新增14实际native joins/typed mass screens共319position exclusion IDs独立核对；物理去向/动力学未知，perMK分母仍typed total按source count分配，uniform质量假设待来源闭合。12massfit实测3pass/5marginal/4hard，不放宽1%。这12旧v2终态实际目录比历史计费多51178B，均在预约内；旧证据不改，后续v4。

coarse完整401帧转换经actual v4 importer/真实smallparse通过后启动PID1212281/start_ticks218667718，实际输出 `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_FULL_CFD_CANARY_DP01258_T4_TYPED_FULL401_V4/f2_s1_full_cfd_canary_dp01258_t4_typed_full401-v4-primary-001`；CPU2/wall7200/disk16GiB，共享v4，尚未授予科学资格。先检查实际terminal再登记common-query reader，不重复启动。

继续336/118/14参考终态/有效条件划分/七cards/无模型evaluator/完整便携内部重放全部目标，原预算与期限不重置。以下历史记录保留。

最新语义纠正：`checkpoints/F2_CONTROL_SEMANTICS_CORRECTION_001.json` 核对历史solver绑定metadata，ROT090代表0.90秒转动时长，末角-105°；源控制一致，先前“角度命名冲突”解释撤回。实际转动0.5..1.4秒，与motion表/XML覆盖0..4秒分别记录。旧代码/收据/检查点保留，新v15使用正确语义；coarse已匹配真实曲线，无须重跑CFD。

## 2026-10-07T19:43:16.132667+00:00：真实完整CFD产物、首帧cohort与完整回放接口修复

恢复入口为 `checkpoints/CHECKPOINT_010_INTEGRATED.json`，目标active、未完成。独立字段审计快照139例（F2=48、F4=48、F6=41、F1=2），实际F1/F6两单worker继续，以PID/start_ticks与新收据为准。F4剩余24已completed，释放槽已由F1接续；F3/F5/F7仍在就绪队列。

Forward-only共享v4终态存储检查已独立证实finalreceipt、实际目录与ledgercharge相等，边界超预约拒绝并释放；另3项实际lifecycle测试通过。旧v2/v3与消费过的代码/测试保留。新任务使用v4和实测充分预约。

F4–F7新增24GenCase均终态完成，但仅12档初始质量在1%内（含8原档），12档超过2%硬失败，必须继续质量兼容粒距，不放宽阈值。28原生文件在14哨点上的gzip独立解压SHA/字节均匹配，259818202B→66595695B；只证明这28份无损，不代表整campaign存储上界。

F2-S1新dp=.01258已真实完成完整401帧CFD，0..4.000064985853619秒，GPU64.816709秒，最终4665670874B，实际GPU2 UUIDlease、源pre/post哈希、finalbyte charge/release已核对。Fluid10692→10681，11位置排除；RunPARTs给每保存窗口dtmin/max与DTsMin=0，非完整逐step序列。待newowner绑定完整typed转换/审计，科学资格UNKNOWN。源案例名ROT090但实际历史solver启动/结束相同SHA的motion末角-105°；连续匹配使用实际控制，保留冲突。

v13实际guard17源probe与真实H5首帧核对，全部21114fluid/21.114001002861187kg/MK各7038保留，nominalbox19734/1380仅诊断。v14已集成身份/质量关联连续residence与profile绑定evaluator，primary实际20测试PASS；真实full401请求失败，因为native末帧4.000007783879406略晚motion终点4秒。v15必须核对official movement finish后保持末端位姿的语义，保留全部401原时间戳，超出活动控制覆盖仍拒绝；禁止截帧、修改源或无条件外推。

新增5native joins共92位置排除ID及MK/XMLmassscreen已核对，UNKNOWN物理去向/动力学不变；实际typed/perMK冻结分母与任务影响区间待enrichment。三个代理持续推进v15/336语义与portable、native全118、coarse完整typed/14最小study成本与hardmass/F5。整体336/14参考终态/任务标签/划分/七cards/无模型evaluator/内部可迁移重放产品均仍是完成条件。以下为历史记录。

新增资源反例：`checkpoints/TERMINAL_STORAGE_V3_INDEPENDENT_VERIFICATION_001.json` 在真实父guard下、独立fixture中核对32B子worker与最终receipt增长；v3仍完成但最终目录超预约。新v4修复/实际精确字节证明待主进程集成，旧v2/v3不改。

新增实际旁路证据：`checkpoints/CONSUMER_V12_RECEIVER_VERIFICATION_001.json` 经primary sharedguard复现outside/outside线段穿过receiver仍被标为right_censored；C25由source review升级为实际制造接口反例。新v13修复中；不改变旧v12或checkpoint009字节。

## 2026-10-07T19:09:39.423706+00:00：122例审计与实际来源cohort反例

最新协调入口为 `checkpoints/CHECKPOINT_009_INTEGRATED.json`，目标active、未完成。完整保存时序审计独立核对122例，F2=48、F4=41、F6=33；真实F4/F6仍各一worker，实时增量以收据与PID/start_ticks为准。其余家族在真正I/O槽释放后启动，不重复已完成任务。

v12源码/runner/probe/portable入口已集成，primary sharedguard实际17源hash/stat验证与12制造轨迹测试通过。但已绑定初始CSV转float32后，exact nominal source box仅选19734/21114 fluid，漏1380；MK1/2/3各7038，实际xmax=.379999995>nominal.375，zmin=.699999988<.7。v12实际cohort接口拒绝，完整H5未读、不授予资格。新v13须按真实初始ID/type/MK来源定义cohort，记录格点/浮点偏差，保留21.114001002861187kg原分母。见 `CONSUMER_V12_INTEGRATION_REVIEW_001.json`。

有限receiver首次经过还需校准outside/outside线段穿过box与此前invalid帧后的首次事件未知语义；无模型evaluator需真实receiver/aperture、exact身份及质量权重，不把halfspace诊断当接收器任务完成。336来源XML枚举与七cards仍草稿，物理/控制/几何/支持/恢复语义闭合待完成。

Forward-only v3 terminal guard已在forensics分支提交，尚待主进程核对实际目录字节含finalreceipt增长的边界证据；旧v2和活扫描继续。reference推进成本正确的新GenCase、质量匹配间距、其他8哨点来源准备与lossless成本canary。三个代理继续实现，主进程负责集成/方向/预算/独立验证。完整336审计、14科学参考终态、标签/划分及可重放内部产品仍为整体完成条件。以下为历史记录。

## 2026-10-07T19:00:11.963408+00:00：117例审计、真实来源修正与反例

恢复入口为 `checkpoints/CHECKPOINT_008_INTEGRATED.json`；目标仍active、未完成。已验证117个distinct CURRENT完整保存时序审计：F2=48、F4=38、F6=31。F4/F6两个parent PID/start_ticks仍活，每batch一worker，两重I/O槽；其余四族队列在真实槽释放后执行。

已核对F2-S1 exact native ledger，位置排除3-ID403829(frame154)、397194/404024(frame207)，与scan/native CSV/实际receipt hash一致。消费者旧“UNAVAILABLE_EXACT_CASE”声明是索引未定位，不能冒充原生证据不可得；v12应绑定账本，并保留未知物理去向/动力学影响。见 `F2_S1_NATIVE_LEDGER_VERIFICATION_001.json`。另新增071..075五例89个位置排除ID，见 `NATIVE_OMISSION_VERIFICATION_004.json`。

五哨点15GenCase inputs/原树与集成树/实际receipt来源已核对，9档初始mass在1%内（包括5个原粒距档）、2档1-2%、4档>2%硬失败，不能认为五三档研究已通过。F3 v1两哨点错误共用forcing CSV；真实solver分别a4afb8a9...与9a776c1c...，新v2按各自exact solver input digest生成。初态几何生成成功不等于实际forcing匹配。见 `REFERENCE_PREPARATION_VERIFICATION_004/005.json`。

v11开发代码与336 metadata枚举/七cards草稿已集成，但真实H5请求未放行。primary sharedguard实际复现：(1)多缺失段净通量界漏真值；(2)全current mass NaN时未知界错误为0；(3)速度/动能/前沿严重错误仍evaluator PASS。v11 probe还默认跳过实际source hash/stat交叉核对；time/output科学误差份额混为运行成本。新v12补反例、真实receiver3D/aperture任务、冻结物理尺度和实际迁移/runner入口。语义lineage closure仍待完成，不把cards草稿当最终交付。见 `CONSUMER_V11_INTEGRATION_REVIEW_001.json`。

GenCase新F3S2 original001实际38,807,949B超过16MiB预约，binary返回0却guard failed；另11个v1与5个v2短任务也超预约但未被终态检查捕获。旧v2 runtime只有周期检查、没有terminal bound检查；历史bytes/receipts保留。forensics代理负责新入口forward-only修复及快速假worker反例；reference代理按实测全输出/复制forcing成本登记新attempt。现有F4/F6请求预约足够且继续，不重启/不改活代码。

14实际参考研究、336原因/范围、真实标签及有效条件划分、七完整cards与可重放便携产品仍全部属于完成条件。禁止用单个checkpoint、通过制造反例或预检代替科学验收。以下为历史记录。

## 2026-10-07T18:45:22.237014+00:00：同步长期目标，109例审计与新初态证据

当前目标入口为 `../GOAL_STAGE2_ZH.md`，同步应用中已登记的第二阶段目标；`../GOAL_ZH.md` 保留首阶段历史文本。审阅材料作为设计证据，不独立授予资源或执行权限。恢复先读 `checkpoints/CHECKPOINT_007_INTEGRATED.json`，再检查真实PID/start_ticks、批次收据和累计ledger。

独立核对109个distinct CURRENT完整保存时序审计（F2=48、F4=35、F6=26）。F4/F6真实parent仍存活，每batch一个worker、全局两重I/O槽；四个其他家族的队列等待实际槽位释放。动态进度以实际收据为准。

F2-S1粗档dp=.01258实际GenCase的10692个流体粒子，初始质量21.286334054304kg，偏差+0.8162075%，通过已定1%初始质量门；dp=.01236失败保留。连续Def除登记dp/CFL/运动文件名外相同，motion字节相同。该证据不代表三网格、时间/保存误差或QN已通过。14来源资源matrix中的.005秒方案约399.96GiB，仍超过Home500GiB下限之上的新增余量；还不是空间新增/时间双运行的完整上界。继续其他13哨点实际准备和固定任务采样研究。

新增两批12例native joins已核对，共251个位置排除ID（059..064为138，065..070为113）；物理去向与动力学影响UNKNOWN。见 `NATIVE_OMISSION_VERIFICATION_002/003.json`。继续全覆盖与确切F2-S1账本索引。

v10已集成为保留的开发版本，但实际请求把3个后期丢失ID质量重复加入初始分母，还存在validmask、质量加权停留、净通量未知量与区域语义问题。实际H5请求未放行，详见 `CONSUMER_V10_INTEGRATION_REVIEW_001.json`，消费者分支在新v11修复。禁止修改旧版本或把prefix制造检查当完整任务科学资格。

三个原子代理继续实现，主进程负责资源/集成/独立复核。336审计、14参考、真实标签与划分、七cards及便携内部产品仍是完成条件；目标active、未完成。以下为历史时间戳记录。

## 2026-10-07T18:29:39.435605+00:00：v9 开发旁路保留，均速错误待新版本修复

最新主分支已保留 v9 的源绑定 F2 宏与 F6 FloatingInfo 接口、质量分布/SO(3)制造证据；34个输入的原工作树/集成树 SHA 与实际guard launch/end一致。该接口仍不具备真实参考资格。主进程发现质量加权均速缺少总质量除法，以及位置body-frame/速度world-frame标识风险；详见 `checkpoints/CONSUMER_V9_INTEGRATION_REVIEW_001.json`。由消费者分支在新版本修复并补独立非单位质量、整体质量缩放与跨括号重复反例。不得将旧v9均速用于科学比较，也不得修改已消费字节。

全局可恢复状态仍以 `checkpoints/CHECKPOINT_006_INTEGRATED.json` 和运行中的实际F4/F6 receipts为准；F2粗档mass不匹配、其余真实标签/14参考/泄漏审阅/七cards/便携包工作继续。

## 2026-10-07T18:25:55.953841+00:00：观测接口集成、初始质量失配与精确边界证据

`checkpoints/CHECKPOINT_006_INTEGRATED.json` 是最新协调入口。独立核对了 101 个 CURRENT 全保存时序字段审计（F2=48、F4=31、F6=22）；F4/F6 两个 batch parent PID/start_ticks 仍存活，进度继续以实时收据为准。F1/F3/F5/F7 准备队列在真实 I/O 槽位释放后启动。

v5–v8 的 4 个实际 guard 输入字节在来源树与集成树完全一致，primary guarded 13 项测试通过。该信用只覆盖开发接口、制造观测和迁移检查，真实粒子分布/冻结物理尺度/标签与数值资格仍待完成。见 `CONSUMER_V8_DELIVERY_VERIFICATION_001.json` 和 `INTEGRATION_RESULT_004.json`。

F2-S1 新 coarse dp=.0125 的实际 GenCase 初始流体质量 22.04296875kg，比 dp0=21.114kg 高约4.40%，超过初始质量2%上界，不进入匹配三网格研究；fine dp=.008 为+0.4213%。已委派质量匹配替代梯度与相位检查，禁止回填质量或改变连续物理问题。实际XML motion持续4s，ROT090为90度角度；旧 observer .9s 控制持续时间不受来源支持，须新版本冻结配置。

F2-055 Idp418100 原生 Posd y=-1.2000000971163445m，低于binary下界-1.2m约9.71e-8m，CSV的-1.2掩盖越界。已独立核对原生小文件字节和输入hash，详见 `NATIVE_BOUNDARY_VERIFICATION_001.json`；物理去向/动力学影响保持UNKNOWN。16例v2诊断和10项测试见 `INTEGRATION_RESULT_003.json`，全已完成案例原因台账继续扩展。

目标保持active；336审计、14参考研究、真实标签/划分、七份cards与便携内部包全部仍属于完成条件。下面是带时间戳的历史记录，不能替代本次实时状态。

## 2026-10-07T18:06:02.800417+00:00：F2 完整审计终态，F4 恢复已实际启动

`checkpoints/CHECKPOINT_005_INTEGRATED.json` 为最新协调入口。F2 全 48 个 distinct CURRENT 案例完成完整保存时序字段审计；此快照所有家族合计 89 个。F4 剩余 24 项的 `stage2-F4-science-002` 已实际启动，parent PID 1085950；F6 的 `stage2-F6-science-001` parent PID 1060071 仍存活。每队列 1 worker、共 2 个科学 I/O slots，guard/input digest/resource accounting 保持生效。具体进度以实时 receipt 为准，不从旧 stale running 状态推断。

14 个哨点 frame0 的 conversion 一致性和 v4 的 17 个集成测试已实际通过。Reference/forensics/consumers 的下一版实现仍在委派执行，新 CFD 和真实全时序标签尚未启动；它们须先有实际连续物理条件匹配、观测校准、预登记容差/成本与输入绑定。目标保持 active、未完成。

14 哨点初始帧核对的实际绑定详见 `checkpoints/SENTINEL_INITIAL_VERIFICATION_001.json`；只给 frame0 转换一致性信用。

## 2026-10-07 17:56 UTC：v4 集成与真实缺失证据

`checkpoints/INTEGRATION_RESULT_002.json` 记录实际输入哈希及收据。active consumer 为 `scripts/ds_data02_stage2_consumers_v4.py`；主分支 guarded 17 项测试通过，制造轨迹 operator replay 通过。该容差仅用于制造轨迹，不授予真实数据科学资格，也不能排除原生保存帧之间未解析的重复穿越。旧 v1/v2/v3 与全部历史报告保留。

真实 full-timeline field audit 截至本次快照共 80 个不同案例（F2=43、F4=24、F6=13）；后续动态进度以具体执行收据为准。F2 science-002 和 F6 science-001 的 detached batch parents 仍存活；F4 science-001 的历史 running 标记是已明确无进程的 stale 状态，不用于重启已完成项。F2 释放一个 I/O slot 后调度 F4 未完成 24 项，scan-F4-168 使用恢复 request 002。

F6-240/241 已完成 native exclusions 对齐：3+4 个 position 排除。数值排除类别已建立，物理去向/动力学影响未知；必须结合实际 MapRealPos、底壁几何和原生状态诊断。rigid-body massbody 与 SPH support weight 分开，禁止粒子总质量代替刚体物理质量。

三个执行分支持续进行：reference 的 14 个初始帧 individual guard jobs 已全部完成、转换一致性 PASS（主进程已逐一核对收据）；继续 v2.3 provenance 反例及 F2-S1 三网格/time/output 复用与缺口准备；forensics 做 16 个 native 诊断和 provenance 反例、扩展已完成 scans；consumers 做 source-bound 真实单案例 replay 与全 336 的物理条件/几何控制谱系审计。具体读取真实时序由主进程安排 I/O；无模型、无 hidden test、无公开发布。目标未完成。

# 第二阶段恢复入口

当前目标仍在执行，完成条件未满足。先读 `checkpoints/CHECKPOINT_004_INTEGRATED.json`、`checkpoints/INTEGRATION_RESULT_001.json` 和 `checkpoints/CONSUMER_V3_VERIFICATION_001.json`，再检查真实进程和共享ledger。不要只根据running状态文件重启任务。

已验证的长任务：F2剩余19项，batch stage2-F2-science-002，PID 1060070、start_ticks 217766475；F6全48项，batch stage2-F6-science-001，PID 1060071、start_ticks 217766476。进程独立会话启动，launch记录在数据根runtime/batch-launchers，各批次收据在runtime/batches。guard子进程继续绑定batch父进程死亡，最多两个科学I/O批次、每批一个worker，父预算和500GiB空闲下限生效。

旧exec sessions 30970/20699已不存在，独立ps确认旧父进程及worker均退出。F2旧批次终态interrupted，保留完成28例；F4旧batch文件残留running，但scan-F4-168-001执行收据是SIGTERM中断失败、实际PID不存在，保留已完成24例。两个受中断案例登记新attempt002，旧证据不改。见BATCH_RECOVERY_001.json，不能重启旧batch或把中断解释为物理失败。

全部336例入口：CURRENT336.json。新的335个扫描请求与一个已完成复用案例在SCIENTIFIC_SCAN_QUEUES.json。未启动的F1/F3/F5/F7只是已准备队列；F4剩余24项在当前任一科学I/O槽位释放后恢复，其中scan-F4-168使用002，其余未启动请求使用001。已完成收据与数组hash匹配才可复用。

F2-S1的401帧已扫描，3个遗漏ID均与原生PartOut/RunPARTs精确对齐，原因为位置排除；实际三点越过求解域x下界。物理去向和动力学影响仍未知。原案例保留，下一步预登记同输入扩大数值域的有界配对影响实验，并检查其它F2案例是否同因。

14个哨点的实际XML、启动argv、原控制和native step日志已复核；初态等价、raw-vs-typed和时空精度研究尚未完成。37项运行器/科学读取/原生对账测试通过，不授予QN/QE。S1的标签与消费者收口仍需实际CURRENT接口集成。

每个实际solver只通过共享runner启动，启动前核对GPU UUID授权与外部进程、空间预约和父累计预算。尚未启动新CFD或模型。checkpoint不代表目标达成。

当前消费者入口为scripts/ds_data02_stage2_consumers_v3.py，历史v1/v2仅保留重放谱系。主进程共享预算下13项v3反例测试全部通过；真实14个F5同manifest case_id产品维持同group/role。这个开发角色接口还不代表全局物理条件、控制模板或参数支持泄漏审阅完成。四个历史probe的launch源码均已由确切Git blob hash恢复；此前003失败保留。

已合入14个来源绑定的原生遗漏对账：11个F2案例有324个位置排除，3个F4案例有5个密度排除，物理去向及动态影响仍未知。F2-S1首帧418104粒子、14个字段检查全部通过；只证明该帧原生到typed转换一致性，不证明初态物理正确或空间/时间收敛。

2026-10-07T17:22Z：原生遗漏解码v2批次14项全部成功；此前不支持参数的v1失败保留，两个批次的请求字节均与批次launch digest一致。14项尚需完成scan/native来源绑定与原因对账，不能据解码成功授予科学资格。F2/F4科学扫描分别完成20/17项，其它请求继续由现有活进程推进。

消费者分支提交250fa6679已通过两次真实CURRENT探针，但集成审阅发现跨粒子分块累计穿越被覆盖、分辨率可能被划分到不同谱系组等问题，修复及反例交给原子代理，以新的不可变v2模块执行后再集成。probe001的源码digest与当前模块不一致，历史源码恢复状态待查；probe002绑定当前模块。不将接口成功与标签正确性等同。参考子代理当前收窄为F2-S1首帧原生/typed等价检查，之后再扩展到14哨点。
