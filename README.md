# RushFridump 🐰⚡

> Lightning fast Frida memory dumper with intelligent version management and professional interface

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![Frida](https://img.shields.io/badge/Frida-16.0%2B-green.svg)](https://frida.re)
[![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20Local-lightgrey.svg)]()

## ✨ Features

🚀 **Lightning Fast** - Optimized memory dumping with real-time progress bars  
🔧 **Smart Version Management** - Automatically detects and manages frida-server versions  
🎯 **Intelligent Process Discovery** - Fuzzy matching with helpful suggestions  
🎨 **Professional Interface** - Beautiful colored output with clear status indicators  
🤖 **Android Focused** - Specialized for Android devices with automatic frida-server management  
🐰 **User Friendly** - Clean error messages and troubleshooting guidance  

## 🚀 Quick Start

### Prerequisites

Before running RushFridump, ensure you have:

```bash
# 1. Python 3.10+ installed
python3 --version

# 2. Frida tools installed  
pip install frida frida-tools

# 3. Android SDK Platform Tools (required for Android devices)
# macOS: brew install android-platform-tools
# Ubuntu: sudo apt install android-tools-adb
```

### For Android Devices
- **Device rooted** with su access
- **USB debugging enabled** in Developer Options
- **frida-server installed** on device (RushFridump manages versions automatically)

## 📦 Installation

```bash
git clone https://github.com/yourusername/rushfridump.git
cd rushfridump
python3 rushfridump.py -h
```

## 💻 Usage

### Basic Commands

```bash
# Android app with string extraction
python3 rushfridump.py -U -s "Gmail"

# Android app with verbose output
python3 rushfridump.py -U -v "WhatsApp" 

# Local Windows/macOS process
python3 rushfridump.py -o /tmp/dumps "Calculator"

# Custom output directory  
python3 rushfridump.py -U -o ./custom_dumps "Instagram"
```

### Command Options

```
Usage: python3 rushfridump.py [options] <process_name>

Required:
  process_name          Target process name (exact or partial match)

Options:
  -U, --usb            Connect to USB device (Android)
  -s, --strings        Extract strings from memory dump
  -v, --verbose        Enable verbose output with debugging info
  -r, --read-only      Include read-only memory regions  
  -o, --out DIR        Custom output directory (default: ./<process_name>)
  --max-size BYTES     Maximum dump file size (default: 20MB)
  -h, --help           Show help message
```

## 🎯 Smart Features

### Automatic Version Management
RushFridump automatically detects version conflicts and manages frida-server:

```
Frida Version Status:
  Client: 17.2.12
  Available servers:
    ✗ /data/local/tmp/frida-server-16.1.11 (16.1.11)
    ✓ /data/local/tmp/frida-server-17.2.12 (17.2.12)  ← Auto-selected
    ✗ /data/local/tmp/frida-server-mac (16.1.11)
    ✗ /data/local/tmp/frida-server-ubuntu (16.3.3)
```

### Real-time Progress Tracking
```
[→] Processing 1203 memory ranges...
[██████████████████████████████] 100% Dumping range 1203/1203
[✓] Memory dump completed
```

### Organized Output
```
./Gmail/
├── memory.txt      # All memory ranges in single file
└── strings.txt     # Extracted strings (with -s flag)
```

## 🛠️ Device Setup Guide

### Android Setup
```bash
# 1. Enable USB debugging and connect device
adb devices

# 2. Check if device is rooted  
adb shell su -c "id"

# 3. RushFridump will handle frida-server automatically
python3 rushfridump.py -U "com.android.chrome"
```

### Local Process Setup
```bash
# 1. Ensure Frida is installed locally
frida-ps

# 2. Run RushFridump on local process
python3 rushfridump.py "Calculator"
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| **"Process not found"** | Use `frida-ps -U` to find exact process name |
| **"No USB devices"** | Check `adb devices` and enable USB debugging |
| **"Version mismatch"** | RushFridump auto-fixes this - ensure device is rooted |
| **"Permission denied"** | Verify root access: `adb shell su -c "id"` |
| **"Connection failed"** | Restart frida-server: `adb shell su -c "killall frida-server"` |

### Getting Process Names
```bash
# List all processes on device
frida-ps -U

# List processes matching pattern  
frida-ps -U | grep -i gmail

# Use partial names with RushFridump (it suggests matches)
python3 rushfridump.py -U -v "gmai"
```

## 🆚 Why RushFridump?

| Feature | Original Fridump | RushFridump |
|---------|------------------|-------------|
| Version Management | ❌ Manual | ✅ **Automatic** |
| Progress Tracking | ❌ Text only | ✅ **Visual progress bars** |
| Error Messages | ❌ Generic | ✅ **Detailed with solutions** |
| Process Discovery | ❌ Exact match only | ✅ **Fuzzy matching + suggestions** |
| Interface | ❌ Plain text | ✅ **Professional colored output** |
| Output Organization | ❌ Multiple files | ✅ **Single organized file** |

## 🏗️ Requirements

- **Python 3.10+** (tested with 3.10, 3.11, 3.13)
- **Frida 16.0+** (automatically managed)
- **Root access** for Android devices
- **ADB tools** for Android devices

## 📝 License

Based on the original [Fridump](https://github.com/Nightbringer21/fridump) project  
Enhanced by RushFridump with intelligent automation and professional interface 🐰

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

<div align="center">

**Made with ❤️ for the security research community**

⭐ Star this repo if RushFridump helped you!

</div>
