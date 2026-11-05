import pytest
from app.preproc.utils.pii import detect_pii

class TestPIIDetector:
    def test_national_id_detected(self):
        """Should detect Vietnamese national ID (9-12 digits)"""
        text = "CCCD: 001234567890"
        contains, types = detect_pii(text)
        assert contains is True
        assert "national_id" in types
    
    def test_phone_detected(self):
        """Should detect Vietnamese phone numbers"""
        # Standard mobile format
        text1 = "Liên hệ: 0912345678"
        contains, types = detect_pii(text1)
        assert contains is True
        assert "phone" in types
        
        # International format
        text2 = "Call +84912345678"
        contains, types = detect_pii(text2)
        assert contains is True
        assert "phone" in types
    
    def test_email_detected(self):
        """Should detect email addresses"""
        text = "Contact: user@example.com for info"
        contains, types = detect_pii(text)
        assert contains is True
        assert "email" in types
    
    def test_multiple_pii_types(self):
        """Should detect multiple PII types in same text"""
        text = "CCCD 123456789012, SĐT 0987654321, email: test@gov.vn"
        contains, types = detect_pii(text)
        assert contains is True
        assert "national_id" in types
        assert "phone" in types
        assert "email" in types
        assert len(types) == 3
    
    def test_clean_text_no_pii(self):
        """Should return False for text without PII"""
        text = "This is a clean legal document about land regulations."
        contains, types = detect_pii(text)
        assert contains is False
        assert types == []
    
    def test_empty_text(self):
        """Should handle empty text gracefully"""
        contains, types = detect_pii("")
        assert contains is False
        assert types == []
    
    def test_false_positive_reduction(self):
        """Numbers in context should not always trigger (conservative)"""
        # This is borderline - our current regex will catch it
        # If needed, we can add more sophisticated context checks
        text = "Article 123 section 456"
        contains, types = detect_pii(text)
        # Current implementation: this will NOT match (too short)
        # 9+ digits needed
        assert contains is False
