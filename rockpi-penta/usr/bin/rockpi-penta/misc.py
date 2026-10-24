#!/usr/bin/env python3
import re
import os
import time
import subprocess
import multiprocessing as mp
import traceback
import json
import shlex
import shutil

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
        # Persistent OLED warnings; each check can be toggled independently.
        conf['warnings']['enabled'] = cfg.getboolean('Warnings', 'enabled', fallback=True)
        conf['warnings']['smart_health'] = cfg.getboolean('Warnings', 'smart_health', fallback=True)
        conf['warnings']['disk_temperature'] = cfg.getboolean('Warnings', 'disk_temperature', fallback=True)
        conf['warnings']['disk_temp_limit'] = cfg.getfloat('Warnings', 'disk_temp_limit', fallback=55.0)
        conf['warnings']['cpu_temperature'] = cfg.getboolean('Warnings', 'cpu_temperature', fallback=False)
        conf['warnings']['cpu_temp_limit'] = cfg.getfloat('Warnings', 'cpu_temp_limit', fallback=85.0)
        conf['warnings']['mount_missing'] = cfg.getboolean('Warnings', 'mount_missing', fallback=True)
        conf['warnings']['disk_usage'] = cfg.getboolean('Warnings', 'disk_usage', fallback=True)
        conf['warnings']['disk_usage_limit'] = cfg.getfloat('Warnings', 'disk_usage_limit', fallback=90.0)
        conf['warnings']['raid_degraded'] = cfg.getboolean('Warnings', 'raid_degraded', fallback=True)
        conf['warnings']['network_interfaces'] = _split_list(
            cfg.get('Warnings', 'network_interfaces', fallback=''))
        conf['warnings']['network_link'] = cfg.getboolean('Warnings', 'network_link', fallback=False)
        conf['warnings']['network_low_speed'] = cfg.getboolean('Warnings', 'network_low_speed', fallback=False)
        conf['warnings']['network_min_speed_mbps'] = cfg.getint('Warnings', 'network_min_speed_mbps', fallback=100)
        conf['warnings']['network_latency'] = cfg.getboolean('Warnings', 'network_latency', fallback=False)
        conf['warnings']['network_target'] = cfg.get('Warnings', 'network_target', fallback='1.1.1.1').strip()
        conf['warnings']['network_latency_limit_ms'] = cfg.getfloat(
            'Warnings', 'network_latency_limit_ms', fallback=100.0)
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
        conf['warnings']['enabled'] = True
        conf['warnings']['smart_health'] = True
        conf['warnings']['disk_temperature'] = True
        conf['warnings']['disk_temp_limit'] = 55.0
        conf['warnings']['cpu_temperature'] = False
        conf['warnings']['cpu_temp_limit'] = 85.0
        conf['warnings']['mount_missing'] = True
        conf['warnings']['disk_usage'] = True
        conf['warnings']['disk_usage_limit'] = 90.0
        conf['warnings']['raid_degraded'] = True
        conf['warnings']['network_interfaces'] = []
        conf['warnings']['network_link'] = False
        conf['warnings']['network_low_speed'] = False
        conf['warnings']['network_min_speed_mbps'] = 100
        conf['warnings']['network_latency'] = False
        conf['warnings']['network_target'] = '1.1.1.1'
        conf['warnings']['network_latency_limit_ms'] = 100.0

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
    temperatures = []
    for device, data in get_disk_smart_data():
        temp = data.get('temperature', {}).get('current')
        if temp is None:
            for attr in data.get('ata_smart_attributes', {}).get('table', []):
                if attr.get('name') in ('Temperature_Celsius', 'Airflow_Temperature_Cel'):
                    temp = attr.get('raw', {}).get('value')
                    break
        if temp is not None:
            try:
                temperatures.append((device, float(temp)))
            except (TypeError, ValueError):
                continue
    return temperatures


def get_disk_smart_data():
    """Return cached SMART JSON for detected disks when smartctl is available."""
    if time.time() - _smart_cache.get('time', 0) < 30:
        return _smart_cache.get('disks', [])
    try:
        devices = check_output("lsblk -dnpo NAME,TYPE | awk '$2==\"disk\"{print $1}'").splitlines()
    except subprocess.CalledProcessError:
        return []
    disks = []
    for device in devices:
        try:
            result = subprocess.run(['smartctl', '-a', '-j', device], check=False,
                                    capture_output=True, text=True, timeout=5)
            data = json.loads(result.stdout)
            disks.append((os.path.basename(device), data))
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            continue
    _smart_cache['time'] = time.time()
    _smart_cache['disks'] = disks
    return disks


