"""Model-run audit storage.

Only metadata is stored: hashes, sizes, timing, and status. The prompt body is
not persisted unless a caller explicitly recorded a truncated preview, and
there is no column anywhere that could hold an API key.
"""

from __future__ import annotations

from typing import Any, Optional

from core.enums import AnalysisSource, ModelRunStatus, ModelRunTask
from core.model_run import ModelRun
from database.repositories.base import BaseRepository, from_json_text, to_json_text

__all__ = ["ModelRunRepository"]


class ModelRunRepository(BaseRepository):
    """Stores :class:`~core.model_run.ModelRun` records."""

    table = "model_runs"
    id_prefix = "run"

    def save(self, run: ModelRun) -> str:
        """Insert a model run record.

        Raises:
            DatabaseError: If the write fails.
        """
        self.upsert(
            {
                "id": run.id,
                "provider": run.provider,
                "model": run.model,
                "prompt_version": run.prompt_version,
                "task": run.task.value,
                "input_hash": run.input_hash,
                "input_chars": run.input_chars,
                "output_hash": run.output_hash,
                "output_chars": run.output_chars,
                "analysis_source": run.analysis_source.value,
                "created_at": run.created_at.isoformat(),
                "latency_ms": run.latency_ms,
                "status": run.status.value,
                "error": run.error,
                "temperature": run.temperature,
                "prompt_preview": run.prompt_preview,
                "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
                "metadata_json": to_json_text(run.model_run_metadata),
            },
            conflict_column="id",
        )
        return run.id

    def get_run(self, run_id: str) -> Optional[ModelRun]:
        row = self.get(run_id)
        return None if row is None else self._to_model(row)

    def by_task(
        self, task: ModelRunTask, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM model_runs WHERE task = ? ORDER BY created_at DESC LIMIT ?",
            (task.value, int(limit)),
        )

    def by_analysis_source(self, source: AnalysisSource) -> list[dict[str, Any]]:
        """Every run whose output came from general model knowledge.

        Later phases use this to check how much of a pipeline is ungrounded.
        """
        return self.db.query(
            "SELECT * FROM model_runs WHERE analysis_source = ? ORDER BY created_at DESC",
            (source.value,),
        )

    def stats(self) -> dict[str, int]:
        """Counts by status and by analysis source."""
        return {
            "total": self.count(),
            "success": int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM model_runs WHERE status = ?",
                    (ModelRunStatus.SUCCESS.value,),
                )
                or 0
            ),
            "failed": int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM model_runs WHERE status = ?",
                    (ModelRunStatus.FAILED.value,),
                )
                or 0
            ),
            "ai_general": int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM model_runs WHERE analysis_source = ?",
                    (AnalysisSource.AI_GENERAL.value,),
                )
                or 0
            ),
        }

    def _to_model(self, row: dict[str, Any]) -> ModelRun:
        return ModelRun(
            id=row["id"],
            provider=row["provider"],
            model=row["model"],
            prompt_version=row["prompt_version"],
            task=ModelRunTask(row["task"]),
            input_hash=row["input_hash"],
            input_chars=row["input_chars"],
            output_hash=row["output_hash"],
            output_chars=row["output_chars"],
            analysis_source=AnalysisSource(row["analysis_source"]),
            created_at=row["created_at"],
            latency_ms=row["latency_ms"],
            status=ModelRunStatus(row["status"]),
            error=row["error"],
            temperature=row["temperature"],
            prompt_preview=row["prompt_preview"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            model_run_metadata=from_json_text(row["metadata_json"], {}) or {},
        )
