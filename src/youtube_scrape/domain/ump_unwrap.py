"""Unwrap YouTube UMP (Universal Media Protocol) format to clean DASH fMP4.

YouTube's player downloads DASH fragments wrapped in a protobuf-based UMP format.
This module unwraps UMP containers to extract clean moof+mdat fragments.
"""

from __future__ import annotations

import struct


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Read a protobuf varint from data. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            return 0, offset
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if not (byte & 0x80):
            break
        shift += 7
        if shift > 64:
            return 0, offset
    return result, offset


def _find_box_positions(data: bytes, box_type: bytes, start: int = 0) -> list[tuple[int, int]]:
    """Find all positions of a box type with valid size. Returns list of (offset, size)."""
    positions = []
    offset = start
    while True:
        pos = data.find(box_type, offset)
        if pos == -1:
            break
        # Check for size field before the box type
        if pos >= 4:
            try:
                size = struct.unpack(">I", data[pos-4:pos])[0]
                # Validate size is reasonable
                if 8 <= size <= 100_000_000 and pos - 4 + size <= len(data):
                    positions.append((pos - 4, size))
            except struct.error:
                pass
        offset = pos + 1
    return positions


def _unwrap_ump_mdat_content(mdat_content: bytes) -> bytes:
    """Unwrap UMP protobuf wrappers from within mdat content.
    
    YouTube wraps AV1 data in UMP (Universal Media Protocol) protobuf messages
    inside the mdat boxes. This function extracts the clean AV1 data.
    
    Args:
        mdat_content: Raw bytes from inside an mdat box (after the 8-byte header).
        
    Returns:
        Clean media data with UMP wrappers removed.
    """
    import struct
    
    if not mdat_content:
        return b""
    
    # Check if there are any UMP markers in the data
    if b'\x3a' not in mdat_content:
        # No UMP markers, return as-is
        return mdat_content
    
    # Count how many UMP markers we have
    ump_count = mdat_content.count(b'\x3a')
    
    # If few UMP markers, might be false positives in AV1 data
    if ump_count < 10:
        return mdat_content
    
    # Data has UMP wrappers - need to unwrap
    # Strategy: scan for AV1 temporal units (0x12) and extract them,
    # skipping any UMP wrappers (0x3a)
    
    result = bytearray()
    offset = 0
    
    while offset < len(mdat_content) - 2:
        byte = mdat_content[offset]
        
        if byte == 0x12:
            # Found AV1 temporal unit start
            # Read the OBU header to determine size
            # AV1 OBU format: obu_header (1-2 bytes) + obu_size (leb128) + obu_payload
            
            # Parse OBU header
            obu_header = byte
            obu_forbidden_bit = (obu_header >> 7) & 1
            obu_type = (obu_header >> 3) & 0xF
            obu_extension_flag = (obu_header >> 2) & 1
            obu_has_size_field = (obu_header >> 1) & 1
            
            if obu_forbidden_bit == 0 and obu_type in [1, 2, 3, 4, 5, 6, 7, 8, 15]:
                # Valid OBU header
                obu_start = offset
                obu_offset = offset + 1
                
                # Skip extension header if present
                if obu_extension_flag:
                    obu_offset += 1
                
                # Read OBU size (leb128)
                obu_size = 0
                shift = 0
                while obu_offset < len(mdat_content):
                    size_byte = mdat_content[obu_offset]
                    obu_size |= (size_byte & 0x7F) << shift
                    obu_offset += 1
                    if not (size_byte & 0x80):
                        break
                    shift += 7
                    if shift > 56:
                        break
                
                # Total OBU size = header + (optional extension) + size field + payload
                obu_total_size = obu_offset - obu_start + obu_size
                
                if obu_total_size > 0 and obu_start + obu_total_size <= len(mdat_content):
                    # Extract this OBU
                    result.extend(mdat_content[obu_start:obu_start + obu_total_size])
                    offset = obu_start + obu_total_size
                    continue
        
        elif byte == 0x3a:
            # Found UMP marker - skip it and its content
            # Read the varint size
            size_offset = offset + 1
            msg_size = 0
            shift = 0
            varint_bytes = 0
            
            while size_offset < len(mdat_content) and varint_bytes < 5:
                size_byte = mdat_content[size_offset]
                msg_size |= (size_byte & 0x7F) << shift
                size_offset += 1
                varint_bytes += 1
                if not (size_byte & 0x80):
                    break
                shift += 7
            
            # Skip over the UMP message
            if 0 < msg_size < 500000 and size_offset + msg_size <= len(mdat_content):
                offset = size_offset + msg_size
                continue
        
        offset += 1
    
    # Return extracted clean data
    if len(result) > 100:
        return bytes(result)
    
    return mdat_content


