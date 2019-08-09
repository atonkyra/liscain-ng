import zmq
import beautifultable
import argparse
import sys
import time

parser = argparse.ArgumentParser(description='liscain-cli')
parser.add_argument('-a', '--adopt-by-id', required=False, help='adopt a switch by id', type=int, default=None)
parser.add_argument('-i', '--identity', required=False, help='identity of switch', default=None)
parser.add_argument('-l', '--list', required=False, help='list switches', default=False, action='store_true')
parser.add_argument('--adopt-nowait', required=False, help='dont wait for adoption result', default=False, action='store_true')
args = parser.parse_args()


def show_devices(device_listing):
    table = beautifultable.BeautifulTable()
    table.default_alignment = beautifultable.ALIGN_LEFT
    table.max_table_width = 128
    table.column_headers = ['id', 'identifier', 'device_class', 'device_type', 'address', 'mac_address', 'state']
    for device in device_listing:
        row = []
        for col in table.column_headers:
            row.append(device[col])
        table.append_row(row)
    print(table)


def list_devices(zmq_sock):
    zmq_sock.send_json({'cmd': 'list'})
    device_list = zmq_sock.recv_json()
    show_devices(device_list)


def adopt_device(zmq_sock, device_id, identity, config_filename):
    with open(config_filename) as fp:
        config = fp.read()
        zmq_sock.send_json({'cmd': 'adopt', 'id': device_id, 'identity': identity, 'config': config})
        result = zmq_sock.recv_json()
        if args.adopt_nowait:
            show_devices([result])
        else:
            sys.stdout.write('adopting')
            while True:
                sys.stdout.write('.')
                sys.stdout.flush()
                zmq_sock.send_json({'cmd': 'status', 'id': device_id})
                result = zmq_sock.recv_json()
                if result['state'] != 'CONFIGURING':
                    break
                time.sleep(1)
            print()
            show_devices([result])


def main():
    zmq_context = zmq.Context()
    zmq_sock = zmq_context.socket(zmq.REQ)
    zmq_sock.connect('tcp://127.0.0.1:1337')
    if args.list:
        list_devices(zmq_sock)
    if args.adopt_by_id is not None:
        if args.identity is None:
            print('identity is required when adopting')
            return
        adopt_device(zmq_sock, 1, args.identity, 'config/{}.cfg'.format(args.identity))


if __name__ == '__main__':
    main()
