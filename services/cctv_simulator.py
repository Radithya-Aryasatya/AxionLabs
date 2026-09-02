"""
services/cctv_simulator.py
============================
Simulates CCTV camera feeds and depth maps for demo purposes.

Since we don't have real CCTV cameras, this service:
1. Maps existing static images to "CCTV frames" per dock
2. Generates or uses pre-computed depth maps (Depth Anything V2)
3. Simulates "live" variation (random frame selection from a set)
4. Provides departure-cue simulation (door closing, truck movement)
"""

import os
import random
import shutil
from typing import Dict, Any, Tuple, Optional
from datetime import datetime


# Base paths
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IMG_DIR = os.path.join(_BASE_DIR, "img")
_CCTV_DIR = os.path.join(_BASE_DIR, "assets", "cctv_frames")
_DEPTH_DIR = os.path.join(_BASE_DIR, "assets", "depth_maps")


# Simulated CCTV states for each dock
class CctvState:
    """Simulates the state of a CCTV camera feed for a dock."""

    def __init__(self, dock_number: int):
        self.dock_number = dock_number
        self.doors_closing = False
        self.truck_moving = False
        self.loading_in_progress = True
        self.last_frame_time = datetime.now()
        self.frame_set = self._get_frame_set()

    def _get_frame_set(self) -> list:
        """Get available image frames for this dock."""
        frames = []
        if os.path.exists(_IMG_DIR):
            for f in sorted(os.listdir(_IMG_DIR)):
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    frames.append(os.path.join(_IMG_DIR, f))
        if not frames:
            # Fallback: create placeholder paths
            frames = [
                os.path.join(_IMG_DIR, "1.jpg"),
                os.path.join(_IMG_DIR, "2.jpg"),
            ]
        return frames

    def get_current_frame(self) -> str:
        """Get the current frame path (simulates 'live' by cycling)."""
        if not self.frame_set:
            return ""
        # Simulate live: pick a frame based on time
        idx = int(datetime.now().timestamp() / 2) % len(self.frame_set)
        return self.frame_set[idx]

    def get_depth_map(self) -> str:
        """Get the corresponding depth map path."""
        depth_name = f"depth_dock_{self.dock_number}.png"
        depth_path = os.path.join(_DEPTH_DIR, depth_name)
        if os.path.exists(depth_path):
            return depth_path

        # Fallback to pre-computed depth or generate one
        fallback = os.path.join(_BASE_DIR, "my_photo_depth.png")
        if os.path.exists(fallback):
            return fallback

        # Copy first available frame as fallback
        if self.frame_set and os.path.exists(self.frame_set[0]):
            shutil.copy2(self.frame_set[0], depth_path)
            return depth_path

        return ""

    def simulate_departure(self):
        """Simulate the truck beginning to depart."""
        self.doors_closing = True
        self.truck_moving = True
        self.loading_in_progress = False

    def simulate_anomaly_resolution(self):
        """Reset to a clean state."""
        self.doors_closing = False
        self.truck_moving = False
        self.loading_in_progress = True


class CctvSimulator:
    """
    Manages CCTV simulation for all docks.
    """

    def __init__(self):
        self._states: Dict[int, CctvState] = {}
        # Ensure directories exist
        os.makedirs(_CCTV_DIR, exist_ok=True)
        os.makedirs(_DEPTH_DIR, exist_ok=True)

    def get_state(self, dock_number: int) -> CctvState:
        """Get or create the CCTV state for a dock."""
        if dock_number not in self._states:
            self._states[dock_number] = CctvState(dock_number)
        return self._states[dock_number]

    def get_frame(self, dock_number: int) -> str:
        """Get current frame for a dock."""
        return self.get_state(dock_number).get_current_frame()

    def get_depth_map(self, dock_number: int) -> str:
        """Get depth map for a dock."""
        return self.get_state(dock_number).get_depth_map()

    def simulate_departure(self, dock_number: int):
        """Trigger departure simulation for a dock."""
        self.get_state(dock_number).simulate_departure()

    def reset_dock(self, dock_number: int):
        """Reset a dock to loading state."""
        self.get_state(dock_number).simulate_anomaly_resolution()

    def trigger_messy_stacking_scenario(self, dock_number: int):
        """
        Activate Scenario 1 conditions: loading in progress,
        doors open, with a messy layout (uses lower-indexed frames
        that simulate disordered cargo).
        """
        state = self.get_state(dock_number)
        state.doors_closing = False
        state.truck_moving = False
        state.loading_in_progress = True

    def get_fleet_state_dict(self, dock_number: int) -> dict:
        """Get a state dict suitable for the Gemini service."""
        state = self.get_state(dock_number)
        return {
            'loading_in_progress': state.loading_in_progress,
            'doors_closing': state.doors_closing,
            'truck_moving': state.truck_moving,
            'anomaly_unresolved': False,
            'fill_percentage': 50.0,
            'dock_number': dock_number,
        }


# Singleton instance
_simulator = None

def get_cctv_simulator() -> CctvSimulator:
    """Get the singleton CCTV simulator instance."""
    global _simulator
    if _simulator is None:
        _simulator = CctvSimulator()
    return _simulator
