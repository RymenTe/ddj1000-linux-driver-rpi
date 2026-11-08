import sys, struct, collections
path=sys.argv[1]
f=open(path,'rb').read()
off=0; linktypes={}; ifc=0
stats=collections.Counter(); sizes=collections.defaultdict(collections.Counter)
devs=collections.Counter(); first=None; last=None; samples=collections.defaultdict(list)
while off+12<=len(f):
    btype,blen=struct.unpack_from('<II',f,off)
    if blen<12: break
    body=f[off+8:off+blen-4]
    if btype==1:
        lt=struct.unpack_from('<H',body,0)[0]; linktypes[ifc]=lt; ifc+=1
    elif btype==6:
        iid,tsh,tsl,cap,orig=struct.unpack_from('<IIIII',body,0)
        pkt=body[20:20+cap]; ts=((tsh<<32)|tsl)/1e6
        first=first or ts; last=ts
        if linktypes.get(iid)==249 and len(pkt)>=27:
            hl,irp,st,fn,info,bus,dev,ep,tr,dl=struct.unpack_from('<HQIHBHHBBI',pkt,0)
            data=pkt[hl:]
            d='IN' if ep&0x80 else 'OUT'
            resp=info&1
            key=(dev,ep,tr,'resp' if resp else 'req')
            stats[key]+=1
            if dl: sizes[key][dl]+=1
            devs[dev]+=1
            if tr==1 and dl and len(samples[key])<4: samples[key].append(data[:dl].hex())
    off+=blen
tn={0:'ISO',1:'INT',2:'CTRL',3:'BULK'}
print('linktypes',linktypes,'duration %.1fs'%((last or 0)-(first or 0)))
print('devices',dict(devs))
for k,v in sorted(stats.items()):
    dev,ep,tr,r=k
    print('dev%-3d ep0x%02x %-4s %-4s n=%-7d sizes=%s'%(dev,ep,tn.get(tr,tr),r,v,dict(sizes[k].most_common(5))))
for k,v in samples.items():
    print('INT sample',k); [print('   ',x) for x in v]
