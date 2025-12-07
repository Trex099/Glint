import sys, os, time, ssl
# import gzip, multiprocessing
# from io import BytesIO
# Python-aware urllib stuff
try:
    # from urllib.request import urlopen, Request  # These are unused
    import queue as q
except ImportError:
    # Import urllib2 to catch errors
    # Use the specific imports we need instead of the whole module
    # from urllib2 import urlopen, Request  # These are unused in this context
    import Queue as q

TERMINAL_WIDTH = 120 if os.name=="nt" else 80

def get_size(size, suffix=None, use_1024=False, round_to=2, strip_zeroes=False):
    # size is the number of bytes
    # suffix is the target suffix to locate (B, KB, MB, etc) - if found
    # use_2014 denotes whether or not we display in MiB vs MB
    # round_to is the number of dedimal points to round our result to (0-15)
    # strip_zeroes denotes whether we strip out zeroes 

    # Failsafe in case our size is unknown
    if size == -1:
        return "Unknown"
    # Get our suffixes based on use_1024
    ext = ["B","KiB","MiB","GiB","TiB","PiB"] if use_1024 else ["B","KB","MB","GB","TB","PB"]
    div = 1024 if use_1024 else 1000
    s = float(size)
    s_dict = {} # Initialize our dict
    # Iterate the ext list, and divide by 1000 or 1024 each time to setup the dict {ext:val}
    for e in ext:
        s_dict[e] = s
        s /= div
    # Get our suffix if provided - will be set to None if not found, or if started as None
    suffix = next((x for x in ext if x.lower() == suffix.lower()),None) if suffix else suffix
    # Get the largest value that's still over 1
    biggest = suffix if suffix else next((x for x in ext[::-1] if s_dict[x] >= 1), "B")
    # Determine our rounding approach - first make sure it's an int; default to 2 on error
    try:round_to=int(round_to)
    except:round_to=2
    round_to = 0 if round_to < 0 else 15 if round_to > 15 else round_to # Ensure it's between 0 and 15
    bval = round(s_dict[biggest], round_to)
    # Split our number based on decimal points
    a,b = str(bval).split(".")
    # Check if we need to strip or pad zeroes
    b = b.rstrip("0") if strip_zeroes else b.ljust(round_to,"0") if round_to > 0 else ""
    return "{:,}{} {}".format(int(a),"" if not b else "."+b,biggest)

def _process_hook(queue, total_size, bytes_so_far=0, update_interval=1.0, max_packets=0):
    packets = []
    speed = remaining = ""
    last_update = time.time()
    while True:
        # Write our info first so we have *some* status while
        # waiting for packets
        if total_size > 0:
            percent = float(bytes_so_far) / total_size
            percent = round(percent*100, 2)
            t_s = get_size(total_size)
            try:
                b_s = get_size(bytes_so_far, t_s.split(" ")[1])
            except:
                b_s = get_size(bytes_so_far)
            perc_str = " {:.2f}%".format(percent)
            bar_width = (TERMINAL_WIDTH // 3)-len(perc_str)
            progress = "=" * int(bar_width * (percent/100))
            sys.stdout.write("\r\033[K{}/{} | {}{}{}{}{}".format(
                b_s,
                t_s,
                progress,
                " " * (bar_width-len(progress)),
                perc_str,
                speed,
                remaining
            ))
        else:
            b_s = get_size(bytes_so_far)
            sys.stdout.write("\r\033[K{}{}".format(b_s, speed))
        sys.stdout.flush()
        # Now we gather the next packet
        try:
            packet = queue.get(timeout=update_interval)
            # Packets should be formatted as a tuple of
            # (timestamp, len(bytes_downloaded))
            # If "DONE" is passed, we assume the download
            # finished - and bail
            if packet == "DONE":
                print("") # Jump to the next line
                return
            # Append our packet to the list and ensure we're not
            # beyond our max.
            # Only check max if it's > 0
            packets.append(packet)
            if max_packets > 0:
                packets = packets[-max_packets:]
            # Increment our bytes so far as well
            bytes_so_far += packet[1]
        except q.Empty:
            # Didn't get anything - reset the speed
            # and packets
            packets = []
            speed = " | 0 B/s"
            remaining = " | ?? left" if total_size > 0 else ""
        except KeyboardInterrupt:
            print("") # Jump to the next line
            return
        # If we have packets and it's time for an update, process
        # the info.
        update_check = time.time()
        if packets and update_check - last_update >= update_interval:
            last_update = update_check # Refresh our update timestamp
            speed = " | ?? B/s"
            if len(packets) > 1:
                # Let's calculate the amount downloaded over how long
                try:
                    first,last = packets[0][0],packets[-1][0]
                    chunks = sum([float(x[1]) for x in packets])
                    t = last-first
                    assert t >= 0
                    bytes_speed = 1. / t * chunks
                    speed = " | {}/s".format(get_size(bytes_speed,round_to=1))
                    # Get our remaining time
                    if total_size > 0:
                        seconds_left = (total_size-bytes_so_far) / bytes_speed
                        days  = seconds_left // 86400
                        hours = (seconds_left - (days*86400)) // 3600
                        mins  = (seconds_left - (days*86400) - (hours*3600)) // 60
                        secs  = seconds_left - (days*86400) - (hours*3600) - (mins*60)
                        if days > 99 or bytes_speed == 0:
                            remaining = " | ?? left"
                        else:
                            remaining = " | {}{:02d}:{:02d}:{:02d} left".format(
                                "{}:".format(int(days)) if days else "",
                                int(hours),
                                int(mins),
                                int(round(secs))
                            )
                except:
                    pass
                # Clear the packets so we don't reuse the same ones
                packets = []

import urllib.request
# ssl already imported at the top
import os

class Downloader:
    def __init__(self, **kwargs):
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        # Use system proxy settings
        proxy = urllib.request.getproxies()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxy)
        )
        self.opener.addheaders = [('User-agent', 'Mozilla/5.0')]
        self.url = kwargs.get("url", None)
        self.binary = kwargs.get("binary", False)
        self.silent = kwargs.get("silent", False)

    def get_string(self):
        if not self.url:
            return None
        try:
            response = self.opener.open(self.url)
            return response.read().decode("utf-8")
        except:
            return None

    def get_binary(self):
        if not self.url:
            return None
        try:
            response = self.opener.open(self.url)
            return response.read()
        except:
            return None
