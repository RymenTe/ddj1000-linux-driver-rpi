import sys, struct, collections
f=open(sys.argv[1],'rb').read(); off=0; t0=None; agg=collections.defaultdict(lambda:[0,0,set()])
ex={}
while off+12<=len(f):
    bt,bl=struct.unpack_from('<II',f,off); b=f[off+8:off+bl-4]
    if bt==6:
        iid,th,tl,cap,_=struct.unpack_from('<IIIII',b,0); p=b[20:20+cap]; ts=((th<<32)|tl)/1e6
        t0=t0 if t0 is not None else ts
        if len(p)>=27:
            hl,irp,st,fn,info,bus,dev,ep,tr,dl=struct.unpack_from('<HQIHBHHBBI',p,0); d=p[hl:hl+dl]
            if dev==6 and ep==0x06 and dl:
                cmd=d[1]; a=agg[cmd]; a[0]+=1
                nz=max([i for i,x in enumerate(d) if x]+[0])+1; a[1]=max(a[1],nz); a[2].add(d[0])
                if cmd not in ex or nz>ex[cmd][0]: ex[cmd]=(nz,ts-t0,d[:nz].hex())
    off+=bl
for c,(n,mx,decks) in sorted(agg.items()):
    print('cmd 0x%02x n=%-4d max_used_bytes=%-3d deckbytes=%s  longest@%.2fs: %s'%(c,n,mx,sorted(hex(x) for x in decks),ex[c][1],ex[c][2]))
