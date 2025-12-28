# Phase 2: Auto-Fix Agent

**Status:** Planning
**Target:** POC on savaslabs.com (Drupal + GitHub)

---

## Prerequisites (Completed 2025-12-26)

**Drupal Content Moderation is now enabled on savaslabs.com:**
- Modules installed: `workflows`, `content_moderation`
- Editorial workflow configured with states: Draft -> Needs Review -> Published
- Applied to all 14 content types
- Agent can create draft revisions, submit for review; human approves via Drupal admin

**Workflow transitions:**
| Transition | From -> To | Purpose |
|------------|-----------|---------|
| Submit for Review | Draft -> Needs Review | Agent submits proposed fix |
| Publish | Needs Review -> Published | Human approves |
| Request Changes | Needs Review -> Draft | Human rejects, sends back |

---

## Overview

Extend the scanner to not just detect issues but propose and apply fixes automatically, with human approval workflow.

---

## Architecture

```
+------------------------------------------------------------------+
|                     Scan Results (Issues)                         |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                   Fix Classifier                                  |
|                                                                  |
|  Categorizes each issue:                                         |
|  - CONTENT_FIX - Can fix via CMS API (alt text, spelling, etc)  |
|  - CODE_FIX - Can fix via Git PR (templates, config)            |
|  - MANUAL_ONLY - Requires human judgment (design decisions)      |
|  - NOT_FIXABLE - Detection-only (3rd party, external)           |
+-----------------------------+------------------------------------+
                              |
            +-----------------+-----------------+
            v                                   v
+---------------------+             +---------------------+
|  Content Fixer      |             |   Code Fixer        |
|  (Drupal API)       |             |   (GitHub PRs)      |
+---------+-----------+             +---------+-----------+
          |                                   |
          v                                   v
+---------------------+             +---------------------+
| Create unpublished  |             |  Create PR with:    |
| revision with:      |             |  - Diff             |
| - Proposed change   |             |  - Screenshots      |
| - Before/after      |             |  - Issue details    |
+---------+-----------+             +---------+-----------+
          |                                   |
          +----------------+------------------+
                           v
+------------------------------------------------------------------+
|                  Approval Queue                                   |
|                                                                  |
|  - Web UI showing pending fixes                                  |
|  - Before/after preview                                          |
|  - One-click approve/reject per fix                              |
|  - Batch approve by category                                     |
|  - Slack notifications for new fixes                             |
+------------------------------------------------------------------+
```

---

## Fix Workflow (User-Initiated)

**Overview:** When the user is ready to address issues, they check boxes in the report to select which issues to fix. The system then creates GitHub issues for persistence/tracking, attempts fixes, and reports results.

```
+------------------------------------------------------------------+
|                  HTML Report with Checkboxes                      |
|                                                                  |
|  [x] [HIGH] Missing alt text on /about (image.jpg)               |
|  [x] [MEDIUM] No cookie consent mechanism detected               |
|  [ ] [LOW] Meta description too short on /contact                |
|                                                                  |
|  [Fix Selected Issues]                                           |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|              1. Create GitHub Issues (Persistence)                |
|                                                                  |
|  - One issue per selected item (or group by type)                |
|  - Labels: "website-quality", "auto-fix", category label         |
|  - Includes: issue details, page URL, recommended fix            |
|  - Purpose: Track progress, survives failures, audit trail       |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|              2. Classify and Route Each Issue                     |
+-----------------------------+------------------------------------+
                              |
            +-----------------+-----------------+
            v                                   v
+------------------------+          +------------------------+
|   CODE_FIX Issues      |          |  CONTENT_FIX Issues    |
|   (templates, config)  |          |  (CMS content, media)  |
+-----------+------------+          +-----------+------------+
            |                                   |
            v                                   v
+------------------------+          +------------------------+
|  3a. Create GitHub PR  |          | 3b. Create Draft       |
|                        |          |     Revision in Drupal |
|  - Branch per fix or   |          |                        |
|    batch fixes in one  |          |  - Uses Content        |
|  - Include before/     |          |    Moderation          |
|    after in PR body    |          |  - "Needs Review"      |
|  - Request review      |          |    state               |
|  - Link to GH issue    |          |                        |
+-----------+------------+          +-----------+------------+
            |                                   |
            v                                   v
+------------------------+          +------------------------+
|  4a. Update GitHub     |          | 4b. Update GitHub      |
|      Issue             |          |     Issue              |
|                        |          |                        |
|  - Link to PR          |          |  - Link to Drupal      |
|  - Status: "PR ready"  |          |    content review URL  |
|                        |          |  - Status: "Pending    |
|                        |          |    editorial approval" |
+------------------------+          +------------------------+
```

---

## Key Design Decisions

### 1. GitHub Issues for Persistence
- Every selected fix becomes a GitHub issue FIRST
- If the agent fails mid-process, the issue tracks what was attempted
- Labels categorize: `code-fix`, `content-fix`, `accessibility`, `seo`, etc.
- Linked to scan report for context

