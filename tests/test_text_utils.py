"""Tests for text processing utilities."""

from mailtag.utils.text_utils import (
    _remove_signatures,
    smart_truncate,
)


class TestSmartTruncate:
    """Test smart truncation functionality."""

    def test_truncate_short_text(self):
        """Test that short text is not truncated."""
        text = "This is a short email."
        result = smart_truncate(text, max_chars=100)
        assert result == text

    def test_truncate_empty_text(self):
        """Test empty text handling."""
        assert smart_truncate("", max_chars=100) == ""
        assert smart_truncate(None, max_chars=100) == ""

    def test_truncate_removes_quoted_replies(self):
        """Test that quoted replies are removed."""
        text = """Hello,

This is my message.

> This is a quoted reply
> Another quoted line

More content here."""

        result = smart_truncate(text, max_chars=500)
        # Main goal: preserve important content
        assert "This is my message" in result
        assert "More content here" in result

    def test_truncate_removes_signatures(self):
        """Test that email signatures are removed."""
        text = """Hello,

This is the main message.

--
Best regards,
John Doe
Company Name"""

        result = smart_truncate(text, max_chars=500)
        assert "This is the main message" in result
        # Main goal: important content is preserved

    def test_truncate_preserves_keywords(self):
        """Test that high-signal keywords are preserved."""
        text = """Some initial text here.

Random paragraph without keywords.

Another paragraph also without special words.

This contains an important invoice for your payment.

Final paragraph."""

        result = smart_truncate(text, max_chars=200)
        # Should include the paragraph with "invoice" and "payment" keywords
        assert "invoice" in result.lower()

    def test_truncate_respects_max_chars(self):
        """Test that result respects max_chars limit."""
        text = "A" * 5000
        result = smart_truncate(text, max_chars=1500)
        assert len(result) <= 1503  # 1500 + "..."

    def test_truncate_paragraph_extraction(self):
        """Test that first paragraphs are extracted."""
        text = """First paragraph here.

Second paragraph with content.

Third paragraph.

Fourth paragraph.

Fifth paragraph."""

        result = smart_truncate(text, max_chars=500)
        assert "First paragraph" in result
        assert "Second paragraph" in result
        # Later paragraphs may or may not be included depending on space


class TestRemoveSignatures:
    """Test signature removal."""

    def test_remove_standard_signature(self):
        """Test removing standard -- signature."""
        text = """Email content

--
Signature here"""
        result = _remove_signatures(text)
        assert "Signature here" not in result
        assert "Email content" in result

    def test_remove_sent_from_signature(self):
        """Test removing 'Sent from' signatures."""
        text = """Email content

Sent from my iPhone"""
        result = _remove_signatures(text)
        assert "Sent from" not in result

    def test_remove_outlook_signature(self):
        """Test removing Outlook signatures."""
        text = """Email content

Get Outlook for Android"""
        result = _remove_signatures(text)
        assert "Get Outlook" not in result

    def test_remove_closing_phrases(self):
        """Test removing common closing phrases."""
        text = """Email content

Best regards,
John"""
        result = _remove_signatures(text)
        assert "Best regards" not in result

    def test_remove_french_closings(self):
        """Test removing French closing phrases."""
        text = """Contenu de l'email

Cordialement,
Jean"""
        result = _remove_signatures(text)
        assert "Cordialement" not in result


class TestIntegration:
    """Test integration scenarios."""

    def test_newsletter_processing(self):
        """Test processing a typical newsletter."""
        body = """Dear Subscriber,

Here is your weekly newsletter.

Top stories:
- Story 1 https://example.com/1
- Story 2 https://example.com/2
- Story 3 https://example.com/3
- Story 4 https://example.com/4
- Story 5 https://example.com/5
- Story 6 https://example.com/6

--
Unsubscribe: https://example.com/unsub
This is an automated email. Do not reply.
Sent from Newsletter System"""

        # Smart truncate should remove signature
        truncated = smart_truncate(body, max_chars=200)
        assert "Unsubscribe" not in truncated
        assert "Do not reply" not in truncated
        assert "Sent from" not in truncated

    def test_invoice_email_processing(self):
        """Test processing an invoice email."""
        body = """Hello,

Your invoice #12345 for $100.00 is ready.

Please process payment at your earliest convenience.

Details:
- Amount: $100.00
- Due date: 2025-12-01

> Previous conversation:
> > Thanks for your order

Best regards,
Billing Team"""

        # Smart truncate should preserve invoice info
        truncated = smart_truncate(body, max_chars=300)
        assert "invoice" in truncated.lower()
        assert "payment" in truncated.lower()
