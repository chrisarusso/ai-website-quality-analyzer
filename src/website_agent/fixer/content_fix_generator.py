"""LLM-powered content fix generator for Drupal.

Uses LLM to intelligently fix content issues (broken links, spelling, etc.)
based on user instructions and context. Creates draft revisions for human review.

Changes are tracked for rollback capability.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

from .run_tracker import get_tracker

logger = logging.getLogger(__name__)

# Only import openai if available
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@dataclass
class ContentFix:
    """A generated content fix."""
    node_id: int
    paragraph_id: Optional[int]
    field_name: str
    original_content: str
    fixed_content: str
    explanation: str
    confidence: float  # 0.0 to 1.0


@dataclass
class ContentFixResult:
    """Result of attempting to generate a content fix."""
    success: bool
    message: str
    fix: Optional[ContentFix] = None
    revision_url: Optional[str] = None
    revision_id: Optional[int] = None
    diff_url: Optional[str] = None
    error: Optional[str] = None


class ContentFixGenerator:
    """Generates content fixes using LLM based on issues and user instructions."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ):
        """Initialize the content fix generator.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: LLM model to use for fix generation
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.client = None

        if OPENAI_AVAILABLE and self.api_key:
            self.client = openai.OpenAI(api_key=self.api_key)

    async def generate_fix(
        self,
        page_url: str,
        issue_title: str,
        issue_description: str,
        user_instructions: str,
        category: str = "unknown",
        original_value: Optional[str] = None,
        proposed_value: Optional[str] = None,
    ) -> ContentFixResult:
        """Generate a content fix using LLM.

        Args:
            page_url: URL of the page containing the issue
            issue_title: Title of the quality issue
            issue_description: Full description of the issue
            user_instructions: User-provided context and instructions
            category: Issue category (links, spelling, etc.)
            original_value: Original text/link that's problematic (optional)
            proposed_value: Suggested fix value (optional)

        Returns:
            ContentFixResult with the generated fix or error details
        """
        if not self.client:
            return ContentFixResult(
                success=False,
                message="OpenAI client not available",
                error="No API key or openai package not installed",
            )

        # Step 1: Get the content from Drupal
        # Pass original_value as search text to find the right paragraph
        content_result = await self._get_drupal_content(page_url, search_text=original_value)
        if not content_result.get("success"):
            return ContentFixResult(
                success=False,
                message=f"Could not get content from Drupal: {content_result.get('error')}",
                error=content_result.get("error"),
            )

        nid = content_result["nid"]
        paragraph_id = content_result.get("paragraph_id")
        field_name = content_result.get("field_name", "body")
        original_content = content_result["content"]
        previous_revision_id = content_result.get("current_revision_id")

        # Step 2: Use LLM to generate the fix
        fix_result = self._generate_fix_with_llm(
            content=original_content,
            issue_title=issue_title,
            issue_description=issue_description,
            page_url=page_url,
            user_instructions=user_instructions,
            original_value=original_value,
            proposed_value=proposed_value,
            category=category,
        )

        if fix_result is None:
            return ContentFixResult(
                success=False,
                message="LLM could not generate a fix",
                error="Fix generation failed",
            )

        # Verify the fix is different from original
        if fix_result["fixed_content"] == original_content:
            return ContentFixResult(
                success=False,
                message="Generated fix was identical to original",
                error="No changes made by LLM",
            )

        # Step 3: Apply the fix to Drupal
        apply_result = await self._apply_fix_to_drupal(
            nid=nid,
            paragraph_id=paragraph_id,
            field_name=field_name,
            new_content=fix_result["fixed_content"],
            reason=fix_result["explanation"],
        )

        if not apply_result.get("success"):
            return ContentFixResult(
                success=False,
                message=f"Could not apply fix to Drupal: {apply_result.get('error')}",
                fix=ContentFix(
                    node_id=nid,
                    paragraph_id=paragraph_id,
                    field_name=field_name,
                    original_content=original_content,
                    fixed_content=fix_result["fixed_content"],
                    explanation=fix_result["explanation"],
                    confidence=fix_result["confidence"],
                ),
                error=apply_result.get("error"),
            )

        # Record the change for rollback capability
        tracker = get_tracker()
        tracker.record_change(
            node_id=nid,
            paragraph_id=paragraph_id,
            field_name=field_name,
            original_content=original_content,
            fixed_content=fix_result["fixed_content"],
            revision_id=apply_result.get("revision_id"),
            revision_url=apply_result.get("revision_url"),
            previous_revision_id=previous_revision_id,
            fix_type="content",
            issue_title=issue_title,
        )

        return ContentFixResult(
            success=True,
            message=fix_result["explanation"],
            fix=ContentFix(
                node_id=nid,
                paragraph_id=paragraph_id,
                field_name=field_name,
                original_content=original_content,
                fixed_content=fix_result["fixed_content"],
                explanation=fix_result["explanation"],
                confidence=fix_result["confidence"],
            ),
            revision_url=apply_result.get("revision_url"),
            revision_id=apply_result.get("revision_id"),
            diff_url=apply_result.get("diff_url"),
        )

    def _generate_fix_with_llm(
        self,
        content: str,
        issue_title: str,
        issue_description: str,
        page_url: str,
        user_instructions: str,
        original_value: Optional[str],
        proposed_value: Optional[str],
        category: str,
    ) -> Optional[dict]:
        """Use LLM to generate the actual fix.

        Returns:
            Dict with fixed_content, explanation, and confidence, or None on failure
        """
        # Truncate content if too long
        max_content_len = 8000
        if len(content) > max_content_len:
            content = content[:max_content_len] + "\n... (truncated)"

        prompt = f"""You are a SURGICAL content editor. Your job is to make ONE SPECIFIC change and NOTHING else.

