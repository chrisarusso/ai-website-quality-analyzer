# Website Quality Agent - Backlog

Future improvements and planned enhancements.

---

## Known Issues / Bugs

### Bug: Pages List Not Collapsible
**Problem:** The "Pages Crawled" section toggle doesn't work in HTML reports.

**Root cause:** CSS missing for `.hidden` class on pages list:
```css
.category-issues.hidden { display: none; }  /* exists */
/* .pages-list.hidden or generic .hidden is MISSING */
```

**Fix:** Add `.hidden { display: none; }` to the CSS or specifically `.pages-list.hidden { display: none; }`

---

## Short-Term Improvements

### Redirect Deduplication (Drupal-specific)
**Problem:** Pages like `/node/100` that redirect to `/blog/article-title` are currently crawled and analyzed as two separate pages, duplicating issues.

**Solution:**
- During crawl, track redirect chains
- If URL A redirects to URL B, only analyze URL B
- Store the redirect mapping for reference (so we know node/100 -> blog/article-title)
- In report, could note "X redirect URLs detected" but don't count them as separate pages
- Drupal-specific: detect `/node/\d+` pattern and follow redirects before analysis

**Implementation notes:**
- Playwright already follows redirects; need to capture the redirect chain
- Compare `page.url()` after navigation to the original URL to detect redirects
- Store `original_url` and `final_url` in page metadata
- Dedupe based on `final_url` when aggregating issues

### Header/Footer Content Deduplication
**Problem:** Headers and footers appear on every page. Issues in these areas (e.g., missing alt text on logo, empty link text on nav items) get reported once per page, creating hundreds of duplicate errors.

**Solution:**
- Extract header/footer content separately (detect `<header>`, `<footer>`, `<nav>`, or common class patterns like `.site-header`, `.site-footer`)
- Hash the content of these regions
- If the hash matches across pages, only analyze once
- Report issues as "Site-wide (header)" or "Site-wide (footer)" instead of per-page
- Count as 1 issue, not N issues (where N = number of pages)

**Implementation approach:**
1. After first page crawl, extract and hash header/footer HTML
2. On subsequent pages, compare hashes
3. If match, skip analysis of that region
4. Create a special "site-wide" category in issues
5. In report, show these separately: "Site-wide Issues (appear on all pages)"

**Edge cases:**
- Some pages may have different headers (e.g., homepage vs inner pages)
- Could group by hash and report "Found on X pages" for each variant
- May need fuzzy matching if minor differences (e.g., active nav state)

### Site-Wide Issue Grouping (Generalizing Header/Footer)
**Problem:** Some issues apply to every page (e.g., "No cookie consent mechanism detected", "Missing lang attribute") and get reported N times, inflating issue counts.

**Solution:**
- After analysis, identify issues that appear on 90%+ of pages with identical title/description
- Group these as "Site-Wide Issues" in a separate section at the top
- Count as 1 issue in totals, not N issues
- Show "Appears on X pages" instead of listing each URL
- Examples: cookie consent, lang attribute, missing privacy policy link, social icons without aria-labels

**Implementation:**
1. After aggregating all issues, hash by `(title, description, element)`
2. If an issue hash appears on >90% of pages, mark as site-wide
3. In report, show site-wide section first with deduplicated issues
4. Remaining per-page issues shown normally

### SEO Check Calibration
**Problem:** Our custom SEO checks are more aggressive than Lighthouse. Some checks flag issues Lighthouse doesn't consider problems, leading to inflated issue counts and potential false positives.

**Checks to review:**
- "Meta description too short" (<70 chars) - Lighthouse only flags missing, not short
- "No structured data" - Lighthouse doesn't flag this at all
- "No Open Graph tags" / "Incomplete Open Graph tags" - Lighthouse doesn't flag
- Title length thresholds (30-60 chars) - may be too strict

**Options:**
1. **Reduce severity:** Change these from Medium/Low to "Info" or remove scoring impact
2. **Make configurable:** Allow "strict" vs "lighthouse-compatible" mode
3. **Remove:** Drop checks that Lighthouse doesn't validate
4. **Keep but document:** Label as "best practices beyond Lighthouse"

**Recommendation:** Create a separate "Best Practices" or "Recommendations" category that doesn't affect the score, only reports opportunities.

---

## Future Quality Checks

After MVP, expand to cover additional quality checks organized by category:

### Content Quality (Expanded)
- Reading level analysis (Flesch-Kincaid score)
- Passive voice detection
- Sentence length distribution
- Word complexity/jargon detection
- Cliches and buzzwords
- Brand voice consistency
- Outdated content detection (stale dates, past events)
- Placeholder text detection ("Lorem ipsum", "Coming soon")
- Missing/weak CTAs
- Value proposition clarity

### SEO (Expanded)
- Twitter Card validation
- Schema.org markup validation
- FAQ schema opportunities
- How-to schema opportunities
- Local business schema
- Breadcrumb schema
- XML sitemap validation
- Redirect chains and loops
- Soft 404 detection
- URL structure analysis
- Trailing slash consistency
- Parameter canonicalization
- Hreflang for multilingual sites
- Internal linking depth analysis
- Anchor text distribution
- Image filename optimization
- Next-gen image formats (WebP, AVIF)

### Accessibility (Expanded)
- Skip navigation links
- Focus management
- ARIA live regions
- Accessible modals/dialogs
- Table accessibility
- PDF accessibility
- Video captions and audio descriptions
- Touch target size validation
- Motion/animation (prefers-reduced-motion)
- Reading order (visual vs DOM)

### Security (Expanded)
- Content Security Policy analysis
- Cookie security (HttpOnly, Secure, SameSite)
- CORS misconfiguration
- Clickjacking protection (X-Frame-Options)
- HSTS configuration
- API key exposure in JavaScript
- Directory listing detection
- Backup file exposure (.bak, .old, .zip)
- Source control exposure (.git/)
- Debug mode detection
- Verbose error messages
- Open redirects
- DOM-based XSS patterns

### Performance (Expanded)
- Time to First Byte (TTFB)
- First Contentful Paint (FCP)
- Time to Interactive (TTI)
- Render-blocking resource detection
- Unused CSS/JS detection
- Image lazy loading validation
- Font loading optimization
- Browser caching headers
- CDN usage detection
- HTTP/2 or HTTP/3 usage
- Preconnect/prefetch opportunities
- Third-party script impact

### UX/Usability
- 404 page quality
- Search functionality presence
- Navigation depth (clicks to content)
- Breadcrumb presence
- Consistent navigation
- Mobile menu functionality
- Form validation feedback
- Error message clarity
- Print styles

### Technical/Code Quality
- W3C HTML validation
- CSS validation
- Console errors
- Deprecated API usage
- Outdated library detection
- Known vulnerable dependencies

### Compliance (Expanded)
- Privacy policy completeness
- Cookie policy completeness
- Terms of service presence
- Data collection transparency
- Industry-specific compliance indicators (HIPAA, PCI-DSS)

### Brand & Marketing
- Social media links validation
- Contact information completeness
- Trust signals (testimonials, certifications)
- Newsletter signup presence

### AI Engine Optimization (AEO/GEO)
- FAQ content format
- Q&A schema markup
- Citation-worthy content
- Source attribution
- Expert author signals (E-E-A-T)
- Content freshness dates
- Topic coverage depth

---

## Open Questions

- [ ] How to handle CommonCrawl integration for blocked sites?
- [ ] What's the right scan depth limit for freemium tier?
- [ ] How to price for different site sizes (pages)?
- [ ] Should we integrate with existing SEO tools (Screaming Frog, Ahrefs)?
