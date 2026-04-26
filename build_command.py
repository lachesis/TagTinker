#!/usr/bin/env python3
import argparse
import glob
import sys
import os

try:
    import serial
    HAS_PYSERIAL = True
except ImportError:
    HAS_PYSERIAL = False

def tagtinker_barcode_to_plid(barcode):
    """Convert 17-digit barcode to 4-byte plid. Returns None if invalid."""
    if not barcode or len(barcode) != 17:
        return None
    a = 0
    for i in range(2, 7):
        a = a * 10 + (ord(barcode[i]) - ord('0'))
    b = 0
    for i in range(7, 12):
        b = b * 10 + (ord(barcode[i]) - ord('0'))
    id_val = (a << 16) | b
    return [
        id_val & 0xFF,
        (id_val >> 8) & 0xFF,
        (id_val >> 16) & 0xFF,
        (id_val >> 24) & 0xFF,
    ]

def parse_plid_input(input_str):
    """Parse plid from barcode, hex string, or 0. Returns lower/zfilled 8-char hex."""
    if input_str == '0':
        return '00000000'
    elif len(input_str) == 17:
        plid = tagtinker_barcode_to_plid(input_str)
        if plid is None:
            return None
        return ''.join(f"{b:02x}" for b in plid).zfill(8)
    elif len(input_str) == 8 and all(c in '0123456789abcdefABCDEF' for c in input_str):
        return input_str.lower().zfill(8)
    else:
        return None

def cmd_page(plid_hex, page, duration, bit7=None, bit2=None, bit1=None):
    page_val = int(page) & 0xF
    forever = duration is None
    cmd_byte = 0x01 | ((page_val & 0xf) << 3) | (0x80 if forever else 0x00)

    if bit7 is not None:
        cmd_byte = (cmd_byte & ~0x80) | ((bit7 & 1) << 7)
    if bit2 is not None:
        cmd_byte = (cmd_byte & ~0x04) | ((bit2 & 1) << 2)
    if bit1 is not None:
        cmd_byte = (cmd_byte & ~0x02) | ((bit1 & 1) << 1)

    plid_bytes = [int(plid_hex[i:i+2], 16) for i in range(0, 8, 2)]

    if duration is not None:
        dur_bytes = [(duration >> 8) & 0xFF, duration & 0xFF]
    else:
        dur_bytes = [0x00, 0x00]

    result = [0x85] + plid_bytes + [0x06, cmd_byte, 0x00, 0x00] + dur_bytes
    return ' '.join(f"{b:02X}" for b in result)

def cmd_refresh(plid_hex):
    cmd_byte = 0xD9
    plid_bytes = [int(plid_hex[i:i+2], 16) for i in range(0, 8, 2)]
    result = [0x85] + plid_bytes + [0x06, cmd_byte, 0x00, 0x00, 0x00, 0x00]
    return ' '.join(f"{b:02X}" for b in result)

def cmd_debugpage(plid_hex):
    cmd_byte = 0xF9
    plid_bytes = [int(plid_hex[i:i+2], 16) for i in range(0, 8, 2)]
    result = [0x85] + plid_bytes + [0x06, cmd_byte, 0x00, 0x00, 0x00, 0x00]
    return ' '.join(f"{b:02X}" for b in result)

def cmd_ping(plid_hex):
    plid_bytes = [int(plid_hex[i:i+2], 16) for i in range(0, 8, 2)]
    result = [0x85] + plid_bytes + [0x97, 0x01, 0x00, 0x00, 0x00] + [0x01] * 20
    return ' '.join(f"{b:02X}" for b in result)

def cmd_blink(plid_hex, duration, bright):
    if duration is None:
        duration = 1
    cmd_byte = (0x80 if bright else 0x00) | (9 << 3) | 0x01

    plid_bytes = [int(plid_hex[i:i+2], 16) for i in range(0, 8, 2)]
    dur_bytes = [(duration >> 8) & 0xFF, duration & 0xFF]

    result = [0x85] + plid_bytes + [0x06, cmd_byte, 0x00, 0x00] + dur_bytes
    return ' '.join(f"{b:02X}" for b in result)

def cmd_logo(plid_hex, off):
    cmd_byte = 0x80 | (10 << 3) | (0x02 if off else 0x00) | 0x01
    plid_bytes = [int(plid_hex[i:i+2], 16) for i in range(0, 8, 2)]
    result = [0x85] + plid_bytes + [0x06, cmd_byte, 0x00, 0x00, 0x00, 0x00]
    return ' '.join(f"{b:02X}" for b in result)

def find_flipper_serial_port():
    """Find /dev/ttyACM* devices. Returns port path or None if count != 1."""
    ports = glob.glob('/dev/ttyACM*')
    if len(ports) == 1:
        return ports[0]
    return None

