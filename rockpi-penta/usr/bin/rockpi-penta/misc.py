#!/usr/bin/env python3
import re
import os
import time
import subprocess
import multiprocessing as mp
import traceback
import json
import shlex

import gpiod
from configparser import ConfigParser
from collections import defaultdict, OrderedDict

cmds = {
    'blk': "lsblk | awk '{print $1}'",
    'up': "echo Uptime: `uptime | sed 's/.*up \\([^,]*\\), .*/\\1/'`",
    'temp': "cat /sys/class/thermal/thermal_zone0/temp",
    'ip': "hostname -I | awk '{printf \"IP %s\", $1}'",
    'cpu': "uptime | awk '{printf \"CPU Load: %.2f\", $(NF-2)}'",
    'men': "free -m | awk 'NR==2{printf \"Mem: %s/%sMB\", $3,$2}'",
    'disk': "df -h | awk '$NF==\"/\"{printf \"Disk: %d/%dGB %s\", $3,$2,$5}'"
}

lv2dc = OrderedDict({'lv3': 1.0, 'lv2': 0.75, 'lv1': 0.50, 'lv0': 0.25})


def check_output(cmd):
    return subprocess.check_output(cmd, shell=True).decode().strip()


def check_call(cmd):
    return subprocess.check_call(cmd, shell=True)


def get_blk():
    conf['disk_devices'] = [x for x in check_output(cmds['blk']).strip().split('\n') if x.startswith('sd')]


def get_info(s):
    return check_output(cmds[s])


def get_cpu_temp():
    t = float(get_info('temp')) / 1000
    if conf['oled']['f-temp']:
        temp = "CPU Temp: {:.0f}°F".format(t * 1.8 + 32)
    else:
        temp = "CPU Temp: {:.1f}°C".format(t)
    return temp


def read_conf():
    conf = defaultdict(dict)

    try:
        cfg = ConfigParser()
        cfg.read('/etc/rockpi-penta.conf')
        # fan
        conf['fan']['lv0'] = cfg.getfloat('fan', 'lv0')
        conf['fan']['lv1'] = cfg.getfloat('fan', 'lv1')
        conf['fan']['lv2'] = cfg.getfloat('fan', 'lv2')
        conf['fan']['lv3'] = cfg.getfloat('fan', 'lv3')
        conf['fan']['linear'] = cfg.getboolean('fan', 'linear', fallback=False)
        # key
        conf['key']['click'] = cfg.get('key', 'click')
        conf['key']['twice'] = cfg.get('key', 'twice')
        conf['key']['press'] = cfg.get('key', 'press')
        # time
        conf['time']['twice'] = cfg.getfloat('time', 'twice')
        conf['time']['press'] = cfg.getfloat('time', 'press')
        # other
        conf['slider']['auto'] = cfg.getboolean('slider', 'auto')
        conf['slider']['time'] = cfg.getfloat('slider', 'time')
        conf['slider']['refresh'] = cfg.getfloat('slider', 'refresh', fallback=1.0)
        conf['oled']['rotate'] = cfg.getboolean('oled', 'rotate')
        conf['oled']['f-temp'] = cfg.getboolean('oled', 'f-temp')
        conf['oled']['brightness'] = min(255, max(0, cfg.getint('oled', 'brightness', fallback=255)))
        # Optional OLED sources. Empty lists disable the corresponding pages.
        conf['disk']['space_usage_mnt_points'] = _split_list(
            cfg.get('disk', 'space_usage_mnt_points', fallback='/'))
        conf['disk']['io_usage_mnt_points'] = _split_list(
            cfg.get('disk', 'io_usage_mnt_points', fallback=''))
        conf['disk']['disks_temp'] = cfg.getboolean('disk', 'disks_temp', fallback=True)
        conf['network']['interfaces'] = _split_list(
            cfg.get('network', 'interfaces', fallback='auto'))
    except Exception:
        traceback.print_exc()
        # fan
        conf['fan']['lv0'] = 35
        conf['fan']['lv1'] = 40
        conf['fan']['lv2'] = 45
        conf['fan']['lv3'] = 50
        conf['fan']['linear'] = False
        # key
        conf['key']['click'] = 'slider'
        conf['key']['twice'] = 'switch'
        conf['key']['press'] = 'none'
        # time
        conf['time']['twice'] = 0.7  # second
        conf['time']['press'] = 1.8
        # other
        conf['slider']['auto'] = True
        conf['slider']['time'] = 10  # second
        conf['slider']['refresh'] = 1.0
        conf['oled']['rotate'] = False
        conf['oled']['f-temp'] = False
        conf['oled']['brightness'] = 255
        conf['disk']['space_usage_mnt_points'] = ['/']
        conf['disk']['io_usage_mnt_points'] = []
        conf['disk']['disks_temp'] = True
        conf['network']['interfaces'] = ['auto']

    return conf


def _split_list(value):
    return [item.strip() for item in value.split('|') if item.strip()]


def read_key(pattern, size):
    line_number = int(os.environ['BUTTON_LINE'])
    chip_path = f"/dev/gpiochip{os.environ['BUTTON_CHIP']}"
    s = ''
    with gpiod.request_lines(
        chip_path,
        consumer='hat_button',
        config={line_number: gpiod.LineSettings(
            direction=gpiod.line.Direction.INPUT
        )},
    ) as request:
        while True:
            s = s[-size:] + str(request.get_value(line_number).value)
            for t, p in pattern.items():
                if p.match(s):
                    return t
            time.sleep(0.1)


def watch_key(q=None):
    size = int(conf['time']['press'] * 10)
    wait = int(conf['time']['twice'] * 10)
    pattern = {
        'click': re.compile(r'1+0+1{%d,}' % wait),
        'twice': re.compile(r'1+0+1+0+1{3,}'),
        'press': re.compile(r'1+0{%d,}' % size),
    }

    while True:
        q.put(read_key(pattern, size))


