# usage: display-init-test.py <midi-port hw:X,0,0> <hidraw> <dump.txt> <hold_s>
# Stage 2: rekordbox display-init SysEx (no heartbeat, no unlock) via ONE rawmidi FD, then HID replay deck 1.
import os, sys, time, select, subprocess
port, hid, dump, hold = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
card = port.split(':')[1].split(',')[0]
mfd = os.open('/dev/snd/midiC%sD0' % card, os.O_RDWR | os.O_NONBLOCK)
H = bytes.fromhex('f0 00 40 05 00 00 02 00 00')
M0A = H + bytes.fromhex('00 0a 00 28 00 26 00 18 3d 3a 05 64 50 2a 54 40 14 1a 04 69 13') + bytes(28) + b'\xf7'
M0B0 = H + bytes.fromhex('00 0b 31 00 00 00 00 00 f7')
M0B1 = H + bytes.fromhex('00 0b 31 5e 50 01 00 00 f7')
M0C = H + bytes.fromhex('00 0c 00 00 02 0e 0e 00 00 00 f7')
M31 = H + bytes.fromhex('03 01 f7')
def drain(tag):
    out = b''
    while select.select([mfd], [], [], 0.02)[0]:
        try: out += os.read(mfd, 4096)
        except BlockingIOError: break
    if out: print('%-8s IN %s' % (tag, out.hex(' ')))
def send(m, tag):
    os.write(mfd, m); time.sleep(0.004); drain(tag)
print('0a len', len(M0A))
for rnd in range(3):
    for m, tg in ((M0A,'0a'),(M0B0,'0b-0'),(M0B1,'0b-1'),(M0C,'0c'),(M31,'03 01')):
        send(m, tg)
    time.sleep(0.3); drain('wait%d' % rnd)
# HID replay deck 1 (same as stage 1), interleaving 03 01 like rekordbox
seq = [(float(t), bytes.fromhex(h)) for t, ep, h in (l.split() for l in open(dump))
       if ep == '06' and h.startswith('10') and 51.70 <= float(t) <= 52.50]
hfd = os.open(hid, os.O_WRONLY)
t0 = time.monotonic(); c0 = seq[0][0]; last21 = None
for t, d in seq:
    dt = (t - c0) - (time.monotonic() - t0)
    if dt > 0: time.sleep(dt)
    os.write(hfd, b'\x00' + d)
    if d[1] == 0x21: last21 = d
print('hid sent', len(seq)); drain('afterhid')
end = time.monotonic() + hold; k = 0
while time.monotonic() < end:
    os.write(hfd, b'\x00' + last21); k += 1
    if k % 60 == 0: send(M31, '03 01 hold')
    time.sleep(1/60)
drain('end'); os.close(hfd); os.close(mfd); print('done')
