import tftpy
import logging
import ipaddress
import threading
import time
import lib.db
import sqlalchemy.orm
from sqlalchemy import and_
from devices.ciscoswitch import CiscoSwitch
from io import StringIO
from lib.config import config
from lib.switchstate import SwitchState


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)-15s %(levelname)-8s %(name)-12s %(message)s'
)
logger = logging.getLogger('lis-cain')
logger.setLevel(logging.INFO)
logging.getLogger('tftpy.TftpServer').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpPacketTypes').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpStates').setLevel(logging.CRITICAL)


def serve_file(name, **kwargs):
    remote_address = kwargs['raddress']
    remote_id = 'lc-{:02x}'.format(int(ipaddress.ip_address(remote_address)))
    if name in ['network-confg']:
        device = None
        with lib.db.sql_ses() as ses:
            try:
                device = ses.query(CiscoSwitch).filter(
                    and_(
                        CiscoSwitch.identifier == remote_id,
                        CiscoSwitch.state != SwitchState.CONFIGURED
                    )
                ).one()
            except sqlalchemy.orm.exc.NoResultFound:
                device = CiscoSwitch()
                device.initialize(identifier=remote_id, address=remote_address)
                ses.add(device)
                ses.commit()
                ses.refresh(device)
        if device.state == SwitchState.INIT or device.state == SwitchState.INIT_TIMEOUT:
            device.change_state(SwitchState.INIT_IN_PROGRESS)
            threading.Thread(target=device.pull_init_info, daemon=True).start()
            return device.emit_base_config()
        else:
            logger.info('%s requests config, but is in state %s, ignoring request', remote_id, -device.state)
        return StringIO()
    else:
        logger.debug('%s requested %s, ignoring', remote_id, name)
    return StringIO()


def tftp_server():
    srv = tftpy.TftpServer(tftproot=None, dyn_file_func=serve_file)
    srv.listen()


def main():
    lib.db.initialize(config.get('liscain', 'database'))
    tftp_task = threading.Thread(target=tftp_server, daemon=True)
    tftp_task.start()
    while True:
        #for switch in confdb.values():
        #    logger.info('switch %s (%s): state = %s', switch.identifier, switch.device_type, switch.state)
        pass
        time.sleep(10)


if __name__ == '__main__':
    main()