def get_warnings():
    """Return active configured warnings for the OLED warning page."""
    options = conf['warnings']
    if not options.get('enabled', True):
        return []

    warnings = []
    if options.get('smart_health', True):
        for device, data in get_disk_smart_data():
            health = data.get('smart_status', {}).get('passed')
            if health is False:
                warnings.append(f'{device} SMART FAIL')
            concerning_attributes = {
                'Reallocated_Sector_Ct': 'reallocated sectors',
                'Current_Pending_Sector': 'pending sectors',
                'Offline_Uncorrectable': 'uncorrectable sectors',
            }
            for attribute in data.get('ata_smart_attributes', {}).get('table', []):
                label = concerning_attributes.get(attribute.get('name'))
                raw_value = attribute.get('raw', {}).get('value', 0)
                try:
                    if label and int(raw_value) > 0:
                        warnings.append(f'{device} {label}')
                except (TypeError, ValueError):
                    continue
            nvme = data.get('nvme_smart_health_information_log', {})
            critical_warning = nvme.get('critical_warning', 0)
            try:
                if int(critical_warning) != 0:
                    warnings.append(f'{device} NVMe ALERT')
            except (TypeError, ValueError):
                pass
            try:
                if int(nvme.get('media_errors', 0)) > 0:
                    warnings.append(f'{device} media errors')
            except (TypeError, ValueError):
                pass

    if options.get('disk_temperature', True):
        limit = options.get('disk_temp_limit', 55.0)
        for device, temp in get_disk_temperatures(force=True):
            if temp >= limit:
                warnings.append(f'{device} temp {temp:.0f}C >{limit:.0f}C')

    if options.get('cpu_temperature', False):
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as thermal:
                temp = float(thermal.read().strip()) / 1000.0
            limit = options.get('cpu_temp_limit', 85.0)
            if temp >= limit:
                warnings.append(f'CPU temp {temp:.0f}C >{limit:.0f}C')
        except (OSError, ValueError):
            pass

    mountpoints = conf['disk']['space_usage_mnt_points']
    if options.get('mount_missing', True):
        for mountpoint in mountpoints:
            if not os.path.ismount(mountpoint):
                warnings.append(f'Mount missing: {os.path.basename(mountpoint.rstrip("/")) or "/"}')

    if options.get('disk_usage', True):
        limit = options.get('disk_usage_limit', 90.0)
        for mountpoint in mountpoints:
            if not os.path.ismount(mountpoint):
                continue
            try:
                usage = shutil.disk_usage(mountpoint)
                percent = usage.used * 100.0 / usage.total if usage.total else 0.0
                if percent >= limit:
                    label = os.path.basename(mountpoint.rstrip('/')) or '/'
                    warnings.append(f'{label} full {percent:.0f}% >{limit:.0f}%')
            except OSError:
                continue

    if options.get('raid_degraded', True):
        warnings.extend(_get_raid_warnings())

    monitored_interfaces = options.get('network_interfaces', [])
    if monitored_interfaces:
        if options.get('network_link', False) or options.get('network_low_speed', False):
            for interface in monitored_interfaces:
                interface_path = os.path.join('/sys/class/net', interface)
                try:
                    with open(os.path.join(interface_path, 'operstate')) as state_file:
                        state = state_file.read().strip()
                except OSError:
                    warnings.append(f'{interface} unavailable')
                    continue
                if state != 'up':
                    if options.get('network_link', False) and state == 'down':
                        warnings.append(f'{interface} link down')
                    continue
                if options.get('network_low_speed', False):
                    try:
                        with open(os.path.join(interface_path, 'speed')) as speed_file:
                            speed = int(speed_file.read().strip())
                        minimum = options.get('network_min_speed_mbps', 100)
                        if speed > 0 and speed < minimum:
                            warnings.append(f'{interface} link {speed}Mbps <{minimum}')
                    except (OSError, ValueError):
                        pass

    if options.get('network_latency', False):
        target = options.get('network_target', '')
        if target:
            latency, reachable = _get_network_latency(target)
            limit = options.get('network_latency_limit_ms', 100.0)
            if reachable is False:
                warnings.append(f'Ping {target} unreachable')
            elif latency is not None and latency >= limit:
                warnings.append(f'Latency {latency:.0f}ms >{limit:.0f}ms')

    return warnings


def _get_raid_warnings():
    try:
        with open('/proc/mdstat') as mdstat:
            lines = mdstat.readlines()
    except OSError:
        return []

    warnings = []
    for index, line in enumerate(lines):
        match = re.match(r'^(md\d+)\s*:\s*(.*)', line)
        if not match:
            continue
        array_name, status = match.groups()
        block = [status]
        for following in lines[index + 1:index + 4]:
            if re.match(r'^md\d+\s*:', following):
                break
            block.append(following)
        array_status = ' '.join(block)
        if 'inactive' in status:
            warnings.append(f'{array_name} RAID inactive')
            continue
        counts = re.search(r'\[(\d+)/(\d+)\]\s+\[([U_]+)\]', array_status)
        if counts and (counts.group(1) != counts.group(2) or '_' in counts.group(3)):
            warnings.append(f'{array_name} RAID degraded')
    return warnings


def _get_network_latency(target):
    now = time.time()
    cached = _latency_cache.get(target)
    if cached and now - cached['time'] < 10:
        return cached['latency'], cached['reachable']
    try:
        result = subprocess.run(['ping', '-n', '-c', '1', '-W', '1', target],
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, None
    match = re.search(r'time[=<]\s*([\d.]+)\s*ms', result.stdout)
    if match:
        latency, reachable = float(match.group(1)), True
    elif result.returncode != 0:
        latency, reachable = None, False
    else:
        latency, reachable = None, None
    _latency_cache[target] = {'time': now, 'latency': latency, 'reachable': reachable}
    return latency, reachable


_io_cache = {}
_smart_cache = {}
_latency_cache = {}


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