def get_disk_info(cache={}):
    if not cache.get('time') or time.time() - cache['time'] > 30:
        info = []
        for mountpoint in conf['disk']['space_usage_mnt_points']:
            try:
                result = subprocess.run(['df', '-hP', mountpoint], check=True,
                                        capture_output=True, text=True, timeout=5)
                fields = result.stdout.splitlines()[-1].split()
                label = os.path.basename(fields[-1].rstrip('/')) or '/'
                info.append((label[:7], fields[4]))
            except (OSError, subprocess.SubprocessError, IndexError):
                continue
        cache['info'] = ([item[0] for item in info], [item[1] for item in info])
        cache['time'] = time.time()

    return cache['info']


def _mount_source(mountpoint):
    try:
        return check_output("findmnt -nro SOURCE --target " + shlex.quote(mountpoint)).splitlines()[0]
    except (subprocess.CalledProcessError, IndexError):
        return ''


def _disk_counters():
    counters = {}
    try:
        with open('/proc/diskstats') as stats:
            for line in stats:
                fields = line.split()
                if len(fields) >= 14:
                    counters[fields[2]] = (int(fields[5]), int(fields[9]))
    except OSError:
        pass
    return counters


def _network_counters():
    counters = {}
    try:
        with open('/proc/net/dev') as stats:
            for line in stats:
                if ':' not in line:
                    continue
                interface, values = line.split(':', 1)
                values = values.split()
                if len(values) >= 9:
                    counters[interface.strip()] = (int(values[0]), int(values[8]))
    except OSError:
        pass
    return counters


def get_interface_list():
    configured = conf['network']['interfaces']
    available = sorted(_network_counters())
    if configured == ['auto']:
        return [name for name in available if name != 'lo']
    return [name for name in configured if name in available]


def get_io_rates():
    """Return current per-mount and per-interface rates in MiB/s."""
    now = time.time()
    snapshot = {'time': now, 'disks': {}, 'network': {}}
    disk_counts = _disk_counters()
    for mountpoint in conf['disk']['io_usage_mnt_points']:
        source = _mount_source(mountpoint)
        device = os.path.basename(source)
        if device in disk_counts:
            snapshot['disks'][mountpoint] = (device, disk_counts[device])
    network_counts = _network_counters()
    for interface in get_interface_list():
        if interface in network_counts:
            snapshot['network'][interface] = network_counts[interface]

    previous = _io_cache.get('snapshot')
    rates = {'disks': {}, 'network': {}}
    if previous:
        elapsed = max(now - previous['time'], 0.001)
        for mountpoint, (device, values) in snapshot['disks'].items():
            old = previous['disks'].get(mountpoint)
            if old and old[0] == device:
                rates['disks'][mountpoint] = tuple(
                    max(0, value - old[1][i]) * 512 / elapsed / 1048576 for i, value in enumerate(values))
        for interface, values in snapshot['network'].items():
            old = previous['network'].get(interface)
            if old:
                rates['network'][interface] = tuple(
                    max(0, value - old[i]) / elapsed / 1048576 for i, value in enumerate(values))
    _io_cache['snapshot'] = snapshot
    return rates


def get_disk_temperatures(force=False):
    """Read temperatures from detected block devices when smartctl is available."""
    if not conf['disk']['disks_temp'] and not force:
        return []
    if time.time() - _temp_cache.get('time', 0) < 30:
        return _temp_cache.get('temperatures', [])
    try:
        devices = check_output("lsblk -dnpo NAME,TYPE | awk '$2==\"disk\"{print $1}'").splitlines()
    except subprocess.CalledProcessError:
        return []
    temperatures = []
    for device in devices:
        try:
            result = subprocess.run(['smartctl', '-A', '-j', device], check=False,
                                    capture_output=True, text=True, timeout=5)
            data = json.loads(result.stdout)
            temp = data.get('temperature', {}).get('current')
            if temp is None:
                for attr in data.get('ata_smart_attributes', {}).get('table', []):
                    if attr.get('name') in ('Temperature_Celsius', 'Airflow_Temperature_Cel'):
                        temp = attr.get('raw', {}).get('value')
                        break
            if temp is not None:
                temperatures.append((os.path.basename(device), float(temp)))
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            continue
    _temp_cache['time'] = time.time()
    _temp_cache['temperatures'] = temperatures
    return temperatures


_io_cache = {}
_temp_cache = {}


def slider_next(pages):
    conf['idx'].value += 1
    return pages[conf['idx'].value % len(pages)]


def slider_sleep():
    time.sleep(conf['slider']['time'])


def get_refresh_period():
    return max(0.0, conf['slider'].get('refresh', 1.0))


def fan_temp2dc(t):
    # lv0 is the turn-on threshold in both modes.
    if t < conf['fan']['lv0']:
        return 0.0

    if conf['fan']['linear']:
        # Ramp smoothly from 25% at lv0 to 100% at lv3.
        low_temp = conf['fan']['lv0']
        high_temp = conf['fan']['lv3']
        if high_temp <= low_temp:
            return 1.0
        return min(1.0, 0.25 + 0.75 * (t - low_temp) / (high_temp - low_temp))

    # Stepped mode: 25%, 50%, 75%, then 100% at each configured threshold.
    for lv, dc in lv2dc.items():
        if t >= conf['fan'][lv]:
            return dc
    return 0.0


def fan_switch():
    conf['run'].value = not conf['run'].value


def get_func(key):
    return conf['key'].get(key, 'none')


conf = {'disk': [], 'idx': mp.Value('d', -1), 'run': mp.Value('d', 1)}
conf.update(read_conf())
