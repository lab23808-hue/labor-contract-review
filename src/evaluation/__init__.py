"""evaluation：审查质量评估基准相关的代码（标准答案 schema、条款素材库、
50 份评估合同生成器、诊断实验的核心逻辑）。

`evaluation/` 只放纯逻辑（pydantic schema、数据生成、比对算法），不做任何
文件 I/O 的入口封装——真正的命令行入口在 `scripts/run_eval_samples.py`、
`scripts/compare_eval_results.py`、`scripts/generate_eval_contracts.py`，
和项目里 `rules/`（纯逻辑）与 `scripts/`（入口）的分工方式一致。

本包不依赖 document/rag/llm/langgraph——评估样本的"标准答案"是人工/开发者
离线设计好的，不需要真的跑一遍合同解析和切分才能存在；需要真实跑 ClauseSplitter
的部分（比较"标准条款边界"和"系统实际切分结果"）在 `evaluation/diagnostics.py`
里单独处理，并在没有 `langchain_text_splitters` 时显式跳过、不假装跑了。
"""
