"""Eval layer: score an `AnswerWithSources` against gold facts + cited docs.

Phase 4 ships the per-fact LLM-as-judge — `JudgeVerdict` schema, pure-Python
aggregation, the `Judge` seam (`OpenAIJudge` + `StubJudge`), and a typed `questions`
loader. See `.claude/sdd/features/sprint-2/phase-4-perfact-judge/` and ADR-0001.
"""
