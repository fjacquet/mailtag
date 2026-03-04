# MailTag Classification Improvements Specification

**Version**: 1.0  
**Date**: 2025-11-22  
**Status**: Planning Phase  
**Branch**: `feature/classification-improvements`

---

## Executive Summary

This specification outlines improvements to the MailTag email classification system based on a comprehensive analysis of the current AMSC (Adaptive Multi-Signal Classification) architecture. The improvements are prioritized into three tiers based on impact and effort, with an initial focus on measurement, confidence scoring, and database expansion.

### Current State

- ✅ Sophisticated 5-signal hierarchical classification (AMSC)
- ✅ Efficient 3-pass processing system for IMAP
- ✅ Domain-based classification reducing AI calls by 80-90%
- ❌ No classification accuracy tracking or metrics
- ❌ AI confidence scoring configured but not implemented
- ❌ Limited use of email content and metadata
- ❌ No feedback loop for continuous improvement

### Success Metrics

- **Accuracy**: Track classification accuracy per signal (baseline → target)
- **Performance**: Reduce AI fallback rate from ~20% to <10%
- **Quality**: Achieve >95% confidence on 80%+ of classifications
- **Coverage**: Expand domain DB from 58 to 150+ commercial domains

---

## Implementation Tiers

### Tier 1: Foundation & Quick Wins (Week 1-2)

**Goal**: Enable measurement and utilize existing infrastructure

1. ✅ AI Confidence Scoring
2. ✅ Classification Metrics System
3. ✅ Domain Database Expansion
4. ✅ Enhanced Email Body Utilization

### Tier 2: Intelligence & Features (Week 3-4)

**Goal**: Improve classification quality through better features and prompts

1. ⏳ Advanced Prompt Engineering
2. ⏳ Feature Engineering (temporal, content, metadata)
3. ⏳ Semantic Similarity Classification
4. ⏳ User Feedback Loop

### Tier 3: Advanced ML & Optimization (Future)

**Goal**: Production ML system with continuous learning

1. 🔮 Multi-Model Ensemble
2. 🔮 Active Learning System
3. 🔮 Category Optimization
4. 🔮 Real-Time Accuracy Dashboard

---

## Tier 1: Detailed Specifications

### 1. AI Confidence Scoring

#### Current State

- Configuration exists: `ai_confidence_threshold = 0.98` in `config.toml`
- AI model returns only category name (no confidence)
- No uncertainty handling beyond "À Classer" for parse errors

#### Proposed Changes

**1.1 Update AI Prompt to Request Confidence**

**File**: `src/mailtag/classifier.py`

```python
# BEFORE (line ~200)
prompt = (
    f"Sujet: {email.subject}\n"
    f"De: {sender}\n"
    f"Corps: {truncated_body}\n\n"
    "Classe dans une catégorie FEUILLE...\n"
    "IMPORTANT: Réponds UNIQUEMENT avec le nom exact...\n"
)

# AFTER
prompt = (
    f"Sujet: {email.subject}\n"
    f"De: {sender}\n"
    f"Corps: {truncated_body}\n\n"
    "Classe dans une catégorie FEUILLE (catégorie de dernier niveau):\n"
    f"{category_list}\n\n"
    "Si la catégorie appropriée n'existe pas, propose un nouveau sous-dossier.\n\n"
    "IMPORTANT: Réponds en format JSON structuré:\n"
    '{\n'
    '  "category": "NomExactCategorie",\n'
    '  "confidence": 0.95,\n'
    '  "reason": "brève explication (optionnel)"\n'
    '}\n\n'
    "- category: nom exact de la liste ou 'Parent/NewSub'\n"
    "- confidence: score entre 0.0 et 1.0\n"
    "- reason: pourquoi cette catégorie (1 phrase courte)\n"
)
```

**1.2 Parse JSON Response with Error Handling**

