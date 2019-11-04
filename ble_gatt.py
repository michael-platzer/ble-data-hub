#!/usr/bin/env python3

# inspired by: https://github.com/aykevl/pynus

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

DBUS_OBJ_MAN = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROPS = 'org.freedesktop.DBus.Properties'

BLUEZ = 'org.bluez'
BLUEZ_ADAPTER = 'org.bluez.Adapter1'
BLUEZ_DEVICE = 'org.bluez.Device1'
BLUEZ_GATTSERV = 'org.bluez.GattService1'
BLUEZ_GATTCHAR = 'org.bluez.GattCharacteristic1'
BLUEZ_GATTDESC = 'org.bluez.GattDescriptor1'

class BluezBus:
    def __init__(self, new_device_cb, remove_device_cb):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        self._sysbus = dbus.SystemBus()
        self._bluez = dbus.Interface(self._sysbus.get_object(BLUEZ, '/'), DBUS_OBJ_MAN)

        self._new_dev_cb = new_device_cb
        self._rem_dev_cb = remove_device_cb

        self._adapters = []
        self._connected_devices = {}
        self._monitored_gatt_chars = {}

    def __enter__(self):
        for path, interfaces in self._bluez.GetManagedObjects().items():
            if BLUEZ_ADAPTER in interfaces:
                self._adapters.append(path)
            if BLUEZ_DEVICE in interfaces:
                self._on_new_device(path, interfaces)

        self._sig_recv_new = self._sysbus.add_signal_receiver(lambda *args: self._on_new_device(*args), dbus_interface=DBUS_OBJ_MAN, signal_name='InterfacesAdded')
        self._sig_recv_rem = self._sysbus.add_signal_receiver(lambda *args: self._on_rem_device(*args), dbus_interface=DBUS_OBJ_MAN, signal_name='InterfacesRemoved')

        for path in self._adapters:
            obj = dbus.Interface(self._sysbus.get_object(BLUEZ, path), BLUEZ_ADAPTER)
            obj.StartDiscovery()

        return self

    def __exit__(self, type, value, traceback):
        self._sig_recv_new.remove()
        self._sig_recv_rem.remove()

        for path in self._adapters:
            obj = dbus.Interface(self._sysbus.get_object(BLUEZ, path), BLUEZ_ADAPTER)
            obj.StopDiscovery()

        for path, device in self._connected_devices.items():
            device.disconnect()

    def _on_new_device(self, path, interfaces):
        if BLUEZ_DEVICE in interfaces:
            props = interfaces[BLUEZ_DEVICE]
            self._new_dev_cb(path, props['Address'], props['Alias'], list(props['UUIDs']))

    def _on_rem_device(self, path, interfaces):
        if BLUEZ_DEVICE in interfaces:
            self._rem_dev_cb(path)

    def connect_device(self, path, new_service_cb, rem_service_cb = lambda *args: None):
        dev = BluezDevice(self, path, new_service_cb, rem_service_cb)
        self._connected_devices[path] = dev
        dev.connect()

    def disconnect_device(self, path):
        dev = self._connected_devices[path]
        dev.disconnect()
        del self._connected_devices[path]

    def watch_gatt_char(self, path, value_changed_cb):
        d_paths = [ p for p in self._connected_devices if path.startswith(p) ]
        assert len(d_paths) == 1, f"device for GATT char {path} not found"
        char = BluezGattChar(self, d_paths[0], path, value_changed_cb)
        self._monitored_gatt_chars[path] = char

    def modify_gatt_char(self, path, value):
        char = dbus.Interface(self._sysbus.get_object(BLUEZ, path), BLUEZ_GATTCHAR)
        char.WriteValue(value, {})


class BluezDevice:
    def __init__(self, bus, path, new_service_cb, remove_service_cb):
        self._bus = bus

        self._device = dbus.Interface(self._bus._sysbus.get_object(BLUEZ, path), BLUEZ_DEVICE)

        self._path = path

        self._new_serv_cb = new_service_cb
        self._rem_serv_cb = remove_service_cb

        device_props = dbus.Interface(self._device, DBUS_PROPS)
        self._sig_recv = device_props.connect_to_signal('PropertiesChanged', lambda *args: self._on_prop_changed(*args))

    def __del__(self):
        self._sig_recv.remove()

    def _on_prop_changed(self, properties, changed_props, invalidated_props):
        if changed_props.get('ServicesResolved', False):
            self._probe_services()

    def _probe_services(self):
        man_objs = self._bus._bluez.GetManagedObjects()

        for path, interfaces in man_objs.items():
            if path.startswith(self._path) and BLUEZ_GATTSERV in interfaces:
                props = interfaces[BLUEZ_GATTSERV]

                chars = {}
                for c_path, c_ifaces in man_objs.items():
                    if c_path.startswith(path) and BLUEZ_GATTCHAR in c_ifaces:
                        c_props = c_ifaces[BLUEZ_GATTCHAR]
                        chars[c_path] = c_props['UUID']

                self._new_serv_cb(self._path, path, props['UUID'], chars)

    def connect(self):
        self._device.Connect()

    def disconnect(self):
        self._device.Disconnect()

class BluezGattChar:
    def __init__(self, bus, dev_path, path, value_changed_cb):
        self._bus = bus

        self._char = dbus.Interface(self._bus._sysbus.get_object(BLUEZ, path), BLUEZ_GATTCHAR)
        self._char_props = dbus.Interface(self._char, DBUS_PROPS)

        self._dev_path = dev_path
        self._path = path
        self._props = self._bus._bluez.GetManagedObjects()[self._path]

        self._val_chgd_cb = value_changed_cb

        self._sig_recv = self._char_props.connect_to_signal('PropertiesChanged', lambda *args: self._on_prop_changed(*args))
        self._char.StartNotify()

    def __del__(self):
        self._sig_recv.remove()

    def _on_prop_changed(self, properties, changed_props, invalidated_props):
        if 'Value' in changed_props:
            self._val_chgd_cb(self._dev_path, self._path, bytes(changed_props['Value']))

    def get_value(self):
        return bytes(self._char.ReadValue({}))

    def set_value(self, value):
        self._char.WriteValue(value, {})
