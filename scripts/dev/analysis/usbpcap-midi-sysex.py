#!/usr/bin/env python3
import sys, struct, collections
# Decode USB-MIDI (EP 0x04 OUT / 0x85 IN) of device DEV from a USBPcap pcapng; print SysEx messages with time.
f=open(sys.argv[1],'rb').read(); DEV=int(sys.argv[2]) if len(sys.argv)>2 else 6
off=0; t0=None; buf={0x04:b'',0x85:b''}; short=collections.Counter()
L={0:0,1:0,2:2,3:3,4:3,5:1,6:2,7:3,8:3,9:3,0xA:3,0xB:3,0xC:2,0xD:2,0xE:3,0xF:1}
while off+12<=len(f):
    bt,bl=struct.unpack_from('<II',f,off); b=f[off+8:off+bl-4]
    if bt==6:
        iid,th,tl,cap,_=struct.unpack_from('<IIIII',b,0); p=b[20:20+cap]; ts=((th<<32)|tl)/1e6
        t0=t0 if t0 is not None else ts
        if len(p)>=27:
            hl,irp,st,fn,info,bus,dev,ep,tr,dl=struct.unpack_from('<HQIHBHHBBI',p,0); d=p[hl:hl+dl]
            if dev==DEV and ep in buf and tr==3 and dl:
                for i in range(0,len(d)-3,4):
                    cin=d[i]&0x0F; m=d[i+1:i+1+L[cin]]
                    if cin==4: buf[ep]+=m
                    elif cin in (5,6,7) and (buf[ep] or m[:1]==b'\xf0'):
                        buf[ep]+=m; print('%8.3f %s SYSEX %s'%(ts-t0,'OUT' if ep==4 else 'IN ',buf[ep].hex(' '))); buf[ep]=b''
                    elif cin>=8: short[('OUT' if ep==4 else 'IN',m[:2].hex(' '))]+=1
    off+=bl
print('short messages (dir, status+data1) top 40:')
for k,n in short.most_common(40): print('  ',k,n)
