# Java MLK 使用文档

本文档说明在当前版本中如何使用 RepoAudit 进行 Java 内存泄漏（MLK）检测。

## 1. 适用范围

Java MLK 现支持两种模式：

- `hybrid`（默认）：LLM 路径分析 + 符号化证据增强。
- `symbolic`：纯符号化分析，不调用 LLM。

该模式开关仅影响 `language=Java` 且 `bug-type=MLK` 的场景。

## 2. 环境准备

在仓库根目录执行：

```bash
pip install -r requirements.txt
cd lib
python build.py
cd ..
```

如果使用 `hybrid` 模式，还需安装 LLM 相关依赖并配置 API Key：

- OpenAI 模型：`OPENAI_API_KEY`
- DeepSeek 模型：`DEEPSEEK_API_KEY` 或 `DEEPSEEK_API_KEY2`
- Claude 模型：`ANTHROPIC_API_KEY`

## 3. Java MLK 命令行参数

基础命令：

```bash
python src/repoaudit.py --scan-type dfbscan --project-path <PATH> --language Java --bug-type MLK --java-mlk-mode <hybrid|symbolic>
```

关键参数说明：

- `--java-mlk-mode hybrid|symbolic`：模式选择，默认 `hybrid`
- `--model-name <MODEL>`：`hybrid` 必填，`symbolic` 可不填
- `--max-symbolic-workers <N>`：解析/符号化阶段并行度
- `--max-neural-workers <N>`：`hybrid` 下 LLM 推理并行度
- `--call-depth <N>`：跨过程传播深度

## 4. 快速开始

### 4.1 Hybrid 模式（默认，调用 LLM）

```bash
python src/repoaudit.py \
  --scan-type dfbscan \
  --project-path benchmark/Java/toy/MLK \
  --language Java \
  --bug-type MLK \
  --java-mlk-mode hybrid \
  --model-name deepseek-chat \
  --max-symbolic-workers 1 \
  --max-neural-workers 4 \
  --call-depth 3
```

### 4.2 Symbolic 模式（不调用 LLM）

```bash
python src/repoaudit.py \
  --scan-type dfbscan \
  --project-path benchmark/Java/toy/MLK \
  --language Java \
  --bug-type MLK \
  --java-mlk-mode symbolic \
  --max-symbolic-workers 1
```

## 5. 输出结果

每次运行结束后，默认会生成：

- `result/dfbscan/<model>/<bug>/<language>/<project>/<timestamp>/detect_info.json`
- `result/dfbscan/<model>/<bug>/<language>/<project>/<timestamp>/transfer_info.json`
- `log/dfbscan/<model>/<bug>/<language>/<project>/<timestamp>/dfbscan.log`

说明：

- `symbolic` 模式下，路径中的 `<model>` 通常为 `None`。
- `detect_info.json` 保存漏洞报告和解释信息。
- `transfer_info.json` 保存资源所有权转移路径。

## 6. 建议的实验流程（论文可用）

建议按以下方式做实验：

1. 先跑 `symbolic`，得到稳定基线。
2. 在同一数据集上跑 `hybrid`（固定模型与 prompt 版本）。
3. 比较 Precision / Recall / F1 及解释质量。
4. 以 `hybrid vs symbolic` 作为消融实验结果。

## 7. 内置 Java MLK 基准

运行基准脚本：

```bash
python tests/java_mlk_extractor_benchmark.py
```

运行基准断言：

```bash
python -m unittest tests.test_java_mlk_extractor_benchmark
```

当前基准期望：

- `cases = 35`
- `tp = 13`
- `fp = 0`
- `fn = 0`
- `tn = 22`

## 8. 常见问题排查

- `Error: --model-name is required for dfbscan.`
  - 原因：当前是 `hybrid` 模式，但未提供模型名。
  - 解决：补充 `--model-name ...`，或切换到 `--java-mlk-mode symbolic`。

- `ModuleNotFoundError: No module named 'openai'`
  - 原因：`hybrid` 模式缺少 LLM 依赖。
  - 解决：重新执行 `pip install -r requirements.txt`。

- Hybrid 模式出现 API Key 报错
  - 检查是否为当前模型提供了正确的环境变量。

- 运行较慢
  - 先缩小项目范围，再逐步调大 `--max-symbolic-workers` 和 `--max-neural-workers`。
