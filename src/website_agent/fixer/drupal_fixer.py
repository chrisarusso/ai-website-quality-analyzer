"""Drupal content fixer using the shared drupal-editor-agent library.

Uses Terminus/Drush for Pantheon sites, with Playwright fallback.
Creates revisions in 'ava_suggestion' moderation state for human approval.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Optional

from drupal_editor import DrupalClient
from drupal_editor.operations.nodes import DraftRevision


@dataclass
class DrupalFixResult:
    """Result of a Drupal fix operation."""

    success: bool
    message: str
    node_id: Optional[str] = None
    revision_id: Optional[int] = None
    revision_url: Optional[str] = None
    moderation_state: Optional[str] = None
    original_value: Optional[str] = None
    new_value: Optional[str] = None
    error: Optional[str] = None


class DrupalFixer:
    """Applies fixes to Drupal content using the shared drupal-editor-agent.

    Uses Terminus/Drush for Pantheon-hosted sites (preferred),
    falls back to Playwright browser automation if Terminus not available.

    All changes are created as draft revisions in 'ava_suggestion' state,
    requiring human approval before publishing.
    """

    def __init__(self, client: Optional[DrupalClient] = None):
        """Initialize the Drupal fixer.

        Args:
            client: DrupalClient instance (creates one from env if not provided)
        """
        self._client = client
        self._authenticated = False

    async def _ensure_client(self) -> DrupalClient:
        """Ensure we have an authenticated client."""
        if self._client is None:
            self._client = DrupalClient.from_env()

        if not self._authenticated:
            success = await self._client.authenticate()
            if not success:
                raise RuntimeError("Failed to authenticate with Drupal")
            self._authenticated = True

        return self._client

    async def fix_spelling_error(
        self,
        page_url: str,
        original_text: str,
        corrected_text: str,
        field_name: str = "body",
    ) -> DrupalFixResult:
        """Fix a spelling error in Drupal content.

        Handles both simple body fields and paragraph-based content.

        Args:
            page_url: URL of the page containing the error
            original_text: The misspelled text to find
            corrected_text: The corrected text to replace with
            field_name: Which field to search (default: "body")

        Returns:
            DrupalFixResult with the outcome
        """
        try:
            client = await self._ensure_client()

            # Extract node ID from URL - try direct extraction first, then resolve alias
            nid = self._extract_nid_from_url(page_url)
            if not nid:
                # Try resolving URL alias via Drush
                nid = await self.resolve_url_to_nid(page_url)
                if not nid:
                    return DrupalFixResult(
                        success=False,
                        message=f"Could not resolve URL to node ID: {page_url}",
                        error="URL alias resolution failed",
                    )

            # First try paragraph-based fix (common for Savas sites)
            paragraph_result = await self._fix_in_paragraphs(
                client, nid, original_text, corrected_text
            )
            if paragraph_result.success:
                return paragraph_result

            # Fall back to simple body field
            try:
                result: DraftRevision = await client.nodes.find_and_replace(
                    nid=nid,
                    field=field_name,
                    find=original_text,
                    replace=corrected_text,
                    reason=f"Ava: Fixed spelling - '{original_text}' → '{corrected_text}'",
                )

                if result.success:
                    return DrupalFixResult(
                        success=True,
                        message=f"Fixed spelling: '{original_text}' → '{corrected_text}'",
                        node_id=f"node/{nid}",
                        revision_id=result.revision_id,
                        revision_url=result.revision_url,
                        moderation_state=result.moderation_state,
                        original_value=original_text,
                        new_value=corrected_text,
                    )
                else:
                    return DrupalFixResult(
                        success=False,
                        message=f"Text not found in body or paragraphs: '{original_text}'",
                        node_id=f"node/{nid}",
                        error=result.error or "Text not found",
                    )
            except Exception as body_error:
                return DrupalFixResult(
                    success=False,
                    message=f"Text not found in body or paragraphs: '{original_text}'",
                    node_id=f"node/{nid}",
                    error=str(body_error),
                )

        except Exception as e:
            return DrupalFixResult(
                success=False,
                message=f"Drupal fix error: {e}",
                error=str(e),
            )

    async def _fix_in_paragraphs(
        self,
        client: DrupalClient,
        nid: int,
        original_text: str,
        corrected_text: str,
    ) -> DrupalFixResult:
        """Find and fix text in paragraph fields.

        Searches through field_body_paragraphs for text fields containing
        the original text, then updates the paragraph.
        """
        from drupal_editor.auth.terminus import TerminusAuth
        import base64

        if not isinstance(client.auth, TerminusAuth):
            return DrupalFixResult(
                success=False,
                message="Paragraph fix requires Terminus auth",
                error="Not using Terminus",
            )

        # Escape for PHP
        original_escaped = original_text.replace("'", "\\'").replace('"', '\\"')
        corrected_escaped = corrected_text.replace("'", "\\'").replace('"', '\\"')

        # PHP code to find and fix in paragraphs
        php_code = f'''
$nid = {nid};
$find = "{original_escaped}";
$replace = "{corrected_escaped}";

$node = \\Drupal::entityTypeManager()->getStorage("node")->load($nid);
if (!$node) {{
    print json_encode(["success" => false, "error" => "Node not found"]);
    return;
}}

// Check for paragraph field
$para_field = null;
foreach (["field_body_paragraphs", "field_paragraphs", "field_content"] as $field) {{
    if ($node->hasField($field)) {{
        $para_field = $field;
        break;
    }}
}}

if (!$para_field) {{
    print json_encode(["success" => false, "error" => "No paragraph field found"]);
    return;
}}

$paragraphs = $node->get($para_field)->referencedEntities();
$found = false;
$para_id = null;
$field_name = null;

// Search all paragraphs for the text
foreach ($paragraphs as $para) {{
    foreach ($para->getFields() as $fname => $field) {{
        if (in_array($fname, ["field_body_text", "field_text", "field_body", "field_content"])) {{
            $value = $field->value ?? "";
            if (is_string($value) && strpos($value, $find) !== false) {{
                $found = true;
                $para_id = $para->id();
                $field_name = $fname;

                // Do the replacement
                $new_value = str_replace($find, $replace, $value);
                $para->set($fname, $new_value);
                $para->setNewRevision(TRUE);
                $para->save();

                // Also trigger node revision for moderation
                $node->setNewRevision(TRUE);
                $node->set("moderation_state", "ava_suggestion");
                $node->setRevisionLogMessage("Ava: Fixed spelling - " . $find . " → " . $replace);
                $node->save();

                break 2;
            }}
        }}
    }}
}}

if ($found) {{
    $vid = $node->getRevisionId();
    $base_url = \\Drupal::request()->getSchemeAndHttpHost();
    print json_encode([
        "success" => true,
        "paragraph_id" => $para_id,
        "field" => $field_name,
        "revision_id" => $vid,
        "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $vid . "/view",
        "moderation_state" => "ava_suggestion"
    ]);
}} else {{
    print json_encode(["success" => false, "error" => "Text not found in paragraphs"]);
}}
'''

        try:
            result = await client.auth.php_eval(php_code)
            if result.success and result.stdout.strip():
                import json
                try:
                    data = json.loads(result.stdout.strip())
                    if data.get("success"):
                        return DrupalFixResult(
                            success=True,
                            message=f"Fixed in paragraph {data.get('paragraph_id')}: '{original_text}' → '{corrected_text}'",
                            node_id=f"node/{nid}",
                            revision_id=data.get("revision_id"),
                            revision_url=data.get("revision_url"),
                            moderation_state=data.get("moderation_state"),
                            original_value=original_text,
                            new_value=corrected_text,
                        )
                    else:
                        return DrupalFixResult(
                            success=False,
                            message=data.get("error", "Unknown error"),
                            node_id=f"node/{nid}",
                            error=data.get("error"),
                        )
                except json.JSONDecodeError:
                    return DrupalFixResult(
                        success=False,
                        message=f"Invalid response: {result.stdout[:100]}",
                        error="JSON parse error",
                    )
            else:
                return DrupalFixResult(
                    success=False,
                    message=f"Drush error: {result.stderr or 'No output'}",
                    error=result.stderr,
                )
        except Exception as e:
            return DrupalFixResult(
                success=False,
                message=f"Paragraph fix error: {e}",
                error=str(e),
            )

    async def fix_broken_link(
        self,
        page_url: str,
        broken_link_url: str,
        action: str = "remove",
        replacement_url: Optional[str] = None,
        field_name: str = "body",
    ) -> DrupalFixResult:
        """Fix a broken link in Drupal content.

        Can either remove the link (keeping the text) or replace the URL.
        Handles both simple body fields and paragraph-based content.

        Args:
            page_url: URL of the page containing the broken link
            broken_link_url: The broken link URL to fix
            action: "remove" to remove link (keep text), "replace" to update URL
            replacement_url: New URL if action is "replace"
            field_name: Which field to search (default: "body")

        Returns:
            DrupalFixResult with the outcome
        """
        try:
            client = await self._ensure_client()

            # Extract node ID from URL
            nid = self._extract_nid_from_url(page_url)
            if not nid:
                nid = await self.resolve_url_to_nid(page_url)
                if not nid:
                    return DrupalFixResult(
                        success=False,
                        message=f"Could not resolve URL to node ID: {page_url}",
                        error="URL alias resolution failed",
                    )

            # Try fixing in paragraphs first (common for Savas sites)
            paragraph_result = await self._fix_link_in_paragraphs(
                client, nid, broken_link_url, action, replacement_url
            )
            if paragraph_result.success:
                return paragraph_result

            # Fall back to simple body field
            return await self._fix_link_in_body(
                client, nid, broken_link_url, action, replacement_url, field_name
            )

        except Exception as e:
            return DrupalFixResult(
                success=False,
                message=f"Drupal link fix error: {e}",
                error=str(e),
            )

    async def _fix_link_in_body(
        self,
        client: DrupalClient,
        nid: int,
        broken_link_url: str,
        action: str,
        replacement_url: Optional[str],
        field_name: str,
    ) -> DrupalFixResult:
        """Fix a broken link in the body field using regex find/replace."""
        from drupal_editor.auth.terminus import TerminusAuth

        if not isinstance(client.auth, TerminusAuth):
            return DrupalFixResult(
                success=False,
                message="Link fix requires Terminus auth",
                error="Not using Terminus",
            )

        # Escape URL for PHP regex
        escaped_url = broken_link_url.replace("/", "\\/").replace(".", "\\.").replace("?", "\\?")

        if action == "remove":
            # Replace <a href="broken">text</a> with just text
            reason = f"Ava: Removed broken link to {broken_link_url}"
            php_code = f'''
$nid = {nid};
$url_pattern = "{escaped_url}";

$node = \\Drupal::entityTypeManager()->getStorage("node")->load($nid);
if (!$node || !$node->hasField("{field_name}")) {{
    print json_encode(["success" => false, "error" => "Node or field not found"]);
    return;
}}

$body = $node->get("{field_name}")->value;
$format = $node->get("{field_name}")->format;

// Pattern to match <a href="url">text</a> and replace with just text
$pattern = '/<a[^>]*href=["\']' . preg_quote("{broken_link_url}", "/") . '["\'][^>]*>(.*?)<\\/a>/is';
$new_body = preg_replace($pattern, '$1', $body);

if ($new_body !== $body) {{
    $node->set("{field_name}", ["value" => $new_body, "format" => $format]);
    $node->setNewRevision(TRUE);
    $node->set("moderation_state", "ava_suggestion");
    $node->setRevisionLogMessage("{reason}");
    $node->save();

    $vid = $node->getRevisionId();
    $base_url = \\Drupal::request()->getSchemeAndHttpHost();
    print json_encode([
        "success" => true,
        "revision_id" => $vid,
        "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $vid . "/view",
        "moderation_state" => "ava_suggestion"
    ]);
}} else {{
    print json_encode(["success" => false, "error" => "Link not found in body"]);
}}
'''
        else:  # replace
            if not replacement_url:
                return DrupalFixResult(
                    success=False,
                    message="Replacement URL required for replace action",
                    error="No replacement URL",
                )

            reason = f"Ava: Updated link from {broken_link_url} to {replacement_url}"
            replacement_escaped = replacement_url.replace("'", "\\'").replace('"', '\\"')
            php_code = f'''
$nid = {nid};
$old_url = "{broken_link_url}";
$new_url = "{replacement_escaped}";

$node = \\Drupal::entityTypeManager()->getStorage("node")->load($nid);
if (!$node || !$node->hasField("{field_name}")) {{
    print json_encode(["success" => false, "error" => "Node or field not found"]);
    return;
}}

$body = $node->get("{field_name}")->value;
$format = $node->get("{field_name}")->format;

$new_body = str_replace($old_url, $new_url, $body);

if ($new_body !== $body) {{
    $node->set("{field_name}", ["value" => $new_body, "format" => $format]);
    $node->setNewRevision(TRUE);
    $node->set("moderation_state", "ava_suggestion");
    $node->setRevisionLogMessage("{reason}");
    $node->save();

    $vid = $node->getRevisionId();
    $base_url = \\Drupal::request()->getSchemeAndHttpHost();
    print json_encode([
        "success" => true,
        "revision_id" => $vid,
        "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $vid . "/view",
        "moderation_state" => "ava_suggestion"
    ]);
}} else {{
    print json_encode(["success" => false, "error" => "Link URL not found in body"]);
}}
'''

        try:
            result = await client.auth.php_eval(php_code)
            if result.success and result.stdout.strip():
                import json
                try:
                    data = json.loads(result.stdout.strip())
                    if data.get("success"):
                        action_text = "Removed" if action == "remove" else f"Updated to {replacement_url}"
                        return DrupalFixResult(
                            success=True,
                            message=f"{action_text} broken link: {broken_link_url}",
                            node_id=f"node/{nid}",
                            revision_id=data.get("revision_id"),
                            revision_url=data.get("revision_url"),
                            moderation_state=data.get("moderation_state"),
                            original_value=broken_link_url,
                            new_value=replacement_url or "(removed)",
                        )
                    else:
                        return DrupalFixResult(
                            success=False,
                            message=data.get("error", "Unknown error"),
                            node_id=f"node/{nid}",
                            error=data.get("error"),
                        )
                except json.JSONDecodeError:
                    return DrupalFixResult(
                        success=False,
                        message=f"Invalid response: {result.stdout[:100]}",
                        error="JSON parse error",
                    )
            else:
                return DrupalFixResult(
                    success=False,
                    message=f"Drush error: {result.stderr or 'No output'}",
                    error=result.stderr,
                )
        except Exception as e:
            return DrupalFixResult(
                success=False,
                message=f"Link fix error: {e}",
                error=str(e),
            )

    async def _fix_link_in_paragraphs(
        self,
        client: DrupalClient,
        nid: int,
        broken_link_url: str,
        action: str,
        replacement_url: Optional[str],
    ) -> DrupalFixResult:
        """Fix a broken link in paragraph fields."""
        from drupal_editor.auth.terminus import TerminusAuth

        if not isinstance(client.auth, TerminusAuth):
            return DrupalFixResult(
                success=False,
                message="Paragraph link fix requires Terminus auth",
                error="Not using Terminus",
            )

        broken_escaped = broken_link_url.replace("'", "\\'").replace('"', '\\"')
        replacement_escaped = (replacement_url or "").replace("'", "\\'").replace('"', '\\"')
        action_str = "remove" if action == "remove" else "replace"

        if action == "remove":
            reason = f"Ava: Removed broken link to {broken_link_url}"
        else:
            reason = f"Ava: Updated link from {broken_link_url} to {replacement_url}"

        php_code = f'''
$nid = {nid};
$old_url = "{broken_escaped}";
$new_url = "{replacement_escaped}";
$action = "{action_str}";

$node = \\Drupal::entityTypeManager()->getStorage("node")->load($nid);
if (!$node) {{
    print json_encode(["success" => false, "error" => "Node not found"]);
    return;
}}

// Check for paragraph field
$para_field = null;
foreach (["field_body_paragraphs", "field_paragraphs", "field_content"] as $field) {{
    if ($node->hasField($field)) {{
        $para_field = $field;
        break;
    }}
}}

if (!$para_field) {{
    print json_encode(["success" => false, "error" => "No paragraph field found"]);
    return;
}}

$paragraphs = $node->get($para_field)->referencedEntities();
$found = false;
$para_id = null;
$field_name = null;

// Search all paragraphs for the link
foreach ($paragraphs as $para) {{
    foreach ($para->getFields() as $fname => $field) {{
        if (in_array($fname, ["field_body_text", "field_text", "field_body", "field_content"])) {{
            $value = $field->value ?? "";
            if (is_string($value) && strpos($value, $old_url) !== false) {{
                $found = true;
                $para_id = $para->id();
                $field_name = $fname;

                if ($action == "remove") {{
                    // Remove link tags but keep text
                    $pattern = '/<a[^>]*href=["\']' . preg_quote($old_url, "/") . '["\'][^>]*>(.*?)<\\/a>/is';
                    $new_value = preg_replace($pattern, '$1', $value);
                }} else {{
                    // Replace URL
                    $new_value = str_replace($old_url, $new_url, $value);
                }}

                $para->set($fname, $new_value);
                $para->setNewRevision(TRUE);
                $para->save();

                // Also trigger node revision for moderation
                $node->setNewRevision(TRUE);
                $node->set("moderation_state", "ava_suggestion");
                $node->setRevisionLogMessage("{reason}");
                $node->save();

                break 2;
            }}
        }}
    }}
}}

if ($found) {{
    $vid = $node->getRevisionId();
    $base_url = \\Drupal::request()->getSchemeAndHttpHost();
    print json_encode([
        "success" => true,
        "paragraph_id" => $para_id,
        "field" => $field_name,
        "revision_id" => $vid,
        "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $vid . "/view",
        "moderation_state" => "ava_suggestion"
    ]);
}} else {{
    print json_encode(["success" => false, "error" => "Link not found in paragraphs"]);
}}
'''

        try:
            result = await client.auth.php_eval(php_code)
            if result.success and result.stdout.strip():
                import json
                try:
                    data = json.loads(result.stdout.strip())
                    if data.get("success"):
                        action_text = "Removed" if action == "remove" else f"Updated to {replacement_url}"
                        return DrupalFixResult(
                            success=True,
                            message=f"{action_text} broken link in paragraph {data.get('paragraph_id')}: {broken_link_url}",
                            node_id=f"node/{nid}",
                            revision_id=data.get("revision_id"),
                            revision_url=data.get("revision_url"),
                            moderation_state=data.get("moderation_state"),
                            original_value=broken_link_url,
                            new_value=replacement_url or "(removed)",
                        )
                    else:
                        return DrupalFixResult(
                            success=False,
                            message=data.get("error", "Unknown error"),
                            node_id=f"node/{nid}",
                            error=data.get("error"),
                        )
                except json.JSONDecodeError:
                    return DrupalFixResult(
                        success=False,
                        message=f"Invalid response: {result.stdout[:100]}",
                        error="JSON parse error",
                    )
            else:
                return DrupalFixResult(
                    success=False,
                    message=f"Drush error: {result.stderr or 'No output'}",
                    error=result.stderr,
                )
        except Exception as e:
            return DrupalFixResult(
                success=False,
                message=f"Paragraph link fix error: {e}",
                error=str(e),
            )

    async def fix_grammar_error(
        self,
        page_url: str,
        original_text: str,
        corrected_text: str,
        field_name: str = "body",
    ) -> DrupalFixResult:
        """Fix a grammar error in Drupal content.

        Same as fix_spelling_error but with different reason message.
        """
        try:
            client = await self._ensure_client()

            nid = self._extract_nid_from_url(page_url)
            if not nid:
                return DrupalFixResult(
                    success=False,
                    message=f"Could not extract node ID from URL: {page_url}",
                    error="Invalid URL format",
                )

            result: DraftRevision = await client.nodes.find_and_replace(
                nid=nid,
                field=field_name,
                find=original_text,
                replace=corrected_text,
                reason=f"Ava: Fixed grammar - '{original_text}' → '{corrected_text}'",
            )

            if result.success:
                return DrupalFixResult(
                    success=True,
                    message=f"Fixed grammar: '{original_text}' → '{corrected_text}'",
                    node_id=f"node/{nid}",
                    revision_id=result.revision_id,
                    revision_url=result.revision_url,
                    moderation_state=result.moderation_state,
                    original_value=original_text,
                    new_value=corrected_text,
                )
            else:
                return DrupalFixResult(
                    success=False,
                    message=f"Failed to fix grammar: {result.error}",
                    node_id=f"node/{nid}",
                    error=result.error,
                )

        except Exception as e:
            return DrupalFixResult(
                success=False,
                message=f"Drupal fix error: {e}",
                error=str(e),
            )

    def _extract_nid_from_url(self, url: str) -> Optional[int]:
        """Extract node ID from a Drupal URL.

        Handles various URL formats:
        - /node/123
        - /blog/my-post (needs URL alias resolution - returns None for now)
        - https://example.com/node/123

        For URL aliases, the orchestrator should use terminus drush to resolve.
        """
        # Try direct node path
        match = re.search(r"/node/(\d+)", url)
        if match:
            return int(match.group(1))

        # For URL aliases, we need the orchestrator to resolve via drush
        # Return None and let the orchestrator handle it
        return None

    async def resolve_url_to_nid(self, page_url: str) -> Optional[int]:
        """Resolve a URL alias to a node ID using Drush.

        Args:
            page_url: Full URL or path to resolve

        Returns:
            Node ID or None if not found
        """
        try:
            client = await self._ensure_client()

            # Extract path from URL
            path = page_url
            url_match = re.match(r"https?://[^/]+(/.*)$", path)
            if url_match:
                path = url_match.group(1)

            path = path.strip("/")

            # Use Drush to resolve the URL alias
            from drupal_editor.auth.terminus import TerminusAuth

            if isinstance(client.auth, TerminusAuth):
                php_code = f"""