def unwrap_ump_to_fragments(ump_data: bytes) -> bytes:
    """Extract clean moof+mdat fragments from UMP-wrapped data.

    Args:
        ump_data: Raw UMP-wrapped bytes (typically after sidx in YouTube DASH).

    Returns:
        Concatenated moof+mdat boxes suitable for appending to DASH init.
    """
    # Find all moof boxes - these mark the start of fragments
    moof_positions = _find_box_positions(ump_data, b"moof")

    if not moof_positions:
        return b""

    fragments = bytearray()

    for moof_offset, moof_size in moof_positions:
        # Extract moof box as-is
        moof_data = ump_data[moof_offset:moof_offset + moof_size]
        fragments.extend(moof_data)

        # Find following mdat box
        mdat_start = moof_offset + moof_size
        mdat_positions = _find_box_positions(ump_data, b"mdat", mdat_start)

        if mdat_positions:
            # Use the first mdat after this moof
            mdat_offset, mdat_size = mdat_positions[0]
            # Ensure this mdat is close to the moof (same fragment)
            if mdat_offset < moof_offset + moof_size + 1000:  # Within 1KB
                # Extract mdat header + content
                mdat_full = ump_data[mdat_offset:mdat_offset + mdat_size]
                mdat_header = mdat_full[:8]  # Size (4) + 'mdat' (4)
                mdat_content = mdat_full[8:]
                
                # Unwrap UMP from mdat content
                clean_content = _unwrap_ump_mdat_content(mdat_content)
                
                # Rebuild mdat with clean content
                new_size = 8 + len(clean_content)
                new_mdat = struct.pack(">I", new_size) + b"mdat" + clean_content
                fragments.extend(new_mdat)

    return bytes(fragments)


def extract_init_segment(data: bytes) -> bytes:
    """Extract the DASH init segment (ftyp + moov) from captured data.

    Args:
        data: Raw captured bytes.

    Returns:
        ftyp + moov boxes, or empty if not found.
    """
    # Find ftyp box
    ftyp_positions = _find_box_positions(data, b"ftyp")
    if not ftyp_positions:
        return b""

    ftyp_offset, ftyp_size = ftyp_positions[0]
    init_end = ftyp_offset + ftyp_size

    # Look for moov after ftyp
    moov_positions = _find_box_positions(data, b"moov", init_end)
    if moov_positions:
        moov_offset, moov_size = moov_positions[0]
        # Check if moov is contiguous or close to ftyp
        if moov_offset <= init_end + 100:
            init_end = moov_offset + moov_size

    return data[ftyp_offset:init_end]


def extract_sidx_segment(data: bytes) -> bytes | None:
    """Extract sidx box if present.

    Args:
        data: Raw captured bytes.

    Returns:
        sidx box bytes or None.
    """
    sidx_positions = _find_box_positions(data, b"sidx")
    if sidx_positions:
        offset, size = sidx_positions[0]
        return data[offset:offset + size]
    return None


def unwrap_ump_media_file(captured_data: bytes) -> bytes:
    """Convert UMP-wrapped capture to clean DASH fMP4 file.

    This is the main entry point for converting captured YouTube media data
    into a playable file.

    Args:
        captured_data: Raw bytes captured from YouTube (includes UMP wrapping).

    Returns:
        Clean DASH fMP4 file with init + fragments.
    """
    # Extract init segment
    init = extract_init_segment(captured_data)
    if not init:
        return b""

    # Try to get sidx (optional but helps with indexing)
    sidx = extract_sidx_segment(captured_data)

    # Find where UMP data starts (after init and sidx)
    ump_start = len(init)
    if sidx:
        ump_start = max(ump_start, len(init) + len(sidx))

    # Find first moof to determine actual fragment start
    moof_positions = _find_box_positions(captured_data, b"moof", ump_start)
    if moof_positions:
        # UMP data starts before first moof
        first_moof_offset = moof_positions[0][0]
        ump_data = captured_data[ump_start:first_moof_offset] + captured_data[first_moof_offset:]
    else:
        ump_data = captured_data[ump_start:]

    # Unwrap fragments
    fragments = unwrap_ump_to_fragments(captured_data)

    # Assemble final file
    result = bytearray(init)
    if sidx:
        result.extend(sidx)
    result.extend(fragments)

    return bytes(result)


def try_ffmpeg_repair(input_path: str, output_path: str) -> bool:
    """Try to repair DASH file using ffmpeg remux.

    First attempts -c copy (fast), then falls back to transcoding if needed.

    Args:
        input_path: Path to input DASH file.
        output_path: Path to output repaired file.

    Returns:
        True if successful, False otherwise.
    """
    import subprocess
    import shutil
    from pathlib import Path

    if shutil.which("ffmpeg") is None:
        return False

    # First try: -c copy (fast remux)
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-fflags", "+genpts+igndts",
                "-i", input_path,
                "-c", "copy",
                "-movflags", "+faststart",
                "-f", "mp4",
                output_path,
                "-y",
            ],
            capture_output=True,
            timeout=120,
        )
        if result.returncode == 0 and Path(output_path).exists():
            return True
    except Exception:
        pass

    # Second try: Transcode to H.264 (slower but fixes bitstream issues)
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-fflags", "+genpts+igndts",
                "-i", input_path,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-movflags", "+faststart",
                "-f", "mp4",
                output_path,
                "-y",
            ],
            capture_output=True,
            timeout=300,
        )
        return result.returncode == 0 and Path(output_path).exists()
    except Exception:
        return False
