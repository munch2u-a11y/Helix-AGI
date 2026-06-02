"""
Helix — Background Daemon (Dream Engine Wrapper)

Thin wrapper around the DreamEngine for backward compatibility
with main.py. The actual belief crystallization logic lives in
core/dream_engine.py.

Previous version (stub): previous_versions/background_daemon_20260504_stub.py
"""

from core.physics_engine import PhysicsEngine
from core.curator import Curator
from memory.belief_store import BeliefStore



class BackgroundDaemon:
    """Background processing daemon — delegates to Curator.

    Maintains the BackgroundDaemon interface expected by main.py
    while routing all real work to the Curator.
    """

    def __init__(
        self,
        physics_engine: PhysicsEngine,
        belief_store: BeliefStore = None,
        memory_manager=None,
        llm_client=None,
        data_dir: str = "data",
    ):
        self.physics = physics_engine
        self.belief_store = belief_store

        # Initialize the curator
        self.curator = None
        if belief_store:
            self.curator = Curator(
                physics_engine=physics_engine,
                belief_store=belief_store,
                memory_manager=memory_manager,
                llm_client=llm_client,
                data_dir=data_dir,
            )

    def run_dream_cycle(self) -> dict:
        """Run a full recursive belief crystallization cycle.

        This is the main entry point — called manually via the 'dream'
        console command, or eventually by an overnight scheduler.
        """
        if not self.curator:
            return {"status": "error", "reason": "no belief store configured"}

        # Return stats from the internal synchronous run (if called directly)
        return self.curator._run_nightly_cycle()

    def run_consolidation_pass(self) -> dict:
        """Run lightweight belief maintenance.
        
        Delegated to the curator's nightly cycle or synthesis logic.
        """
        if not self.curator:
            return {"status": "error", "reason": "no curator configured"}
        # Fallback mapping: the curator handles this in its synthesis step.
        return self.curator._run_nightly_cycle()

    def run_pulse(self):
        """Legacy interface — no-op in new architecture."""
        pass
