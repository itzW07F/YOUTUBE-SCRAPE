"""Fix DASH fMP4 moof/mdat alignment for captured YouTube fragments.

YouTube's DASH player captures fragments where the moof sample tables may not
perfectly align with the mdat content due to partial captures or UMP unwrapping.
This module repairs the sample size tables in moof boxes to match actual mdat data.
"""

from __future__ import annotations

import struct
from typing import Any


def _read_box(data: bytes, offset: int) -> tuple[str, int, int, int] | None:
    """Read a box from data. Returns (type, size, start_offset, end_offset) or None."""
    if offset + 8 > len(data):
        return None

    size = struct.unpack(">I", data[offset:offset+4])[0]
    box_type = data[offset+4:offset+8].decode("latin-1", errors="ignore")

    if size == 0:
        size = len(data) - offset
    elif size == 1:
        if offset + 16 > len(data):
            return None
        size = struct.unpack(">Q", data[offset+8:offset+16])[0]

    if size < 8 or offset + size > len(data):
        return None

    return box_type, size, offset, offset + size


def _find_box(data: bytes, box_type: str, start: int = 0) -> tuple[int, int] | None:
    """Find a box by type. Returns (offset, size) or None."""
    offset = start
    while offset < len(data) - 8:
        result = _read_box(data, offset)
        if result is None:
            break
        found_type, size, box_start, box_end = result
        if found_type == box_type:
            return box_start, size
        # For containers, search inside too (but carefully)
        if found_type in ("moof", "traf"):
            inner = _find_box(data[box_start+8:box_end], box_type, 0)
            if inner:
                return box_start + 8 + inner[0], inner[1]
        offset = box_end
    return None


def _parse_trun(data: bytes, offset: int, size: int) -> dict[str, Any]:
    """Parse track run (trun) box."""
    if size < 12:
        return {}

    # Read version and flags
    version = data[offset + 8]
    flags = struct.unpack(">I", data[offset + 8:offset + 12])[0] & 0xFFFFFF

    # Sample count
    sample_count = struct.unpack(">I", data[offset + 12:offset + 16])[0]

    # Data offset (if present)
    data_offset_present = flags & 0x01
    sample_duration_present = flags & 0x0100
    sample_size_present = flags & 0x0200
    sample_flags_present = flags & 0x0400
    sample_cts_present = flags & 0x0800

    result = {
        "version": version,
        "flags": flags,
        "sample_count": sample_count,
        "data_offset": None,
        "samples": [],
        "offset": offset,
        "size": size,
    }

    pos = offset + 16

    if data_offset_present:
        if pos + 4 <= offset + size:
            result["data_offset"] = struct.unpack(">i", data[pos:pos+4])[0]
            pos += 4

    # Read sample entries
    for _ in range(sample_count):
        sample = {}
        if sample_duration_present:
            if pos + 4 <= offset + size:
                sample["duration"] = struct.unpack(">I", data[pos:pos+4])[0]
                pos += 4
        if sample_size_present:
            if pos + 4 <= offset + size:
                sample["size"] = struct.unpack(">I", data[pos:pos+4])[0]
                pos += 4
        if sample_flags_present:
            if pos + 4 <= offset + size:
                sample["flags"] = struct.unpack(">I", data[pos:pos+4])[0]
                pos += 4
        if sample_cts_present:
            if pos + 4 <= offset + size:
                sample["cts"] = struct.unpack(">I", data[pos:pos+4])[0]
                pos += 4
        result["samples"].append(sample)

    return result


