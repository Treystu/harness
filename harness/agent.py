"""Runtime composition root for the request lifecycle lanes."""

from pathlib import Path
from typing import Optional

from ._http import HttpTransport, Transport
from .chat_lifecycle import ChatLifecycleMixin
from .config import Settings, load_settings
from .edit_lifecycle import AutoEditLifecycleMixin
from .execution_stages import ExecutionStageMixin
from .lifecycle import LifecycleCoordinator
from .request_router import RequestRoutingMixin
from .simple_action_lifecycle import SimpleActionLifecycleMixin
from .task_lifecycle import TaskLaneLifecycleMixin

__all__ = ["AutonomousAgent"]


class AutonomousAgent(
    RequestRoutingMixin,
    SimpleActionLifecycleMixin,
    ChatLifecycleMixin,
    AutoEditLifecycleMixin,
    TaskLaneLifecycleMixin,
    ExecutionStageMixin,
):
    """Compose route adapters around one typed lifecycle coordinator."""

    #: The HTTP seam. Typed as the ``Transport`` base, not the concrete
    #: ``HttpTransport``: the GUI binds a run-scoped cancellation view
    #: (``_CancellationBoundTransport``) over this same instance, and a caller
    #: may inject any transport that honours ``get``/``post``.
    transport: Transport
    #: Whether a model reply may propose a runnable script. Set by the caller
    #: that owns the scripting policy and the workspace (the GUI chat face);
    #: false keeps the proposal card out of every other lane.
    script_proposals: bool

    def __init__(
        self,
        settings: Optional[Settings] = None,
        root_dir: Optional[Path] = None,
        history_dir: Optional[Path] = None,
        transport: Optional[HttpTransport] = None,
    ):
        self.settings = settings or load_settings()
        self.root_dir = Path(root_dir).resolve() if root_dir is not None else None
        self.history_dir = history_dir
        self.transport = transport or HttpTransport()
        self.script_proposals = False
        self.lifecycle = LifecycleCoordinator(history_dir=history_dir)
        from .lifecycle_guards import RateCircuit

        self._rate_circuit = RateCircuit()
