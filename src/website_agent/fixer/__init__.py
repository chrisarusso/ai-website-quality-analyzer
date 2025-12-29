"""Fix orchestration module for Website Quality Agent.

This module handles:
- Classifying issues into fix types (CODE_FIX, CONTENT_FIX, MANUAL_ONLY)
- Creating GitHub issues for tracking
- Creating GitHub PRs for code fixes
- Creating Drupal draft revisions for content fixes via Terminus/Drush
- LLM-powered content fix generation for intelligent Drupal fixes
"""

from .classifier import FixClassifier
from .code_fix_generator import CodeFix, CodeFixGenerator, CodeFixResult
from .content_fix_generator import ContentFix, ContentFixGenerator, ContentFixResult, generate_content_fix_sync
from .github_client import CodeSearchResult, GitHubClient, GitHubClientError, GitHubIssue, GitHubPR
from .orchestrator import FixOrchestrator, FixResult

# Optional: DrupalFixer requires drupal-editor-agent package
try:
    from .drupal_fixer import DrupalFixer, DrupalFixResult, fix_spelling_sync, fix_broken_link_sync, rollback_revision_sync
except ImportError:
    DrupalFixer = None
    DrupalFixResult = None
    fix_spelling_sync = None
    fix_broken_link_sync = None
    rollback_revision_sync = None
from .run_tracker import (
    FixRunTracker,
    FixChange,
    RollbackProof,
    RunRollbackResult,
    get_tracker,
    rollback_run_sync,
    print_rollback_proof,
)

__all__ = [
    "CodeFix",
    "CodeFixGenerator",
    "CodeFixResult",
    "CodeSearchResult",
    "ContentFix",
    "ContentFixGenerator",
    "ContentFixResult",
    "generate_content_fix_sync",
    "FixClassifier",
    "DrupalFixer",
    "DrupalFixResult",
    "fix_spelling_sync",
    "fix_broken_link_sync",
    "rollback_revision_sync",
    "GitHubClient",
    "GitHubClientError",
    "GitHubIssue",
    "GitHubPR",
    "FixOrchestrator",
    "FixResult",
    # Run tracking and rollback
    "FixRunTracker",
    "FixChange",
    "RollbackProof",
    "RunRollbackResult",
    "get_tracker",
    "rollback_run_sync",
    "print_rollback_proof",
]
