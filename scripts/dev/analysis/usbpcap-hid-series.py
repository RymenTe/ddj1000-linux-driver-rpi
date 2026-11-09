#!/usr/bin/env python3
import sys
# usage: series.py dump deckprefix(10/20/..) cmd(2f/2c) t_from t_to  -> payload bytes (6-byte header stripped)
dump,dk,cmd,a,b=sys.argv[1],sys.argv[2],sys.argv[3],float(sys.argv[4]),float(sys.argv[5])
out=b''
for line in open(dump):
    t,ep,h=line.split()
    if ep=='06' and h.startswith(dk+cmd) and a<float(t)<b:
        out+=bytes.fromhex(h)[6:]
sys.stdout.buffer.write(out)