```python
def _get_category_from_ai(self, email: Email) -> str | None:
    """Get category from AI model with confidence scoring."""
    
    # ... existing cache check ...
    
    response = completion(
        model=self.model_name,
        messages=[{"role": "user", "content": prompt}],
        api_base=self.api_base,
        max_tokens=150,  # Increased for JSON response
        temperature=0.2,
        num_ctx=2048,
    )
    
    raw_response = response.choices[0].message.content.strip()
    
    # Parse JSON response
    try:
        import json
        import re
        
        # Extract JSON from response (handles markdown code blocks)
        json_match = re.search(r'\{[^}]+\}', raw_response)
        if json_match:
            result = json.loads(json_match.group(0))
            category = result.get("category", "").strip()
            confidence = float(result.get("confidence", 0.0))
            reason = result.get("reason", "")
            
            # Log confidence and reason
            logger.debug(f"AI classification: {category} (confidence: {confidence:.2f}, reason: {reason})")
            
            # Track in metrics
            if hasattr(self, 'metrics'):
                self.metrics.record("classification.ai_confidence", confidence)
                self.metrics.increment(f"classification.ai_category.{category}")
            
            # Check against threshold
            if confidence < self.config.classifier.ai_confidence_threshold:
                logger.info(f"AI confidence {confidence:.2f} below threshold {self.config.classifier.ai_confidence_threshold}, routing to 'À Classer'")
                self.metrics.increment("classification.ai_low_confidence")
                return "À Classer"
            
            # Validate category exists
            if category not in self.categories_set and "/" not in category:
                logger.warning(f"AI suggested invalid category: {category}")
                return "À Classer"
            
            return category
            
        else:
            # Fallback to old parsing if JSON not found
            logger.warning(f"AI response not JSON format: {raw_response[:100]}")
            return self._parse_legacy_response(raw_response)
            
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error(f"Failed to parse AI response: {e}, raw: {raw_response[:100]}")
        self.metrics.increment("classification.ai_parse_error")
        return "À Classer"

def _parse_legacy_response(self, response: str) -> str | None:
    """Fallback parser for non-JSON responses."""
    # Keep existing parsing logic as fallback
    category = response.strip()
    if category in self.categories_set or "/" in category:
        return category
    return "À Classer"
```

**1.3 Configuration Update**

**File**: `config.toml`

```toml
[classifier]
ai_confidence_threshold = 0.85  # Lowered from 0.98 (was too strict)
historical_confidence_threshold = 0.9
min_count = 10
request_ai_reasoning = true  # New: request explanation from AI
```

#### Testing Requirements

- ✅ Unit test: JSON parsing with valid/invalid responses
- ✅ Integration test: Full classification with confidence scoring
- ✅ Edge cases: Malformed JSON, missing fields, out-of-range confidence
- ✅ Backward compatibility: Legacy string responses still work

#### Success Criteria

- All AI classifications include confidence score
- Low-confidence emails (<0.85) route to "À Classer"
- Confidence distribution tracked in metrics
- No regression in classification accuracy

---

### 2. Classification Metrics System

#### Current State

- Excellent performance metrics (timing, memory, call counts)
- Zero classification quality metrics
- No signal effectiveness tracking
- No category distribution analysis

#### Proposed Changes

**2.1 Extend Metrics System**

**File**: `src/mailtag/metrics.py`

```python
# Add new metric types
class ClassificationMetrics:
    """Metrics specific to email classification quality."""
    
    def __init__(self):
        self.signal_hits = Counter()  # Which signal classified email
        self.category_distribution = Counter()  # Category usage
        self.confidence_scores = defaultdict(list)  # Confidence per signal
        self.errors = Counter()  # Error types
        self.processing_times = defaultdict(list)  # Time per signal
        
    def record_classification(
        self,
        email_id: str,
        signal: str,  # validated_db, server_labels, historical, domain, ai
        category: str,
        confidence: float | None = None,
        processing_time_ms: float = 0.0
    ):
        """Record a successful classification."""
        self.signal_hits[signal] += 1
        self.category_distribution[category] += 1
        
        if confidence is not None:
            self.confidence_scores[signal].append(confidence)
        
        if processing_time_ms > 0:
            self.processing_times[signal].append(processing_time_ms)
    
    def record_error(self, error_type: str, context: str = ""):
        """Record classification error."""
        self.errors[f"{error_type}:{context}"] += 1
    
    def get_signal_hit_rates(self) -> dict[str, float]:
        """Calculate percentage of emails classified by each signal."""
        total = sum(self.signal_hits.values())
        if total == 0:
            return {}
        return {
            signal: (count / total) * 100
            for signal, count in self.signal_hits.items()
        }
    
    def get_summary(self) -> dict:
        """Get comprehensive metrics summary."""
        total_classified = sum(self.signal_hits.values())
        
        return {
            "total_classified": total_classified,
            "signal_hit_rates": self.get_signal_hit_rates(),
            "top_categories": dict(self.category_distribution.most_common(10)),
            "avg_confidence_by_signal": {
                signal: statistics.mean(scores) if scores else 0.0
                for signal, scores in self.confidence_scores.items()
            },
            "avg_processing_time_ms": {
                signal: statistics.mean(times) if times else 0.0
                for signal, times in self.processing_times.items()
            },
            "errors": dict(self.errors.most_common()),
            "timestamp": datetime.now().isoformat()
        }
    
    def export_to_json(self, filepath: Path):
        """Export metrics to JSON file."""
        with open(filepath, 'w') as f:
            json.dump(self.get_summary(), f, indent=2)
    
    def reset(self):
        """Reset all counters."""
        self.signal_hits.clear()
        self.category_distribution.clear()
        self.confidence_scores.clear()
        self.errors.clear()
        self.processing_times.clear()
```