def _build_trun(original: dict[str, Any], new_samples: list[dict[str, Any]]) -> bytes:
    """Build a new trun box with fixed sample sizes."""
    version = original["version"]
    flags = original["flags"]

    # Rebuild flags based on what we have in samples
    sample_duration_present = any("duration" in s for s in new_samples)
    sample_size_present = any("size" in s for s in new_samples)
    sample_flags_present = any("flags" in s for s in new_samples)
    sample_cts_present = any("cts" in s for s in new_samples)
    data_offset_present = original.get("data_offset") is not None

    # Reconstruct flags
    new_flags = flags & 0x01  # Keep data offset flag
    if sample_duration_present:
        new_flags |= 0x0100
    if sample_size_present:
        new_flags |= 0x0200
    if sample_flags_present:
        new_flags |= 0x0400
    if sample_cts_present:
        new_flags |= 0x0800

    # Calculate size
    sample_count = len(new_samples)
    entry_size = 0
    if sample_duration_present:
        entry_size += 4
    if sample_size_present:
        entry_size += 4
    if sample_flags_present:
        entry_size += 4
    if sample_cts_present:
        entry_size += 4

    data_size = 12  # version/flags + sample_count
    if data_offset_present:
        data_size += 4
    data_size += sample_count * entry_size

    # Full box size includes header
    full_size = 8 + data_size

    # Build box
    box = bytearray()
    # Size
    box.extend(struct.pack(">I", full_size))
    # Type
    box.extend(b"trun")
    # Version and flags
    box.append(version)
    box.extend(struct.pack(">I", new_flags)[1:])  # 3 bytes of flags
    # Sample count
    box.extend(struct.pack(">I", sample_count))

    # Data offset if present
    if data_offset_present:
        box.extend(struct.pack(">i", original["data_offset"]))

    # Samples
    for sample in new_samples:
        if sample_duration_present and "duration" in sample:
            box.extend(struct.pack(">I", sample["duration"]))
        if sample_size_present and "size" in sample:
            box.extend(struct.pack(">I", sample["size"]))
        if sample_flags_present and "flags" in sample:
            box.extend(struct.pack(">I", sample["flags"]))
        if sample_cts_present and "cts" in sample:
            box.extend(struct.pack(">I", sample["cts"]))

    return bytes(box)


def _extract_av1_samples(mdat_data: bytes) -> list[int]:
    """Extract AV1 OBU sample sizes from mdat data.

    AV1 uses Open Bitstream Units (OBUs). Each OBU starts with a header:
    - obu_forbidden_bit (1 bit)
    - obu_type (4 bits)
    - obu_extension_flag (1 bit)
    - obu_has_size_field (1 bit)
    - obu_reserved_1bit (1 bit)
    - If obu_has_size_field: leb128 encoded size
    - If obu_extension_flag: temporal_id and spatial_id

    For DASH, the mdat contains a sequence of OBUs.
    """
    samples = []
    offset = 0

    while offset < len(mdat_data):
        if offset >= len(mdat_data):
            break

        # Read OBU header byte
        header = mdat_data[offset]
        obu_type = (header >> 3) & 0xF
        extension_flag = (header >> 2) & 1
        has_size_field = (header >> 1) & 1

        header_size = 1
        if extension_flag:
            header_size += 1

        # Read OBU size if present
        if has_size_field:
            size, new_offset = _read_leb128(mdat_data, offset + header_size)
            if new_offset <= offset + header_size:
                # Failed to read, treat rest as one sample
                samples.append(len(mdat_data) - offset)
                break
            obu_size = size
            size_field_size = new_offset - offset - header_size
        else:
            # OBU extends to end of temporal unit (not typical in DASH)
            obu_size = len(mdat_data) - offset - header_size
            size_field_size = 0

        total_obu_size = header_size + size_field_size + obu_size

        # For DASH, we treat each OBU as a sample or group OBUs
        # For now, let's be conservative and add this OBU size
        samples.append(total_obu_size)

        offset += total_obu_size

    return samples if samples else [len(mdat_data)]


