from pathlib import Path

import pytest

from ares.fake_crm_sandbox.store import SandboxConflict, SandboxStore


def test_restart_preserves_receipts_and_source_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = SandboxStore(path)
    deal = original.get_deal("deal-001")
    task = original.write("task", deal.id, "Synthetic task", "task-key")
    original.write("note", deal.id, "Synthetic note", "note-key")
    original.create_lead({"name": "Synthetic lead"}, "lead-key")
    stage = "negotiation" if deal.stage != "negotiation" else "proposal"
    original.update_stage(deal.id, stage, deal.version, "stage-key")
    restarted = SandboxStore(path)
    replay = restarted.write("task", deal.id, "Synthetic task", "task-key")
    assert replay.duplicate and replay.external_id == task.external_id
    assert len(restarted.tasks) == len(restarted.notes) == len(restarted.leads) == 1
    assert restarted.get_deal(deal.id).stage == stage
    assert restarted.update_stage(deal.id, stage, deal.version, "stage-key").duplicate
    assert restarted.create_lead({"name": "Synthetic lead"}, "lead-key").duplicate
    with pytest.raises(SandboxConflict):
        restarted.write("task", deal.id, "Different payload", "task-key")


def test_corrupt_state_never_silently_resets_source(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"version": 999}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported_sandbox_state"):
        SandboxStore(path)