**2.2 Integrate into Classifier**

**File**: `src/mailtag/classifier.py`

```python
from mailtag.metrics import ClassificationMetrics

class EmailClassifier:
    def __init__(self, config: Config):
        # ... existing init ...
        self.classification_metrics = ClassificationMetrics()
    
    def classify_email(self, email: Email) -> str:
        """Classify email using AMSC strategy with metrics tracking."""
        import time
        
        start_time = time.perf_counter()
        
        # Signal 1: Validated DB
        category = self._get_category_from_validated_db(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self.classification_metrics.record_classification(
                email.msg_id, 
                signal="validated_db",
                category=category,
                confidence=1.0,  # Validated = 100% confidence
                processing_time_ms=elapsed_ms
            )
            return category
        
        # Signal 2: Server-side labels
        category = self._get_category_from_labels(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self.classification_metrics.record_classification(
                email.msg_id,
                signal="server_labels",
                category=category,
                confidence=0.95,  # High confidence from user's organization
                processing_time_ms=elapsed_ms
            )
            # Still update suggestion DB
            self.database.update_suggestion(email.sender_address, category)
            return category
        
        # Signal 3: Historical DB
        category = self._get_category_from_history(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            # Calculate actual confidence
            sender_classifications = self.database.suggestion_db.get(email.sender_address, {})
            total_count = sum(sender_classifications.values())
            confidence = sender_classifications.get(category, 0) / total_count if total_count > 0 else 0.0
            
            self.classification_metrics.record_classification(
                email.msg_id,
                signal="historical_db",
                category=category,
                confidence=confidence,
                processing_time_ms=elapsed_ms
            )
            return category
        
        # Signal 4: Domain classification
        category = self._get_category_from_domain(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self.classification_metrics.record_classification(
                email.msg_id,
                signal="domain_db",
                category=category,
                confidence=0.90,  # Domain rules are high confidence
                processing_time_ms=elapsed_ms
            )
            self.database.update_suggestion(email.sender_address, category)
            return category
        
        # Signal 5: AI classification
        category = self._get_category_from_ai(email)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        if category and category != "À Classer":
            # Confidence already recorded in _get_category_from_ai
            self.classification_metrics.record_classification(
                email.msg_id,
                signal="ai_model",
                category=category,
                confidence=None,  # Already tracked internally
                processing_time_ms=elapsed_ms
            )
            self.database.update_suggestion(email.sender_address, category)
        else:
            self.classification_metrics.record_error("ai_uncertain", email.sender_address)
            category = "À Classer"
        
        return category
    
    def export_metrics(self, output_dir: Path = Path("data/metrics")):
        """Export classification metrics to file."""
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = output_dir / f"classification_metrics_{timestamp}.json"
        self.classification_metrics.export_to_json(filepath)
        logger.info(f"Exported classification metrics to {filepath}")
        return filepath
```

**2.3 Add Metrics Reporting**

**File**: `src/mailtag/utils/tasks.py`

