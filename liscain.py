import tftpy
import logging
import ipaddress
import threading
import time
from lib.switchstate import SwitchState
from devices.ciscoswitch import CiscoSwitch
from io import StringIO
import configparser


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)-15s %(levelname)-8s %(name)-12s %(message)s'
)
logger = logging.getLogger('lis-cain')
logger.setLevel(logging.INFO)
logging.getLogger('tftpy.TftpServer').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpPacketTypes').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpStates').setLevel(logging.CRITICAL)


config = configparser.ConfigParser()
with open('config.ini') as fp:
    config.read_file(fp)


confdb = {}


def serve_file(name, **kwargs):
    remote_address = kwargs['raddress']
    remote_id = 'lc-{:02x}'.format(int(ipaddress.ip_address(remote_address)))
    if name in ['network-confg']:
        if remote_id not in confdb or confdb[remote_id].state == SwitchState.INIT_TIMEOUT:
            confdb[remote_id] = CiscoSwitch(config, remote_id, remote_address)
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

