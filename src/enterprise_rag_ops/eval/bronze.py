"""Bronze data layer writer for evaluation runs, complying with ADR-0010 §2 + §4 (no secrets).

Persists the raw request + response payload to a gitignored directory structure:
data/raw_eval/{run_id}/{question_id}__{model}__{call_type}.json
"""

import json
import os
import threading
from pathlib import Path
from typing import Any


class BronzeWriter:
    """Writes raw request and response payloads to a gitignored bronze store (ADR-0010).

    Uses a thread-safe lock to serialize writes to individual JSON files.
    """

    def __init__(self, run_id: str, root: Path | str = Path("data/raw_eval")) -> None:
        """Initialize the BronzeWriter with a run ID and root directory.

        Raises:
            ValueError: If run_id contains os.sep, '/', or '..'.
        """
        if not run_id:
            raise ValueError("run_id cannot be empty")
        if "/" in run_id or ".." in run_id or os.sep in run_id:
            raise ValueError(f"run_id contains invalid path characters: {run_id}")

        self.run_id = run_id
        self._root = Path(root)
        self._run_dir = self._root / run_id
        self._lock = threading.Lock()

    def write(
        self,
        question_id: str,
        model: str,
        call_type: str,
        payload: Any,
    ) -> Path:
        """Write one call's raw payload to ``{run_id}/{question_id}__{model}__{call_type}.json``.

        Overwrite-by-key (open "w") for idempotency on re-run; thread-safe + per-record flush
        so a crashed sweep leaves complete files. ``run_id`` is bound + validated at init.

        Returns:
            Path: The path to the written JSON file.
        """
        file_path = self._run_dir / f"{question_id}__{model}__{call_type}.json"

        with self._lock:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()

        return file_path
