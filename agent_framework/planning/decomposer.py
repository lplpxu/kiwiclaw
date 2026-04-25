"""Task Decomposition Module

Decomposes complex tasks into subtasks with dependencies.
[PHASE8] 规划推理 - TaskDecomposer
"""

from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import uuid

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE8] [TaskDecomposer] {msg}")


class TaskStatus(Enum):
    """Status of a decomposed task"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskPriority(Enum):
    """Priority levels for tasks"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class DecomposedTask:
    """A single decomposed subtask"""
    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL

    # Dependencies
    depends_on: List[str] = field(default_factory=list)  # Task IDs this depends on
    blocked_by: List[str] = field(default_factory=list)  # Task IDs blocking this

    # Execution info
    assigned_to: str = ""  # Agent/worker ID
    result: Any = None
    error: str = ""

    # Metadata
    created_at: float = 0
    started_at: float = 0
    completed_at: float = 0
    estimated_duration: int = 0  # seconds

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "depends_on": self.depends_on,
            "blocked_by": self.blocked_by,
            "assigned_to": self.assigned_to,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class TaskGraph:
    """Manages the task dependency graph

    Provides topological sorting and dependency tracking.
    """

    def __init__(self):
        self.tasks: Dict[str, DecomposedTask] = {}

    def add_task(self, task: DecomposedTask) -> None:
        """Add a task to the graph"""
        self.tasks[task.id] = task

    def get_task(self, task_id: str) -> Optional[DecomposedTask]:
        """Get a task by ID"""
        return self.tasks.get(task_id)

    def remove_task(self, task_id: str) -> bool:
        """Remove a task from the graph"""
        if task_id not in self.tasks:
            return False

        # Remove from dependencies
        for task in self.tasks.values():
            if task_id in task.depends_on:
                task.depends_on.remove(task_id)
            if task_id in task.blocked_by:
                task.blocked_by.remove(task_id)

        del self.tasks[task_id]
        return True

    def get_ready_tasks(self) -> List[DecomposedTask]:
        """Get all tasks that are ready to execute (no pending dependencies)"""
        ready = []
        for task in self.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

            # Check if all dependencies are completed
            all_deps_done = all(
                self.tasks.get(dep_id, DecomposedTask("", "", "")).status == TaskStatus.COMPLETED
                for dep_id in task.depends_on
            )

            if all_deps_done:
                ready.append(task)

        # Sort by priority
        ready.sort(key=lambda t: t.priority.value, reverse=True)
        return ready

    def get_blocked_tasks(self) -> List[DecomposedTask]:
        """Get all blocked tasks"""
        blocked = []
        for task in self.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

            # Check if any dependency is not completed
            has_blocker = any(
                self.tasks.get(dep_id, DecomposedTask("", "", "")).status != TaskStatus.COMPLETED
                for dep_id in task.depends_on
            )

            if has_blocker:
                blocked.append(task)

        return blocked

    def topological_sort(self) -> List[DecomposedTask]:
        """Return tasks in topological order (dependencies first)"""
        result: List[DecomposedTask] = []
        visited: Set[str] = set()
        temp_visited: Set[str] = set()

        def visit(task_id: str):
            if task_id in temp_visited:
                raise ValueError(f"Circular dependency detected: {task_id}")

            if task_id in visited:
                return

            temp_visited.add(task_id)

            task = self.tasks.get(task_id)
            if task:
                for dep_id in task.depends_on:
                    visit(dep_id)

                temp_visited.remove(task_id)
                visited.add(task_id)
                result.append(task)

        for task_id in self.tasks:
            visit(task_id)

        return result

    def get_execution_plan(self) -> List[List[DecomposedTask]]:
        """Get execution plan as batches (tasks in same batch can run in parallel)

        Returns:
            List of batches, where each batch is a list of tasks
        """
        plan: List[List[DecomposedTask]] = []
        remaining = set(self.tasks.keys())

        while remaining:
            # Find all tasks with satisfied dependencies
            batch = []
            for task_id in list(remaining):
                task = self.tasks[task_id]
                if task.status != TaskStatus.PENDING:
                    remaining.remove(task_id)
                    continue

                deps_satisfied = all(
                    dep_id not in remaining or
                    self.tasks[dep_id].status == TaskStatus.COMPLETED
                    for dep_id in task.depends_on
                )

                if deps_satisfied:
                    batch.append(task)

            if not batch:
                # No tasks can run (likely circular dependency)
                break

            plan.append(batch)
            for task in batch:
                remaining.discard(task.id)

        return plan

    def is_complete(self) -> bool:
        """Check if all tasks are completed"""
        return all(
            task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            for task in self.tasks.values()
        )

    def get_stats(self) -> dict:
        """Get execution statistics"""
        statuses = {}
        for task in self.tasks.values():
            status = task.status.value
            statuses[status] = statuses.get(status, 0) + 1

        return {
            "total": len(self.tasks),
            "by_status": statuses,
            "ready": len(self.get_ready_tasks()),
            "blocked": len(self.get_blocked_tasks()),
        }


class TaskDecomposer:
    """Decomposes complex tasks into subtasks

    Uses an LLM to analyze the task and create a decomposition plan.
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    async def decompose(
        self,
        task: str,
        context: Dict[str, Any] = None,
        max_subtasks: int = 10,
    ) -> TaskGraph:
        """Decompose a task into subtasks

        Args:
            task: The task to decompose
            context: Additional context
            max_subtasks: Maximum number of subtasks to create

        Returns:
            TaskGraph with decomposed tasks
        """
        graph = TaskGraph()

        # For now, use a simple rule-based decomposition
        # In practice, this would use an LLM to analyze the task

        # Simple decomposition based on common patterns
        if any(keyword in task.lower() for keyword in ["search", "find", "look up"]):
            graph.add_task(DecomposedTask(
                name="Search",
                description=f"Search for information related to: {task}",
            ))

        if any(keyword in task.lower() for keyword in ["create", "make", "build", "generate"]):
            graph.add_task(DecomposedTask(
                name="Create",
                description=f"Create the requested item: {task}",
            ))

        if any(keyword in task.lower() for keyword in ["read", "analyze", "examine", "review"]):
            graph.add_task(DecomposedTask(
                name="Analyze",
                description=f"Analyze and review: {task}",
            ))

        if any(keyword in task.lower() for keyword in ["write", "document", "report"]):
            graph.add_task(DecomposedTask(
                name="Write",
                description=f"Write documentation for: {task}",
            ))

        if any(keyword in task.lower() for keyword in ["test", "verify", "check"]):
            graph.add_task(DecomposedTask(
                name="Verify",
                description=f"Test and verify: {task}",
            ))

        # If no tasks added, create a single "Execute" task
        if not graph.tasks:
            graph.add_task(DecomposedTask(
                name="Execute",
                description=f"Execute task: {task}",
            ))

        return graph

    def decompose_with_llm(
        self,
        task: str,
        context: Dict[str, Any] = None,
        max_subtasks: int = 10,
    ) -> TaskGraph:
        """Decompose using LLM (placeholder for actual implementation)"""
        import asyncio

        # This would call the LLM to analyze and decompose the task
        # For now, use the simple decomposition
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.decompose(task, context, max_subtasks))
