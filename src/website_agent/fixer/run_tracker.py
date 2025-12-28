"""Track fix runs for rollback capability.

Stores information about each fix applied during a run so they can be
rolled back as a batch with proof of the rollback.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FixChange:
    """Record of a single fix change."""
    node_id: int
    paragraph_id: Optional[int]
    field_name: str
    original_content: str
    fixed_content: str
    revision_id: int
    revision_url: str
    previous_revision_id: Optional[int]  # The revision before our change
    fix_type: str  # "content" or "code"
    issue_title: str
    timestamp: str


@dataclass
class RollbackProof:
    """Proof that a change was rolled back."""
    node_id: int
    original_revision_id: int  # The revision we created (being rolled back)
    rolled_back_to_revision_id: int  # The revision we rolled back to
    new_revision_id: int  # The new revision created by rollback
    new_revision_url: str
    content_preview: str  # First 200 chars of restored content
    success: bool
    message: str


class FixRunTracker:
    """Tracks changes made during fix runs for rollback."""

    def __init__(self, storage_dir: Optional[str] = None):
        """Initialize the tracker.

        Args:
            storage_dir: Directory to store run logs. Defaults to /tmp/fix-runs/
        """
        self.storage_dir = Path(storage_dir or os.environ.get("FIX_RUN_STORAGE", "/tmp/fix-runs"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._current_run_id: Optional[str] = None
        self._current_changes: list[FixChange] = []

    def start_run(self, run_id: Optional[str] = None) -> str:
        """Start a new fix run.

        Args:
            run_id: Optional run ID. Generated if not provided.

        Returns:
            The run ID
        """
        self._current_run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        self._current_changes = []
        logger.info(f"Started fix run: {self._current_run_id}")
        return self._current_run_id

    def record_change(
        self,
        node_id: int,
        paragraph_id: Optional[int],
        field_name: str,
        original_content: str,
        fixed_content: str,
        revision_id: int,
        revision_url: str,
        previous_revision_id: Optional[int],
        fix_type: str,
        issue_title: str,
    ) -> None:
        """Record a change made during the current run."""
        if not self._current_run_id:
            self.start_run()

        change = FixChange(
            node_id=node_id,
            paragraph_id=paragraph_id,
            field_name=field_name,
            original_content=original_content,
            fixed_content=fixed_content,
            revision_id=revision_id,
            revision_url=revision_url,
            previous_revision_id=previous_revision_id,
            fix_type=fix_type,
            issue_title=issue_title,
            timestamp=datetime.now().isoformat(),
        )
        self._current_changes.append(change)
        logger.info(f"Recorded change: node/{node_id} rev {revision_id}")

    def end_run(self) -> str:
        """End the current run and save to disk.

        Returns:
            Path to the saved run file
        """
        if not self._current_run_id:
            return ""

        run_file = self.storage_dir / f"{self._current_run_id}.json"

        run_data = {
            "run_id": self._current_run_id,
            "started_at": self._current_changes[0].timestamp if self._current_changes else datetime.now().isoformat(),
            "ended_at": datetime.now().isoformat(),
            "change_count": len(self._current_changes),
            "changes": [asdict(c) for c in self._current_changes],
        }

        with open(run_file, "w") as f:
            json.dump(run_data, f, indent=2)

        logger.info(f"Saved run {self._current_run_id} with {len(self._current_changes)} changes to {run_file}")

        run_id = self._current_run_id
        self._current_run_id = None
        self._current_changes = []

        return str(run_file)

    def get_run(self, run_id: str) -> Optional[dict]:
        """Load a run from disk.

        Args:
            run_id: The run ID to load

        Returns:
            Run data dict or None if not found
        """
        run_file = self.storage_dir / f"{run_id}.json"
        if not run_file.exists():
            return None

        with open(run_file) as f:
            return json.load(f)

    def get_latest_run(self) -> Optional[dict]:
        """Get the most recent run.

        Returns:
            Run data dict or None if no runs exist
        """
        run_files = sorted(self.storage_dir.glob("*.json"), reverse=True)
        if not run_files:
            return None

        with open(run_files[0]) as f:
            return json.load(f)

    def list_runs(self, limit: int = 10) -> list[dict]:
        """List recent runs.

        Args:
            limit: Maximum number of runs to return

        Returns:
            List of run summaries (run_id, change_count, started_at)
        """
        run_files = sorted(self.storage_dir.glob("*.json"), reverse=True)[:limit]
        runs = []

        for run_file in run_files:
            with open(run_file) as f:
                data = json.load(f)
                runs.append({
                    "run_id": data["run_id"],
                    "change_count": data["change_count"],
                    "started_at": data["started_at"],
                    "ended_at": data.get("ended_at"),
                })

        return runs


# Global tracker instance
_tracker: Optional[FixRunTracker] = None


def get_tracker() -> FixRunTracker:
    """Get the global tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = FixRunTracker()
    return _tracker