### 2. Code Fixes -> Pull Request
- Agent clones repo, makes changes, creates PR
- PR description includes: issue details, before/after, link to GH issue
- Reviewer can approve/request changes as normal
- On merge: close the linked GitHub issue

### 3. Content Fixes -> Drupal Draft Revision
- Agent uses JSON:API to create draft revision (not published)
- Drupal Content Moderation workflow handles approval
- Editorial team sees pending changes in their normal workflow
- Agent updates GH issue with link: "Pending review at [Drupal admin URL]"
- On publish: agent detects and closes GH issue (or manual close)

### 4. Failure Handling
- If agent can't fix an issue, it comments on the GH issue explaining why
- Manual intervention can then take over
- Nothing is lost - all context is in the GitHub issue

### 5. Batch vs Individual
- Similar CODE_FIX issues can be batched into one PR
- Each CONTENT_FIX is individual (different content items)
- User can choose: "Fix all" or "Fix one at a time"

### 6. User Context/Instructions for Fixes
- Each issue in the report has an optional text input for user notes
- User can provide context the LLM wouldn't know
- Notes are stored in the GitHub issue body
- Agent reads notes before attempting fix

**Example Use Case:**
```
Issue: [HIGH] 403 Forbidden error on link to /team/john-smith

User Note: "This is a former colleague. Their page was intentionally
disabled when they left the company. The fix should update the team
card template to conditionally show/hide the link based on whether
the person is still active at Savas. Check the 'is_active' field
in the team member content type."
```

The agent would then:
1. Create GitHub issue with user's context included
2. Understand this isn't a broken link to fix, but a template logic change
3. Look for the team card template and `is_active` field
4. Create PR with conditional link logic

**UI Implementation:**
- Expandable "Add fix instructions" textarea below each issue
- Placeholder text: "Optional: Add context or instructions for the fix agent..."
- Character limit: 1000 chars
- Stored with issue when "Fix Selected Issues" clicked

---

## Issue-to-Fix Mapping

| Issue Type | Fix Type | Method | Confidence |
|------------|----------|--------|------------|
| Missing alt text (content images) | CONTENT_FIX | Drupal API - update media entity | High (AI generates alt) |
| Missing alt text (theme images) | CODE_FIX | Git PR - update template | High |
| Spelling errors | CONTENT_FIX | Drupal API - update node body | High (have suggestion) |
| Grammar errors | CONTENT_FIX | Drupal API - update node body | Medium (verify suggestion) |
| Missing meta description | CONTENT_FIX | Drupal API - update node field | Medium (AI generates) |
| Empty link text | CODE_FIX | Git PR - update template | High |
| Missing lang attribute | CODE_FIX | Git PR - update html.html.twig | High |
| Missing H1 | CODE_FIX | Git PR - update page template | Medium |
| Multiple H1s | CODE_FIX | Git PR - change extra H1->H2 | Medium |
| Missing canonical | CODE_FIX | Git PR - add metatag | High |
| Cookie consent missing | MANUAL_ONLY | Needs design/legal decision | N/A |
| Third-party tracking | MANUAL_ONLY | Business decision | N/A |

---

## POC Scope (Savas Labs)

### POC 1: Alt Text Fixer (Highest Impact)
**Goal:** Auto-generate alt text for images missing it, submit as draft revisions

**Steps:**
1. From scan, get list of images missing alt text with their URLs
2. For each image:
   - Download the image
   - Use GPT-4o vision to generate descriptive alt text
   - Find the image in Drupal (via JSON:API query by URL)
   - Create a revision with the new alt text (unpublished)
   - Log the proposed change
3. Notify via Slack: "X images have proposed alt text - review at [URL]"

**Drupal Integration:**
```bash
# Get media entities via JSON:API
GET /jsonapi/media/image?filter[field_media_image.uri][value]=public://...

# Update with new alt text (creates revision)
PATCH /jsonapi/media/image/{uuid}
{
  "data": {
    "type": "media--image",
    "id": "{uuid}",
    "attributes": {
      "field_media_image": {
        "alt": "AI-generated alt text here"
      }
    }
  }
}
```

**AI Alt Text Generation:**
```python
# Use GPT-4o vision
response = openai.chat.completions.create(
    model="gpt-4o",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "Generate concise, descriptive alt text for this image. Be specific but brief (under 125 chars). Don't start with 'Image of' or 'Picture of'."},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]
    }]
)
```

### POC 2: Spelling/Grammar Fixer
**Goal:** Apply spelling/grammar fixes to content, submit as draft revisions

**Steps:**
1. From scan, get spelling/grammar issues with context
2. For each issue:
   - Find the node containing this text (search via JSON:API)
   - Get current body content
   - Apply the fix (replace misspelled word or grammar issue)
   - Create revision with fix (unpublished)
   - Log before/after
3. Notify via Slack

**Challenge:** Locating exact content in Drupal
- May need to search across multiple fields (body, summary, custom fields)
- Need to handle HTML entities and formatting

### POC 3: Code Template Fixer
**Goal:** Create GitHub PRs for template-level issues

**Steps:**
1. Clone Savas Labs repo
2. For each code-fixable issue:
   - Identify which template file to modify
   - Make the change (add lang attr, fix empty link, etc.)
   - Stage the change