```python
def run_classification_with_metrics(provider: EmailProvider, classifier: EmailClassifier):
    """Run classification and generate metrics report."""
    
    # ... existing classification logic ...
    
    # After classification completes
    summary = classifier.classification_metrics.get_summary()
    
    logger.info("=" * 60)
    logger.info("CLASSIFICATION METRICS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total emails classified: {summary['total_classified']}")
    logger.info("")
    logger.info("Signal Hit Rates:")
    for signal, rate in summary['signal_hit_rates'].items():
        logger.info(f"  {signal:20s}: {rate:6.2f}%")
    logger.info("")
    logger.info("Top 10 Categories:")
    for category, count in list(summary['top_categories'].items())[:10]:
        logger.info(f"  {category:40s}: {count:4d} emails")
    logger.info("")
    logger.info("Average Confidence by Signal:")
    for signal, conf in summary['avg_confidence_by_signal'].items():
        logger.info(f"  {signal:20s}: {conf:.3f}")
    logger.info("")
    
    if summary['errors']:
        logger.warning("Classification Errors:")
        for error, count in summary['errors'].items():
            logger.warning(f"  {error}: {count}")
    
    # Export to file
    filepath = classifier.export_metrics()
    logger.info(f"Full metrics exported to: {filepath}")
    logger.info("=" * 60)
```

#### Testing Requirements

- ✅ Unit tests for ClassificationMetrics methods
- ✅ Integration test: Full classification run with metrics
- ✅ Verify metrics export format
- ✅ Test signal hit rate calculations

#### Success Criteria

- Every classification recorded with signal type
- Metrics summary generated after each run
- JSON export includes all required fields
- Performance overhead <5ms per email

---

### 3. Domain Database Expansion

#### Current State

- 58 commercial domains in `db/domain_classifications.json`
- Pass 3 manual matching files contain uncategorized commercial domains
- ~20% of emails still fall through to AI

#### Proposed Changes

**3.1 Analyze Pass 3 Manual Matching Files**

**File**: `src/mailtag/utils/domain_analyzer.py` (NEW)

```python
"""Analyze Pass 3 manual matching files to identify domain classification candidates."""

import json
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
import re

from loguru import logger


@dataclass
class DomainCandidate:
    """Candidate domain for classification."""
    domain: str
    email_count: int
    unique_senders: set[str]
    sample_senders: list[str]
    suggested_category: str | None = None
    confidence: float = 0.0


class DomainAnalyzer:
    """Analyze email data to find domain classification opportunities."""
    
    def __init__(self, non_commercial_domains_path: Path):
        """Initialize with non-commercial domains to exclude."""
        import yaml
        with open(non_commercial_domains_path) as f:
            self.non_commercial = set(yaml.safe_load(f))
    
    def analyze_pass3_files(self, data_dir: Path) -> list[DomainCandidate]:
        """Analyze all Pass 3 manual matching files."""
        
        # Aggregate data from all Pass 3 files
        domain_data = defaultdict(lambda: {
            'count': 0,
            'senders': set(),
            'sender_list': []
        })
        
        for filepath in data_dir.glob("pass3_manual_matching_*.json"):
            logger.info(f"Processing {filepath.name}")
            
            with open(filepath) as f:
                data = json.load(f)
            
            for sender, count in data.items():
                # Extract domain
                domain = self._extract_domain(sender)
                if not domain or domain in self.non_commercial:
                    continue
                
                domain_data[domain]['count'] += count
                domain_data[domain]['senders'].add(sender)
                domain_data[domain]['sender_list'].append(sender)
        
        # Convert to candidates
        candidates = []
        for domain, data in domain_data.items():
            if data['count'] >= 5:  # At least 5 emails from domain
                candidate = DomainCandidate(
                    domain=domain,
                    email_count=data['count'],
                    unique_senders=data['senders'],
                    sample_senders=list(data['senders'])[:5]
                )
                candidates.append(candidate)
        
        # Sort by email count
        candidates.sort(key=lambda c: c.email_count, reverse=True)
        
        logger.info(f"Found {len(candidates)} domain candidates")
        return candidates
    
    def _extract_domain(self, email: str) -> str | None:
        """Extract domain from email address."""
        match = re.search(r'@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})$', email.lower())
        return match.group(1) if match else None
    
    def export_candidates(self, candidates: list[DomainCandidate], output_path: Path):
        """Export candidates to JSON for manual review."""
        
        export_data = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_candidates": len(candidates),
                "total_emails": sum(c.email_count for c in candidates)
            },
            "candidates": [
                {
                    "domain": c.domain,
                    "email_count": c.email_count,
                    "unique_senders": len(c.unique_senders),
                    "sample_senders": c.sample_senders,
                    "suggested_category": c.suggested_category or "REVIEW_NEEDED",
                    "confidence": c.confidence
                }
                for c in candidates
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Exported {len(candidates)} candidates to {output_path}")
    
    def generate_report(self, candidates: list[DomainCandidate]) -> str:
        """Generate human-readable report."""
        
        lines = [
            "=" * 80,
            "DOMAIN CLASSIFICATION CANDIDATES",
            "=" * 80,
            f"Total candidates: {len(candidates)}",
            f"Total emails: {sum(c.email_count for c in candidates)}",
            "",
            "Top 50 Domains by Email Count:",
            "-" * 80,
            f"{'Domain':<30} {'Emails':>8} {'Senders':>8} Sample",
            "-" * 80
        ]
        
        for candidate in candidates[:50]:
            sample = candidate.sample_senders[0] if candidate.sample_senders else ""
            lines.append(
                f"{candidate.domain:<30} {candidate.email_count:>8} "
                f"{len(candidate.unique_senders):>8} {sample}"
            )
        
        lines.extend([
            "-" * 80,
            "",
            "Next Steps:",
            "1. Review domain_candidates.json",
            "2. For each domain, determine appropriate category",
            "3. Add to db/domain_classifications.json",
            "4. Re-run classification to measure impact",
            ""
        ])
        
        return "\n".join(lines)
```

