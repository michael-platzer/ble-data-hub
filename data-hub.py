#!/usr/bin/env python3

from gi.repository import GLib
import ble_gatt as ble

import socket
import hashlib
import base64
import struct
import json

PORT = 8080

NUS_SERVICE_UUID      = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NUS_CHARACTERISTIC_RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
NUS_CHARACTERISTIC_TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'


def ws_connection(conn):
    connf = conn.makefile(mode='rw')

    ############################################################################
    # Initialize websocket connection:

    # receive request:
    method, ws_path, proto = tuple(connf.readline().rstrip('\r\n').split())

    headers = {}
    while True:
        line = connf.readline().rstrip('\r\n')
        if len(line) == 0:
            break

        name, val = tuple([ data.strip() for data in line.split(':', 1) ])
        headers[name] = val

    ws_key = headers['Sec-WebSocket-Key']

    # write response:
    ws_key = (ws_key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('utf-8')
    ws_hash = base64.b64encode(hashlib.sha1(ws_key).digest())

    connf.write('HTTP/1.1 101 Switching Protocols\r\n')
    connf.write('Upgrade: websocket\r\n')
    connf.write('Connection: upgrade\r\n')
    connf.write(f"Sec-WebSocket-Accept: {ws_hash.decode('utf-8')}\r\n")
    connf.write('\r\n')
    connf.flush()

    # methods for sending and receiving packets:

    def websocket_send(data, pkg_type = 1):
        header = bytes([ 0x80 + pkg_type, len(data) ])
        conn.sendall(header + data)

    def websocket_recv():
        hdr = conn.recv(2, socket.MSG_WAITALL)
        fin, opcode = bool(hdr[0] & 0x80), hdr[0] & 0xF
        masking, msg_len = bool(hdr[1] & 0x80), hdr[1] & 0x7F

        if masking:
            mask = conn.recv(4, socket.MSG_WAITALL) * (msg_len // 4 + 1)

        msg = conn.recv(msg_len, socket.MSG_WAITALL)

        if masking:
            msg = bytes([ d ^ m for d, m in zip(msg, mask) ])

        # if we got a ping, return a pong:
        if opcode == 9:
            websocket_send(msg, 10)
            return None

        return msg


    ############################################################################
    # Data-hub session:

    # maintain a dict with properties of nearby devices; key is the bluez path,
    # value is a tuple with mac address, alias and uuids
    dev_props = {}

    def forward_gatt_value(dev_path, char_path, value):
        dev_addr, _, _ = dev_props[dev_path]
        msg = '{ "type": "value_update", "dev_addr": "' + dev_addr + '",'
        msg += ' "value": "' + str(value) + '" }'
        websocket_send(msg.encode('utf-8'))

    def forward_uart_packet(dev_path, char_path, packet):
        magic, pack_len, value = struct.unpack('<IIi', packet)
        forward_gatt_value(dev_path, char_path, value)

    # devices to watch: in this dict key is a device UUID and the value is
    # a tuple with a characteristic UUID and a function to be called when the
    # value of that characteristic changes:
    dev_uuids = {
        '6e400001-b5a3-f393-e0a9-e50e24dcca9e': # NUS service (watch TX)
            ('6e400003-b5a3-f393-e0a9-e50e24dcca9e', forward_uart_packet)
    }

    def new_ble_device(path, addr, alias, uuids):
        print('new ble device:', path, addr, alias)
        for dev_uuid in dev_uuids:
            if dev_uuid in uuids:
                dev_props[path] = (addr, alias, uuids)
                msg = '{ "type": "new_device", "dev_addr": "' + addr + '" }'
                websocket_send(msg.encode('utf-8'))

    def remove_ble_device(path):
        print('remove ble device:', path)
        if path in dev_props:
            addr, _, _ = dev_props[path]
            del dev_props[path]
            msg = '{ "type": "rem_device", "dev_addr": "' + addr + '" }'
            websocket_send(msg.encode('utf-8'))

    def connect_ble_device(addr):
        paths = [ path for path, prop in dev_props.items() if prop[0] == addr ]
        assert len(paths) == 1, f"no matching device for address {addr}"
        bus.connect_device(paths[0], new_service)

    def new_service(dev_path, serv_path, uuid, characteristics):
        print('new service:', serv_path, 'uuid:', uuid)
        for dev_uuid, action in dev_uuids.items():
            if dev_uuid == uuid:
                char_uuid, callback = action
                for c_path, c_uuid in characteristics.items():
                    if c_uuid == char_uuid:
                        bus.watch_gatt_char(c_path, callback)


    def websocket_message(*args):
        msg = websocket_recv()
        if msg != None:
            print('websocket message:', msg)
            fields = json.loads(msg.decode('utf-8'))
            if fields['type'] == 'conn_device':
                connect_ble_device(fields['dev_addr'])

    GLib.io_add_watch(conn.fileno(), GLib.IO_IN, websocket_message)


    bus = ble.BluezBus(new_ble_device, remove_ble_device)
    with bus:
        loop = GLib.MainLoop()
        loop.run()


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', PORT))
    sock.listen(1)

    while True:
        conn, addr = sock.accept()
        with conn:
            print('Connection from ', addr)
            ws_connection(conn)
