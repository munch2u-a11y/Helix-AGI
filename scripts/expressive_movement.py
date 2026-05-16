import os
import fcntl
import struct
import time
import sys

V4L2_CID_PAN_ABSOLUTE = 0x009a0908
V4L2_CID_TILT_ABSOLUTE = 0x009a0909
VIDIOC_S_CTRL = 0xc008561c

def send_ptz(device, pan_deg=None, tilt_deg=None):
    if not os.path.exists(device):
        print(f"Device {device} not found.")
        return

    try:
        fd = os.open(device, os.O_RDWR)
        try:
            if pan_deg is not None:
                # 1 degree = 3600 arc-seconds
                val = int(pan_deg * 3600)
                data = struct.pack('ii', V4L2_CID_PAN_ABSOLUTE, val)
                fcntl.ioctl(fd, VIDIOC_S_CTRL, data)
            if tilt_deg is not None:
                val = int(tilt_deg * 3600)
                data = struct.pack('ii', V4L2_CID_TILT_ABSOLUTE, val)
                fcntl.ioctl(fd, VIDIOC_S_CTRL, data)
        finally:
            os.close(fd)
    except Exception as e:
        print(f"Error: {e}")

def nod(device, degrees=10, count=1):
    for _ in range(count):
        send_ptz(device, tilt_deg=degrees)
        time.sleep(0.5)
        send_ptz(device, tilt_deg=-degrees)
        time.sleep(0.5)
    send_ptz(device, tilt_deg=0)

def shake(device, degrees=15, count=1):
    for _ in range(count):
        send_ptz(device, pan_deg=degrees)
        time.sleep(0.5)
        send_ptz(device, pan_deg=-degrees)
        time.sleep(0.5)
    send_ptz(device, pan_deg=0)

if __name__ == "__main__":
    cam = "/dev/video0"
    cmd = sys.argv[1] if len(sys.argv) > 1 else "nod"
    
    if cmd == "nod":
        nod(cam)
    elif cmd == "shake":
        shake(cam)
    else:
        print("Usage: expressive_movement.py [nod|shake]")
