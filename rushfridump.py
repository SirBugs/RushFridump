#!/usr/bin/env python3

import textwrap
import frida
import os
import sys
import subprocess
import re
import time
import utils
import argparse
from pathlib import Path

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
    def __init__(self, usb=False, verbose=False):
        self.usb = usb
        self.verbose = verbose
        self.device_id = None
        
    def log(self, msg, color=Colors.WHITE, prefix="[INFO]"):
        print(f"{color}{prefix}{Colors.END} {msg}")
        
    def log_success(self, msg):
        self.log(msg, Colors.GREEN, "[✓]")
        
    def log_warning(self, msg):
        self.log(msg, Colors.YELLOW, "[!]")
        
    def log_error(self, msg):
        self.log(msg, Colors.RED, "[✗]")
        
    def log_info(self, msg):
        self.log(msg, Colors.BLUE, "[→]")

    def get_client_version(self):
        try:
            return frida.__version__
        except:
            return None

    def get_adb_devices(self):
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True)
            devices = []
            for line in result.stdout.split('\n')[1:]:
                if '\tdevice' in line:
                    devices.append(line.split('\t')[0])
            return devices
        except:
            return []

    def adb_shell(self, cmd):
        if not self.device_id:
            return None
        try:
            result = subprocess.run(['adb', '-s', self.device_id, 'shell', f'su -c "{cmd}"'], 
                                  capture_output=True, text=True, timeout=10)
            return result.stdout.strip() if result.returncode == 0 else None
        except:
            return None

    def get_device_servers(self):
        servers = []
        ls_output = self.adb_shell('ls /data/local/tmp/frida-server* 2>/dev/null')
        if ls_output:
            for line in ls_output.split('\n'):
                if line.strip() and 'frida-server' in line:
                    full_path = line.strip()
                    # Extract just the filename in case we get full paths
                    server_name = full_path.split('/')[-1] if '/' in full_path else full_path
                    server_path = f'/data/local/tmp/{server_name}'
                    
                    # Try to extract version from filename first
                    version_match = re.search(r'frida-server-(\d+\.\d+\.\d+)', server_name)
                    if version_match:
                        version = version_match.group(1)
                    else:
                        # Try to get version by running the server
                        version_output = self.adb_shell(f'{server_path} --version 2>/dev/null')
                        if version_output and version_output.strip():
                            version = version_output.strip()
                        else:
                            version = 'unknown'
                    
                    servers.append((server_path, version))
        return servers

    def is_server_running(self):
        ps_output = self.adb_shell('ps | grep frida-server')
        return ps_output and 'frida-server' in ps_output

    def kill_servers(self):
        self.adb_shell('pkill -f frida-server')
        time.sleep(2)

    def start_server(self, server_path):
        self.adb_shell(f'nohup {server_path} > /dev/null 2>&1 &')
        time.sleep(3)

    def setup_device(self):
        if not self.usb:
            return True
            
        devices = self.get_adb_devices()
        if not devices:
            self.log_error("No USB devices found. Check 'adb devices'")
            return False
            
        if len(devices) > 1:
            self.log_warning(f"Multiple devices found: {', '.join(devices)}")
            self.device_id = devices[0]
            self.log_info(f"Using device: {self.device_id}")
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
            
        print(f"  Available servers:")
        matching_server = None
        
        for server_path, version in servers:
            status = "✓" if version == client_ver else "✗"
            color = Colors.GREEN if version == client_ver else Colors.YELLOW
            print(f"    {color}{status} {server_path} ({version}){Colors.END}")
            if version == client_ver:
                matching_server = server_path
                
        if matching_server:
            self.log_success(f"Found matching server: {matching_server}")
            
            if self.is_server_running():
                self.log_info("Stopping current frida-server")
                self.kill_servers()
                
            self.log_info(f"Starting frida-server {client_ver}")
            self.start_server(matching_server)
            
            if self.is_server_running():
                self.log_success("Frida-server started successfully")
                return True
            else:
                self.log_error("Failed to start frida-server")
                return False
        else:
            self.log_warning(f"No matching server found for client version {client_ver}")
            available_versions = [v for _, v in servers if v != 'unknown']
            if available_versions:
                self.log_info(f"Available versions: {', '.join(available_versions)}")
            return False

def print_banner():
    banner = f"""{Colors.CYAN}{Colors.BOLD}
 ____            _     ______      _     _                    
|  _ \\ _   _ ___| |__ |  ____|_ __(_) __| |_   _ _ __ ___  _ __  {Colors.YELLOW}(\\   /)
{Colors.CYAN}| |_) | | | / __| '_ \\| |_ | '__| |/ _` | | | | '_ ` _ \\| '_ \\ {Colors.YELLOW}( ._. )
{Colors.CYAN}|  _ <| |_| \\__ \\ | | |  _|| |  | | (_| | |_| | | | | | | |_) |{Colors.YELLOW}o_("_)("_)
{Colors.CYAN}|_| \\_\\\\___,_|___/_| |_|_|  |_|  |_|\\__,_|\\__,_|_| |_| |_| .__/ 
                                                        |_|    
{Colors.END}    {Colors.GREEN}🚀 Lightning Fast Memory Dumper 🚀{Colors.END}
"""
    print(banner)