**3.2 CLI Command for Domain Analysis**

**File**: `src/main.py`

```python
@click.command()
@click.option('--output', default='data/domain_candidates.json', help='Output file path')
def analyze_domains(output: str):
    """Analyze Pass 3 files to identify domain classification candidates."""
    from mailtag.utils.domain_analyzer import DomainAnalyzer
    
    config = load_config()
    analyzer = DomainAnalyzer(
        non_commercial_domains_path=Path("data/non_commercial_domains.yaml")
    )
    
    candidates = analyzer.analyze_pass3_files(Path("data"))
    analyzer.export_candidates(candidates, Path(output))
    
    report = analyzer.generate_report(candidates)
    print(report)
    
    logger.info(f"Review {output} and add entries to db/domain_classifications.json")

# Add to CLI
cli.add_command(analyze_domains)
```

**3.3 Batch Domain Update Script**

**File**: `scripts/update_domain_db.py` (NEW)

```python
#!/usr/bin/env python3
"""Helper script to batch update domain classifications."""

import json
from pathlib import Path

def update_domain_db(candidates_file: Path, domain_db_file: Path):
    """Update domain DB with reviewed candidates."""
    
    # Load candidates with manual categories added
    with open(candidates_file) as f:
        data = json.load(f)
    
    # Load existing domain DB
    with open(domain_db_file) as f:
        domain_db = json.load(f)
    
    # Add new entries
    added = 0
    for candidate in data['candidates']:
        domain = candidate['domain']
        category = candidate.get('suggested_category', '').strip()
        
        # Skip if no category or placeholder
        if not category or category in ['REVIEW_NEEDED', '']:
            continue
        
        # Add to DB
        if domain not in domain_db:
            domain_db[domain] = category
            added += 1
            print(f"Added: {domain} → {category}")
    
    # Save updated DB
    with open(domain_db_file, 'w') as f:
        json.dump(domain_db, f, indent=2, sort_keys=True)
    
    print(f"\nAdded {added} new domain classifications")
    print(f"Total domains in DB: {len(domain_db)}")

if __name__ == '__main__':
    update_domain_db(
        Path('data/domain_candidates.json'),
        Path('db/domain_classifications.json')
    )
```

#### Workflow

1. Run `python src/main.py analyze-domains`
2. Review `data/domain_candidates.json`
3. For each candidate, add `suggested_category` field
4. Run `python scripts/update_domain_db.py`
5. Re-run classification to measure impact

#### Testing Requirements

- ✅ Unit test: Domain extraction from email addresses
- ✅ Unit test: Non-commercial domain filtering
- ✅ Integration test: Full analysis pipeline
- ✅ Verify JSON export format

#### Success Criteria

- Identify 50+ new commercial domains from Pass 3 files
- Reduce AI fallback rate by 50%+
- Domain DB grows from 58 to 150+ entries

---

### 4. Enhanced Email Body Utilization

#### Current State

- Email body truncated to 500 characters
- Simple truncation loses important context
- Headers and footers waste token budget

#### Proposed Changes

**4.1 Smart Body Extraction**

**File**: `src/mailtag/utils/text_utils.py` (NEW)