$path = '/{path}';
$url = \\Drupal::service('path_alias.manager')->getPathByAlias($path);
if ($url && preg_match('/\\/node\\/(\\d+)/', $url, $matches)) {{
    print $matches[1];
}} else {{
    print '';
}}
"""
                result = await client.auth.php_eval(php_code)
                if result.success and result.stdout.strip().isdigit():
                    return int(result.stdout.strip())

            return None

        except Exception:
            return None

    async def close(self) -> None:
        """Clean up resources."""
        if self._client:
            await self._client.close()

    def get_summary(self) -> str:
        """Get a summary of all changes made."""
        if self._client:
            return self._client.get_summary()
        return "No changes made"


def fix_spelling_sync(
    page_url: str,
    original_text: str,
    corrected_text: str,
    field_name: str = "body",
) -> DrupalFixResult:
    """Synchronous wrapper for fix_spelling_error.

    Useful for calling from non-async code (like the orchestrator).
    """
    fixer = DrupalFixer()

    async def _run():
        try:
            result = await fixer.fix_spelling_error(
                page_url=page_url,
                original_text=original_text,
                corrected_text=corrected_text,
                field_name=field_name,
            )
            return result
        finally:
            await fixer.close()

    # Run in event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already in an async context, create a new task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _run())
                return future.result(timeout=60)
        else:
            return loop.run_until_complete(_run())
    except RuntimeError:
        # No event loop, create one
        return asyncio.run(_run())


def fix_broken_link_sync(
    page_url: str,
    broken_link_url: str,
    action: str = "remove",
    replacement_url: Optional[str] = None,
    field_name: str = "body",
) -> DrupalFixResult:
    """Synchronous wrapper for fix_broken_link.

    Useful for calling from non-async code (like the orchestrator).

    Args:
        page_url: URL of the page containing the broken link
        broken_link_url: The broken link URL to fix
        action: "remove" to remove link (keep text), "replace" to update URL
        replacement_url: New URL if action is "replace"
        field_name: Which field to search (default: "body")
    """
    fixer = DrupalFixer()

    async def _run():
        try:
            result = await fixer.fix_broken_link(
                page_url=page_url,
                broken_link_url=broken_link_url,
                action=action,
                replacement_url=replacement_url,
                field_name=field_name,
            )
            return result
        finally:
            await fixer.close()

    # Run in event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _run())
                return future.result(timeout=60)
        else:
            return loop.run_until_complete(_run())
    except RuntimeError:
        return asyncio.run(_run())


def rollback_revision_sync(
    nid: int,
    target_revision_id: Optional[int] = None,
) -> DrupalFixResult:
    """Rollback to a previous revision.

    If target_revision_id is not specified, rolls back to the revision
    before the most recent one.

    Args:
        nid: Node ID to rollback
        target_revision_id: Specific revision ID to rollback to (optional)
    """
    fixer = DrupalFixer()

    async def _run():
        try:
            client = await fixer._ensure_client()

            from drupal_editor.auth.terminus import TerminusAuth
            if not isinstance(client.auth, TerminusAuth):
                return DrupalFixResult(
                    success=False,
                    message="Rollback requires Terminus auth",
                    error="Not using Terminus",
                )

            if target_revision_id:
                # Rollback to specific revision
                php_code = f'''
$nid = {nid};
$target_vid = {target_revision_id};

$storage = \\Drupal::entityTypeManager()->getStorage("node");
$revision = $storage->loadRevision($target_vid);

if (!$revision) {{
    print json_encode(["success" => false, "error" => "Revision not found"]);
    return;
}}

// Set this revision as the new current revision
$revision->setNewRevision(TRUE);
$revision->isDefaultRevision(TRUE);
$revision->set("moderation_state", "ava_suggestion");
$revision->setRevisionLogMessage("Ava: Rolled back to revision " . $target_vid);
$revision->save();

$new_vid = $revision->getRevisionId();
$base_url = \\Drupal::request()->getSchemeAndHttpHost();
print json_encode([
    "success" => true,
    "revision_id" => $new_vid,
    "rolled_back_to" => $target_vid,
    "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $new_vid . "/view",
    "moderation_state" => "ava_suggestion"
]);
'''
            else:
                # Rollback to the revision before the current one
                php_code = f'''
$nid = {nid};

$storage = \\Drupal::entityTypeManager()->getStorage("node");
$node = $storage->load($nid);

if (!$node) {{
    print json_encode(["success" => false, "error" => "Node not found"]);
    return;
}}

// Get all revisions
$vids = $storage->revisionIds($node);
if (count($vids) < 2) {{
    print json_encode(["success" => false, "error" => "No previous revision to rollback to"]);
    return;
}}

// Get the second-to-last revision (the one before current)
$target_vid = $vids[count($vids) - 2];
$revision = $storage->loadRevision($target_vid);

if (!$revision) {{
    print json_encode(["success" => false, "error" => "Previous revision not found"]);
    return;
}}

// Set this revision as the new current revision
$revision->setNewRevision(TRUE);
$revision->isDefaultRevision(TRUE);
$revision->set("moderation_state", "ava_suggestion");
$revision->setRevisionLogMessage("Ava: Rolled back to revision " . $target_vid);
$revision->save();

$new_vid = $revision->getRevisionId();
$base_url = \\Drupal::request()->getSchemeAndHttpHost();
print json_encode([
    "success" => true,
    "revision_id" => $new_vid,
    "rolled_back_to" => $target_vid,
    "revision_url" => $base_url . "/node/" . $nid . "/revisions/" . $new_vid . "/view",
    "moderation_state" => "ava_suggestion"
]);
'''

            result = await client.auth.php_eval(php_code)
            if result.success and result.stdout.strip():
                import json
                try:
                    data = json.loads(result.stdout.strip())
                    if data.get("success"):
                        return DrupalFixResult(
                            success=True,
                            message=f"Rolled back to revision {data.get('rolled_back_to')}",
                            node_id=f"node/{nid}",
                            revision_id=data.get("revision_id"),
                            revision_url=data.get("revision_url"),
                            moderation_state=data.get("moderation_state"),
                        )
                    else:
                        return DrupalFixResult(
                            success=False,
                            message=data.get("error", "Unknown error"),
                            node_id=f"node/{nid}",
                            error=data.get("error"),
                        )
                except json.JSONDecodeError:
                    return DrupalFixResult(
                        success=False,
                        message=f"Invalid response: {result.stdout[:100]}",
                        error="JSON parse error",
                    )
            else:
                return DrupalFixResult(
                    success=False,
                    message=f"Drush error: {result.stderr or 'No output'}",
                    error=result.stderr,
                )
        except Exception as e:
            return DrupalFixResult(
                success=False,
                message=f"Rollback error: {e}",
                error=str(e),
            )
        finally:
            await fixer.close()

    # Run in event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _run())
                return future.result(timeout=60)
        else:
            return loop.run_until_complete(_run())
    except RuntimeError:
        return asyncio.run(_run())
