# 电缆双端回波复核台

线缆检测资料员使用浏览器处理台架合成两端脉冲回波、端头延迟、传播速度、噪声及盲区参数、名义长度，交付带极性、距离证据与遮蔽缺口的成对异常点候选及复测建议。全部内置数据为合成样例，不连接生产设备或在线服务。

## 本机运行

Python 3.11 或以上（含标准库 SQLite），不需要下载包。现代浏览器负责界面；Node.js 仅用于构建时检查 JavaScript 语法。

```sh
python3 -m echotrace.server
```

访问 `http://127.0.0.1:8865`。默认把封存成果写入 `.local/echotrace.sqlite`；可传 `--port`、`--db` 覆盖。界面先显示合成首例；可切换对照、导入 JSON、查看证据明细、封存成果、比较同对象版本或下载指定版本。

## 手动核对

```sh
python3 -m echotrace.check_flow wave
python3 -m echotrace.check_flow visibility
python3 -m echotrace.check_flow export
python3 -m echotrace.check_flow batch_intake
```

这些命令在临时成果库和临时回环端口运行实际 HTTP 接口，分别核对样例、对照和拒绝路径。`batch_intake` 演练甲乙两端交错到达、一段完全重叠的样点、冲突片段恰好赶在确认前、过期基准拒绝、确认丢失重试与工作台重启；`examples` 保存业务示例及可人工核算的观测点。完整命令见 `.project-runtime.json`；自动化测试套件留置，不包含私有验收测试、缺陷任务或参考解答。

## 分批收档

界面「分批收档」折叠区面向两端波形由不同人分次补交的场景：先登记线缆、两端采样序号范围与完整档标定，再逐份交带序号片段（允许乱序）。页面按登记范围显示已收、缺口与隔离序号；同端同序号读数不同会列出争议来源，需人工隔离而不是默认取最后一份。资料员按当前材料基准封存，若等候期间清单被其他窗口改变会被拒绝并要求重新核对；确认响应丢失可用同一确认重试，查回同一份成果和实际使用的片段，重启工作台也不会换材料。一次性整包导入与封存入口保持不变。

### 扩展复核

使用「复核样例」，随后在「扩展复核」切换各项结果。有效输入见 `examples/review-sample.json` 与 `examples/review-alternate.json`。例如运行 `python3 -m echotrace.check_flow capture_gaps` 可核对派生结果、拒绝非法复核和基础版本兼容性。
