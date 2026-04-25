"""Assemble DASH fMP4 fragments using byte range requests.

This module implements proper DASH segment assembly by:
1. Parsing the sidx (segment index) box to understand fragment structure
2. Making range requests for each fragment
3. Assembling into a complete playable file
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any


@dataclass
class SegmentInfo:
    """Information about a single DASH segment."""
    start_byte: int
    end_byte: int
    duration: float
    referenced_size: int


def parse_sidx_box(data: bytes, offset: int, size: int) -> list[SegmentInfo]:
    """Parse sidx (segment index) box to get segment information.

    The sidx box contains the mapping of time ranges to byte ranges for DASH segments.
    """
    if size < 24:
        return []

    # Read version and flags
    version = data[offset + 8]
    flags = struct.unpack(">I", data[offset + 8:offset + 12])[0] & 0xFFFFFF

    # Reference ID (4 bytes)
    reference_id = struct.unpack(">I", data[offset + 12:offset + 16])[0]

    # Timescale (4 bytes) - ticks per second
    timescale = struct.unpack(">I", data[offset + 16:offset + 20])[0]
    if timescale == 0:
        timescale = 1

    # Read earliest presentation time and first offset based on version
    if version == 0:
        earliest_time = struct.unpack(">I", data[offset + 20:offset + 24])[0]
        first_offset = struct.unpack(">I", data[offset + 24:offset + 28])[0]
        ref_count_offset = offset + 28
    else:  # version == 1
        earliest_time = struct.unpack(">Q", data[offset + 20:offset + 28])[0]
        first_offset = struct.unpack(">Q", data[offset + 28:offset + 36])[0]
        ref_count_offset = offset + 36

    # Reserved (2 bytes)
    # Reference count (2 bytes)
    if ref_count_offset + 4 > offset + size:
        return []

    ref_count = struct.unpack(">H", data[ref_count_offset + 2:ref_count_offset + 4])[0]

    segments: list[SegmentInfo] = []
    # The first_offset is relative to the first byte AFTER the sidx box
    # So the first segment starts at: sidx_end_offset + first_offset
    sidx_end_offset = offset + size
    current_offset = sidx_end_offset + first_offset

    # Each reference is 12 bytes
    ref_data_start = ref_count_offset + 4
    for i in range(ref_count):
        if ref_data_start + 12 > offset + size:
            break

        ref_data = data[ref_data_start:ref_data_start + 12]

        # Parse reference
        # First 4 bits: reference_type (1 bit) + referenced_size (31 bits)
        first_word = struct.unpack(">I", ref_data[0:4])[0]
        reference_type = (first_word >> 31) & 1
        referenced_size = first_word & 0x7FFFFFFF

        # Duration (4 bytes, unsigned)
        subsegment_duration = struct.unpack(">I", ref_data[4:8])[0]

        # Flags (4 bytes) - includes sap info
        flags = struct.unpack(">I", ref_data[8:12])[0]

        # Calculate byte range (absolute file positions)
        start_byte = current_offset
        end_byte = current_offset + referenced_size - 1

        # Calculate duration in seconds
        duration = subsegment_duration / timescale

        segments.append(SegmentInfo(
            start_byte=start_byte,
            end_byte=end_byte,
            duration=duration,
            referenced_size=referenced_size
        ))

        current_offset += referenced_size
        ref_data_start += 12

    return segments


def find_sidx_box(data: bytes) -> tuple[int, int] | None:
    """Find sidx box in data. Returns (offset, size) or None."""
    # Limit search to first 500KB - sidx is typically early in DASH files
    search_limit = min(len(data), 500_000)
    offset = 0
    while offset < search_limit - 8:
        if offset + 8 > search_limit:
            break

        try:
            size = struct.unpack(">I", data[offset:offset + 4])[0]
            box_type = data[offset + 4:offset + 8]
        except (struct.error, IndexError):
            break

        if size == 0:
            size = search_limit - offset
        elif size == 1:
            if offset + 16 > search_limit:
                break
            try:
                size = struct.unpack(">Q", data[offset + 8:offset + 16])[0]
            except struct.error:
                break

        if box_type == b"sidx":
            return offset, size

        if size < 8 or offset + size > search_limit:
            offset += 1
        else:
            offset += size

    return None


def get_fragment_byte_ranges(captured_data: bytes, base_offset: int = 0) -> list[tuple[int, int]]:
    """Get byte ranges for all fragments from sidx.

    Args:
        captured_data: Data containing sidx box
        base_offset: Base offset to add to all byte ranges (for range requests)

    Returns:
        List of (start, end) byte tuples for each fragment
    """
    sidx_info = find_sidx_box(captured_data)
    if not sidx_info:
        return []

    offset, size = sidx_info
    segments = parse_sidx_box(captured_data, offset, size)

    # Convert to byte ranges with base offset
    ranges = []
    for seg in segments:
        # The sidx first_offset is relative to the first byte after the moof+mdat pair
        # For range requests, we need absolute file positions
        ranges.append((seg.start_byte + base_offset, seg.end_byte + base_offset))

    return ranges


def calculate_full_size_from_sidx(captured_data: bytes) -> int | None:
    """Calculate expected full file size from sidx box.

    This helps determine how much data we're missing.
    """
    sidx_info = find_sidx_box(captured_data)
    if not sidx_info:
        return None

    offset, size = sidx_info
    segments = parse_sidx_box(captured_data, offset, size)

    if not segments:
        return None

    # Total size is the end of the last segment + any init data before sidx
    last_seg_end = segments[-1].end_byte
    return last_seg_end + 1


def estimate_content_length(captured_data: bytes) -> int | None:
    """Estimate the total content length from sidx or other indicators."""
    # Try sidx first
    full_size = calculate_full_size_from_sidx(captured_data)
    if full_size:
        return full_size

    # Fallback: look for content-range header pattern in the data
    # This would require storing headers during capture
    return None
