"""Resolve the self-contained H3 Director Cut runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
COMMON_ROOT = PROJECT_ROOT / "ai_libraries_common"

# The one default H3 API graph, shared by every entry point (director_cut_studio.py and
# h3_prompt_studio.py). Default = the house lane (owner order 2026-09-16): SparseRef DiT + ref2v 4-step
# turbo, TurboSampler, shift 6/3 on the scheduler only. Siblings, picked with OPEN API WORKFLOW at
# project start: ..._singularity_turbo_api.json (backup DiT) and ..._sparseref_fl2vturbo_api.json
# (arm-B variant). Existing projects keep the workflow_path they recorded; the old 3audio_3video graph
# stays on disk.
LATEST_WORKFLOW = PROJECT_ROOT / "video_minimax_h3_r2v_9image_sparseref_turbo_api.json"


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    python: Path
    ffmpeg: Path
    ffprobe: Path
    blip_model_cache: Path
    blip_snapshot: Path
    blip_model_id: str
    speech_model: Path

    def missing(self) -> list[Path]:
        return [
            path
            for path in (
                self.python,
                self.ffmpeg,
                self.ffprobe,
                self.blip_model_cache,
                self.blip_snapshot,
                self.speech_model,
            )
            if not path.exists()
        ]


def load_runtime_paths() -> RuntimePaths:
    config_path = COMMON_ROOT / "runtime_config.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))

    def absolute(key: str) -> Path:
        return (COMMON_ROOT / data[key]).resolve()

    return RuntimePaths(
        python=absolute("python"),
        ffmpeg=absolute("ffmpeg"),
        ffprobe=absolute("ffprobe"),
        blip_model_cache=absolute("blip_model_cache"),
        blip_snapshot=absolute("blip_snapshot"),
        blip_model_id=data["blip_model_id"],
        speech_model=absolute("speech_model"),
    )
