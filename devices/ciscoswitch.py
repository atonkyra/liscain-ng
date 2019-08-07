from lib.switchstate import SwitchState
import logging
import telnetlib
import re
import socket
import time
from io import StringIO


class CiscoSwitch:
    def __init__(self, config, identifier, address):
        self.config = config
        self.identifier = identifier
        self.address = address
        self.state = SwitchState.INIT
        self._logger = logging.getLogger('[{}]'.format(identifier))
        self.device_type = 'UNKNOWN'
        self._logger.info('new switch')

    def pull_init_info(self):
        retry_max = 10
        for retry in range(1, retry_max+1):
            try:
                tc = telnetlib.Telnet(self.address, timeout=3)
                self._write(tc, None, [b'\r\n[Uu]sername: '])
                self._write(tc, self.config.get('liscain', 'liscain_init_username'), [b'\r\n[Pp]assword: '])
                self._write(tc, self.config.get('liscain', 'liscain_init_password'))
                self._logger.info('authenticated')
                self._read_pid(tc)
                self._logger.info('generating ssh keys...')
                self._write(tc, 'configure terminal')
                self._write(tc, 'ip ssh rsa keypair-name ssh')
                self._write(tc, 'crypto key generate rsa mod 2048 label ssh', timeout=120)
                self._write(tc, 'end')
                self._write(tc, 'exit')
                self._logger.info('logged out')
                self.state = SwitchState.READY
                self._logger.info('successfully initialized switch, state now %s', self.state)
                return
            except socket.timeout:
                self._logger.info('timeout, retry %i/%i', retry, retry_max)
                continue
            except EOFError:
                self._logger.info('switch not ready, wait 10s (retry %i/%i)', retry, retry_max)
                time.sleep(10)
        self.state = SwitchState.INIT_TIMEOUT
        self._logger.error('failed to fetch information from switch')

    def _write(self, telnet_client, data, expect=None, timeout=None):
        if data is not None:
            telnet_client.write('{}\n'.format(data).encode('ascii'))
        if expect is not None:
            _, match, data = telnet_client.expect(expect, timeout=timeout)
            return data.decode('ascii')
        else:
            _, match, data = telnet_client.expect(
                ['\r\n{}(\\([a-zA-Z0-9-.,]+\\))?#'.format(self.identifier).encode('ascii')],
                timeout=timeout
            )
            return data.decode('ascii')

    def _read_pid(self, telnet_client):
        data = re.search(r'PID: ([a-zA-Z0-9-]+)', self._write(telnet_client, 'show inventory'))
        if data is not None:
            self.device_type = data.group(1)
            self._logger.info('type detected as %s', self.device_type)

    def emit_base_config(self):
        with open('baseconfig/cisco.cfg') as fp:
            conf = fp.read().format(
                liscain_hostname=self.identifier,
                liscain_adopt_dn=self.config.get('liscain', 'liscain_adopt_dn'),
                liscain_init_username=self.config.get('liscain', 'liscain_init_username'),
                liscain_init_password=self.config.get('liscain', 'liscain_init_password'),
            )
            return StringIO(conf)
