"""Transient transport of one provider call's raw request + serialized response.

NOT persisted to gold (EvalRecord). Surfaced as the 3rd element of *_with_stats and
consumed only by the runner's bronze write. Kept off records.py on purpose.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class RawCall(BaseModel):
    """Transient transport of one provider call's raw request + serialized response.

    NOT persisted to gold (EvalRecord). Surfaced as the 3rd element of *_with_stats and
    consumed only by the runner's bronze write. Kept off records.py on purpose.
    """

    model_config = ConfigDict(extra="forbid")
    request: dict[str, Any]  # model + messages/contents + sampling params actually sent
    response: dict[str, Any]  # provider response serialized to a JSON-able dict (FR-2)
