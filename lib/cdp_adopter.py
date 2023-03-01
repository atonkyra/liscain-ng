from lib.db import sql_ses, base
from sqlalchemy import Column, Integer, String, orm, Enum, and_, not_
import sqlalchemy.orm
import logging
from lib.config import config
import time
from devices import remap_to_subclass
from devices.device import Device
import tasks
from lib.switchstate import SwitchState
import threading
from lib.commander import Commander
import re
import requests


class CDPAdopter:
    def __init__(self, commander: Commander):
        self._logger = logging.getLogger('cdp-adopter')
        self._commander = commander

    def _jaspy_lookup(self, device, remote_device, remote_interface):
        self._logger.info(
            'cdp_adopter/%s: reverse lookup %s: %s',
            device.identifier, remote_device, remote_interface
        )
        jaspy_api = config.get('liscain', 'autoconf_cdp_jaspy_api')
        fqdn = '{}'.format(remote_device)
        device_interfaces = requests.get('{}/interface'.format(jaspy_api), params={'device_fqdn': fqdn}).json()
        whoami = None
        for device_interface in device_interfaces:
            if remote_interface == device_interface['name'] or remote_interface == device_interface['description']:
                for part in device_interface['alias'].split():
                    if 'liscain:' in part:
                        _, whoami = part.split(':', 1)
                        break
                if whoami is not None:
                    break
        return whoami

    def autoadopt(self, device):
        re_cisco_cdp_remote_device = re.compile(
            r'^Device ID: (?P<remote_device>.+?)$',
            re.MULTILINE
        )
        re_cisco_cdp_interfaces = re.compile(
            r'^Interface: (?P<local_interface>.+?),(.+)?Port ID \(outgoing port\): (?P<remote_interface>.+)$',
            re.MULTILINE
        )
        cdp_info = device.neighbor_info(True)
        whoami_results = set()
        for switch_data in cdp_info.split('------'):
            if 'Device ID' not in switch_data:
                continue
            switch_data = switch_data.strip('-')
            remote_device_match = re_cisco_cdp_remote_device.search(switch_data)
            interfaces_match = re_cisco_cdp_interfaces.search(switch_data)
            if not remote_device_match or not interfaces_match:
                continue
            groupdict_remotedev = remote_device_match.groupdict()
            groupdict_ifaces = interfaces_match.groupdict()

            whoami = self._jaspy_lookup(device, groupdict_remotedev['remote_device'], groupdict_ifaces['remote_interface'])
            if whoami is not None:
                whoami_results.add(whoami)

        switch_name = None
        if len(whoami_results) == 1:
            switch_name = whoami_results.pop()
            self._logger.info(
                'cdp_adopter/%s: reverse switch CDP neighbors resolved to %s',
                device.identifier, switch_name
            )
        elif len(whoami_results) > 1:
            self._logger.error(
                'cdp_adopter/%s: more than 1 result for reverse switch CDP neighbors (%s)',
                device.identifier, whoami_results
            )
            return
        else:
            self._logger.error(
                'cdp_adopter/%s: unable to find reverse switch CDP neighbors',
                device.identifier
            )
            return

        autoconf_path = config.get('liscain', 'autoconf_path')
        whitelisted_prefixes = config.get('liscain', 'autoconf_version_whitelist_prefix')
        version_ok = False
        if whitelisted_prefixes is None:
            version_ok = True
        else:
            whitelisted_prefixes = whitelisted_prefixes.split(',')
            for whitelisted_prefix in whitelisted_prefixes:
                if device.version.startswith(whitelisted_prefix):
                    version_ok = True
                    break

        if not version_ok:
            self._logger.info(
                'cdp_adopter/%s (%s @ %s) does not meet autoconf criteria (version)',
                device.identifier, switch_name, device.address
            )
            return

        config_path = '{}/{}.cfg'.format(autoconf_path, switch_name)
        self._logger.info('cdp_adopter/%s: trying autoadopt for %s', device.identifier, switch_name)
        switch_config = None
        try:
            with open(config_path) as fp:
                switch_config = fp.read()
        except FileNotFoundError:
            self._logger.error('cdp_adopter/%s: failed to open %s for switch autoconfiguration', device.identifier, config_path)
            return
        try:
            self._commander.enqueue(
                device,
                tasks.DeviceConfigurationTask(device, identity=switch_name, configuration=switch_config),
            )
        except BaseException as e:
            self._logger.error(e)


