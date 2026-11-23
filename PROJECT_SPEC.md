# 电缆双端回波复核台：数据规格

## 使用者和目标

线缆检测资料员提交台架合成两端脉冲回波、端头延迟、传播速度、噪声及盲区参数、名义长度，得到带极性、距离证据与遮蔽缺口的成对异常点候选及复测建议。服务在回环地址启动，仅供本机处理。无需登录，不控制真实设备或放行生产数据。

## 数据合同

时间以纳秒计，速度为米／纳秒，距离为米。样例只使用离线台架读数，非联网采集。局部峰须超过门限且两邻点绝对值更低，测距为相对零点时延乘传播速度后除以二。同极性、全局距离差在允许范围且两端互为唯一候选才配对；没有对端峰不能直接排除异常。 两端窗口投影至甲端坐标后分段，区分窗口内部可见的端头集合，并附落在区间内部的闭合证据；可见不等于排除异常。

`examples/sample.json` 是字段及合法取值示例。`alternate.json` 是同一对象的另一有效输入，`reject.json` 是应被阻止的输入。对象在输入顶层以 `id` 标识；归约行使用原始身份或来源组件组合作为标识。缺测映射为 `null` 或待定状态，不当成数值零。接口接受不超过 512 KiB 的 UTF-8 JSON 对象；重复字段、非法数值或域内冲突返回 400。

成果保存数据合同版本、原始包、各阶段输出、输入摘要和整包摘要。SQLite 通过唯一摘要让同一个有效产物只存一次，错误输入不落库；版本比对只允许同一对象和同一合同版本。校验摘要用于本地内容完整性，不是签名。

## 生产工作流

| 工作流 | 公开入口 | 主要样例观测 |
|---|---|---|
| 原始波形 | `POST /echotrace/api/evaluate 的 outputs.wave` | left/点1 的 时刻 为 40 |
| 脉冲提取 | `POST /echotrace/api/evaluate 的 outputs.peak` | left/点1 的 状态 为 "positive" |
| 距离归一 | `POST /echotrace/api/evaluate 的 outputs.location` | left/点1 的 状态 为 "masked" |
| 盲区遮蔽 | `POST /echotrace/api/evaluate 的 outputs.window` | right 的 起点 为 4 |
| 两端配对 | `POST /echotrace/api/evaluate 的 outputs.pair` | left/点3@right/点5 的 甲端基准位置 为 30 |
| 歧义定位 | `POST /echotrace/api/evaluate 的 outputs.pending` | left/点5 的 状态 为 "unconfirmed" |
| 复测路径 | `POST /echotrace/api/evaluate 的 outputs.revisit` | left/点1 的 状态 为 "masked" |
| 双端可见区 | `POST /echotrace/api/evaluate 的 outputs.visibility` | view-2 的 终点 为 96 |
| 版本差图 | `POST /echotrace/api/compare` | 异版产生差异，同版无差异，跨对象拒绝 |
| 封存版本 | `POST /echotrace/api/seal` | 同输入仅写入一次，旧版不随对照改变 |
| 导出交接 | `GET /echotrace/api/export/<摘要>` | 下载头有效且内容完整保留历史快照 |
| 分批登记 | `POST /echotrace/api/intake/register` | 同登记重复提交得到同一批次与原回执 |
| 片段回执 | `POST /echotrace/api/intake/fragment` | 同片段重复提交只取回原回执，乱序可收 |
| 隔离争议 | `POST /echotrace/api/intake/quarantine` | 隔离后材料清单基准变化，冲突解除 |
| 分批封存 | `POST /echotrace/api/intake/confirm` | 基准过期返回 409，同确认标识重试查回同成果 |

## 分批收档

甲乙两端波形允许由不同人分次补交，不必一次交齐。资料员先登记一次台架采集：所属线缆、两端各自的采样序号范围（整数闭区间，每端 3–600 个序号）和完整档所需标定（端头零点、盲区、门限，连同长度、速度、容差）。登记内容寻址生成批次标识并落库，离开页面或重启工作台后仍可按 `GET /echotrace/api/intake/<批次>` 查回全部已收材料与缺口。

