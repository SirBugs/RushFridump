#!/usr/bin/env python3

import argparse
import mmap
import os
import random
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import utils


def _require_frida():
    """Import frida on demand so `--search` doesn't need it installed."""
    try:
        import frida  # noqa: F401
        return frida
    except ImportError:
        sys.stderr.write(
            "error: the 'frida' package is not installed.\n"
            "       install it with: pip install frida frida-tools\n"
        )
        sys.exit(2)


class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'


class FridaManager:
    DEFAULT_FRIDA_PORT = 27042

    def __init__(self, usb=False, verbose=False, device_id=None, port=None):
        self.usb = usb
        self.verbose = verbose
        self.device_id = device_id
        self.port = port
        self._forward_active = False

    def log(self, msg, color=Colors.WHITE, prefix="[INFO]"):
        print(f"{color}{prefix}{Colors.END} {msg}")

    def log_success(self, msg):
        self.log(msg, Colors.GREEN, "[\u2713]")

    def log_warning(self, msg):
        self.log(msg, Colors.YELLOW, "[!]")

    def log_error(self, msg):
        self.log(msg, Colors.RED, "[\u2717]")

    def log_info(self, msg):
        self.log(msg, Colors.BLUE, "[\u2192]")

    def get_client_version(self):
        frida = _require_frida()
        return getattr(frida, '__version__', None)

    def get_adb_devices(self):
        try:
            result = subprocess.run(
                ['adb', 'devices'], capture_output=True, text=True, timeout=10
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            self.log_error(f"adb unavailable: {e}")
            return []
        devices = []
        for line in result.stdout.split('\n')[1:]:
            if '\tdevice' in line:
                devices.append(line.split('\t')[0])
        return devices

    def adb_shell(self, cmd, timeout=15, as_root=True):
        """Run a shell command on the selected device.

        Uses shlex.quote so embedded quotes/metacharacters in `cmd` cannot
        break out of the `su -c` wrapper.
        """
        if not self.device_id:
            return None
        if as_root:
            shell_cmd = f"su -c {shlex.quote(cmd)}"
        else:
            shell_cmd = cmd
        try:
            result = subprocess.run(
                ['adb', '-s', self.device_id, 'shell', shell_cmd],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def get_device_servers(self):
        servers = []
        ls_output = self.adb_shell('ls /data/local/tmp/frida-server* 2>/dev/null')
        if not ls_output:
            return servers
        for line in ls_output.split('\n'):
            line = line.strip()
            if not line or 'frida-server' not in line:
                continue
            server_name = line.rsplit('/', 1)[-1]
            server_path = f'/data/local/tmp/{server_name}'

            version_match = re.search(r'frida-server-(\d+\.\d+\.\d+)', server_name)
            if version_match:
                version = version_match.group(1)
            else:
                version_output = self.adb_shell(
                    f'{shlex.quote(server_path)} --version 2>/dev/null'
                )
                version = version_output.strip() if version_output else 'unknown'
            servers.append((server_path, version))
        return servers

    def is_server_running(self):
        out = self.adb_shell('pidof frida-server')
        if out and out.strip().isdigit():
            return True
        # Fallback for devices without pidof.
        out = self.adb_shell('pgrep -f frida-server')
        return bool(out and out.strip())

    def kill_servers(self):
        self.adb_shell('pkill -f frida-server')
        time.sleep(2)

    def start_server(self, server_path):
        # chmod first — some users drop the binary without the exec bit.
        self.adb_shell(f'chmod 755 {shlex.quote(server_path)}')
        # When a custom port is set, bind to loopback only so apps that probe
        # 127.0.0.1:27042 from inside the sandbox find nothing.
        listen_arg = ''
        if self.port:
            listen_arg = f' -l 127.0.0.1:{int(self.port)}'
        # Detach with setsid so the adb channel can close cleanly. Use a
        # short timeout because this command is expected to return fast.
        self.adb_shell(
            f'setsid {shlex.quote(server_path)}{listen_arg} '
            f'>/dev/null 2>&1 < /dev/null &',
            timeout=5,
        )
        time.sleep(3)

    def setup_port_forward(self):
        """adb forward tcp:<port> tcp:<port> so the host can reach the
        loopback-bound frida-server on the device."""
        if not self.port or not self.device_id:
            return False
        try:
            result = subprocess.run(
                ['adb', '-s', self.device_id, 'forward',
                 f'tcp:{int(self.port)}', f'tcp:{int(self.port)}'],
                capture_output=True, text=True, timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            self.log_error(f"adb forward failed: {e}")
            return False
        if result.returncode != 0:
            self.log_error(f"adb forward failed: {result.stderr.strip()}")
            return False
        self._forward_active = True
        self.log_info(
            f"adb forward tcp:{self.port} -> device tcp:{self.port}"
        )
        return True

    def remove_port_forward(self):
        if not self._forward_active or not self.device_id or not self.port:
            return
        try:
            subprocess.run(
                ['adb', '-s', self.device_id, 'forward', '--remove',
                 f'tcp:{int(self.port)}'],
                capture_output=True, text=True, timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        self._forward_active = False

    def wait_for_forwarded_port(self, timeout=10.0):
        """Probe the forwarded host port until frida-server accepts a TCP
        connection. Returns True on success, False on timeout."""
        if not self.port:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(
                    ('127.0.0.1', int(self.port)), timeout=1.0,
                ):
                    return True
            except OSError:
                time.sleep(0.3)
        return False

    def setup_device(self):
        if not self.usb:
            return True

        devices = self.get_adb_devices()
        if not devices:
            self.log_error("No USB devices found. Check 'adb devices'")
            return False

        if self.device_id:
            if self.device_id not in devices:
                self.log_error(
                    f"Requested device '{self.device_id}' not found. "
                    f"Available: {', '.join(devices)}"
                )
                return False
            self.log_info(f"Using device: {self.device_id}")
            return True

        if len(devices) > 1:
            self.log_warning(f"Multiple devices found: {', '.join(devices)}")
            self.device_id = devices[0]
            self.log_info(f"Using device: {self.device_id} (pass -D to choose)")
        else:
            self.device_id = devices[0]

        return True

    def manage_versions(self):
        if not self.usb:
            return True

        client_ver = self.get_client_version()
        if not client_ver:
            self.log_error("Could not detect Frida client version")
            return False

        servers = self.get_device_servers()

        print(f"\n{Colors.CYAN}Frida Version Status:{Colors.END}")
        print(f"  Client: {Colors.GREEN}{client_ver}{Colors.END}")

        if not servers:
            self.log_warning("No frida-server found on device")
            return False

        print("  Available servers:")
        matching_server = None

        client_ver_norm = client_ver.strip()
        for server_path, version in servers:
            version_norm = version.strip()
            matches = version_norm == client_ver_norm
            status = "\u2713" if matches else "\u2717"
            color = Colors.GREEN if matches else Colors.YELLOW
            print(f"    {color}{status} {server_path} ({version}){Colors.END}")
            if matches:
                matching_server = server_path

        if not matching_server:
            self.log_warning(
                f"No matching server found for client version {client_ver}"
            )
            available_versions = [v for _, v in servers if v != 'unknown']
            if available_versions:
                self.log_info(
                    f"Available versions: {', '.join(available_versions)}"
                )
            return False

        self.log_success(f"Found matching server: {matching_server}")

        if self.is_server_running():
            self.log_info("Stopping current frida-server")
            self.kill_servers()

        self.log_info(f"Starting frida-server {client_ver}")
        self.start_server(matching_server)

        if self.is_server_running():
            self.log_success("Frida-server started successfully")
            return True

        self.log_error("Failed to start frida-server")
        return False


def print_banner():
    c = Colors
    logo = [
        r" ____            _     _____     _     _                       ",
        r"|  _ \ _   _ ___| |__ |  ___| __(_) __| |_   _ _ __ ___  _ __  ",
        r"| |_) | | | / __| '_ \| |_ | '__| |/ _` | | | | '_ ` _ \| '_ \ ",
        r"|  _ <| |_| \__ \ | | |  _|| |  | | (_| | |_| | | | | | | |_) |",
        r"|_| \_\\__,_|___/_| |_|_|  |_|  |_|\__,_|\__,_|_| |_| |_| .__/ ",
        r"                                                        |_|    ",
    ]
    bunny = [
        "",
        r"    (\_/)",
        r"    (o.o)",
        r'   (")_(")',
        "",
        "",
    ]
    width = max(len(line) for line in logo) + 3
    print()
    for lg, bn in zip(logo, bunny):
        print(f"{c.CYAN}{c.BOLD}{lg.ljust(width)}{c.END}{c.YELLOW}{bn}{c.END}")
    print(f"\n    {c.GREEN}Lightning Fast Memory Dumper{c.END}\n")


def parse_args():
    parser = argparse.ArgumentParser(
        prog='rushfridump',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Lightning fast Frida memory dumper with automatic version management",
    )
    parser.add_argument('process', nargs='?',
                        help='target process name (omit when using --search)')
    parser.add_argument('--search', metavar='DIR', default=None,
                        help='search DIR/memory.bin for terms passed via --term and exit')
    parser.add_argument('-t', '--term', action='append', default=[], dest='terms',
                        metavar='TEXT',
                        help='search term (repeatable). Used with --search')
    parser.add_argument('-i', '--ignore-case', action='store_true',
                        help='case-insensitive search (with --search)')
    parser.add_argument('-C', '--context', type=int, default=16,
                        help='bytes of context printed around each hit when --raw-context is set '
                             '(default: 16)')
    parser.add_argument('--max-string', type=int, default=512,
                        help='cap on bytes expanded around each hit when reconstructing the '
                             'surrounding printable string (default: 512)')
    parser.add_argument('--raw-context', action='store_true',
                        help='print a fixed byte window instead of the full surrounding string')
    parser.add_argument('-o', '--out', type=str, help='output directory')
    parser.add_argument('-U', '--usb', action='store_true', help='USB device')
    parser.add_argument('-D', '--device', type=str, default=None,
                        help='specific adb device serial (when multiple are attached)')
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
    parser.add_argument('-r', '--read-only', action='store_true',
                        help='dump read-only memory (shortcut for --permissions r--)')
    parser.add_argument('--permissions', type=str, default=None,
                        help='Frida memory permission filter, e.g. rw-, r--, r-x (overrides -r)')
    parser.add_argument('-s', '--strings', action='store_true',
                        help='extract printable strings from the dump')
    parser.add_argument('--max-range-size', type=int, default=20 * 1024 * 1024,
                        help='skip memory ranges larger than this many bytes (default: 20MB)')
    parser.add_argument('--chunk-size', type=int, default=1 * 1024 * 1024,
                        help='read each range in chunks of this size in bytes (default: 1MB)')
    parser.add_argument('--no-auto-server', action='store_true',
                        help='skip automatic frida-server version management')
    parser.add_argument('-P', '--port', type=int, default=None,
                        help='start frida-server on this port (loopback-only on '
                             'device) and adb-forward it. Use to evade apps that '
                             'detect the default 27042 port')
    parser.add_argument('--random-port', action='store_true',
                        help='pick a random high port for --port (overrides -P if '
                             'both are passed without an explicit value)')
    return parser.parse_args()


def _resolve_permissions(args):
    if args.permissions:
        return args.permissions
    if args.read_only:
        return 'r--'
    return 'rw-'


def _dump_ranges(agent, ranges, memory_file, index_file, chunk_size, verbose, manager):
    total_size = 0
    dumped_ranges = 0
    total = len(ranges)

    print(f"{Colors.BLUE}[\u2192]{Colors.END} Processing {total} memory ranges...")

    with open(memory_file, 'wb') as f, open(index_file, 'w', encoding='utf-8') as idx:
        idx.write("# offset_in_dump\tbase\tsize\n")
        for i, range_info in enumerate(ranges):
            base = range_info["base"]
            size = range_info["size"]

            bar_length = 30
            filled = int(bar_length * (i + 1) / total)
            bar = '\u2588' * filled + '\u2591' * (bar_length - filled)
            progress = int((i + 1) * 100 / total)
            print(
                f"\r{Colors.CYAN}[{bar}] {progress}%{Colors.END} "
                f"Dumping range {i + 1}/{total}",
                end='', flush=True,
            )
            if verbose:
                print(f"\n{Colors.BLUE}[\u2192]{Colors.END} Range: {base} size={size}")

            offset = f.tell()
            written = 0
            read_failed = False
            try:
                remaining = size
                addr_int = int(base, 16) if isinstance(base, str) else int(base)
                while remaining > 0:
                    to_read = min(chunk_size, remaining)
                    data = agent.read_memory(hex(addr_int + written), to_read)
                    if not data:
                        read_failed = True
                        break
                    f.write(data)
                    written += len(data)
                    remaining -= len(data)
            except Exception as e:
                if verbose:
                    print(f"\n{Colors.YELLOW}[!]{Colors.END} Failed to dump {base}: {e}")
                read_failed = True

            if written > 0:
                idx.write(f"{offset}\t{base}\t{written}\n")
                total_size += written
                dumped_ranges += 1
            elif read_failed and verbose:
                print(f"\n{Colors.YELLOW}[!]{Colors.END} Skipped unreadable range {base}")

    print()
    return dumped_ranges, total_size


def _load_index(index_path):
    """Return list of (offset, end, base) rows from an index.tsv, or []."""
    ranges = []
    if not index_path.exists():
        return ranges
    with open(index_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            try:
                off = int(parts[0])
                base = parts[1]
                size = int(parts[2])
            except ValueError:
                continue
            ranges.append((off, off + size, base))
    ranges.sort()
    return ranges


def _locate(ranges, offset):
    """Binary-search the range list for the (base, relative_offset) of `offset`."""
    lo, hi = 0, len(ranges)
    while lo < hi:
        mid = (lo + hi) // 2
        start, end, _base = ranges[mid]
        if offset < start:
            hi = mid
        elif offset >= end:
            lo = mid + 1
        else:
            return ranges[mid][2], offset - start
    return None, None


def _printable_context(data):
    return ''.join(chr(b) if 0x20 <= b <= 0x7E else '.' for b in data)


def _expand_ascii(mm, start, end, max_expand):
    """Grow [start, end) outward while bytes stay ASCII-printable."""
    limit_l = max(0, start - max_expand)
    limit_r = min(len(mm), end + max_expand)
    left = start
    while left > limit_l and 0x20 <= mm[left - 1] <= 0x7E:
        left -= 1
    right = end
    while right < limit_r and 0x20 <= mm[right] <= 0x7E:
        right += 1
    return left, right, mm[left:right].decode('ascii', errors='replace')


def _expand_utf16le(mm, start, end, max_expand):
    """Grow [start, end) outward in 2-byte steps while each pair looks like
    UTF-16LE text (high byte 0, low byte printable-ish)."""
    limit_l = max(0, start - max_expand)
    limit_r = min(len(mm), end + max_expand)
    left = start
    while left - 2 >= limit_l and mm[left - 1] == 0 and mm[left - 2] >= 0x20 \
            and mm[left - 2] != 0x7F:
        left -= 2
    right = end
    while right + 1 < limit_r and mm[right + 1] == 0 and mm[right] >= 0x20 \
            and mm[right] != 0x7F:
        right += 2
    try:
        text = mm[left:right].decode('utf-16-le', errors='replace')
    except Exception:
        text = mm[left:right].decode('ascii', errors='replace')
    return left, right, text


def search_memory(directory, terms, ignore_case=False, context_bytes=16,
                  max_string=512, raw_context=False):
    directory = Path(directory)
    mem_path = directory / 'memory.bin'
    idx_path = directory / 'index.tsv'

    if not mem_path.exists():
        print(f"{Colors.RED}[\u2717]{Colors.END} {mem_path} not found", file=sys.stderr)
        return 1
    if not terms:
        print(f"{Colors.RED}[\u2717]{Colors.END} no search terms provided (use -t TEXT)",
              file=sys.stderr)
        return 1

    ranges = _load_index(idx_path)
    if not ranges:
        print(f"{Colors.YELLOW}[!]{Colors.END} {idx_path} missing or empty; "
              f"hits will show absolute offsets only")

    flags = re.IGNORECASE if ignore_case else 0
    patterns = []
    for term in terms:
        for enc_name, enc in (('ascii', 'utf-8'), ('utf16le', 'utf-16-le')):
            try:
                pat = re.compile(re.escape(term.encode(enc)), flags)
            except UnicodeEncodeError:
                continue
            patterns.append((term, enc_name, pat))

    print(f"{Colors.BLUE}[\u2192]{Colors.END} Searching {mem_path} "
          f"({utils.human_size(mem_path.stat().st_size)}) "
          f"for {len(terms)} term(s)...")

    hits_per_term = {t: 0 for t in terms}
    total_hits = 0

    file_size = mem_path.stat().st_size
    if file_size == 0:
        print(f"{Colors.YELLOW}[!]{Colors.END} memory.bin is empty")
        return 1

    seen_spans = set()

    with open(mem_path, 'rb') as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            mm_len = len(mm)
            for term, enc_name, pat in patterns:
                for m in pat.finditer(mm):
                    off = m.start()
                    base, roff = _locate(ranges, off)
                    loc = f"{base}+0x{roff:x}" if base is not None else f"file+0x{off:x}"

                    if raw_context:
                        cs = max(0, off - context_bytes)
                        ce = min(mm_len, m.end() + context_bytes)
                        display = _printable_context(mm[cs:ce])
                    else:
                        if enc_name == 'ascii':
                            left, right, text = _expand_ascii(mm, off, m.end(), max_string)
                        else:
                            left, right, text = _expand_utf16le(mm, off, m.end(), max_string)
                        span_key = (enc_name, left, right)
                        if span_key in seen_spans:
                            continue
                        seen_spans.add(span_key)
                        display = text.replace('\n', '\\n').replace('\r', '\\r')

                    print(f"  {Colors.GREEN}[{enc_name}]{Colors.END} "
                          f"'{term}' @ {Colors.CYAN}{loc}{Colors.END}  |  {display}")
                    hits_per_term[term] += 1
                    total_hits += 1

    print()
    for term, n in hits_per_term.items():
        color = Colors.GREEN if n else Colors.YELLOW
        print(f"  {color}{n:>6}{Colors.END}  '{term}'")
    print(f"\n{Colors.GREEN}[\u2713]{Colors.END} total hits: {total_hits}")
    return 0 if total_hits else 1


def main():
    print_banner()
    args = parse_args()

    if args.search:
        sys.exit(search_memory(args.search, args.terms,
                               ignore_case=args.ignore_case,
                               context_bytes=args.context,
                               max_string=args.max_string,
                               raw_context=args.raw_context))

    if not args.process:
        print(f"{Colors.RED}[\u2717]{Colors.END} process name is required "
              f"(or use --search DIR -t TEXT)", file=sys.stderr)
        sys.exit(2)

    port = args.port
    if args.random_port and not port:
        port = random.randint(30000, 60000)
    if port and not args.usb:
        print(f"{Colors.RED}[✗]{Colors.END} --port requires -U/--usb",
              file=sys.stderr)
        sys.exit(2)

    manager = FridaManager(args.usb, args.verbose,
                           device_id=args.device, port=port)

    if not manager.setup_device():
        sys.exit(1)

    if args.usb and not args.no_auto_server:
        if not manager.manage_versions():
            sys.exit(1)

    if port:
        if not manager.setup_port_forward():
            sys.exit(1)
        if not manager.wait_for_forwarded_port(timeout=10.0):
            manager.log_error(
                f"frida-server not reachable on 127.0.0.1:{port} "
                f"(check that the server supports the -l flag)"
            )
            manager.remove_port_forward()
            sys.exit(1)
        manager.log_success(
            f"frida-server reachable via 127.0.0.1:{port} (loopback-only on device)"
        )

    if args.out:
        output_dir = args.out
    else:
        clean_name = re.sub(r'[^\w\-_]', '_', args.process)
        output_dir = f"./{clean_name}"

    manager.log_info(f"Output directory: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)

    session = None
    script = None

    def _cleanup():
        try:
            if script is not None:
                script.unload()
        except Exception:
            pass
        try:
            if session is not None:
                session.detach()
        except Exception:
            pass
        manager.remove_port_forward()

    def _sigint(signum, frame):
        print(f"\n{Colors.YELLOW}[!] Interrupted by user{Colors.END}")
        _cleanup()
        sys.exit(130)

    signal.signal(signal.SIGINT, _sigint)

    frida = _require_frida()

    def _get_device():
        if port:
            return frida.get_device_manager().add_remote_device(
                f"127.0.0.1:{port}"
            )
        if args.usb:
            return frida.get_usb_device()
        return None

    try:
        device = _get_device()
        if device is not None:
            session = device.attach(args.process)
        else:
            session = frida.attach(args.process)
        manager.log_success(f"Attached to process: {args.process}")
    except frida.ProcessNotFoundError:
        manager.log_error(f"Process '{args.process}' not found")
        try:
            device = _get_device()
            if device is not None:
                processes = device.enumerate_processes()
                needle = args.process.lower()
                similar = [p.name for p in processes if needle in p.name.lower()][:5]
                if similar:
                    manager.log_info(f"Similar processes: {', '.join(similar)}")
        except frida.InvalidArgumentError:
            pass
        except Exception as e:
            if args.verbose:
                manager.log_warning(f"Could not enumerate processes: {e}")
        _cleanup()
        sys.exit(1)
    except Exception as e:
        manager.log_error(f"Connection failed: {e}")
        _cleanup()
        sys.exit(1)

    try:
        script = session.create_script("""
            rpc.exports = {
                enumerateRanges: function (prot) {
                    return Process.enumerateRanges(prot);
                },
                readMemory: function (address, size) {
                    return Memory.readByteArray(ptr(address), size);
                }
            };
        """)
        script.load()
        agent = script.exports_sync

        perms = _resolve_permissions(args)
        manager.log_info(f"Enumerating ranges with permissions '{perms}'")
        ranges = agent.enumerate_ranges(perms)
        manager.log_info(f"Found {len(ranges)} memory ranges")

        valid_ranges = [r for r in ranges if r["size"] <= args.max_range_size]
        skipped = len(ranges) - len(valid_ranges)
        if skipped:
            manager.log_warning(
                f"Skipping {skipped} range(s) larger than "
                f"{utils.human_size(args.max_range_size)} "
                f"(raise with --max-range-size)"
            )

        if not valid_ranges:
            manager.log_error("No memory ranges to dump")
            sys.exit(1)

        memory_file = Path(output_dir) / "memory.bin"
        index_file = Path(output_dir) / "index.tsv"

        dumped_ranges, total_size = _dump_ranges(
            agent, valid_ranges, memory_file, index_file,
            args.chunk_size, args.verbose, manager,
        )

        manager.log_success("Memory dump completed")
        manager.log_info(f"Ranges dumped: {dumped_ranges}/{len(valid_ranges)}")
        manager.log_info(f"Total size: {utils.human_size(total_size)}")
        manager.log_info(f"Output: {memory_file}")
        manager.log_info(f"Index:  {index_file}")

        if args.strings:
            manager.log_info("Extracting strings...")
            strings_file = Path(output_dir) / "strings.txt"
            count = utils.strings(memory_file, strings_file)
            manager.log_success(f"Strings saved: {strings_file} ({count} entries)")

        print(f"\n{Colors.GREEN}RushFridump completed successfully!{Colors.END}")
    finally:
        _cleanup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[!] Interrupted by user{Colors.END}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.RED}[\u2717] Fatal error: {e}{Colors.END}")
        sys.exit(1)