## Content to Fix
```html
{content}
```

## Issue Details
**Title:** {issue_title}
**Category:** {category}
**Description:** {issue_description}
**Page URL:** {page_url}

## EXACT Change Required
**Find this text:** {original_value or 'Not specified'}
**Replace with:** {proposed_value or 'Not specified'}

## User Instructions
{user_instructions or 'No specific instructions provided.'}

## CRITICAL RULES - YOU MUST FOLLOW THESE EXACTLY:

1. **SURGICAL PRECISION**: Find the EXACT text specified in "Find this text" and replace it with EXACTLY the text in "Replace with". Do NOT modify anything else.

2. **NO REFORMATTING**: Do NOT reformat, restructure, or "improve" any other part of the content. Leave all other text, spacing, line breaks, and HTML exactly as-is.

3. **ONE CHANGE ONLY**: Make ONLY the single change specified. If you cannot find the exact text, set confidence to 0 and explain.

4. **PRESERVE EVERYTHING ELSE**: The output should be character-for-character identical to the input EXCEPT for the specific word/phrase being fixed.

5. **For broken links**: If removing a link, keep the link text but remove only the <a> tags. Example: `<a href="bad">Text</a>` becomes `Text`. Do NOT change the surrounding content.

6. **For spelling/grammar**: Change ONLY the misspelled word. Do NOT touch punctuation, spacing, or nearby text.

Return JSON with this structure:
{{
    "fixed_content": "The COMPLETE content with ONLY the specified change applied",
    "explanation": "Changed 'X' to 'Y'",
    "confidence": 0.95,
    "changes_made": ["Replaced 'X' with 'Y'"]
}}

CRITICAL VERIFICATION:
- Your fixed_content should differ from the original by ONLY the specific text being corrected
- If you're tempted to fix other issues or "improve" the text, STOP - do not do it
- If the change would affect more than 1-2 words (or one link), you're doing too much

