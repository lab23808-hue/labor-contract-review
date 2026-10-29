# ADR 001：用 Protocol 取代领域层对具体实现的依赖

## 背景

改造前 `domain` 直接 import `infra.storage` / `infra.llm.client`，导致领域逻辑绑定具体文件存储和 LLM 客户端。

## 决策

在 `src/domain/ports.py` 定义 `LLMPort`、`StoragePort` 以及端口错误类型。领域层只依赖这些 Protocol；`infra` 的具体实现负责满足接口，并在 `api/dependencies.py` 组合根注入。

## 结果

- `grep -rn "from infra" src/domain src/workflow` 为空。
- 测试可以直接注入 fake 端口。
- 具体异常类型仍由 infra 提供，但通过端口错误基类解耦。
