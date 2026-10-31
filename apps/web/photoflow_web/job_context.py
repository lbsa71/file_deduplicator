"""Local mutation identity shared by the coordinator and filesystem journal owner."""

from contextvars import ContextVar

operation_id = ContextVar("photoflow_operation_id", default=None)
