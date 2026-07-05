from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from monitor_app.config import get_concealment_config
from monitor_app.evidence import (
    FusedConcealmentObservation,
    HandObservation,
    HandObservationState,
    HandSide,
)


@dataclass
class _PersonRef:
    camera_id: str
    stable_id: int
    hip_centroid: Tuple[float, float]
    observations: List[HandObservation] = field(default_factory=list)


class ConcealmentFusionEngine:
    """Fuse per-camera hand observations into zone-level concealment states."""

    def __init__(self):
        self._load_config()

    def _load_config(self):
        fusion = get_concealment_config("fusion", {}) or {}
        self.single_camera_insufficient = bool(
            fusion.get("single_camera_insufficient", True)
        )
        self.side_view_never_confirms = bool(
            fusion.get("side_view_never_confirms", True)
        )
        self.min_supporting_cameras = int(fusion.get("min_supporting_cameras", 2))
        self.min_frontal_quality = float(fusion.get("min_frontal_quality", 0.60))
        self.min_fused_confidence = float(fusion.get("min_fused_confidence", 0.75))
        self.veto_visible_threshold = float(fusion.get("veto_visible_threshold", 0.70))
        self.unknown_is_neutral = bool(fusion.get("unknown_is_neutral", True))
        self.association_max_hip_distance_norm = float(
            fusion.get("association_max_hip_distance_norm", 0.15)
        )
        self.fusion_stale_ms = float(fusion.get("fusion_stale_ms", 500))

    def fuse_zone(
        self,
        zone_id: str,
        camera_observations: Dict[str, Tuple[float, List[HandObservation]]],
        zone_cameras: List[str],
    ) -> List[FusedConcealmentObservation]:
        now = time.time()
        stale_s = self.fusion_stale_ms / 1000.0
        person_refs: List[_PersonRef] = []

        for camera_id in zone_cameras:
            payload = camera_observations.get(str(camera_id))
            if not payload:
                continue
            updated_at, observations = payload
            if now - updated_at > stale_s:
                continue

            by_person: Dict[int, List[HandObservation]] = {}
            for obs in observations:
                by_person.setdefault(obs.stable_id, []).append(obs)

            for stable_id, obs_list in by_person.items():
                hip = obs_list[0].hip_centroid or (0.5, 0.5)
                person_refs.append(
                    _PersonRef(
                        camera_id=str(camera_id),
                        stable_id=int(stable_id),
                        hip_centroid=(float(hip[0]), float(hip[1])),
                        observations=obs_list,
                    )
                )

        if not person_refs:
            return []

        subject_groups = self._associate_subjects(person_refs)
        fused_results: List[FusedConcealmentObservation] = []

        for subject_slot, refs in enumerate(subject_groups):
            camera_stable_ids = {
                ref.camera_id: ref.stable_id for ref in refs
            }
            for hand in (HandSide.LEFT, HandSide.RIGHT):
                hand_obs = []
                for ref in refs:
                    hand_obs.extend(
                        [o for o in ref.observations if o.hand == hand]
                    )
                if not hand_obs:
                    continue
                fused = self._fuse_hand_observations(
                    zone_id=zone_id,
                    subject_slot=subject_slot,
                    hand=hand,
                    observations=hand_obs,
                    camera_stable_ids=camera_stable_ids,
                )
                fused_results.append(fused)

        return fused_results

    def _associate_subjects(self, person_refs: List[_PersonRef]) -> List[List[_PersonRef]]:
        zones_cfg = get_concealment_config("zones", {}) or {}
        default_zone = zones_cfg.get("default", {}) or {}
        max_merge = int(default_zone.get("max_occupancy_for_auto_merge", 2))

        if len(person_refs) <= max_merge:
            return [person_refs]

        groups: List[List[_PersonRef]] = []
        for ref in person_refs:
            placed = False
            for group in groups:
                anchor = group[0]
                if self._hip_distance(ref.hip_centroid, anchor.hip_centroid) <= self.association_max_hip_distance_norm:
                    group.append(ref)
                    placed = True
                    break
            if not placed:
                groups.append([ref])
        return groups

    @staticmethod
    def _hip_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def _fuse_hand_observations(
        self,
        zone_id: str,
        subject_slot: int,
        hand: HandSide,
        observations: List[HandObservation],
        camera_stable_ids: Dict[str, int],
    ) -> FusedConcealmentObservation:
        visible = [
            o
            for o in observations
            if o.state == HandObservationState.VISIBLE
            and o.confidence >= self.veto_visible_threshold
        ]
        concealed = [
            o
            for o in observations
            if o.state == HandObservationState.CONCEALED
            and o.view_quality >= self.min_frontal_quality
        ]
        unknown = [o for o in observations if o.state == HandObservationState.UNKNOWN]

        if self.side_view_never_confirms:
            concealed = [
                o for o in concealed if o.view_quality >= self.min_frontal_quality
            ]

        if visible:
            conf = sum(o.confidence for o in visible) / len(visible)
            return FusedConcealmentObservation(
                zone_id=zone_id,
                subject_slot=subject_slot,
                hand=hand,
                fused_state=HandObservationState.VISIBLE,
                fused_confidence=conf,
                vetoing_cameras=sorted({o.camera_id for o in visible}),
                unknown_cameras=sorted({o.camera_id for o in unknown}),
                camera_stable_ids=camera_stable_ids,
            )

        if len(concealed) >= self.min_supporting_cameras:
            conf = sum(o.confidence for o in concealed) / len(concealed)
            if conf >= self.min_fused_confidence:
                return FusedConcealmentObservation(
                    zone_id=zone_id,
                    subject_slot=subject_slot,
                    hand=hand,
                    fused_state=HandObservationState.CONCEALED,
                    fused_confidence=conf,
                    supporting_cameras=sorted({o.camera_id for o in concealed}),
                    unknown_cameras=sorted({o.camera_id for o in unknown}),
                    camera_stable_ids=camera_stable_ids,
                )

        if self.single_camera_insufficient and len(concealed) < self.min_supporting_cameras:
            return FusedConcealmentObservation(
                zone_id=zone_id,
                subject_slot=subject_slot,
                hand=hand,
                fused_state=HandObservationState.UNKNOWN,
                fused_confidence=0.0,
                supporting_cameras=sorted({o.camera_id for o in concealed}),
                unknown_cameras=sorted({o.camera_id for o in unknown}),
                camera_stable_ids=camera_stable_ids,
            )

        if concealed and not self.unknown_is_neutral:
            conf = sum(o.confidence for o in concealed) / len(concealed)
            return FusedConcealmentObservation(
                zone_id=zone_id,
                subject_slot=subject_slot,
                hand=hand,
                fused_state=HandObservationState.CONCEALED,
                fused_confidence=conf,
                supporting_cameras=sorted({o.camera_id for o in concealed}),
                unknown_cameras=sorted({o.camera_id for o in unknown}),
                camera_stable_ids=camera_stable_ids,
            )

        return FusedConcealmentObservation(
            zone_id=zone_id,
            subject_slot=subject_slot,
            hand=hand,
            fused_state=HandObservationState.UNKNOWN,
            fused_confidence=0.0,
            supporting_cameras=sorted({o.camera_id for o in concealed}),
            unknown_cameras=sorted({o.camera_id for o in unknown}),
            camera_stable_ids=camera_stable_ids,
        )

    def fuse_all_zones(
        self, camera_observations: Dict[str, Tuple[float, List[HandObservation]]]
    ) -> List[FusedConcealmentObservation]:
        zones_cfg = get_concealment_config("zones", {}) or {}
        if not zones_cfg:
            zones_cfg = {"default": {"cameras": list(camera_observations.keys())}}

        all_fused: List[FusedConcealmentObservation] = []
        for zone_id, zone_data in zones_cfg.items():
            zone_cameras = [str(c) for c in (zone_data.get("cameras") or [])]
            all_fused.extend(
                self.fuse_zone(zone_id, camera_observations, zone_cameras)
            )
        return all_fused


_engine: Optional[ConcealmentFusionEngine] = None


def get_concealment_fusion_engine() -> ConcealmentFusionEngine:
    global _engine
    if _engine is None:
        _engine = ConcealmentFusionEngine()
    return _engine
