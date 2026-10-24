#!/usr/bin/python3
import os
import time
import multiprocessing as mp
import queue

import adafruit_ssd1306
import board
import digitalio
import busio
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

import misc

font = {
    '10': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 10),
    '11': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 11),
    '12': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 12),
    '14': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 14),
}

display_queue = mp.Queue()


def disp_init():
    RESET = getattr(board.pin, os.environ['OLED_RESET'])
    i2c = busio.I2C(getattr(board.pin, os.environ['SCL']), getattr(board.pin, os.environ['SDA']))
    disp = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c, reset=digitalio.DigitalInOut(RESET))
    disp.contrast(misc.conf['oled']['brightness'])
    disp.fill(0)
    disp.show()
    return disp


disp = disp_init()

image = Image.new('1', (disp.width, disp.height))
draw = ImageDraw.Draw(image)


def disp_show():
    im = image.rotate(180) if misc.conf['oled']['rotate'] else image
    disp.image(im)
    disp.write_framebuf()
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)


def show_warnings(warnings, header_visible=True, offset=0):
    """Keep an active warning page visible until all warnings clear."""
    if header_visible:
        draw.text((0, -2), '!! WARNING !!', font=font['11'], fill=255)
    if misc.conf['warnings'].get('showwarningcount', True):
        warning_count = '9+' if len(warnings) >= 10 else str(len(warnings))
        count_bbox = draw.textbbox((0, -2), warning_count, font=font['11'])
        padding = 2
        count_width = count_bbox[2] - count_bbox[0]
        badge_left = disp.width - count_width - (padding * 2)
        text_x = badge_left + padding - count_bbox[0]
        if misc.conf['warnings'].get('warningcountinverted', False):
            draw.rectangle((badge_left, -2, disp.width - 1, 9), fill=255)
            draw.text((text_x, -2), warning_count, font=font['11'], fill=0)
        else:
            draw.text((disp.width - count_width - count_bbox[0], -2),
                      warning_count, font=font['11'], fill=255)
    visible_warnings = [warnings[(offset + index) % len(warnings)]
                        for index in range(min(2, len(warnings)))]
    now = time.monotonic()
    for index, warning in enumerate(visible_warnings):
        y = 10 + index * 11
        text_width = draw.textbbox((0, y), warning, font=font['11'])[2]
        if text_width <= disp.width:
            draw.text((0, y), warning, font=font['11'], fill=255)
            continue

        # Repeat the text after a short gap to create a continuous marquee.
        cycle_width = text_width + 24
        scroll_x = int(now * 32) % cycle_width
        draw.text((-scroll_x, y), warning, font=font['11'], fill=255)
        draw.text((cycle_width - scroll_x, y), warning, font=font['11'], fill=255)
    disp_show()


def welcome():
    draw.text((0, 0), 'ROCKPi SATA HAT', font=font['14'], fill=255)
    draw.text((32, 16), 'Loading...', font=font['12'], fill=255)
    disp_show()


def goodbye():
    draw.text((32, 8), 'Good Bye ~', font=font['14'], fill=255)
    disp_show()
    time.sleep(2)
    disp_show()  # clear


def put_disk_info():
    k, v = misc.get_disk_info()
    entries = ['{} {}'.format(name, used) for name, used in zip(k, v)]
    rows = ['  '.join(entries[i:i + 2]) for i in range(0, len(entries), 2)]
    if not rows:
        rows = ['No mounted disks']
    return [
        {'xy': (0, -2), 'text': 'Disk usage', 'fill': 255, 'font': font['11']},
        {'xy': (0, 10), 'text': rows[0][:21], 'fill': 255, 'font': font['11']},
        {'xy': (0, 21), 'text': (rows[1] if len(rows) > 1 else '')[:21], 'fill': 255, 'font': font['11']},
    ]


def gen_pages():
    pages = [
        [
            {'xy': (0, -2), 'text': misc.get_info('up'), 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': misc.get_cpu_temp(), 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': misc.get_info('ip'), 'fill': 255, 'font': font['11']},
        ],
        [
            {'xy': (0, 2), 'text': misc.get_info('cpu'), 'fill': 255, 'font': font['12']},
            {'xy': (0, 18), 'text': misc.get_info('men'), 'fill': 255, 'font': font['12']},
        ],
        put_disk_info(),
    ]

    rates = misc.get_io_rates()
    for mountpoint in misc.conf['disk']['io_usage_mnt_points']:
        read, write = rates['disks'].get(mountpoint, (0.0, 0.0))
        label = os.path.basename(misc._mount_source(mountpoint)) or mountpoint
        pages.append([
            {'xy': (0, -2), 'text': 'Disk I/O: {}'.format(label)[:21], 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': 'Read:  {:8.3f} MB/s'.format(read), 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': 'Write: {:8.3f} MB/s'.format(write), 'fill': 255, 'font': font['11']},
        ])

    for interface in misc.get_interface_list():
        rx, tx = rates['network'].get(interface, (0.0, 0.0))
        pages.append([
            {'xy': (0, -2), 'text': 'Network I/O: {}'.format(interface)[:21], 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': 'Rx:    {:8.3f} MB/s'.format(rx), 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': 'Tx:    {:8.3f} MB/s'.format(tx), 'fill': 255, 'font': font['11']},
        ])

    temperatures = misc.get_disk_temperatures()
    if temperatures:
        rows = ['{} {}°C'.format(name, temp) for name, temp in temperatures]
        pages.append([
            {'xy': (0, -2), 'text': 'Disk temperatures', 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': '  '.join(rows[:2])[:21], 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': '  '.join(rows[2:4])[:21], 'fill': 255, 'font': font['11']},
        ])

    return pages


def slider(lock=None):
    """Queue a page advance; the display worker owns all OLED drawing."""
    display_queue.put('next')


def auto_slider(lock=None):
    while True:
        if misc.conf['slider']['auto']:
            misc.slider_sleep()
            slider()
        else:
            time.sleep(0.1)


def refresh_display(display_queue_arg=None):
    """Request periodic redraws without changing the current page."""
    while True:
        period = misc.get_refresh_period()
        if period:
            time.sleep(period)
            display_queue.put('refresh')
        else:
            time.sleep(0.1)


def display_process(display_queue_arg=None):
    """Serialize page changes and data refreshes on the OLED device."""
    current_page = 0
    warning_active = False
    while True:
        try:
            action = display_queue.get(timeout=0.25)
        except queue.Empty:
            if not warning_active:
                continue
            action = 'warning_blink'
        try:
            warnings = misc.get_warnings()
            if warnings:
                warning_active = True
                now = time.monotonic()
                header_visible = int(now / 0.5) % 2 == 0
                warning_offset = int(now / 8) % len(warnings)
                show_warnings(warnings, header_visible, warning_offset)
                continue

            warning_active = False
            pages = gen_pages()
            if not pages:
                continue
            if action == 'next':
                current_page = (current_page + 1) % len(pages)
            else:
                current_page %= len(pages)
            for item in pages[current_page]:
                draw.text(**item)
            disp_show()
        except Exception as exc:
            print('OLED update failed:', exc)


if __name__ == '__main__':
    # For standalone use, run the display worker and its independent timers.
    import threading
    display_queue.put('refresh')
    threading.Thread(target=display_process, daemon=True).start()
    threading.Thread(target=auto_slider, daemon=True).start()
    refresh_display()