```python
"""Text extraction and processing utilities."""

import re
from typing import Tuple


def smart_truncate(body: str, max_chars: int = 1500) -> str:
    """Intelligently truncate email body to preserve important content.
    
    Strategy:
    1. Extract first 2 paragraphs (likely main message)
    2. Find sentences with high-signal keywords
    3. Remove email signatures and disclaimers
    4. Combine and truncate to max_chars
    """
    
    # Remove quoted replies (lines starting with >)
    lines = [line for line in body.split('\n') if not line.strip().startswith('>')]
    clean_body = '\n'.join(lines)
    
    # Remove common email signatures
    signature_patterns = [
        r'\n--\s*\n.*',  # Standard signature delimiter
        r'\nSent from my .*',
        r'\nGet Outlook for .*',
        r'\n_{10,}.*',  # Underline separators
        r'\nBest regards,.*',
        r'\nCordialement,.*',
    ]
    for pattern in signature_patterns:
        clean_body = re.sub(pattern, '', clean_body, flags=re.DOTALL | re.IGNORECASE)
    
    # Extract paragraphs
    paragraphs = [p.strip() for p in clean_body.split('\n\n') if p.strip()]
    
    # High-signal keywords that indicate important content
    keywords = [
        'invoice', 'facture', 'payment', 'paiement',
        'order', 'commande', 'delivery', 'livraison',
        'confirm', 'confirmer', 'receipt', 'reçu',
        'subscription', 'abonnement', 'renewal', 'renouvellement',
        'account', 'compte', 'password', 'mot de passe',
        'security', 'sécurité', 'alert', 'alerte',
        'meeting', 'réunion', 'appointment', 'rendez-vous',
        'unsubscribe', 'désabonner'
    ]
    
    # Collect important sentences
    important_sentences = []
    for para in paragraphs[:3]:  # First 3 paragraphs
        sentences = re.split(r'[.!?]\s+', para)
        for sentence in sentences:
            if any(kw in sentence.lower() for kw in keywords):
                important_sentences.append(sentence)
    
    # Build result: first paragraphs + important sentences
    result_parts = paragraphs[:2]  # First 2 paragraphs
    if important_sentences:
        result_parts.append(" ".join(important_sentences[:3]))  # Top 3 important sentences
    
    result = "\n\n".join(result_parts)
    
    # Final truncation
    if len(result) > max_chars:
        result = result[:max_chars] + "..."
    
    return result


def extract_urls(body: str) -> list[str]:
    """Extract all URLs from email body."""
    url_pattern = r'https?://[^\s<>"\']+'
    return re.findall(url_pattern, body)


def count_links(body: str) -> int:
    """Count number of links in email."""
    return len(extract_urls(body))


def has_unsubscribe_link(body: str) -> bool:
    """Check if email contains unsubscribe link (newsletter indicator)."""
    return bool(re.search(r'unsubscribe|désabonner|se désinscrire', body, re.IGNORECASE))
```

**4.2 Update Classifier to Use Smart Truncation**

**File**: `src/mailtag/classifier.py`

```python
from mailtag.utils.text_utils import smart_truncate

class EmailClassifier:
    def _get_category_from_ai(self, email: Email) -> str | None:
        """Get category from AI model."""
        
        # OLD:
        # truncated_body = email.body[:500]
        
        # NEW:
        truncated_body = smart_truncate(email.body, max_chars=1500)
        
        # ... rest of method unchanged ...
```

**4.3 Configuration Update**

**File**: `config.toml`

```toml
[classifier]
ai_confidence_threshold = 0.85
historical_confidence_threshold = 0.9
min_count = 10
request_ai_reasoning = true
max_body_chars = 1500  # New: configurable body truncation
```

#### Testing Requirements

- ✅ Unit tests for smart_truncate with various email formats
- ✅ Test signature removal
- ✅ Test keyword extraction
- ✅ Test URL extraction
- ✅ Integration test: Classification accuracy improvement

#### Success Criteria

- Extract 1500 chars vs 500 chars (3x more context)
- Remove signatures and boilerplate
- Preserve high-signal sentences
- No performance degradation

---

## Configuration Changes Summary

### Updated `config.toml`

