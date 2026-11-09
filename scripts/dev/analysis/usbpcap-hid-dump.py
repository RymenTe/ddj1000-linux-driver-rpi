#!/usr/bin/env python3
# usage: python3 -I usbpcap-hid-dump.py <pcapng> <usb-device-nr> <out.txt>  -> "t ep hex" lines (EP 04/85 MIDI, 06/87 HID; HID-IN zero reports skipped)
import sys, struct
f=open(sys.argv[1],'rb').read(); dev=int(sys.argv[2]); off=0; t0=None
o=open(sys.argv[3],'w')
while off+12<=len(f):
    bt,bl=struct.unpack_from('<II',f,off); b=f[off+8:off+bl-4]
    if bt==6:
        iid,th,tl,cap,_=struct.unpack_from('<IIIII',b,0); p=b[20:20+cap]; ts=((th<<32)|tl)/1e6
        if t0 is None: t0=ts
        if len(p)>=27:
            hl,irp,st,fn,info,bus,d,ep,tr,dl=struct.unpack_from('<HQIHBHHBBI',p,0)
            if d==dev and dl and ep in (0x06,0x04,0x85,0x87):
                data=p[hl:hl+dl]
                if ep==0x87 and not any(data): pass
                else: o.write('%.4f %02x %s\n'%(ts-t0,ep,data.hex()))
    off+=bl
