"""
Helix — Friction Damper

Physics-based friction/damping model for moderating operational friction.
Calculates damping forces considering static/kinetic friction and viscous damping.

Integrated from Helix's own sandbox prototype (friction_damper_prototype.py).
Used by the Stability Sentinel for signal smoothing.
"""

import math
import logging

logger = logging.getLogger("helix.brain.friction_damper")


class FrictionDamper:
    """Models a friction damper for moderating system operational friction.

    Parameters:
        coefficient_of_friction: Friction coefficient (mu)
        normal_force: Normal force on the friction surface
        max_displacement: Maximum displacement the damper can undergo
        damping_coefficient: Viscous damping coefficient (Ns/m)
    """

    def __init__(
        self,
        coefficient_of_friction: float,
        normal_force: float,
        max_displacement: float,
        damping_coefficient: float,
    ):
        self.coefficient_of_friction = coefficient_of_friction
        self.normal_force = normal_force
        self.max_displacement = max_displacement
        self.damping_coefficient = damping_coefficient

        self.static_friction_force = self.coefficient_of_friction * self.normal_force
        # Kinetic friction is typically ~80% of static friction
        self.kinetic_friction_force = 0.8 * self.static_friction_force

        self.current_displacement = 0.0
        self.current_velocity = 0.0
        self.previous_velocity = 0.0
        self.accumulated_energy = 0.0

    def calculate_damping_force(self, current_velocity: float) -> float:
        """Calculate the damping force for a given velocity.

        Returns the total force including kinetic friction and viscous damping.
        Force opposes the direction of motion.
        """
        self.previous_velocity = self.current_velocity
        self.current_velocity = current_velocity

        friction_force = 0.0
        if abs(current_velocity) < 1e-6:
            # Near-zero velocity: static friction (simplified)
            friction_force = 0.0
        else:
            # Kinetic friction opposes motion direction
            friction_force = self.kinetic_friction_force * (
                -1 if current_velocity > 0 else 1
            )

        # Viscous damping component
        viscous_damping_force = self.damping_coefficient * current_velocity

        return friction_force + viscous_damping_force

    def update_state(
        self, time_step: float, displacement: float, velocity: float
    ):
        """Update internal state after a time step."""
        self.current_displacement = displacement
        self.current_velocity = velocity

        # Calculate energy dissipated in this step
        force = self.calculate_damping_force(self.current_velocity)
        work_done = force * (self.current_velocity * time_step)
        self.accumulated_energy += abs(work_done)

    def get_current_state(self) -> dict:
        """Return the current damper state."""
        return {
            "current_displacement": self.current_displacement,
            "current_velocity": self.current_velocity,
            "accumulated_energy_dissipated": self.accumulated_energy,
        }

    def reset(self):
        """Reset the damper state."""
        self.current_displacement = 0.0
        self.current_velocity = 0.0
        self.previous_velocity = 0.0
        self.accumulated_energy = 0.0