```toml
[general]
ollama_model = "gemma3n"
ollama_api_url = "${OLLAMA_API_URL}"
use_imap_folders_for_classification = true

[classifier]
# Confidence thresholds
ai_confidence_threshold = 0.85  # Lowered from 0.98 (more realistic)
historical_confidence_threshold = 0.9
min_count = 10

# AI behavior
request_ai_reasoning = true  # NEW: Request explanations
max_body_chars = 1500  # NEW: Configurable truncation (was hardcoded 500)

[classification_metrics]  # NEW SECTION
enabled = true
export_on_completion = true
export_directory = "data/metrics"
log_interval_minutes = 5  # Log metrics summary every 5 minutes

[imap]
server = "imap.example.com"
username = "${IMAP_USER}"
password = "${IMAP_PASSWORD}"
# ... rest unchanged ...
```

---

## Database Schema Changes

### Classification Metrics Export Schema

**File**: `data/metrics/classification_metrics_YYYYMMDD_HHMMSS.json`

```json
{
  "total_classified": 1523,
  "signal_hit_rates": {
    "validated_db": 15.3,
    "server_labels": 8.2,
    "historical_db": 45.1,
    "domain_db": 22.4,
    "ai_model": 9.0
  },
  "top_categories": {
    "Services/Professional/LinkedIn": 234,
    "Finance/Banking/UBS": 187,
    "Shopping/Online": 156
  },
  "avg_confidence_by_signal": {
    "validated_db": 1.0,
    "server_labels": 0.95,
    "historical_db": 0.92,
    "domain_db": 0.90,
    "ai_model": 0.78
  },
  "avg_processing_time_ms": {
    "validated_db": 0.8,
    "server_labels": 1.2,
    "historical_db": 1.5,
    "domain_db": 1.8,
    "ai_model": 1247.3
  },
  "errors": {
    "ai_uncertain:sender@example.com": 12,
    "ai_parse_error": 3
  },
  "timestamp": "2025-11-22T14:32:15.123456"
}
```

### Domain Candidates Export Schema

**File**: `data/domain_candidates.json`

```json
{
  "metadata": {
    "generated_at": "2025-11-22T14:30:00",
    "total_candidates": 127,
    "total_emails": 3456
  },
  "candidates": [
    {
      "domain": "linkedin.com",
      "email_count": 456,
      "unique_senders": 3,
      "sample_senders": [
        "noreply@linkedin.com",
        "messages@linkedin.com",
        "jobs@linkedin.com"
      ],
      "suggested_category": "Services/Professional/LinkedIn",
      "confidence": 0.95
    }
  ]
}
```

---

## Testing Strategy

### Unit Tests

**New test files:**

- `tests/test_classification_metrics.py` - Metrics system
- `tests/test_domain_analyzer.py` - Domain analysis
- `tests/test_text_utils.py` - Smart truncation
- `tests/test_ai_confidence.py` - JSON response parsing

### Integration Tests

**Updated test files:**

- `tests/test_classifier.py` - Add confidence scoring tests
- `tests/test_tasks.py` - Add metrics reporting tests

### Test Data

**New fixtures:**

- `tests/fixtures/ai_responses.json` - Sample AI JSON responses
- `tests/fixtures/email_bodies.txt` - Various email formats for truncation tests
- `tests/fixtures/pass3_sample.json` - Sample Pass 3 data

### Coverage Goals

- Maintain 80%+ overall coverage
- 100% coverage for new metrics code
- 90%+ coverage for AI response parsing

---

## Rollout Plan

### Phase 1: Development (Week 1)

- [ ] Day 1-2: Implement AI confidence scoring + tests
- [ ] Day 3-4: Implement classification metrics + tests
- [ ] Day 5: Code review + refinement

### Phase 2: Domain Expansion (Week 2)

- [ ] Day 1-2: Implement domain analyzer + tests
- [ ] Day 3: Run analysis on existing Pass 3 files
- [ ] Day 4-5: Manual review + domain DB update

### Phase 3: Testing & Validation (Week 2)

- [ ] Integration testing with real email data
- [ ] Performance regression testing
- [ ] Metrics validation
- [ ] Documentation updates

### Phase 4: Deployment

- [ ] Merge to main branch
- [ ] Run on production data
- [ ] Generate first metrics report
- [ ] Measure improvement vs baseline

---

## Success Metrics & KPIs

### Baseline (Current State)

- AI fallback rate: ~20% (estimated)
- No confidence tracking
- No classification quality metrics
- Domain DB: 58 entries
- Body usage: 500 chars

