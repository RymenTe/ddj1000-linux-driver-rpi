# usage: display-stage3.py <hw:X,0,0> <hidraw> <dump.txt> <hold_s> [--deck 1|2] [--no-init] [--hb-stop-after-ack S]
#   --deck 2: replay deck-2 upload (right display); --no-init: skip display-init SysEx;
#   --hb-stop-after-ack S: stop heartbeat S seconds after the ACK (default: keep running)
# Stage 3: like rekordbox - heartbeat 50 01 every 200 ms + own unlock handshake (one rawmidi FD),
# after ACK: display init SysEx (00 0a/0b/0c, 03 01), then HID replay deck 1 in a thread, heartbeat continues.
import importlib.util, os, sys, threading, time
import argparse
ap = argparse.ArgumentParser(); ap.add_argument('port'); ap.add_argument('hid'); ap.add_argument('dump'); ap.add_argument('hold', type=float)
ap.add_argument('--deck', type=int, default=1); ap.add_argument('--no-init', action='store_true'); ap.add_argument('--hb-stop-after-ack', type=float, default=-1)
A = ap.parse_args(); port, hid, dump, hold = A.port, A.hid, A.dump, A.hold
RANGE = {1: ('10', 51.70, 52.50), 2: ('20', 54.00, 55.00)}[A.deck]
spec = importlib.util.spec_from_file_location('ut', '/home/pi/ddj1000-linux-driver/scripts/dev/ddj1000-unlock-test.py')
ut = importlib.util.module_from_spec(spec); spec.loader.exec_module(ut)
p = ut.load_protocol()
H = bytes.fromhex('f0 00 40 05 00 00 02 00 00')
INIT = [H + bytes.fromhex('00 0a 00 28 00 26 00 18 3d 3a 05 64 50 2a 54 40 14 1a 04 69 13') + bytes(28) + b'\xf7',
        H + bytes.fromhex('00 0b 31 00 00 00 00 00 f7'), H + bytes.fromhex('00 0b 31 5e 50 01 00 00 f7'),
        H + bytes.fromhex('00 0c 00 00 02 0e 0e 00 00 00 f7'), H + bytes.fromhex('03 01 f7')]
seq = [(float(t), bytes.fromhex(h)) for t, ep, h in (l.split() for l in open(dump))
       if ep == '06' and h.startswith(RANGE[0]) and RANGE[1] <= float(t) <= RANGE[2]]
fd = os.open(ut.rawmidi_path(port), os.O_RDWR | os.O_NONBLOCK)
start = time.monotonic(); s = ut.Session(fd, p, start)
stop = threading.Event()
def hid_thread():
    hfd = os.open(hid, os.O_WRONLY); t0 = time.monotonic(); c0 = seq[0][0]; last = None
    for t, d in seq:
        dt = (t - c0) - (time.monotonic() - t0)
        if dt > 0: time.sleep(dt)
        os.write(hfd, b'\x00' + d)
        if d[1] == 0x21: last = d
    s.log('HID upload sent (%d reports), now status 0x21 at 60 Hz' % len(seq))
    while not stop.is_set():
        os.write(hfd, b'\x00' + last); time.sleep(1/60)
    os.close(hfd)
nhb = 0.0; hb = 0; hs_at = -1e9; ack = None; th = None; init_done = False
try:
    while True:
        now = time.monotonic()
        hb_on = not (ack is not None and A.hb_stop_after_ack >= 0 and now - ack > A.hb_stop_after_ack)
        if hb_on and now >= nhb:
            s.send(p.KEEPALIVE_MESSAGE, 'heartbeat', quiet=hb > 0); hb += 1; nhb = now + 0.2
        if ack is None and now - start > 20: s.log('TIMEOUT no ACK'); break
        if ack is not None and not init_done and now - ack > 0.1:
            if not A.no_init:
                for i, m in enumerate(INIT): s.send(m, 'display-init %d' % i); time.sleep(0.003)
            else: s.log('display-init SKIPPED')
            init_done = True
        if init_done and th is None and now - ack > 1.0:
            s.log('>>> HID upload deck %d starts now (heartbeat %s)' % (A.deck, 'ON' if hb_on else 'OFF')); th = threading.Thread(target=hid_thread); th.start()
        if ack is not None and now - ack > hold: s.log('hold finished'); break
        for msg in s.read_messages(timeout=max(0.0, min(0.05, nhb - time.monotonic())) if hb_on else 0.05):
            if msg == p.READY_MESSAGE:
                s.log('RX 11 02 ready')
                if ack is None and time.monotonic() - hs_at >= 2.0:
                    for i, pre in enumerate(p.PRELUDE_MESSAGES): s.send(pre, 'prelude %d' % i)
                    s.send(p.HANDSHAKE_REQUEST, '12 2a'); hs_at = time.monotonic()
            elif p.is_ddj_device_challenge(msg):
                s.log('RX 13 2a challenge'); s.send(p.build_ddj_handshake_response(p.extract_ddj_seed_e(msg)), '14 38')
            elif msg.startswith(p.DDJ_ACK_PREFIX):
                ack = time.monotonic(); s.log('RX 15 02 ACK -> UNLOCKED')
            else:
                s.log('RX sysex ' + p.format_bytes(msg))
finally:
    stop.set()
    if th: th.join()
    os.close(fd); s.log('closed; heartbeats %d; %s' % (hb, 'UNLOCKED' if ack else 'NOT UNLOCKED'))