class BufferedRead:
    def __init__(self, stream):
        self.buffer = bytearray()
        self.stream = stream

    def until(self, eol: str = "\n", cut_eol: bool = True):
        eol = eol.encode("ascii")
        while True:
            # search in buffer
            i = self.buffer.find(eol)
            if i >= 0:
                if cut_eol:
                    read = self.buffer[:i]
                else:
                    read = self.buffer[: i + len(eol)]
                self.buffer = self.buffer[i + len(eol) :]
                return read

            # read and append to buffer
            i = max(1, self.stream.in_waiting)
            data = self.stream.read(i)
            self.buffer.extend(data)

def write_to_serial(port_path, data):
    """Open port with pyserial, write command, close. Returns True on success."""
    if not HAS_PYSERIAL:
        return False
    try:
        with serial.Serial(port_path, 230400, bytesize=serial.EIGHTBITS,
                         parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                         timeout=10) as ser:
            ser.write("\r\n")
            read = BufferedRead(ser)
            read.until(">: ")
            ser.write(data.encode('ascii'))
        return True
    except Exception:
        return False

def main():
    parser = argparse.ArgumentParser(prog='build_command.py')
    parser.add_argument('plid', help='hex plid, barcode, or 0')
    parser.add_argument('--serial', help='serial port path or AUTO')
    parser.add_argument('--no-spaces', action='store_true', help='remove spaces from output')
    subparsers = parser.add_subparsers(dest='subcommand', help='subcommand')

    flip_parser = subparsers.add_parser('page', help='page flip command')
    flip_parser.add_argument('page', help='page number (decimal)')
    flip_parser.add_argument('--duration', type=int, help='duration in ms')
    flip_parser.add_argument('--bit7', type=int, choices=[0, 1], help='override bit 7 of command byte')
    flip_parser.add_argument('--bit2', type=int, choices=[0, 1], help='override bit 2 of command byte')
    flip_parser.add_argument('--bit1', type=int, choices=[0, 1], help='override bit 1 of command byte')

    blink_parser = subparsers.add_parser('blink')
    blink_parser.add_argument('--duration', type=int, help='duration in ms (default 1)')
    blink_parser.add_argument('--bright', action='store_true', help='bright mode')

    subparsers.add_parser('refresh')
    subparsers.add_parser('debugpage')
    subparsers.add_parser('ping')
    logo_parser = subparsers.add_parser('logo')
    logo_parser.add_argument('state', choices=['on', 'off'], help='logo on or off')
    raw_parser = subparsers.add_parser('raw')
    raw_parser.add_argument('bytes', nargs='*', help='hex bytes to send')

    args = parser.parse_args()

    serial_path = args.serial
    if serial_path == 'AUTO':
        serial_path = find_flipper_serial_port()
        if serial_path is None:
            print("Error: AUTO found 0 or multiple /dev/ttyACM* devices", file=sys.stderr)
            sys.exit(1)
    elif serial_path and not os.path.exists(serial_path):
        print(f"Error: serial file '{serial_path}' does not exist", file=sys.stderr)
        sys.exit(1)

    plid_hex = parse_plid_input(args.plid)
    if plid_hex is None:
        print("Error: invalid plid input", file=sys.stderr)
        sys.exit(1)

    output = None
    if args.subcommand == 'page':
        output = cmd_page(plid_hex, args.page, args.duration, args.bit7, args.bit2, args.bit1)
    elif args.subcommand == 'blink':
        output = cmd_blink(plid_hex, args.duration, args.bright)
    elif args.subcommand == 'refresh':
        output = cmd_refresh(plid_hex)
    elif args.subcommand == 'debugpage':
        output = cmd_debugpage(plid_hex)
    elif args.subcommand == 'ping':
        output = cmd_ping(plid_hex)
    elif args.subcommand == 'logo':
        output = cmd_logo(plid_hex, args.state == 'off')
    elif args.subcommand == 'raw':
        plid_bytes = [int(plid_hex[i:i+2], 16) for i in range(0, 8, 2)]
        output = ' '.join(f"{b:02X}" for b in plid_bytes) + ((' ' + ' '.join(args.bytes)) if args.bytes else '')
    else:
        print("Error: no subcommand specified", file=sys.stderr)
        sys.exit(1)

    if args.no_spaces:
        output = output.replace(' ', '')

    print(output)
    if serial_path:
        cmd = f"tag rawsend {output}\r\n"
        if not write_to_serial(serial_path, cmd):
            with open(serial_path, 'a') as f:
                f.write(cmd)

if __name__ == "__main__":
    main()
