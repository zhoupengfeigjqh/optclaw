"""Tests for read_file_tool module."""

import pytest
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
import tempfile
import os

from read_file_tool import read_file_tool


class TestReadFileTool:
    """Test suite for read_file_tool function."""

    # ============================================================
    # Test Cases for Path Security Validation
    # ============================================================

    @patch("read_file_tool.resolve_virtual_path")
    def test_read_file_success(self, mock_resolve):
        """Test successful file reading with valid virtual path."""
        test_content = "Hello, World!\nThis is a test file."
        mock_resolve.return_value = "/tmp/test_file.txt"
        
        with patch("builtins.open", mock_open(read_data=test_content)):
            result = read_file_tool("/mnt/user-data/test.txt")
        
        assert result == test_content
        mock_resolve.assert_called_once_with("/mnt/user-data/test.txt")

    @patch("read_file_tool.resolve_virtual_path")
    def test_resolve_to_none_raises_value_error(self, mock_resolve):
        """Test that ValueError is raised when path resolves to None."""
        mock_resolve.return_value = None
        
        with pytest.raises(ValueError) as exc_info:
            read_file_tool("/unauthorized/path.txt")
        
        assert "resovle to None" in str(exc_info.value)
        assert "access denied for security reasons" in str(exc_info.value)

    # ============================================================
    # Test Cases for File Reading Errors
    # ============================================================

    @patch("read_file_tool.resolve_virtual_path")
    def test_file_not_found_raises_os_error(self, mock_resolve):
        """Test that FileNotFoundError is raised and re-raised with original path."""
        mock_resolve.return_value = "/tmp/nonexistent_file.txt"
        
        with patch("builtins.open", side_effect=FileNotFoundError(2, "No such file")):
            with pytest.raises(FileNotFoundError) as exc_info:
                read_file_tool("/mnt/user-data/nonexistent.txt")
            
            # Verify original path is preserved in error message
            assert exc_info.value.args[2] == "/mnt/user-data/nonexistent.txt"

    @patch("read_file_tool.resolve_virtual_path")
    def test_permission_error_preserves_original_path(self, mock_resolve):
        """Test that PermissionError is re-raised with original virtual path."""
        mock_resolve.return_value = "/root/protected_file.txt"
        
        with patch("builtins.open", side_effect=PermissionError(13, "Permission denied")):
            with pytest.raises(PermissionError) as exc_info:
                read_file_tool("/mnt/user-data/protected.txt")
            
            # Ensure original path is preserved, not the resolved path
            assert exc_info.value.args[2] == "/mnt/user-data/protected.txt"

    @patch("read_file_tool.resolve_virtual_path")
    def test_is_a_directory_error(self, mock_resolve):
        """Test that IsADirectoryError is handled correctly."""
        mock_resolve.return_value = "/tmp/directory"
        
        with patch("builtins.open", side_effect=IsADirectoryError(21, "Is a directory")):
            with pytest.raises(IsADirectoryError) as exc_info:
                read_file_tool("/mnt/user-data/directory")
            
            assert exc_info.value.args[2] == "/mnt/user-data/directory"

    # ============================================================
    # Test Cases for Edge Cases
    # ============================================================

    @patch("read_file_tool.resolve_virtual_path")
    def test_empty_file(self, mock_resolve):
        """Test reading an empty file returns empty string."""
        mock_resolve.return_value = "/tmp/empty_file.txt"
        
        with patch("builtins.open", mock_open(read_data="")):
            result = read_file_tool("/mnt/user-data/empty.txt")
        
        assert result == ""

    @patch("read_file_tool.resolve_virtual_path")
    def test_binary_content_raises_decode_error(self, mock_resolve):
        """Test that reading binary content raises UnicodeDecodeError."""
        mock_resolve.return_value = "/tmp/binary_file.bin"
        
        with patch("builtins.open", side_effect=UnicodeDecodeError("utf-8", b"\x00\x01", 0, 1, "invalid start byte")):
            with pytest.raises(UnicodeDecodeError):
                read_file_tool("/mnt/user-data/binary.bin")

    @patch("read_file_tool.resolve_virtual_path")
    def test_unicode_content(self, mock_resolve):
        """Test reading file with Unicode content."""
        unicode_content = "你好世界\nこんにちは世界\n🎉🎊"
        mock_resolve.return_value = "/tmp/unicode_file.txt"
        
        with patch("builtins.open", mock_open(read_data=unicode_content)):
            result = read_file_tool("/mnt/user-data/unicode.txt")
        
        assert result == unicode_content

    @patch("read_file_tool.resolve_virtual_path")
    def test_multiline_content(self, mock_resolve):
        """Test reading file with multiple lines."""
        multiline_content = "Line 1\nLine 2\nLine 3\nLine 4"
        mock_resolve.return_value = "/tmp/multiline_file.txt"
        
        with patch("builtins.open", mock_open(read_data=multiline_content)):
            result = read_file_tool("/mnt/user-data/multiline.txt")
        
        assert result == multiline_content

    @patch("read_file_tool.resolve_virtual_path")
    def test_special_characters_in_path(self, mock_resolve):
        """Test reading file with special characters in path."""
        test_content = "Content with special chars: !@#$%^&*()"
        mock_resolve.return_value = "/tmp/special_file.txt"
        
        with patch("builtins.open", mock_open(read_data=test_content)):
            result = read_file_tool("/mnt/user-data/special!@#.txt")
        
        assert result == test_content

    # ============================================================
    # Test Cases for Path Resolution Types
    # ============================================================

    @patch("read_file_tool.resolve_virtual_path")
    def test_container_skill_path(self, mock_resolve):
        """Test reading file with container skill path."""
        test_content = "Skill content"
        mock_resolve.return_value = "/skills/custom_skill/file.txt"
        
        with patch("builtins.open", mock_open(read_data=test_content)):
            result = read_file_tool("/skills/custom_skill/file.txt")
        
        assert result == test_content

    # ============================================================
    # Test Cases for Error Message Format
    # ============================================================

    @patch("read_file_tool.resolve_virtual_path")
    def test_error_message_contains_original_path(self, mock_resolve):
        """Verify error messages use original path, not resolved path."""
        mock_resolve.return_value = "/internal/real/path/to/file.txt"
        original_path = "/mnt/user-data/sensitive_file.txt"
        
        with patch("builtins.open", side_effect=OSError(0, "Test error")):
            with pytest.raises(OSError) as exc_info:
                read_file_tool(original_path)
            
            # Error should contain original path, not internal resolved path
            assert original_path in str(exc_info.value.args) or exc_info.value.args[2] == original_path
            assert "/internal/real/path" not in str(exc_info.value.args)

    # ============================================================
    # Test Cases for Large Files
    # ============================================================

    @patch("read_file_tool.resolve_virtual_path")
    def test_large_file(self, mock_resolve):
        """Test reading a large file content."""
        large_content = "x" * (1024 * 1024)  # 1MB of data
        mock_resolve.return_value = "/tmp/large_file.txt"
        
        with patch("builtins.open", mock_open(read_data=large_content)):
            result = read_file_tool("/mnt/user-data/large.txt")
        
        assert len(result) == 1024 * 1024

    # ============================================================
    # Test Cases for File Encoding
    # ============================================================

    @patch("read_file_tool.resolve_virtual_path")
    def test_encoding_parameter_is_utf8(self, mock_resolve):
        """Verify that files are opened with UTF-8 encoding."""
        mock_resolve.return_value = "/tmp/utf8_file.txt"
        
        mock_file = MagicMock()
        mock_file.read.return_value = "Test content"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        
        with patch("builtins.open", return_value=mock_file):
            read_file_tool("/mnt/user-data/utf8.txt")
            
            # Verify open was called with encoding='utf-8'
            from builtins import open as builtin_open
            builtin_open.assert_called_once()
            call_args = builtin_open.call_args
            assert call_args.kwargs.get('encoding') == 'utf-8' or \
                   (len(call_args.args) > 1 and 'encoding' in call_args.args[1])
