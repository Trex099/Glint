"""
Core utility functions for the Universal VM Manager.

This module provides a collection of helper functions for command execution,
file operations, user interaction, and network configuration.
"""

import os
import subprocess
import sys
import shutil
import random
import time
import socket
import shlex


class Style:
    """
    Defines ANSI escape codes for styling terminal output.
    """
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

    @staticmethod
    def dummy():
        """
        Dummy method to satisfy pylint's too-few-public-methods warning.
        """


def print_header(text):
    """Prints a styled header to the console."""
    print(f"\n{Style.HEADER}{Style.BOLD}--- {text} ---{Style.ENDC}")


def print_info(text):
    """Prints an informational message to the console."""
    print(f"{Style.OKCYAN}ℹ️  {text}{Style.ENDC}")


def print_success(text):
    """Prints a success message to the console."""
    print(f"{Style.OKGREEN}✅ {text}{Style.ENDC}")


def print_warning(text):
    """Prints a warning message to the console."""
    print(f"{Style.WARNING}⚠️  {text}{Style.ENDC}")


def print_error(text):
    """Prints an error message to the console."""
    print(f"{Style.FAIL}❌ {text}{Style.ENDC}", file=sys.stderr)


def clear_screen():
    """Clears the console screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def run_command_live(cmd_list, as_root=False, check=True, quiet=False):
    """
    Runs a command and prints its output live.
    """
    if as_root and os.geteuid() != 0:
        cmd_list.insert(0, "sudo")

    cmd_str = ' '.join(shlex.quote(s) for s in cmd_list)
    print(f"\n{Style.OKBLUE}▶️  Executing: {cmd_str}{Style.ENDC}")

    try:
        if quiet:
            # For quiet execution, capture output and only show it on error.
            with subprocess.Popen(cmd_list, capture_output=True, text=True) as process:
                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    print_error(f"Command failed with exit code {process.returncode}")
                    print_error(f"Stderr: {stderr.strip()}")
                else:
                    print_success("  Done.")
                return stdout
        # For live execution, stream output.
        with subprocess.Popen(cmd_list, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, bufsize=1) as process:
            output_lines = []
            for line in iter(process.stdout.readline, ''):
                print(f"  {line.strip()}", flush=True)
                output_lines.append(line)
            process.stdout.close()
            return_code = process.wait()
            if check and return_code != 0:
                raise subprocess.CalledProcessError(return_code, cmd_list,
                                                     output="".join(output_lines))
            return "".join(output_lines)

    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print_error(f"Command failed: {e}")
        if hasattr(e, 'output'):
            print_error(f"Output:\n{e.output}")
        return None


def _run_command(cmd, as_root=False):
    """
    Runs a command and returns its output.
    """
    try:
        if as_root and os.geteuid() != 0:
            cmd.insert(0, "sudo")
        result = subprocess.run(cmd, capture_output=True, text=True,
                                check=True, encoding='utf-8')
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        output = ""
        if hasattr(e, 'stdout') and e.stdout:
            output += e.stdout.strip()
        if hasattr(e, 'stderr') and e.stderr:
            output += e.stderr.strip()
        return output


def _create_launcher_script(script_path, commands, as_root=False):
    """
    Dynamically creates a shell script to run a series of commands in a new terminal.
    """
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write("#!/bin/bash\nset -e\n")
        f.write(f"echo -e '{Style.HEADER}--- VM LAUNCHER "
                f"(This terminal will close when the VM shuts down) ---{Style.ENDC}'\n\n")
        for title, cmd_list in commands:
            final_cmd = "exec " if cmd_list == commands[-1][1] else ""
            if as_root and os.geteuid() != 0:
                cmd_list.insert(0, "sudo")
            quoted_cmd = ' '.join(shlex.quote(s) for s in cmd_list)
            f.write(f"echo -e '{Style.OKBLUE}▶️  {title}...{Style.ENDC}'\n"
                    f"{final_cmd}{quoted_cmd}\n\n")
    os.chmod(script_path, 0o755)


def get_terminal_command(shell_script_path):
    """
    Returns the full command list to launch a command in a new terminal.
    """
    terminals = {'konsole': '-e', 'gnome-terminal': '--', 'xfce4-terminal': '-x', 'xterm': '-e'}
    for term, arg in terminals.items():
        if shutil.which(term):
            return [term, arg, 'bash', shell_script_path]
    return None


def launch_in_new_terminal_and_wait(commands, as_root_script=False):
    """
    Generates a launcher script and executes it in a new terminal,
    WAITING for it to complete.
    """
    script_path = f"/tmp/vm_launcher_{os.getpid()}_{random.randint(1000, 9999)}.sh"
    try:
        _create_launcher_script(script_path, commands, as_root=as_root_script)
        terminal_cmd = get_terminal_command(script_path)
        if not terminal_cmd:
            print_error("No supported terminal found! "
                        "Please run the script manually from the launcher file.")
            print_info(f"Launcher script created at: {script_path}")
            return False

        print_info("Launching VM in a new terminal window... "
                   "The script will wait for it to close.")
        with subprocess.Popen(terminal_cmd) as process:
            process.wait()
        print_info("VM process has terminated.")
        return True
    finally:
        if os.path.exists(script_path):
            time.sleep(1)
            os.remove(script_path)


def remove_file(path, as_root=False):
    """
    Removes a file.
    """
    if as_root:
        if run_command_live(['rm', '-f', path], as_root=True, check=False) is not None:
            print_success(f"Removed: {path}")
            return True
        print_error(f"Could not remove file {path}. Check permissions.")
        return False
    try:
        os.remove(path)
        print_success(f"Removed: {path}")
        return True
    except OSError as e:
        print_error(f"Could not remove file {path}: {e}")
        return False


def remove_dir(path):
    """
    Removes a directory.
    """
    try:
        shutil.rmtree(path)
        print_success(f"Deleted VM: {os.path.basename(path)}")
        return True
    except OSError as e:
        print_error(f"Could not delete directory {path}: {e}")
        return False


def select_from_list(items, prompt, display_key=None):
    """
    Prompts the user to select an item from a list.
    """
    for i, item in enumerate(items):
        display_text = item[display_key] if display_key and isinstance(item, dict) \
            else os.path.basename(item)
        print(f"  {Style.OKBLUE}{i + 1}.{Style.ENDC} {display_text}")
    while True:
        try:
            choice = int(input(f"{Style.BOLD}{prompt} [1-{len(items)}]: {Style.ENDC}").strip())
            if 1 <= choice <= len(items):
                return items[choice - 1]
        except ValueError:
            pass
        print_warning("Invalid selection.")


def find_host_dns():
    """
    Finds the best DNS server from the host's resolv.conf.
    Skips local addresses and falls back to a public DNS.
    """
    try:
        with open("/etc/resolv.conf", "r", encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith("nameserver"):
                    dns_server = line.strip().split()[1]
                    if not dns_server.startswith("127."):
                        print_info(f"Found non-local DNS server: {dns_server}")
                        return dns_server  # Return the first non-local DNS server
    except FileNotFoundError:
        pass  # Fallback to public DNS
    print_warning("No non-local DNS server found, falling back to 8.8.8.8.")
    return "8.8.8.8"  # Default public DNS


def find_unused_port():
    """
    Finds an unused port on the host.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def setup_bridge_network():
    """
    This function previously handled bridge setup but now returns a reliable
    'user' network configuration to ensure stability, as proven by comparison
    with a working reference script.
    """
    print_header("Network Configuration")
    print_info("Using reliable 'user' networking mode for maximum compatibility.")
    dns_server = find_host_dns()
    return f"user,id=net0,dns={dns_server}"


import requests
from tqdm import tqdm

def download_file(url, destination):
    """
    Downloads a file from a URL to a destination, with a progress bar.
    """
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(destination, 'wb') as f:
                pbar = tqdm(total=int(r.headers.get('content-length', 0)), unit='B', unit_scale=True, desc=destination)
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))
                pbar.close()
        return True
    except requests.exceptions.RequestException as e:
        print_error(f"Failed to download {url}: {e}")
        return False


def detect_distro():
    """
    Detects the Linux distribution.
    """
    try:
        with open("/etc/os-release", "r", encoding='utf-8') as f:
            for line in f:
                if line.startswith("ID="):
                    return line.strip().split("=")[1].lower().strip('"')
    except FileNotFoundError:
        return None
    return None
