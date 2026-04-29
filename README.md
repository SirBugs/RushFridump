<h1 align="center">RushFridump</h1>

<p align="center">
  <em>Lightning‑fast Frida memory dumper with automatic <code>frida-server</code> management and built‑in secret hunting.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Frida-16%2B-green" alt="Frida 16+">
  <img src="https://img.shields.io/badge/Platform-Android%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platforms">
</p>

```
  ____            _     _____     _     _
 |  _ \ _   _ ___| |__ |  ___| __(_) __| |_   _ _ __ ___  _ __         (\_/)
 | |_) | | | / __| '_ \| |_ | '__| |/ _` | | | | '_ ` _ \| '_ \        (o.o)
 |  _ <| |_| \__ \ | | |  _|| |  | | (_| | |_| | | | | | | |_) |      (")_(")
 |_| \_\\__,_|___/_| |_|_|  |_|  |_|\__,_|\__,_|_| |_| |_| .__/
                                                         |_|
```

---

## Why RushFridump?

A drop‑in replacement for [`fridump`](https://github.com/Nightbringer21/fridump) focused on the parts that actually slow down a memory‑dump workflow:

- **Auto‑manages `frida-server`** on rooted Android devices — picks the binary that matches your client version, kills the stale one, starts the right one.
- **Chunked reads** so huge regions don't blow up the Frida RPC.
- **Single‑file output** (`memory.bin`) plus a machine‑readable **`index.tsv`** mapping every byte range back to its original base address.
- **Built‑in search** (`--search`) — scan the dump for one or many strings, case‑insensitive, both **ASCII and UTF‑16LE**, with each hit expanded to the full surrounding printable string and tagged with the source memory range.
- **Port‑forwarding mode** (`-P` / `--random-port`) — start `frida-server` on a custom loopback‑only port and `adb forward` it to the host, bypassing apps that probe the default `27042`.
- Graceful cleanup: `script.unload()` / `session.detach()` on exit and on Ctrl+C.

## Installation

```bash
git clone https://github.com/<you>/RushFridump.git
cd RushFridump
pip install frida frida-tools
python3 rushfridump.py --help
```

Runtime dependencies:
- **Python 3.10+**
- **Frida** (`frida` + `frida-tools`) — only needed when dumping; `--search` works without it
- **adb** on PATH (Android only)
- A rooted Android device with a `frida-server-<version>` binary dropped into `/data/local/tmp/` (the tool handles `chmod` and launch)

## Quick start

```bash
# Dump a running app over USB
python3 rushfridump.py -U com.whatsapp

# Dump a local process
python3 rushfridump.py Calculator

# Dump read-only regions too, extract strings afterwards
python3 rushfridump.py -U -r -s com.whatsapp

# Dump via a custom port (evades apps that detect default 27042)
python3 rushfridump.py -U -P 12345 com.whatsapp

# Same idea, but pick a random high port
python3 rushfridump.py -U --random-port com.whatsapp

# Search a previous dump for credentials (ASCII + UTF-16LE, case-insensitive)
python3 rushfridump.py --search ./com_whatsapp -i -t password -t "Bearer " -t api_key
```

Don't know the process name? `frida-ps -Ua` lists running apps with identifiers.

## Output layout

```
./com_whatsapp/
├── memory.bin     # raw bytes, every dumped range concatenated
├── index.tsv      # offset_in_dump \t base_address \t size   (one row per range)
└── strings.txt    # printable ASCII strings (only with -s)
```

`index.tsv` is what lets `--search` tell you *which* memory range a hit came from, not just a file offset.

## Searching a dump

```bash
python3 rushfridump.py --search ./com_whatsapp -t password -t api_key -i
```

Each match prints the **full surrounding printable string** (not a fixed byte window):

```
[ascii]   'password' @ 0x7f3a2c000+0x2814  |  user_password=hunter2&remember=1
[utf16le] 'password' @ 0x7f3a2c000+0x4120  |  Save password for this site?
[ascii]   'api_key'  @ 0x7f3a2e000+0x0918  |  api_key=sk_live_abc123xyz
```

Useful flags:

| Flag | Purpose |
|------|---------|
| `-t, --term TEXT` | Search term (repeat `-t` for multiple terms) |
| `-i, --ignore-case` | Case‑insensitive (ASCII matching) |
| `--max-string N` | Cap expansion at N bytes per side when showing the full string (default **512**) |
| `--raw-context` | Old behaviour: fixed byte window, non‑printables as `.` |
| `-C, --context N` | Window size for `--raw-context` (default 16) |

Overlapping matches within the same expanded string are automatically deduped.

## All options

```
positional:
  process                  target process name (omit when using --search)

