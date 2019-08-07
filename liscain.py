import tftpy
import logging
import ipaddress
import threading
import telnetlib
import re
import socket
import time
from io import StringIO
from enum import Enum


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)-15s %(levelname)-8s %(name)-12s %(message)s'
)
logger = logging.getLogger('lis-cain')
logger.setLevel(logging.INFO)
logging.getLogger('tftpy.TftpServer').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpPacketTypes').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpStates').setLevel(logging.CRITICAL)


liscain_adopt_dn = 'liscain.local'
liscain_init_password = 'foobar'


confdb = {}


class SwitchState(Enum):
    INIT = 0
    READY = 1

    INIT_TIMEOUT = -1


class CiscoSwitch:
    def __init__(self, identifier, address):
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
                self._write(tc, 'liscain', [b'\r\n[Pp]assword: '])
                self._write(tc, liscain_init_password)
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
                liscain_hostname=self.identifier, liscain_adopt_dn=liscain_adopt_dn,
                liscain_init_password=liscain_init_password
            )
            return StringIO(conf)


def serve_file(name, **kwargs):
    remote_address = kwargs['raddress']
    remote_id = 'lc-{:02x}'.format(int(ipaddress.ip_address(remote_address)))
    if name in ['network-confg']:
        if remote_id not in confdb or confdb[remote_id].state == SwitchState.INIT_TIMEOUT:
            confdb[remote_id] = CiscoSwitch(remote_id, remote_address)
            threading.Thread(target=confdb[remote_id].pull_init_info, daemon=True).start()
        return confdb[remote_id].emit_base_config()
    else:
        logger.debug('%s requested %s, ignoring', remote_id, name)
    return StringIO()


def tftp_server():
    srv = tftpy.TftpServer(tftproot=None, dyn_file_func=serve_file)
    srv.listen()


def main():
    tftp_task = threading.Thread(target=tftp_server, daemon=True)
    tftp_task.start()
    while True:
        for switch in confdb.values():
            logger.info('switch %s (%s): state = %s', switch.identifier, switch.device_type, switch.state)
        time.sleep(10)


if __name__ == '__main__':
    main()

