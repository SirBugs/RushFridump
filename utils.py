import re
from pathlib import Path


def strings(input_file, output_file, min_len=4):
    """Extract printable ASCII strings from a binary file.

    Streams the file in chunks so large dumps don't exhaust memory. Handles
    strings that straddle chunk boundaries by carrying a tail over.
    """
    input_path = Path(input_file)
    output_path = Path(output_file)

    pattern = re.compile(b'[\x20-\x7E]{' + str(min_len).encode() + b',}')
    chunk_size = 4 * 1024 * 1024
    count = 0
    carry = b''

    with open(input_path, 'rb') as infile, \
            open(output_path, 'w', encoding='utf-8', errors='ignore') as outfile:
        while True:
            chunk = infile.read(chunk_size)
            if not chunk:
                break
            buf = carry + chunk
            # Keep the trailing printable run for the next iteration so we
            # don't split a string across chunk boundaries.
            tail_start = len(buf)
            for i in range(len(buf) - 1, -1, -1):
                b = buf[i]
                if b < 0x20 or b > 0x7E:
                    tail_start = i + 1
                    break
            else:
                tail_start = 0
            scan = buf[:tail_start]
            carry = buf[tail_start:]

            for m in pattern.finditer(scan):
                outfile.write(m.group(0).decode('ascii', errors='ignore') + '\n')
                count += 1

        if carry:
            for m in pattern.finditer(carry):
                outfile.write(m.group(0).decode('ascii', errors='ignore') + '\n')
                count += 1

    return count


def human_size(n):
    """Format a byte count as a human-readable string."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f"{n:.1f} {unit}" if unit != 'B' else f"{n} {unit}"
        n /= 1024