3. Create a single PR with all template fixes
4. Include in PR description:
   - List of issues fixed
   - Before/after for each
   - Link to scan report

**Example Fixes:**
```twig
{# Before: Missing lang attribute #}
<html>

{# After #}
<html lang="en">
```

```twig
{# Before: Empty link #}
<a href="{{ url }}" class="social-icon">
  <i class="fa fa-twitter"></i>
</a>

{# After #}
<a href="{{ url }}" class="social-icon" aria-label="Twitter">
  <i class="fa fa-twitter" aria-hidden="true"></i>
</a>
```

---

## Approval Workflow Options

### Option A: Drupal Content Moderation (Content Fixes)
- Create revisions in "Draft" or "Needs Review" state
- Editors review in Drupal admin
- Approve -> publishes the revision
- Reject -> deletes the revision

### Option B: Custom Approval UI (All Fixes)
- Web dashboard showing all pending fixes
- Group by type (alt text, spelling, code)
- Preview before/after
- Approve individually or batch
- On approve: publishes revision OR merges PR
- On reject: discards fix, optionally adds to ignore list

### Option C: Slack-Based Approval (Quick POC)
- Post each fix to Slack with buttons
- Approve / Reject buttons
- On approve: API call to publish/merge
- Simple but doesn't scale

---

## Data Model Extension

```python
class ProposedFix(BaseModel):
    """A proposed fix for an issue."""
    id: str
    issue_id: str  # Reference to original issue
    scan_id: str
    fix_type: Literal["CONTENT_FIX", "CODE_FIX", "MANUAL_ONLY"]
    status: Literal["pending", "approved", "rejected", "applied"]

    # What to change
    target_type: str  # "drupal_media", "drupal_node", "git_file"
    target_id: str    # UUID, node ID, or file path
    field_name: Optional[str]  # For Drupal: which field

    # The fix
    original_value: str
    proposed_value: str

    # Metadata
    confidence: float  # 0-1, how confident we are in the fix
    ai_generated: bool  # Was this generated by AI?
    created_at: datetime
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[str]

    # For code fixes
    pr_url: Optional[str]
    commit_sha: Optional[str]
```

---

## Configuration

```yaml
# fixer_config.yaml
drupal:
  base_url: https://savaslabs.com
  api_endpoint: /jsonapi
  auth:
    type: oauth  # or basic, api_key
    client_id: ${DRUPAL_CLIENT_ID}
    client_secret: ${DRUPAL_CLIENT_SECRET}

  # Content moderation states
  draft_state: draft
  published_state: published

github:
  repo: savaslabs/savaslabs.com  # or wherever the theme is
  base_branch: main
  pr_prefix: "fix/website-quality-"

  # Labels to add to PRs
  labels:
    - automated
    - website-quality

openai:
  model: gpt-4o  # For vision/alt text
  temperature: 0.3

slack:
  webhook_url: ${SLACK_WEBHOOK_URL}
  channel: "#website-quality"
  notify_on:
    - new_fixes_proposed
    - fix_approved
    - fix_rejected

approval:
  mode: slack  # slack, dashboard, drupal_moderation
  auto_approve_threshold: 0.95  # Auto-approve if confidence > 95%
  batch_size: 10  # Max fixes to propose at once
```

---

## Implementation Order

1. **Alt Text Fixer POC**
   - [ ] Set up Drupal API authentication
   - [ ] Image -> alt text generation with GPT-4o vision
   - [ ] Create draft revisions in Drupal
   - [ ] Basic Slack notification
   - [ ] Test on 10 images from savaslabs.com

2. **Spelling/Grammar Fixer**
   - [ ] Content search in Drupal (find node by text)
   - [ ] Text replacement logic
   - [ ] Revision creation
   - [ ] Expand Slack notifications

3. **Code Template Fixer**
   - [ ] GitHub API integration
   - [ ] Template file identification
   - [ ] Change generation for common issues
   - [ ] PR creation workflow

4. **Approval Dashboard**
   - [ ] Simple web UI for reviewing fixes
   - [ ] Before/after preview
   - [ ] Approve/reject actions
   - [ ] Integration with Drupal/GitHub

---

## Success Metrics

- **Alt text coverage:** 0% -> 90%+ of images have alt text
- **Time to fix:** Days -> Minutes (from detection to proposed fix)
- **Approval rate:** Target 80%+ of AI suggestions approved
- **False positive rate:** <5% of suggestions rejected as incorrect

---

## Security Considerations

- Drupal API credentials stored securely (not in code)
- GitHub token with minimal required permissions
- All changes create revisions/PRs (never direct publish)
- Audit log of all proposed and applied changes
- Rate limiting to avoid overwhelming CMS

---

## Future Enhancements

- **Learning from rejections:** If a fix is rejected, learn why and improve
- **Bulk operations:** "Fix all spelling errors" with one approval
- **Scheduled runs:** Weekly scan + fix proposal
- **Multi-site support:** Same agent for multiple Drupal sites
- **Custom fix rules:** Define site-specific fixes (e.g., brand name spelling)