### Target (After Tier 1)

- AI fallback rate: <10% (50% reduction)
- Confidence tracking: 100% of AI classifications
- Signal hit rates: Measured and tracked
- Domain DB: 150+ entries (160% increase)
- Body usage: 1500 chars (3x improvement)

### Monitoring

- Weekly classification metrics reports
- Monthly accuracy audits
- Quarterly domain DB review
- Continuous confidence distribution tracking

---

## Risks & Mitigation

### Risk 1: AI Model Not Returning JSON

**Impact**: Medium  
**Probability**: Medium  
**Mitigation**: Fallback to legacy string parsing, monitor parse error rate

### Risk 2: Performance Degradation from Longer Prompts

**Impact**: Low  
**Probability**: Medium  
**Mitigation**: Benchmark before/after, adjust max_body_chars if needed

### Risk 3: Incorrect Domain Categorization

**Impact**: Medium  
**Probability**: Low  
**Mitigation**: Manual review workflow, easy rollback via git

### Risk 4: Metrics Overhead

**Impact**: Low  
**Probability**: Low  
**Mitigation**: Performance tests, optional metrics disabling

---

## Dependencies

### Code Dependencies

- No new external packages required
- Uses existing: litellm, loguru, pydantic

### Configuration Dependencies

- Requires updated config.toml
- Backward compatible with old configs

### Data Dependencies

- Existing Pass 3 manual matching files
- Existing domain classifications DB

---

## Documentation Updates

### Files to Update

- [x] `CLASSIFICATION_IMPROVEMENTS_SPEC.md` (this file)
- [ ] `CLAUDE.md` - Add Tier 1 improvements description
- [ ] `README.md` - Add new CLI commands
- [ ] `docs/metrics.md` - New file documenting metrics system
- [ ] `docs/domain_analysis.md` - New file for domain workflow

### Code Documentation

- Add docstrings to all new functions
- Update existing docstrings where behavior changes
- Add inline comments for complex logic

---

## Future Work (Tier 2 & 3)

### Tier 2 Preview (Week 3-4)

- Advanced prompt engineering with few-shot examples
- Feature engineering (temporal, content, metadata)
- Semantic similarity classification
- User feedback loop

### Tier 3 Preview (Future)

- Multi-model ensemble
- Active learning system
- Category optimization
- Real-time accuracy dashboard

See separate specifications for Tier 2 and Tier 3 when ready to proceed.

---

## Appendix

### A. File Changes Checklist

**New Files:**

- [ ] `src/mailtag/utils/text_utils.py`
- [ ] `src/mailtag/utils/domain_analyzer.py`
- [ ] `scripts/update_domain_db.py`
- [ ] `tests/test_classification_metrics.py`
- [ ] `tests/test_domain_analyzer.py`
- [ ] `tests/test_text_utils.py`
- [ ] `tests/test_ai_confidence.py`
- [ ] `tests/fixtures/ai_responses.json`
- [ ] `tests/fixtures/email_bodies.txt`

**Modified Files:**

- [ ] `src/mailtag/classifier.py` - AI confidence, metrics integration
- [ ] `src/mailtag/metrics.py` - Add ClassificationMetrics class
- [ ] `src/mailtag/utils/tasks.py` - Add metrics reporting
- [ ] `src/main.py` - Add analyze-domains command
- [ ] `config.toml` - Update configuration
- [ ] `CLAUDE.md` - Document new features
- [ ] `README.md` - Update CLI documentation

### B. Commands Reference

```bash
# Run domain analysis
python src/main.py analyze-domains --output data/domain_candidates.json

# Update domain DB after manual review
python scripts/update_domain_db.py

# Run classification with metrics
python src/main.py run --provider imap

# View metrics report
cat data/metrics/classification_metrics_*.json | jq .

# Run tests
uv run pytest tests/test_classification_metrics.py -v
uv run pytest tests/test_domain_analyzer.py -v
uv run pytest tests/test_text_utils.py -v
uv run pytest --cov --cov-branch
```

### C. References

- Current AMSC implementation: `src/mailtag/classifier.py`
- Three-pass system: `src/mailtag/utils/tasks.py`
- Domain utilities: `src/mailtag/utils/domain_utils.py`
- Classification database: `src/mailtag/database.py`
- Configuration: `config.toml`

---

**End of Specification**
