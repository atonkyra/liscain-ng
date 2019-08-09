from lib.switchstate import SwitchState
from lib.config import config
import telnetlib
import re
import socket
import time
from io import StringIO
import devices.device


class CiscoSwitch(devices.device.Device):
    def __init__(self):
        super().__init__()
        self.device_class = 'CiscoIOS'

    def pull_init_info(self):
        retry_max = 10
        for retry in range(1, retry_max+1):
            try:
                tc = telnetlib.Telnet(self.address, timeout=3)
                self._write(tc, None, [b'\r\n[Uu]sername: '])
                self._write(tc, config.get('liscain', 'liscain_init_username'), [b'\r\n[Pp]assword: '])
                self._write(tc, config.get('liscain', 'liscain_init_password'))
                self._logger.info('logged in')
                self._write(tc, 'terminal length 0')
                self._read_mac(tc)
                self._read_pid(tc)
                self._logger.info('generating ssh keys...')
                self._write(tc, 'configure terminal')
                self._write(tc, 'ip ssh rsa keypair-name ssh')
                self._write(tc, 'crypto key generate rsa mod 2048 label ssh', timeout=120)
                self._write(tc, 'sdm prefer dual-ipv4-and-ipv6 default', timeout=10)
                self._write(tc, 'sdm prefer dual-ipv4-and-ipv6 vlan', timeout=10)
                self._write(tc, 'end')
                self._write(tc, 'exit')
                self._logger.info('logged out')
                self.change_state(SwitchState.READY)
                self._logger.info('successfully initialized switch, state now %s', self.state)
                return
            except socket.timeout:
                self._logger.info('timeout, retry %i/%i', retry, retry_max)
                continue
            except EOFError:
                self._logger.info('switch not ready, wait 10s (retry %i/%i)', retry, retry_max)
                time.sleep(10)
        self.change_state(SwitchState.INIT_TIMEOUT)
        self._logger.error('failed to fetch information from switch')

    def configure(self, switch_config):
        try:
            tc = telnetlib.Telnet(self.address, timeout=3)
            self._write(tc, None, [b'\r\n[Uu]sername: '])
            self._write(tc, config.get('liscain', 'liscain_init_username'), [b'\r\n[Pp]assword: '])
            self._write(tc, config.get('liscain', 'liscain_init_password'))
            self._logger.info('[configure] logged in, begin configure')
            self._write(tc, 'terminal length 0')
            self._write(tc, 'tclsh')
            tclsh_exp = [b'\\+>']
            self._write(tc, 'puts [open "flash:liscain.config.in" w+] {', tclsh_exp, newline='\r')
            for config_line in switch_config.split('\n'):
                config_line = config_line.strip()
                self._write(tc, config_line, tclsh_exp, newline='\r')
            self._write(tc, '}')
            self._write(tc, 'exit')
            self._write(tc, 'copy flash:liscain.config.in startup-config', [b'\r\n'])
            self._write(tc, 'startup-config')
            try:
                prompt = self._write(tc, 'reload', [b'\r\n'])
                if 'yes/no' in prompt:
                    self._write(tc, 'no', [b'\r\n'])
                self._write(tc, 'confirm')
            except socket.timeout:
                pass
            self._logger.info('[configure] completed')
            self.change_state(SwitchState.CONFIGURED)
        except socket.timeout:
            self._logger.info('[configure] timed out')
        except EOFError:
            pass

    def change_identity(self, identity):
        old_identity = self.identifier
        try:
            tc = telnetlib.Telnet(self.address, timeout=3)
            self._write(tc, None, [b'\r\n[Uu]sername: '])
            self._write(tc, config.get('liscain', 'liscain_init_username'), [b'\r\n[Pp]assword: '])
            self._write(tc, config.get('liscain', 'liscain_init_password'))
            self._logger.info('[change_identity] logged in')
            self._write(tc, 'terminal length 0')
            self._write(tc, 'configure terminal')
            self.identifier = identity
            self._write(tc, 'hostname {}'.format(identity))
            self._write(tc, 'end')
            self._write(tc, 'exit')
            self._logger.info('[change_identity] logged out')
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
        # Hardware is EtherSVI, address is 04fe.7f07.9040 (bia 04fe.7f07.9040)
        data = re.search(r'EtherSVI, address is ([0-9a-f.]+)', self._write(telnet_client, 'show interface vlan1'))
        if data is not None:
            mac = data.group(1)
            mac = mac.replace('.', '')
            mac_list = []
            for mac_byte in range(0, 6):
                mac_list.append('{}{}'.format(mac[mac_byte * 2], mac[mac_byte * 2 + 1]))
            self.mac_address = ':'.join(mac_list)
            self._logger.info('mac address detected as %s', self.mac_address)
        pass

    def _read_pid(self, telnet_client):
        data = re.search(r'PID: ([a-zA-Z0-9-]+)', self._write(telnet_client, 'show inventory'))
        if data is not None:
            self.device_type = data.group(1)
            self._logger.info('type detected as %s', self.device_type)
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