def parse_args():
    parser = argparse.ArgumentParser(
        prog='rushfridump',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Lightning fast Frida memory dumper with automatic version management")

    parser.add_argument('process', help='target process name')
    parser.add_argument('-o', '--out', type=str, help='output directory')
    parser.add_argument('-U', '--usb', action='store_true', help='USB device')
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
    parser.add_argument('-r', '--read-only', action='store_true', help='include read-only memory')
    parser.add_argument('-s', '--strings', action='store_true', help='extract strings')
    parser.add_argument('--max-size', type=int, default=20*1024*1024, help='max dump size')
    
    return parser.parse_args()

def main():
    print_banner()
    args = parse_args()
    
    # Initialize manager
    manager = FridaManager(args.usb, args.verbose)
    
    # Setup device and version management
    if not manager.setup_device():
        sys.exit(1)
        
    if not manager.manage_versions():
        sys.exit(1)

    # Setup output directory
    if args.out:
        output_dir = args.out
    else:
        clean_name = re.sub(r'[^\w\-_]', '_', args.process)
        output_dir = f"./{clean_name}"
    
    manager.log_info(f"Output directory: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)

    # Connect to process
    try:
        if args.usb:
            session = frida.get_usb_device().attach(args.process)
        else:
            session = frida.attach(args.process)
        manager.log_success(f"Attached to process: {args.process}")
    except frida.ProcessNotFoundError:
        manager.log_error(f"Process '{args.process}' not found")
        if args.usb and args.verbose:
            try:
                processes = frida.get_usb_device().enumerate_processes()
                similar = [p.name for p in processes if args.process.lower() in p.name.lower()][:5]
                if similar:
                    manager.log_info(f"Similar processes: {', '.join(similar)}")
            except:
                pass
        sys.exit(1)
    except Exception as e:
        manager.log_error(f"Connection failed: {e}")
        sys.exit(1)

    # Memory dumping
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

    # Get memory ranges
    perms = 'r--' if args.read_only else 'rw-'
    ranges = agent.enumerate_ranges(perms)
    
    manager.log_info(f"Found {len(ranges)} memory ranges")
    
    # Create single memory file
    memory_file = Path(output_dir) / "memory.txt"
    total_size = 0
    dumped_ranges = 0
    
    # Filter ranges first to get accurate count
    valid_ranges = [r for r in ranges if r["size"] <= args.max_size]
    total_valid = len(valid_ranges)
    
    print(f"{Colors.BLUE}[→]{Colors.END} Processing {total_valid} memory ranges...")
    
    with open(memory_file, 'wb') as f:
        for i, range_info in enumerate(valid_ranges):
            base = range_info["base"]
            size = range_info["size"]
            
            try:
                # Show progress
                progress = int((i + 1) * 100 / total_valid)
                bar_length = 30
                filled = int(bar_length * (i + 1) / total_valid)
                bar = '█' * filled + '░' * (bar_length - filled)
                
                print(f"\r{Colors.CYAN}[{bar}] {progress}%{Colors.END} Dumping range {i+1}/{total_valid}", end='', flush=True)
                
                if args.verbose:
                    print(f"\n{Colors.BLUE}[→]{Colors.END} Range: {base}")
                    
                header = f"\n=== Range {base} (Size: {size}) ===\n".encode()
                f.write(header)
                
                data = agent.read_memory(base, size)
                f.write(data)
                f.write(b"\n")
                
                total_size += size
                dumped_ranges += 1
                
            except Exception as e:
                if args.verbose:
                    print(f"\n{Colors.YELLOW}[!]{Colors.END} Failed to dump {base}: {e}")
                continue
    
    print()  # New line after progress bar

    manager.log_success(f"Memory dump completed")
    manager.log_info(f"Ranges dumped: {dumped_ranges}/{len(ranges)}")
    manager.log_info(f"Total size: {total_size // 1024} KB")
    manager.log_info(f"Output: {memory_file}")

    # Extract strings if requested
    if args.strings:
        manager.log_info("Extracting strings...")
        strings_file = Path(output_dir) / "strings.txt"
        utils.strings(memory_file.name, output_dir)
        manager.log_success(f"Strings saved: {strings_file}")

    print(f"\n{Colors.GREEN}🐰 RushFridump completed successfully!{Colors.END}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[!] Interrupted by user{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}[✗] Fatal error: {e}{Colors.END}")
        sys.exit(1)
