#!/usr/bin/env python3
import sys, struct, collections
f=open(sys.argv[1],'rb').read(); off=0; lts={}; i=0; out=[]; inn=collections.Counter(); t0=None
while off+12<=len(f):
    bt,bl=struct.unpack_from('<II',f,off); b=f[off+8:off+bl-4]
    if bt==1: lts[i]=struct.unpack_from('<H',b,0)[0]; i+=1
    elif bt==6:
        iid,th,tl,cap,_=struct.unpack_from('<IIIII',b,0); p=b[20:20+cap]; ts=((th<<32)|tl)/1e6
        if t0 is None: t0=ts
        if len(p)>=27:
            hl,irp,st,fn,info,bus,dev,ep,tr,dl=struct.unpack_from('<HQIHBHHBBI',p,0); d=p[hl:hl+dl]
            if dev==6 and ep==0x06 and dl: out.append((ts-t0,d))
            if dev==6 and ep==0x87 and dl and any(d): inn[d[:2].hex()]+=1
    off+=bl
c=collections.Counter(d[:3].hex() for _,d in out)
print('HID OUT by first 3 bytes:'); [print('  ',k,n) for k,n in c.most_common(25)]
seen=set()
print('first occurrence of each type (t, data):')
for t,d in out:
    k=d[:3].hex()
    if k in seen: continue
    seen.add(k); print('  %7.3f %s'%(t,d.rstrip(b'\0').hex()))
print('HID IN non-zero by first 2 bytes:', inn.most_common(10))