dumping:
  -U, --usb                connect over USB (Android)
  -D, --device SERIAL      pick a specific adb device when several are attached
  -P, --port PORT          start frida-server on this port (loopback-only on
                           device) and adb-forward it to the host. Requires -U.
  --random-port            pick a random high port for --port automatically
  -r, --read-only          shortcut for --permissions r--
  --permissions PROT       Frida permission filter (e.g. rw-, r--, r-x)
  --max-range-size BYTES   skip ranges larger than this (default: 20 MiB)
  --chunk-size BYTES       read each range in chunks of this size (default: 1 MiB)
  --no-auto-server         skip automatic frida-server version management
  -o, --out DIR            output directory (default: ./<process_name>)
  -s, --strings            extract printable strings into strings.txt after dumping
  -v, --verbose            verbose progress / error output

searching:
  --search DIR             search DIR/memory.bin for terms and exit
  -t, --term TEXT          search term (repeatable)
  -i, --ignore-case        case-insensitive ASCII match
  --max-string N           cap on bytes expanded around each hit (default: 512)
  --raw-context            fixed byte window instead of full-string expansion
  -C, --context N          window size when --raw-context is set (default: 16)
```

## Automatic `frida-server` management

On USB mode, RushFridump inspects `/data/local/tmp/frida-server*`, reports what's available, and picks the one whose version matches your Frida client:

```
Frida Version Status:
  Client: 17.2.12
  Available servers:
    ✗ /data/local/tmp/frida-server-16.1.11 (16.1.11)
    ✓ /data/local/tmp/frida-server-17.2.12 (17.2.12)  ← auto‑selected
```

It then `chmod 755`s the matching binary, kills any running `frida-server`, and starts the correct one via `setsid` so the adb channel detaches cleanly. Pass `--no-auto-server` to skip this entirely.

## Custom port / anti‑detection

Many hardened apps probe `127.0.0.1:27042` from inside their own sandbox to detect Frida. RushFridump can sidestep that:

```bash
# Start frida-server bound to loopback on port 12345 and adb-forward it
python3 rushfridump.py -U -P 12345 com.target.app

# Or let the tool roll a random high port (30000–60000)
python3 rushfridump.py -U --random-port com.target.app
```

What happens under the hood:

1. `frida-server` is launched on the device with `-l 127.0.0.1:<port>` so it only listens on the device's loopback — nothing on `0.0.0.0`, nothing on `27042`.
2. `adb forward tcp:<port> tcp:<port>` exposes it to the host.
3. The host probes `127.0.0.1:<port>` until the server accepts connections, then attaches via `add_remote_device("127.0.0.1:<port>")`.
4. The forward is removed automatically on exit / Ctrl+C.

`-P` / `--random-port` require `-U` (USB mode).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Process '…' not found` | Verify the name with `frida-ps -Ua` (pass the *identifier*, e.g. `com.whatsapp`) |
| `No USB devices found` | `adb devices` — enable USB debugging / trust the host |
| `No matching server found for client version …` | Download the matching `frida-server-<version>-android-<arch>` from the Frida release page and push it to `/data/local/tmp/` |
| `Failed to start frida-server` | Verify root: `adb shell su -c id`. Also check SELinux isn't blocking the binary (`setenforce 0` on permissive test devices) |
| Huge pages skipped | Raise `--max-range-size`; regions > default 20 MiB are skipped by design |
| RPC timeouts on large regions | Lower `--chunk-size` (e.g. `--chunk-size 262144`) |
| `frida-server not reachable on 127.0.0.1:<port>` | Your `frida-server` build may not support the `-l` listen flag — upgrade to a recent release, or drop `-P` and use the default port |
| `--port requires -U/--usb` | `-P` / `--random-port` only make sense with USB mode; add `-U` |

## Credits

Originally inspired by [`fridump`](https://github.com/Nightbringer21/fridump). Rewritten with automatic version handling, chunked reads, a proper search mode, and a cleaner output layout.

## License

MIT. Use for lawful security research and your own devices / apps only.
