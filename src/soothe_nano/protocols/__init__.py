"""Protocol definitions for Soothe plugin authors.

These runtime-agnostic protocols define the stable interfaces that
community plugins can depend on without requiring the full host runtime.

(``workspace_sync`` stays in the soothe host — only the host consumes it.)
"""

from soothe_nano.protocols.concurrency import ConcurrencyPolicy
from soothe_nano.protocols.core_agent import CoreAgentCapabilities, CoreAgentProtocol
from soothe_nano.protocols.durability import (
    DurabilityProtocol,
    ThreadFilter,
    ThreadInfo,
    ThreadMetadata,
)
from soothe_nano.protocols.identity import (
    AKSKPair,
    AuthResult,
    ExternalIdentityMapping,
    IdentityStatus,
    TokenClaims,
    TokenInfo,
    TokenRefreshResult,
    User,
)
from soothe_nano.protocols.memory import MemoryItem, MemoryProtocol
from soothe_nano.protocols.operation_security import (
    OperationKind,
    OperationSecurityContext,
    OperationSecurityDecision,
    OperationSecurityProtocol,
    OperationSecurityRequest,
)
from soothe_nano.protocols.persistence import AsyncPersistStore
from soothe_nano.protocols.planner import (
    GoalDirective,
    PlannerProtocol,
    PlanStep,
    StepReport,
    StepResult,
    planner_outcome_text_preview,
)
from soothe_nano.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyDecision,
    PolicyProfile,
    PolicyProtocol,
)
from soothe_nano.protocols.vector_store import VectorRecord, VectorStoreProtocol

__all__ = [
    # CoreAgent
    "CoreAgentCapabilities",
    "CoreAgentProtocol",
    # Persistence
    "AsyncPersistStore",
    # Policy
    "Permission",
    "PermissionSet",
    "ActionRequest",
    "PolicyContext",
    "PolicyDecision",
    "PolicyProfile",
    "PolicyProtocol",
    # Identity
    "User",
    "AKSKPair",
    "TokenClaims",
    "ExternalIdentityMapping",
    "AuthResult",
    "TokenRefreshResult",
    "TokenInfo",
    "IdentityStatus",
    # Vector store
    "VectorRecord",
    "VectorStoreProtocol",
    # Concurrency / planner
    "ConcurrencyPolicy",
    "GoalDirective",
    "PlanStep",
    "PlannerProtocol",
    "StepReport",
    "StepResult",
    "planner_outcome_text_preview",
    # Memory
    "MemoryItem",
    "MemoryProtocol",
    # Durability
    "DurabilityProtocol",
    "ThreadFilter",
    "ThreadInfo",
    "ThreadMetadata",
    # Operation security
    "OperationKind",
    "OperationSecurityContext",
    "OperationSecurityDecision",
    "OperationSecurityProtocol",
    "OperationSecurityRequest",
]