Return ONLY valid JSON, no other text."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise content editor. Fix content exactly as instructed. Return only valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=10000,
                response_format={"type": "json_object"},
            )

            result_content = response.choices[0].message.content.strip()
            result = json.loads(result_content)

            # Validate the response
            if "fixed_content" not in result:
                logger.error("LLM response missing fixed_content")
                return None

            return {
                "fixed_content": result["fixed_content"],
                "explanation": result.get("explanation", "Fix applied"),
                "confidence": float(result.get("confidence", 0.5)),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM fix generation failed: {e}")
            return None

    async def _get_drupal_content(
        self,
        page_url: str,
        search_text: Optional[str] = None,
    ) -> dict:
        """Get content from Drupal for the given page URL.

        Loads ALL content fields from the node and searches for the one
        containing the issue text.

        Args:
            page_url: URL of the page to get content from
            search_text: Text to search for (to find the right paragraph)

        Returns:
            Dict with success, nid, paragraph_id, field_name, content, or error
        """
        from drupal_editor import DrupalClient
        from drupal_editor.auth.terminus import TerminusAuth

        try:
            client = DrupalClient.from_env()
            success = await client.authenticate()
            if not success:
                return {"success": False, "error": "Failed to authenticate with Drupal"}

            if not isinstance(client.auth, TerminusAuth):
                return {"success": False, "error": "Content fix requires Terminus auth"}

            # Extract path from URL
            path = page_url
            url_match = re.match(r"https?://[^/]+(/.*)$", path)
            if url_match:
                path = url_match.group(1)
            path = path.strip("/")

            # Escape search text for PHP
            escaped_search = ""
            if search_text:
                escaped_search = search_text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

            # Resolve URL alias to node ID and get content
            # This DYNAMICALLY discovers ALL text/formatted fields on the node
            php_code = f"""
$path = '/{path}';
$search_text = "{escaped_search}";

$url = \\Drupal::service('path_alias.manager')->getPathByAlias($path);
if ($url && preg_match('/\\/node\\/(\\d+)/', $url, $matches)) {{
    $nid = $matches[1];
}} else {{
    // Try direct node path
    if (preg_match('/node\\/(\\d+)/', $path, $matches)) {{
        $nid = $matches[1];
    }} else {{
        print json_encode(["success" => false, "error" => "Could not resolve URL to node"]);
        return;
    }}
}}

$storage = \\Drupal::entityTypeManager()->getStorage("node");
$node = $storage->load($nid);

if (!$node) {{
    print json_encode(["success" => false, "error" => "Node not found"]);
    return;
}}

// Get current revision ID for rollback tracking
$current_revision_id = $node->getRevisionId();

// Helper function to extract text content from any entity
function extractTextContent($entity, $type, $paragraph_id = null) {{
    $content = [];
    $fields = $entity->getFields();

    foreach ($fields as $field_name => $field) {{
        $definition = $field->getFieldDefinition();
        $field_type = $definition->getType();

        // Match text, formatted text, and string fields
        if (in_array($field_type, ['text', 'text_long', 'text_with_summary', 'string', 'string_long'])) {{
            $value = $field->value ?? "";
            if (is_string($value) && strlen(trim($value)) > 0) {{
                $content[] = [
                    "type" => $type,
                    "paragraph_id" => $paragraph_id,
                    "field_name" => $field_name,
                    "content" => $value
                ];
            }}
        }}

        // Also check 'processed' for formatted text fields
        if (in_array($field_type, ['text', 'text_long', 'text_with_summary'])) {{
            $processed = $field->processed ?? "";
            if (is_string($processed) && strlen(trim($processed)) > 0 && $processed != $value) {{
                // Only add processed if different from value (avoids duplicates)
            }}
        }}
    }}

    return $content;
}}

// Collect ALL content from node and referenced entities
$all_content = [];

// Get all text fields directly on the node
$all_content = array_merge($all_content, extractTextContent($node, "node_field", null));

// Find and process entity reference fields (paragraphs, blocks, etc.)
$fields = $node->getFields();
foreach ($fields as $field_name => $field) {{
    $definition = $field->getFieldDefinition();
    $field_type = $definition->getType();

    // Check entity reference and entity reference revision fields
    if (in_array($field_type, ['entity_reference', 'entity_reference_revisions'])) {{
        $entities = $field->referencedEntities();
        foreach ($entities as $entity) {{
            $entity_type = $entity->getEntityTypeId();
            // Process paragraphs and other content entities
            if (in_array($entity_type, ['paragraph', 'block_content', 'media'])) {{
                $para_content = extractTextContent($entity, $entity_type, (int)$entity->id());
                $all_content = array_merge($all_content, $para_content);

                // Also check for nested entity references (paragraphs containing paragraphs)
                $nested_fields = $entity->getFields();
                foreach ($nested_fields as $nf_name => $nf) {{
                    $nf_def = $nf->getFieldDefinition();
                    if (in_array($nf_def->getType(), ['entity_reference', 'entity_reference_revisions'])) {{
                        $nested_entities = $nf->referencedEntities();
                        foreach ($nested_entities as $nested) {{
                            if (in_array($nested->getEntityTypeId(), ['paragraph', 'block_content'])) {{
                                $nested_content = extractTextContent($nested, "nested_" . $nested->getEntityTypeId(), (int)$nested->id());
                                $all_content = array_merge($all_content, $nested_content);
                            }}
                        }}
                    }}
                }}
            }}
        }}
    }}
}}

if (count($all_content) == 0) {{
    print json_encode(["success" => false, "error" => "No text content fields found on this node"]);
    return;
}}

// If we have search text, find the content that contains it
$matched_content = null;
$debug_info = [];
if (!empty($search_text)) {{
    foreach ($all_content as $item) {{
        if (stripos($item["content"], $search_text) !== false) {{
            $matched_content = $item;
            break;
        }}
    }}
    // Debug: show what fields were searched
    foreach ($all_content as $item) {{
        $debug_info[] = $item["type"] . ":" . $item["field_name"] . " (" . strlen($item["content"]) . " chars)";
    }}
}}

// If no match found, use first content as fallback
if (!$matched_content) {{
    $matched_content = $all_content[0];
}}

print json_encode([
    "success" => true,
    "nid" => (int)$nid,
    "current_revision_id" => (int)$current_revision_id,
    "paragraph_id" => $matched_content["paragraph_id"],
    "field_name" => $matched_content["field_name"],
    "content" => $matched_content["content"],
    "content_type" => $matched_content["type"],
    "total_content_fields" => count($all_content),
    "fields_searched" => $debug_info,
    "search_text_found" => !empty($search_text) && stripos($matched_content["content"], $search_text) !== false
]);
"""

            result = await client.auth.php_eval(php_code)
            await client.close()

            if result.success and result.stdout.strip():
                try:
                    data = json.loads(result.stdout.strip())
                    return data
                except json.JSONDecodeError:
                    return {"success": False, "error": f"Invalid response: {result.stdout[:100]}"}
            else:
                return {"success": False, "error": result.stderr or "No output from Drush"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _apply_fix_to_drupal(
        self,
        nid: int,
        paragraph_id: Optional[int],
        field_name: str,
        new_content: str,
        reason: str,
    ) -> dict:
        """Apply the fixed content to Drupal.

        Creates a draft revision in 'ava_suggestion' state.

        Returns:
            Dict with success, revision_url, revision_id, or error
        """
        from drupal_editor import DrupalClient
        from drupal_editor.auth.terminus import TerminusAuth

        try:
            client = DrupalClient.from_env()
            success = await client.authenticate()
            if not success:
                return {"success": False, "error": "Failed to authenticate with Drupal"}

            if not isinstance(client.auth, TerminusAuth):
                return {"success": False, "error": "Content fix requires Terminus auth"}

            # Escape content for PHP
            escaped_content = new_content.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            escaped_reason = reason.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

            if paragraph_id:
                # Update paragraph
                php_code = f'''
$nid = {nid};
$para_id = {paragraph_id};
$field_name = "{field_name}";
$new_content = "{escaped_content}";
$reason = "Ava: {escaped_reason}";

// Get agent user for revision attribution
$user_storage = \\Drupal::entityTypeManager()->getStorage("user");
$users = $user_storage->loadByProperties(["name" => "claude-agent-test"]);
$agent_user = reset($users);
$agent_uid = $agent_user ? $agent_user->id() : 1;

$para_storage = \\Drupal::entityTypeManager()->getStorage("paragraph");
$para = $para_storage->load($para_id);

if (!$para) {{
    print json_encode(["success" => false, "error" => "Paragraph not found"]);
    return;
}}

$para->set($field_name, $new_content);
$para->setNewRevision(TRUE);
$para->save();

// Also create node revision for moderation
$node_storage = \\Drupal::entityTypeManager()->getStorage("node");
$node = $node_storage->load($nid);
$previous_vid = $node->getRevisionId();

$node->setNewRevision(TRUE);
$node->set("moderation_state", "ava_suggestion");
$node->setRevisionLogMessage($reason);
$node->setRevisionUserId($agent_uid);
$node->setRevisionCreationTime(time());
$node->save();

$vid = $node->getRevisionId();
$base_url = \\Drupal::request()->getSchemeAndHttpHost();
print json_encode([
    "success" => true,
    "revision_id" => $vid,
    "previous_revision_id" => $previous_vid,
    "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $vid . "/view",
    "diff_url" => $base_url . "/node/" . $nid . "/revisions/view/" . $previous_vid . "/" . $vid . "/visual_inline",
    "moderation_state" => "ava_suggestion"
]);
'''
            else:
                # Update body field directly
                php_code = f'''
$nid = {nid};
$field_name = "{field_name}";
$new_content = "{escaped_content}";
$reason = "Ava: {escaped_reason}";

// Get agent user for revision attribution
$user_storage = \\Drupal::entityTypeManager()->getStorage("user");
$users = $user_storage->loadByProperties(["name" => "claude-agent-test"]);
$agent_user = reset($users);
$agent_uid = $agent_user ? $agent_user->id() : 1;

$storage = \\Drupal::entityTypeManager()->getStorage("node");
$node = $storage->load($nid);

if (!$node) {{
    print json_encode(["success" => false, "error" => "Node not found"]);
    return;
}}

$previous_vid = $node->getRevisionId();

$format = $node->get($field_name)->format ?? "full_html";
$node->set($field_name, ["value" => $new_content, "format" => $format]);
$node->setNewRevision(TRUE);
$node->set("moderation_state", "ava_suggestion");
$node->setRevisionLogMessage($reason);
$node->setRevisionUserId($agent_uid);
$node->setRevisionCreationTime(time());
$node->save();

$vid = $node->getRevisionId();
$base_url = \\Drupal::request()->getSchemeAndHttpHost();
print json_encode([
    "success" => true,
    "revision_id" => $vid,
    "previous_revision_id" => $previous_vid,
    "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $vid . "/view",
    "diff_url" => $base_url . "/node/" . $nid . "/revisions/view/" . $previous_vid . "/" . $vid . "/visual_inline",
    "moderation_state" => "ava_suggestion"
]);
'''

            result = await client.auth.php_eval(php_code)
            await client.close()

            if result.success and result.stdout.strip():
                try:
                    data = json.loads(result.stdout.strip())
                    return data
                except json.JSONDecodeError:
                    return {"success": False, "error": f"Invalid response: {result.stdout[:100]}"}
            else:
                return {"success": False, "error": result.stderr or "No output from Drush"}

        except Exception as e:
            return {"success": False, "error": str(e)}


def generate_content_fix_sync(
    page_url: str,
    issue_title: str,
    issue_description: str,
    user_instructions: str,
    category: str = "unknown",
    original_value: Optional[str] = None,
    proposed_value: Optional[str] = None,
) -> ContentFixResult:
    """Synchronous wrapper for generate_fix.

    Useful for calling from non-async code (like the orchestrator).
    """
    generator = ContentFixGenerator()

    async def _run():
        return await generator.generate_fix(
            page_url=page_url,
            issue_title=issue_title,
            issue_description=issue_description,
            user_instructions=user_instructions,
            category=category,
            original_value=original_value,
            proposed_value=proposed_value,
        )

    # Run in event loop
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