随后逐份提交带序号波形片段 `POST /echotrace/api/intake/fragment`，允许乱序到达、一份片段可含多条连续样点。系统按登记范围给出每端 `covered`（已收）、`missing`（缺口）、`quarantined`（已隔离）序号。同一端同一序号的样点，只有原标识、时刻、幅值全部相符才当作同一条证据；同一份片段重复提交只返回原回执（`duplicate: true`），不同来源的独立提交保留各自回执。重叠片段出现不同读数时，快照的 `conflicts` 指出受影响的端头、序号及两份（或多份）来源回执，系统不默认采用最后到达的一份；资料员可用 `intake/quarantine` 附原因隔离错误来源，隔离会改变材料清单基准 `basis`。任何拼装都不丢点：缺号、跨片段时标非严格递增或原标识重复都以 409 拒绝归档。

归档确认 `POST /echotrace/api/intake/confirm` 携带客户端生成的确认标识与资料员刚核对过的 `basis`。等候期间若另一窗口收下改变清单或争议的新片段，基准不再匹配，确认以 409 拒绝并回带最新快照，不会把资料员没见过的内容一起封存。只有两端序号齐全、无冲突且拼装后的完整波形通过原有 `domain/rules/reconcile` 校验，才在同一事务内写入 `packets` 与确认记录，成果进入原版本列表，可按原入口比较和下载。确认响应丢失时，用同一确认标识重试会查回同一份成果摘要、版本号和实际使用的片段回执（`used_receipts`），不显示半成功；工作台重启后登记、回执与确认仍在，不会换一套材料。分批成果与对同一完整波形调用一次性 `evaluate`/`seal` 的成果在内容寻址下摘要一致。一次性整包导入的使用方式保持原样，不经过分批流程。

## 职责

- `echotrace/contract.py`：JSON 与领域字段边界。
- `echotrace/domain.py`：解析领域单位与归约事实。
- `echotrace/rules.py`：消费归约证据和约束，产生业务判定。
- `echotrace/artifacts.py`：成果规范编码、摘要与差分。
- `echotrace/archive.py`：SQLite 历史版本与原子封存。
- `echotrace/intake.py`：分批收档的登记、片段回执、缺口/冲突快照与严格拼装（纯领域逻辑）。
- `echotrace/intake_store.py`：分批登记、回执、隔离与确认的 SQLite 持久化及同事务封存。
- `echotrace/service.py`：串联归约、比对、历史读取和分批收档编排。
- `echotrace/server.py`：本机 HTTP 及静态界面入口。
- `web/ui.js`：归约阶段、图形、归档与交互。
- `web/intake-panel.js`：分批登记、逐份收档、争议隔离与按基准封存的界面。
- `echotrace/reconcile.py`：联合原始归约事实与业务判定，推导双端可见区。

浏览器显示来源和判定结果；发布决定由服务端归约。自动化测试套件留置。每条工作流的有界核对命令见 `.project-runtime.json`。

## 扩展复核

顶层可选 `review`；省略时基础包与旧版逐字段一致。启用时增加下列结果，与原数据共同封存，旧版与增强版可按阶段比对。`examples/review-sample.json` 给出有效输入结构。

- `capture_gaps` 采样断档：长时差映射到统一位置并裁去盲端与带外范围。
- `capture_view` 有采样支撑的可见区：以采样缺口再拆分标定可见区，保留两种证据口径。
- `peak_support` 邻样点支撑：两个相邻时差分别进入峰形支撑，任意侧过稀即降级。
- `competition` 闭合争用组：保留双侧候选图分量，不从人数相等推出唯一配对。
- `polarity_review` 反极性近邻：只列未解且几何接近的反极性候选，不作为配对。
- `closure_quality` 闭合证据质量：配对结论与两侧样点密度分开标示。
- `revisit_coverage` 复测落点支撑：按预定复测端折回全局坐标并核对真实采样支撑。
