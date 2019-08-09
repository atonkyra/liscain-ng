import devices.ciscoswitch
import devices.device


def remap_to_subclass(item):
    if item.device_class == 'CiscoIOS':
        item.__class__ = devices.ciscoswitch.CiscoSwitch
    return
