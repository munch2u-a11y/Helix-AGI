"""
Helix_main — Scheduler

Lets Helix schedule future wake-ups. When the daemon is dormant,
the scheduler checks for due tasks every 30 seconds. When one fires,
it wakes the daemon and injects the task into the consciousness stream.

Persisted to disk so tasks survive restarts.

Usage from consciousness:
    [SCHEDULE:30] Check the weather for the user
    → Helix wakes in 30 minutes, sees "scheduled task: Check the weather..."
"""

import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger("helix.brain.scheduler")


class Scheduler:
    """Self-scheduling system for Helix.

    Helix can schedule tasks for future execution. Tasks persist
    across restarts. When a task comes due, the wake callback fires.
    """

    def __init__(
        self,
        base_dir: Path,
        config: dict = None,
        wake_callback: Optional[Callable] = None,
    ):
        self.base_dir = base_dir
        self.config = config or {}
        self._wake_callback = wake_callback

        self._tasks_file = base_dir / "brain" / "scheduled_tasks.json"
        self._tasks_file.parent.mkdir(parents=True, exist_ok=True)

        self._check_interval = self.config.get("check_interval", 30)
        self._max_tasks = self.config.get("max_scheduled_tasks", 50)

        self._running = False
        self._thread = None

        # Load existing tasks
        self._tasks = self._load_tasks()
        logger.info(
            f"Scheduler initialized: {len(self._tasks)} pending tasks"
        )

    def schedule(self, minutes: int, description: str) -> dict:
        """Schedule a future task.

        Args:
            minutes: Minutes from now to fire.
            description: What to do when the task fires.

        Returns:
            The created task dict.
        """
        task = {
            "id": f"task_{int(time.time())}_{len(self._tasks)}",
            "description": description,
            "scheduled_at": time.time(),
            "fire_at": time.time() + (minutes * 60),
            "fired": False,
        }

        self._tasks.append(task)

        # Cap total tasks
        if len(self._tasks) > self._max_tasks:
            # Drop oldest completed tasks first
            self._tasks = [
                t for t in self._tasks if not t.get("fired")
            ][-self._max_tasks:]

        self._save_tasks()
        logger.info(
            f"Task scheduled: '{description}' in {minutes} minutes "
            f"(fires at {time.strftime('%H:%M:%S', time.localtime(task['fire_at']))})"
        )
        return task

    def check_and_fire(self) -> list:
        """Check for due tasks and return them.

        Called periodically by the dormant loop or heartbeat.
        Returns list of task dicts that are due now.
        """
        now = time.time()
        due = []

        for task in self._tasks:
            if not task.get("fired") and task["fire_at"] <= now:
                task["fired"] = True
                task["fired_at"] = now
                due.append(task)
                logger.info(f"Task fired: '{task['description']}'")

        if due:
            self._save_tasks()

        return due

    def get_pending(self) -> list:
        """Get all pending (unfired) tasks."""
        return [t for t in self._tasks if not t.get("fired")]

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending task by ID."""
        for task in self._tasks:
            if task["id"] == task_id and not task.get("fired"):
                task["fired"] = True
                task["cancelled"] = True
                self._save_tasks()
                logger.info(f"Task cancelled: '{task['description']}'")
                return True
        return False

    def start(self):
        """Start the scheduler check loop (runs while dormant)."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._check_loop, daemon=True, name="scheduler"
        )
        self._thread.start()
        logger.info(
            f"Scheduler started (checking every {self._check_interval}s)"
        )

    def stop(self):
        """Stop the scheduler check loop."""
        self._running = False

    def _check_loop(self):
        """Background loop that checks for due tasks."""
        while self._running:
            try:
                due_tasks = self.check_and_fire()
                if due_tasks and self._wake_callback:
                    for task in due_tasks:
                        self._wake_callback(
                            trigger=f"scheduled_task:{task['description']}"
                        )
            except Exception as e:
                logger.error(f"Scheduler check error: {e}")

            time.sleep(self._check_interval)

    def _load_tasks(self) -> list:
        """Load tasks from disk."""
        try:
            if self._tasks_file.exists():
                with open(self._tasks_file) as f:
                    data = json.load(f)
                # Filter out old fired tasks (older than 24 hours)
                cutoff = time.time() - 86400
                return [
                    t for t in data
                    if not t.get("fired") or t.get("fired_at", 0) > cutoff
                ]
        except Exception as e:
            logger.warning(f"Failed to load tasks: {e}")
        return []

    def _save_tasks(self):
        """Save tasks to disk."""
        try:
            with open(self._tasks_file, "w") as f:
                json.dump(self._tasks, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save tasks: {e}")
