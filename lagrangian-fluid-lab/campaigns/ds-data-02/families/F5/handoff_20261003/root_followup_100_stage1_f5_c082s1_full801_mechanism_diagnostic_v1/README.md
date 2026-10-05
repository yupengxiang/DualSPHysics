# F5 fresh100：C082S1 full801 shoreline mechanism diagnostic

这是对已经完成的 C082S1 full801 native/typed/XMF 产物的只读机制诊断包。Root369 保留了“运动执行但没有证明 runup 事件”的视觉 hold；Root370 的实际轨迹审计又确认 641 行控制确实执行到 801 个保存状态。fresh100 不改变 C082S1 的几何、运动、阈值或时间轴，也不把焦点帧当作事件成功证据。

实际绑定链是：

- GenCase / placement / native349 / typed350 / XMF351 使用 Root363 已验证的元数据绑定。实际总粒子 194427，fixed 158559，moving 4210，fluid 31658，3-D；native 床标记为 Mk50，源 mkbound=40。
- typed350 的 H5 由 producer metadata 声明 SHA 37cc03e6df12533be701d15b49b6279cd6ba2f62d9e0da7567bf4e27436a9373；源准备阶段不打开、不重哈希 H5。
- workers/runup_mechanism_diagnostic.py 复用 Root363 的 metadata-only binding verifier，然后由 Root 注册的 CPU audit worker 读取 H5 的 position/valid/type/particle_id/time，逐帧扫描全部 801 状态。它保留 frame-zero Type-3 UID 集作为分母，并报告 missing/unexpected/type-changed/nonfinite UID。
- 湿润代理的定义固定为：精确 bed x 域 [-0.2,4.8]、y 域 [-0.22,0.22] 内，有限 active native Type-3 点且 z >= piecewise-linear Mk50 profile。shoreward 方向为源坡床的 +x。报告 wet UID 数、x/y/z extent、shoreward reach、exact below-profile count、5 个坡/趾段统计。
- 水面代理固定为坡段 x=[2.0,4.4]、y=[-0.22,0.22] 内 wet fluid z 的 95th percentile，并给出相对 frame 0 的时序差值、zmax 和 stable-UID 的局部垂向位移代理。frame 0 只作初始静水候选参考，不认证平衡。
- Root370 实际元数据选择四个诊断焦点：moving displacement 候选峰 frame 97/153，fluid z 候选峰 frame 219，fluid displacement 候选峰 frame 718。worker 仍然扫描所有 801 帧，焦点只用于 Root 复核定位。

requests/full801-shoreline-mechanism-diagnostic-request.json 保持 disabled，未来结果/hash 为 null，case increment 为 0；它不授予 Q-N、precision 或 runup label。manifests/shoreline-side-manifest.json 与 shoreline-oblique-manifest.json 是 Root023 已验证 ParaView renderer 的两个 camera-only focused manifest，窗口覆盖坡床/岸线局部。两个 render request 都保持 disabled，reader 保留完整 native fluid 与 fields，camera bounds 不等于 source filtering，也不伪造运动。

Root 后续可按顺序启用：先注册 mechanism audit，再按需要启用 side/oblique focused Root023 render。只有实际诊断与人工视觉证据才能决定是否还有有依据的 excitation 修复；fresh099 的 A080/A120 仍独立保留 disabled。旧 A/B/C、Root314 数值 precision negative、Root363 全 bed audit 和 Root369 hold 均保留，fresh100 不改判、不计新案例。

Source preparation 只读取 JSON/XML/Python metadata，并复制 producer-declared H5 SHA；未读取/哈希 H5、BI4、CSV、VTK 或 DAT，未启动 job，未写 shared ledger/registry。
