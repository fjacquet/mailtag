# Domain-Based Classification Strategy

## Overview

This document describes the new 3-pass email classification system that introduces domain-based classification to dramatically improve performance by reducing AI API calls by 80-90%.

## Current vs New System

### Current System (2-Pass)

1. **Pass 1**: Pattern-based classification (fast)
2. **Pass 2**: AI classification (slow, individual emails)

### New System (3-Pass)

1. **Pass 1**: Pattern-based classification (unchanged)
2. **Pass 2**: Domain-based classification (NEW)
3. **Pass 3**: AI classification (renamed from Pass 2, only for unknowns)

## Pass 2: Domain-Based Classification Details

### Strategy

Many emails come from the same domains (newsletters, services, notifications). If we know that emails from `service@ifolor.ch` should go to `Services/Online/ifolor`, then ALL emails from the `ifolor.ch` domain should go to the same category.

### Algorithm

1. **Collect Senders**: Gather all email senders from emails remaining after Pass 1
2. **Group by Domain**: Extract domain from email addresses and group emails
3. **Filter Non-Commercial**: Exclude personal email providers (gmail.com, yahoo.com, etc.) from domain-based rules
4. **Deduplicate**: For each remaining domain, select at most 3 representative emails for qualification
5. **Domain Lookup**: Check if the domain exists in our historical classification database
6. **Batch Classify**: If domain found, apply the same category to ALL emails from that domain
7. **Fallback**: If domain not found or is non-commercial, keep emails for Pass 3 (AI classification)

### Expected Performance Impact

- **Reduction in AI calls**: 80-90% fewer API calls
- **Faster processing**: Domain lookup is much faster than AI classification
- **Consistent categorization**: All emails from same domain get same category
- **Cost savings**: Fewer AI API calls = lower costs

### Examples

**Commercial Domains (Domain-based classification applies):**

- All emails from `@todoist.com` → `Services/Professional/Todoist`
- All emails from `@ifolor.ch` → `Services/Online/ifolor`
- All emails from `@fnac.com` → `Services/Online/FNAC`
- All emails from `@bloomberg.com` → `Finance/Online/Bloomberg`

**Non-Commercial Domains (Skip to Pass 3 - AI classification):**

- Emails from `@gmail.com` → Individual AI classification (no domain rule)
- Emails from `@yahoo.com` → Individual AI classification (no domain rule)
- Emails from `@outlook.com` → Individual AI classification (no domain rule)
- Emails from `@bluewin.ch` → Individual AI classification (no domain rule)

## Implementation Requirements

### Non-Commercial Domains Configuration

Personal email providers are excluded from domain-based classification:

```yaml
# data/non_commercial_domains.yaml
non_commercial_domains:
  - gmail.com
  - yahoo.com
  - outlook.com
  - bluewin.ch
  # ... more providers
```

### Database Schema

Need to store domain → category mappings (excluding non-commercial domains):

```json
{
  "domain_classifications": {
    "todoist.com": "Services/Professional/Todoist",
    "ifolor.ch": "Services/Online/ifolor",
    "fnac.com": "Services/Online/FNAC",
    "bloomberg.com": "Finance/Online/Bloomberg"
  }
}
```

### Domain Extraction

Extract domain from email addresses:

- `service@ifolor.ch` → `ifolor.ch`
- `noreply@todoist.com` → `todoist.com`
- `notifications@github.com` → `github.com`

### Deduplication Logic

For each remaining domain, select at most 3 emails to avoid processing hundreds of similar emails:

- Prefer emails with different subjects
- Prefer more recent emails
- Ensure representative sample

## Integration Points

### Database Updates

- Extend `ClassificationDatabase` to store domain mappings
- Add methods for domain lookup and storage
- Migrate existing classifications to build initial domain database

### Classifier Updates

- Add new `_get_category_from_domain()` method
- Modify `classify_email()` to include domain-based pass
- Update logging and metrics

### Task Runner Updates

- Modify `run_classification()` to implement 3-pass system
- Add domain grouping and deduplication logic
- Update progress reporting

## Benefits

1. **Performance**: 80-90% reduction in AI calls
2. **Consistency**: Same domain always gets same category
3. **Cost**: Lower AI API costs
4. **Speed**: Domain lookup is near-instant vs AI calls
5. **Scalability**: System scales better with large email volumes

## Risks and Mitigations

### Risk: Domain Too Broad

Some domains might send different types of emails (e.g., `google.com`)

**Mitigation**: Use subdomain or sender-specific matching when needed

### Risk: Personal Email Providers

Personal email domains (gmail.com, yahoo.com) host millions of different users

**Mitigation**: Maintain non-commercial domains list and exclude from domain-based rules

### Risk: Category Changes

Domain classification might become outdated

**Mitigation**: Allow manual override and periodic review of domain mappings

### Risk: New Subdomains

New subdomains might not match existing domain rules

**Mitigation**: Implement fuzzy domain matching for related subdomains