def _read_leb128(data: bytes, offset: int) -> tuple[int, int]:
    """Read LEB128 encoded value. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if not (byte & 0x80):
            break
        shift += 7
        if shift > 64:
            break
    return result, offset


def fix_fragment_moof_mdat(moof_data: bytes, mdat_data: bytes) -> bytes:
    """Fix a single moof+mdat fragment.

    Adjusts the moof's trun box sample sizes to match the actual mdat content.
    """
    # Find trun box in moof
    trun_info = _find_box(moof_data, "trun")
    if not trun_info:
        # No trun, return original
        return moof_data + mdat_data

    trun_offset, trun_size = trun_info
    trun = _parse_trun(moof_data, trun_offset, trun_size)

    if not trun or not trun["samples"]:
        return moof_data + mdat_data

    # Check if we need to fix sample sizes
    has_size = any("size" in s for s in trun["samples"])
    if not has_size:
        # No sample sizes to fix
        return moof_data + mdat_data

    # Get total mdat size (excluding mdat header)
    mdat_content_size = len(mdat_data)

    # Calculate total sample size from trun
    total_sample_size = sum(s.get("size", 0) for s in trun["samples"])

    # If sizes match, no fix needed
    if total_sample_size == mdat_content_size:
        return moof_data + mdat_data

    # Need to fix sample sizes
    # Simple approach: distribute the actual mdat size proportionally
    # Better approach: use AV1 OBU parsing to get actual sizes

    # For now, let's try AV1 OBU parsing
    av1_sizes = _extract_av1_samples(mdat_data)

    if len(av1_sizes) == len(trun["samples"]):
        # Perfect match in count, use AV1 sizes
        new_samples = []
        for i, orig in enumerate(trun["samples"]):
            new_sample = dict(orig)
            new_sample["size"] = av1_sizes[i]
            new_samples.append(new_sample)
    elif len(av1_sizes) > len(trun["samples"]):
        # More AV1 OBUs than samples, combine some
        new_samples = []
        obus_per_sample = len(av1_sizes) // len(trun["samples"])
        remainder = len(av1_sizes) % len(trun["samples"])

        obu_idx = 0
        for i, orig in enumerate(trun["samples"]):
            new_sample = dict(orig)
            count = obus_per_sample + (1 if i < remainder else 0)
            total_size = sum(av1_sizes[obu_idx:obu_idx+count])
            new_sample["size"] = total_size
            new_samples.append(new_sample)
            obu_idx += count
    else:
        # Fewer AV1 OBUs than samples, split or use single size
        # Just use equal distribution
        size_per_sample = mdat_content_size // len(trun["samples"])
        remainder = mdat_content_size % len(trun["samples"])

        new_samples = []
        for i, orig in enumerate(trun["samples"]):
            new_sample = dict(orig)
            new_sample["size"] = size_per_sample + (1 if i < remainder else 0)
            new_samples.append(new_sample)

    # Build new trun
    new_trun = _build_trun(trun, new_samples)

    # Rebuild moof: everything before trun + new trun + everything after trun
    before_trun = moof_data[:trun_offset]
    after_trun = moof_data[trun_offset + trun_size:]

    # Check if moof size changed and update parent boxes if needed
    size_diff = len(new_trun) - trun_size

    if size_diff != 0:
        # Need to update parent box sizes (moof, traf, etc.)
        # For now, just rebuild the moof with updated size
        new_moof_inner = before_trun[8:] + new_trun + after_trun[8:]
        new_moof_size = 8 + len(new_moof_inner)

        new_moof = struct.pack(">I", new_moof_size) + b"moof" + new_moof_inner[8:]
    else:
        new_moof = before_trun + new_trun + after_trun

    return new_moof + mdat_data


def fix_dash_fragments(data: bytes) -> bytes:
    """Fix all moof+mdat fragments in a DASH fMP4 file.

    This is the main entry point for repairing captured YouTube DASH files.
    """
    result = bytearray()
    offset = 0

    # First, extract init segment (ftyp + moov + optional sidx)
    while offset < len(data):
        box = _read_box(data, offset)
        if box is None:
            break

        box_type, size, start, end = box

        if box_type in ("ftyp", "moov", "sidx"):
            # Copy init boxes as-is
            result.extend(data[start:end])
            offset = end
        elif box_type == "moof":
            # Found start of fragments, break and process separately
            break
        else:
            # Skip unknown boxes
            offset = end

    # Now process moof+mdat pairs
    while offset < len(data):
        moof_box = _read_box(data, offset)
        if moof_box is None:
            break

        moof_type, moof_size, moof_start, moof_end = moof_box

        if moof_type != "moof":
            # Not a moof, copy as-is
            result.extend(data[moof_start:moof_end])
            offset = moof_end
            continue

        # Find following mdat
        mdat_box = _read_box(data, moof_end)
        if mdat_box is None:
            # No mdat, copy moof as-is
            result.extend(data[moof_start:moof_end])
            break

        mdat_type, mdat_size, mdat_start, mdat_end = mdat_box

        if mdat_type != "mdat":
            # Not an mdat, copy moof and continue
            result.extend(data[moof_start:moof_end])
            offset = moof_end
            continue

        # Extract moof and mdat data
        moof_data = data[moof_start:moof_end]
        # mdat data excludes the 8-byte header (size + 'mdat')
        mdat_data = data[mdat_start + 8:mdat_end]

        # Fix this fragment
        fixed_fragment = fix_fragment_moof_mdat(moof_data, mdat_data)
        result.extend(fixed_fragment)

        offset = mdat_end

    return bytes(result)
