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

## 职责

- `echotrace/contract.py`：JSON 与领域字段边界。
- `echotrace/domain.py`：解析领域单位与归约事实。
- `echotrace/rules.py`：消费归约证据和约束，产生业务判定。
- `echotrace/artifacts.py`：成果规范编码、摘要与差分。
- `echotrace/archive.py`：SQLite 历史版本与原子封存。
- `echotrace/service.py`：串联归约、比对和历史读取。
- `echotrace/server.py`：本机 HTTP 及静态界面入口。
- `web/ui.js`：归约阶段、图形、归档与交互。
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