@dataclass
class RunRollbackResult:
    """Result of rolling back a fix run."""
    success: bool
    run_id: str
    total_changes: int
    rolled_back: int
    failed: int
    proofs: list[RollbackProof]
    message: str


async def rollback_run_async(run_id: Optional[str] = None) -> RunRollbackResult:
    """Rollback all changes from a fix run.

    Args:
        run_id: The run ID to rollback. If None, rolls back the latest run.

    Returns:
        RunRollbackResult with proof of each rollback
    """
    import json
    from drupal_editor import DrupalClient
    from drupal_editor.auth.terminus import TerminusAuth

    tracker = get_tracker()

    # Get the run to rollback
    if run_id:
        run_data = tracker.get_run(run_id)
    else:
        run_data = tracker.get_latest_run()

    if not run_data:
        return RunRollbackResult(
            success=False,
            run_id=run_id or "unknown",
            total_changes=0,
            rolled_back=0,
            failed=0,
            proofs=[],
            message="No run found to rollback",
        )

    run_id = run_data["run_id"]
    changes = run_data.get("changes", [])

    if not changes:
        return RunRollbackResult(
            success=True,
            run_id=run_id,
            total_changes=0,
            rolled_back=0,
            failed=0,
            proofs=[],
            message="No changes to rollback",
        )

    # Initialize Drupal client
    try:
        client = DrupalClient.from_env()
        success = await client.authenticate()
        if not success:
            return RunRollbackResult(
                success=False,
                run_id=run_id,
                total_changes=len(changes),
                rolled_back=0,
                failed=len(changes),
                proofs=[],
                message="Failed to authenticate with Drupal",
            )

        if not isinstance(client.auth, TerminusAuth):
            return RunRollbackResult(
                success=False,
                run_id=run_id,
                total_changes=len(changes),
                rolled_back=0,
                failed=len(changes),
                proofs=[],
                message="Rollback requires Terminus auth",
            )
    except Exception as e:
        return RunRollbackResult(
            success=False,
            run_id=run_id,
            total_changes=len(changes),
            rolled_back=0,
            failed=len(changes),
            proofs=[],
            message=f"Failed to initialize Drupal client: {e}",
        )

    proofs = []
    rolled_back = 0
    failed = 0

    for change in changes:
        nid = change["node_id"]
        previous_revision_id = change.get("previous_revision_id")
        our_revision_id = change.get("revision_id")

        if not previous_revision_id:
            # Can't rollback without knowing previous revision
            proofs.append(RollbackProof(
                node_id=nid,
                original_revision_id=our_revision_id or 0,
                rolled_back_to_revision_id=0,
                new_revision_id=0,
                new_revision_url="",
                content_preview="",
                success=False,
                message="No previous revision ID recorded - cannot rollback",
            ))
            failed += 1
            continue

        # Rollback to the previous revision
        php_code = f'''
$nid = {nid};
$target_vid = {previous_revision_id};

$storage = \\Drupal::entityTypeManager()->getStorage("node");
$revision = $storage->loadRevision($target_vid);

if (!$revision) {{
    print json_encode(["success" => false, "error" => "Previous revision not found"]);
    return;
}}

// Get content preview from the revision we're restoring
$content_preview = "";
if ($revision->hasField("body") && $revision->get("body")->value) {{
    $content_preview = substr(strip_tags($revision->get("body")->value), 0, 200);
}}

// Check for paragraph fields
foreach (["field_body_paragraphs", "field_paragraphs", "field_content"] as $field) {{
    if ($revision->hasField($field) && !$content_preview) {{
        $paras = $revision->get($field)->referencedEntities();
        foreach ($paras as $para) {{
            foreach (["field_body_text", "field_text", "field_body"] as $pf) {{
                if ($para->hasField($pf) && $para->get($pf)->value) {{
                    $content_preview = substr(strip_tags($para->get($pf)->value), 0, 200);
                    break 2;
                }}
            }}
        }}
    }}
}}

// Create a new revision that restores the previous content
$revision->setNewRevision(TRUE);
$revision->isDefaultRevision(TRUE);
$revision->set("moderation_state", "ava_suggestion");
$revision->setRevisionLogMessage("Ava: Rolled back to revision " . $target_vid);
$revision->save();

$new_vid = $revision->getRevisionId();
$base_url = \\Drupal::request()->getSchemeAndHttpHost();

print json_encode([
    "success" => true,
    "rolled_back_to" => $target_vid,
    "new_revision_id" => $new_vid,
    "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $new_vid . "/view",
    "content_preview" => $content_preview
]);
'''

        try:
            result = await client.auth.php_eval(php_code)
            if result.success and result.stdout.strip():
                try:
                    data = json.loads(result.stdout.strip())
                    if data.get("success"):
                        proofs.append(RollbackProof(
                            node_id=nid,
                            original_revision_id=our_revision_id or 0,
                            rolled_back_to_revision_id=previous_revision_id,
                            new_revision_id=data.get("new_revision_id", 0),
                            new_revision_url=data.get("revision_url", ""),
                            content_preview=data.get("content_preview", "")[:200],
                            success=True,
                            message=f"Rolled back node/{nid} from rev {our_revision_id} to rev {previous_revision_id}",
                        ))
                        rolled_back += 1
                    else:
                        proofs.append(RollbackProof(
                            node_id=nid,
                            original_revision_id=our_revision_id or 0,
                            rolled_back_to_revision_id=previous_revision_id,
                            new_revision_id=0,
                            new_revision_url="",
                            content_preview="",
                            success=False,
                            message=data.get("error", "Unknown error"),
                        ))
                        failed += 1
                except json.JSONDecodeError:
                    proofs.append(RollbackProof(
                        node_id=nid,
                        original_revision_id=our_revision_id or 0,
                        rolled_back_to_revision_id=previous_revision_id,
                        new_revision_id=0,
                        new_revision_url="",
                        content_preview="",
                        success=False,
                        message=f"Invalid response: {result.stdout[:100]}",
                    ))
                    failed += 1
            else:
                proofs.append(RollbackProof(
                    node_id=nid,
                    original_revision_id=our_revision_id or 0,
                    rolled_back_to_revision_id=previous_revision_id,
                    new_revision_id=0,
                    new_revision_url="",
                    content_preview="",
                    success=False,
                    message=result.stderr or "No output from Drush",
                ))
                failed += 1
        except Exception as e:
            proofs.append(RollbackProof(
                node_id=nid,
                original_revision_id=our_revision_id or 0,
                rolled_back_to_revision_id=previous_revision_id,
                new_revision_id=0,
                new_revision_url="",
                content_preview="",
                success=False,
                message=str(e),
            ))
            failed += 1

    await client.close()

    return RunRollbackResult(
        success=failed == 0,
        run_id=run_id,
        total_changes=len(changes),
        rolled_back=rolled_back,
        failed=failed,
        proofs=proofs,
        message=f"Rolled back {rolled_back}/{len(changes)} changes" + (f" ({failed} failed)" if failed else ""),
    )


