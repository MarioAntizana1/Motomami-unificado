#!/usr/bin/env python3
import dbus, dbus.service, dbus.mainloop.glib
from gi.repository import GLib

P = "/test/agent"

class Agent(dbus.service.Object):
    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self): pass
    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, d): return "0000"
    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, d, p): pass
    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, d): return dbus.UInt32(0)
    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, d, p, e): pass
    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, d, p): pass
    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, d): pass
    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, d, u): pass
    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self): pass

dbus.mainloop.glib.DBusGMainLoop(set_default_as_default=True)
bus = dbus.SystemBus()
mgr = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1")
agent = Agent(bus, P)
mgr.RegisterAgent(P, "NoInputNoOutput")
mgr.RequestDefaultAgent(P)
print("Agent registered OK")
GLib.MainLoop().run()
