from lib.switchstate import SwitchState
from lib.config import config
import telnetlib
import re
import socket
import time
from io import StringIO
import devices.device


class CiscoIOS(devices.device.Device):
    def __init__(self):
        super().__init__()
        self.device_class = 'CiscoIOS'

    def neighbor_info(self):
        try:
            tc = telnetlib.Telnet(self.address, timeout=3)
            self._write(tc, None, [b'\r\n[Uu]sername: '])
            self._write(tc, config.get('liscain', 'liscain_init_username'), [b'\r\n[Pp]assword: '])
            self._write(tc, config.get('liscain', 'liscain_init_password'))
            self._write(tc, 'terminal length 0')
            nbr_info = ['cdp']
            neigh_info_started = False
            for line in self._write(tc, 'show cdp neigh').split('\n')[:-1]:
                line = line.strip()
                if 'Device ID' in line:
                    neigh_info_started = True
                if neigh_info_started:
                    nbr_info.append(line)

            return '\n'.join(nbr_info)

        except socket.timeout:
            self._logger.info('timeout getting neighbor info')
            return 'unknown'

        except EOFError:
            self._logger.info('switch not ready while getting neighbor info')
            return 'unknown'

    def initial_setup(self) -> bool:
        retry_max = 10
        for retry in range(1, retry_max+1):
            try:
                tc = telnetlib.Telnet(self.address, timeout=10)
                self._write(tc, None, [b'\r\n[Uu]sername: '])
                self._write(tc, config.get('liscain', 'liscain_init_username'), [b'\r\n[Pp]assword: '])
                self._write(tc, config.get('liscain', 'liscain_init_password'))
                self._logger.debug('logged in')
                self._write(tc, 'terminal length 0')
                self._read_mac(tc)
                self._read_pid(tc)
                self._read_version(tc)
                self._logger.info('generating ssh keys...')
                self._write(tc, 'configure terminal')
                self._write(tc, 'ip ssh rsa keypair-name ssh')
                self._write(tc, 'crypto key generate rsa general-keys label ssh mod 2048', timeout=120)
                self._write(tc, 'sdm prefer dual-ipv4-and-ipv6 default', timeout=10)
                self._write(tc, 'sdm prefer dual-ipv4-and-ipv6 vlan', timeout=10)
                self._write(tc, 'end')
                self._write(tc, 'exit')
                self._logger.debug('logged out')
                self._logger.info('successfully initialized switch')
                return True
            except socket.timeout:
                self._logger.info('timeout, retry %i/%i', retry, retry_max)
                continue
            except EOFError:
                self._logger.info('switch not ready, wait 10s (retry %i/%i)', retry, retry_max)
                time.sleep(10)
        self._logger.error('failed initial setup')
        return False

    def _parse_confighints(self, config):
        hints = {}
        for line in config.split('\n'):
            line = line.strip()
            if not line.startswith('! liscain::'):
                continue
            key, value = line.split('::')[-1].split()
            hints[key.strip()] = value.strip()
        return hints

    def configure(self, switch_config):
        try:
            hints = self._parse_confighints(switch_config)
            if 'device_type' in hints:
                if hints['device_type'].lower() not in self.device_type.lower():
                    self._logger.error(
                        '[configure] wrong device type, expected %s within %s',
                        hints['device_type'],
                        self.device_type,
                    )
                    return False
            tc = telnetlib.Telnet(self.address, timeout=10)
            self._write(tc, None, [b'\r\n[Uu]sername: '])
            self._write(tc, config.get('liscain', 'liscain_init_username'), [b'\r\n[Pp]assword: '])
            self._write(tc, config.get('liscain', 'liscain_init_password'))
            self._logger.debug('[configure] logged in, begin configure')
            self._write(tc, 'terminal length 0')
            self._write(tc, 'tclsh')
            tclsh_exp = [b'\\+>']
            self._write(tc, 'puts [open "flash:liscain.config.in" w+] {', tclsh_exp, newline='\r')
            for config_line in switch_config.split('\n'):
                config_line = config_line.strip()
                self._write(tc, config_line, tclsh_exp, newline='\r')
            self._write(tc, '}')
            self._write(tc, 'exit')
            self._write(tc, 'write')
            self._write(tc, 'copy flash:liscain.config.in startup-config', [b'\r\n'])
            self._write(tc, 'startup-config')
            try:
                prompt = self._write(tc, 'reload', [b'yes/no', b'confirm'])
                if 'yes/no' in prompt:
                    time.sleep(1)
                    self._write(tc, 'no', [b'confirm'])
                time.sleep(1)
                self._write(tc, '')
            except socket.timeout:
                pass
            self._logger.debug('[configure] completed')
            return True
        except socket.timeout:
            self._logger.error('[configure] timed out')
            return False
        except EOFError:
            return True

    def change_identity(self, identity):
        old_identity = self.identifier
        try:
            tc = telnetlib.Telnet(self.address, timeout=10)
            self._write(tc, None, [b'\r\n[Uu]sername: '])
            self._write(tc, config.get('liscain', 'liscain_init_username'), [b'\r\n[Pp]assword: '])
            self._write(tc, config.get('liscain', 'liscain_init_password'))
            self._logger.debug('[change_identity] logged in')
            self._write(tc, 'terminal length 0')
            self._write(tc, 'configure terminal')
            self.identifier = identity
            self._write(tc, 'hostname {}'.format(identity))
            self._write(tc, 'end')
            self._write(tc, 'exit')
            self._logger.debug('[change_identity] logged out')
            return super().change_identity(identity)
        except socket.timeout:
            self.identifier = old_identity
            return False
        except EOFError:
            self.identifier = old_identity
            return False

    def _write(self, telnet_client, data, expect=None, timeout=None, newline='\n'):
        if data is not None:
            telnet_client.write('{}{}'.format(data, newline).encode('ascii'))
        if expect is not None:
            _, match, data = telnet_client.expect(expect, timeout=timeout)
            return data.decode('ascii')
        else:
            _, match, data = telnet_client.expect(
                ['\r\n{}(\\([a-zA-Z0-9-.,]+\\))?#'.format(self.identifier).encode('ascii')],
                timeout=timeout
            )
            return data.decode('ascii')

    def _read_mac(self, telnet_client):
        data = re.search(r'EtherSVI, address is ([0-9a-f.]+)', self._write(telnet_client, 'show interface vlan1'))
        if data is not None:
            mac = data.group(1)
            mac = mac.replace('.', '')
            mac_list = []
            for mac_byte in range(0, 6):
                mac_list.append('{}{}'.format(mac[mac_byte * 2], mac[mac_byte * 2 + 1]))
            self.mac_address = ':'.join(mac_list).lower()
            self._logger.info('mac address detected as %s', self.mac_address)
        pass

    def _read_pid(self, telnet_client):
        data = re.search(r'PID: ([^\s]+)', self._write(telnet_client, 'show inventory'))
        if data is not None:
            self.device_type = data.group(1)
            self._logger.info('type detected as %s', self.device_type)
            self.save()

    def _read_version(self, telnet_client):
        data = re.search(r'Cisco IOS.+Version ([^\s]+), ', self._write(telnet_client, 'show version'))
        if data is not None:
            self.version = data.group(1)
            self._logger.info('version detected as %s', self.version)
            self.save()

    def emit_base_config(self):
        with open('baseconfig/cisco.cfg') as fp:
            conf = fp.read().format(
                liscain_hostname=self.identifier,
                liscain_adopt_dn=config.get('liscain', 'liscain_adopt_dn'),
                liscain_init_username=config.get('liscain', 'liscain_init_username'),
                liscain_init_password=config.get('liscain', 'liscain_init_password'),
            )
            return StringIO(conf)