def rollback_run_sync(run_id: Optional[str] = None) -> RunRollbackResult:
    """Synchronous wrapper for rollback_run_async."""
    import asyncio

    async def _run():
        return await rollback_run_async(run_id)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _run())
                return future.result(timeout=120)
        else:
            return loop.run_until_complete(_run())
    except RuntimeError:
        return asyncio.run(_run())


def print_rollback_proof(result: RunRollbackResult) -> str:
    """Format rollback result as a readable proof string."""
    lines = [
        "=" * 60,
        f"ROLLBACK PROOF - Run: {result.run_id}",
        "=" * 60,
        f"Status: {'SUCCESS' if result.success else 'PARTIAL/FAILED'}",
        f"Total changes: {result.total_changes}",
        f"Rolled back: {result.rolled_back}",
        f"Failed: {result.failed}",
        "",
        "-" * 60,
        "DETAILS:",
        "-" * 60,
    ]

    for i, proof in enumerate(result.proofs, 1):
        lines.append(f"\n[{i}] Node ID: {proof.node_id}")
        lines.append(f"    Status: {'✅ SUCCESS' if proof.success else '❌ FAILED'}")
        lines.append(f"    Message: {proof.message}")
        if proof.success:
            lines.append(f"    Revision: {proof.original_revision_id} → {proof.rolled_back_to_revision_id} (new: {proof.new_revision_id})")
            lines.append(f"    Review URL: {proof.new_revision_url}")
            if proof.content_preview:
                preview = proof.content_preview.replace("\n", " ")[:100]
                lines.append(f"    Content preview: {preview}...")

    lines.extend([
        "",
        "=" * 60,
        f"SUMMARY: {result.message}",
        "=" * 60,
    ])

    return "\n".join(lines)
