import zmq
import beautifultable
import argparse
import sys
import time
from lib.config import config


init_parser = argparse.ArgumentParser(description='liscain-cli', add_help=False)
init_parser.add_argument('mode', choices=['device', 'opt82'])
init_args, inner_args = init_parser.parse_known_args()

parser = argparse.ArgumentParser(description='liscain-cli')
if init_args.mode == 'device':
    parser.add_argument('-n', '--neighbor-info-by-id', required=False, help='show switch neighbor info by id', type=int, default=None)
    parser.add_argument('-a', '--adopt-by-id', required=False, help='adopt a switch by id', type=int, default=None)
    parser.add_argument('-m', '--adopt-by-mac', required=False, help='adopt a switch by (partial) mac', default=None)
    parser.add_argument('-i', '--identity', required=False, help='identity of switch', default=None)
    parser.add_argument('-l', '--list', required=False, help='list switches', default=False, action='store_true')
    parser.add_argument('-d', '--delete-by-id', required=False, help='delete switch by id', default=None, type=int)
    parser.add_argument('-f', '--filter-list', required=False, help='filter list to states (can be repeated)', default=None, action='append')
    parser.add_argument('--adopt-nowait', required=False, help='dont wait for adoption result', default=False, action='store_true')
elif init_args.mode == 'opt82':
    parser.add_argument('-l', '--list', required=False, help='list option82 info', default=False, action='store_true')
    parser.add_argument('-d', '--delete-by-id', required=False, help='delete option 82 info by id', default=None, type=int)
    parser.add_argument('-s', '--set', required=False, help='set option 82 info', default=False, action='store_true')
    parser.add_argument('-m', '--upstream-mac', required=False, help='upstream mac, 0a:0b:1c:3d:e0:ff format')
    parser.add_argument('-p', '--upstream-port', required=False, help='upstream port, free format')
    parser.add_argument('-n', '--downstream-name', required=False, help='downstream switch name')
    pass
args = parser.parse_args(inner_args)


def show_devices(device_listing):
    table = beautifultable.BeautifulTable()
    table.default_alignment = beautifultable.ALIGN_LEFT
    table.max_table_width = 128
    table.column_headers = ['id', 'identifier', 'device_class', 'device_type', 'address', 'mac_address', 'state']
    for device in device_listing:
        row = []
        for col in table.column_headers:
            row.append(device[col])
        if args.filter_list is not None:
            if device['state'] not in args.filter_list:
                continue
        table.append_row(row)
    print(table)


def list_devices(zmq_sock):
    zmq_sock.send_json({'cmd': 'list'})
    device_list = zmq_sock.recv_json()
    show_devices(device_list)


def get_devices(zmq_sock):
    zmq_sock.send_json({'cmd': 'list'})
    device_list = zmq_sock.recv_json()
    return device_list


def get_neigh_info(zmq_sock, device_id):
    zmq_sock.send_json({'cmd': 'neighbor-info', 'id': device_id})
    result = zmq_sock.recv_json()
    if 'error' in result:
        print(result['error'])
    else:
        print(result['info'])


def adopt_device(zmq_sock, device_id, identity, config_filename):
    with open(config_filename) as fp:
        switch_config = fp.read()
        zmq_sock.send_json({'cmd': 'adopt', 'id': device_id, 'identity': identity, 'config': switch_config})
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


def delete_device(zmq_sock, device_id):
    zmq_sock.send_json({'cmd': 'delete', 'id': device_id})
    result = zmq_sock.recv_json()
    if 'error' in result:
        print(result['error'])
    else:
        print(result['info'])


def show_opt82_infos(results):
    table = beautifultable.BeautifulTable()
    table.default_alignment = beautifultable.ALIGN_LEFT
    table.max_table_width = 128
    table.column_headers = [
        'id', 'upstream_switch_mac', 'upstream_port_info', 'downstream_switch_mac', 'downstream_switch_name'
    ]
    for result in results:
        if 'downstream_switch_mac' not in result:
            result['downstream_switch_mac'] = None
        row = []
        for col in table.column_headers:
            row.append(result[col])
        table.append_row(row)
    print(table)


def opt82_set_info(zmq_sock, upstream_mac, upstream_port, downstream_name):
    zmq_sock.send_json(
        {
            'cmd': 'opt82-info',
            'upstream_switch_mac': upstream_mac,
            'upstream_port_info': upstream_port,
            'downstream_switch_name': downstream_name
        }
    )
    result = zmq_sock.recv_json()
    if 'error' in result:
        print(result['error'])
        return
    show_opt82_infos([result])


def opt82_list(zmq_sock):
    zmq_sock.send_json(
        {
            'cmd': 'opt82-list'
        }
    )
    show_opt82_infos(zmq_sock.recv_json())


def opt82_delete_by_id(zmq_sock, opt82_id):
    zmq_sock.send_json(
        {
            'cmd': 'opt82-delete',
            'id': opt82_id
        }
    )
    result = zmq_sock.recv_json()
    if 'error' in result:
        print(result['error'])
    else:
        print(result['info'])


def main():
    zmq_context = zmq.Context()
    zmq_sock = zmq_context.socket(zmq.REQ)
    zmq_sock.connect(config.get('liscain', 'command_socket'))
    if init_args.mode == 'device':
        if args.list:
            list_devices(zmq_sock)
        if args.neighbor_info_by_id is not None:
            get_neigh_info(zmq_sock, args.neighbor_info_by_id)
        if args.delete_by_id is not None:
            delete_device(zmq_sock, args.delete_by_id)
        if args.adopt_by_id is not None:
            if args.identity is None:
                print('identity is required when adopting')
                return
            adopt_device(zmq_sock, args.adopt_by_id, args.identity, 'config/{}.cfg'.format(args.identity))
        if args.adopt_by_mac is not None:
            if args.identity is None:
                print('identity is required when adopting')
                return
            devices = get_devices(zmq_sock)
            mac_matches = []
            simplemac = args.adopt_by_mac.replace(':', '')
            for device in devices:
                if device['state'] not in ['READY', 'CONFIGURE_FAILED']:
                    continue
                if simplemac in device['mac_address'].replace(':', ''):
                    mac_matches.append(device['id'])
            if len(mac_matches) == 1:
                adopt_device(zmq_sock, mac_matches[0], args.identity, 'config/{}.cfg'.format(args.identity))
            elif len(mac_matches) > 1:
                print('error: multiple mac_address matches')
            else:
                print('error: no mac_address matches')

    if init_args.mode == 'opt82':
        if args.list:
            opt82_list(zmq_sock)

        if args.delete_by_id:
            opt82_delete_by_id(zmq_sock, args.delete_by_id)

        if args.set:
            if args.upstream_mac is None or args.upstream_port is None:
                print('error: upstream mac and port are required when setting option82 info')
                return
            opt82_set_info(zmq_sock, args.upstream_mac, args.upstream_port, args.downstream_name)


if __name__ == '__main__':
    main()
