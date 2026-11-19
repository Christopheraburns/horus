"""Synthetic events for ssb/04_detections.sql: one positive case per detection plus negatives.

Writes ssb/test/out/events.jsonl. Expected alerts (7): AIS_GAP 111, LOITERING 113,
STS_ENCOUNTER 115/116 and 117/118, SPEED_JUMP 119 and fff000, SQUAWK_EMERGENCY abc123.
"""
import datetime as dt
import json
import math
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)
T0 = dt.datetime(2026, 11, 18, 0, 0, 0)
rows = []
def iso(t): return t.strftime("%Y-%m-%dT%H:%M:%SZ")
def vessel(mmsi, t, lat, lon, sog, nav=0, msg="PositionReport", name=None):
    rows.append((t, {"schema_version":1,"trace_id":"x","source":"vessels","captured_at":iso(t),
      "entity":{"id":str(mmsi),"name":name or f"SHIP{mmsi}","entityType":"VESSEL","position":{"lat":lat,"lng":lon,"alt":0.0},
      "timestamp":iso(t),"source":{"provider":"aisstream.io","feed":"vessels","originalId":str(mmsi)},
      "properties":{"mmsi":mmsi,"msgType":msg,"sog":sog,"cog":90,"navStatus":nav}}}))
def flight(hexid, t, lat, lon, kn, squawk=""):
    rows.append((t, {"schema_version":1,"trace_id":"x","source":"flights","captured_at":iso(t),
      "entity":{"id":hexid,"name":"CS"+hexid,"entityType":"FLIGHT","position":{"lat":lat,"lng":lon,"alt":10000.0},
      "timestamp":iso(t),"properties":{"squawk":squawk,"speed_knots":kn,"category":"commercial"}}}))
M = dt.timedelta(minutes=1)
# 111: underway 10 kn east, dark 3 h, reappears 1 nm away -> AIS_GAP
for i in range(30): vessel(111, T0+i*M, 20.0, 60.0 + i*10/60/60/math.cos(math.radians(20)), 10)
vessel(111, T0+29*M+180*M, 20.0, 60.09, 0.5)
for i in range(1,5): vessel(111, T0+209*M+i*M, 20.0, 60.09, 0.5)
# 112: same but reappears 30 nm away (left coverage) -> none
for i in range(30): vessel(112, T0+i*M, 21.0, 60.0 + i*10/60/60, 10)
vessel(112, T0+209*M, 21.0, 60.6, 10)
# 113: loitering under way, 3 h every 5 min -> LOITERING once
for i in range(37): vessel(113, T0+i*5*M, 22.0 + (i%3)*0.001, 61.0, 0.5, nav=0)
# 114: same but anchored -> none
for i in range(37): vessel(114, T0+i*5*M, 23.0 + (i%3)*0.001, 61.0, 0.5, nav=1)
# 115/116: STS pair, anchored, ~70 m apart, 2 h -> STS once
for i in range(25):
    vessel(115, T0+i*5*M, 25.0005, 55.0, 0.3, nav=1); vessel(116, T0+i*5*M+30*dt.timedelta(seconds=1), 25.0, 55.0005, 0.2, nav=1)
# 117/118: STS across a grid-cell boundary (lat 26.02) -> STS
for i in range(13):
    vessel(117, T0+i*5*M, 26.0199, 56.0, 0.1, nav=1); vessel(118, T0+i*5*M, 26.0201, 56.0, 0.1, nav=1)
# 120/121: moored side by side -> none
for i in range(13):
    vessel(120, T0+i*5*M, 27.0, 57.0, 0.0, nav=5); vessel(121, T0+i*5*M, 27.0003, 57.0, 0.0, nav=5)
# 119: speed jump 30 nm in 30 s -> SPEED_JUMP
vessel(119, T0+10*M, 10.0, 10.0, 12); vessel(119, T0+10*M+dt.timedelta(seconds=30), 10.5, 10.0, 12)
vessel(119, T0+11*M, 10.5, 10.001, 12)
# static data message -> ignored
vessel(122, T0+5*M, 30.0, 30.0, None, msg="ShipStaticData")
# flights: squawk 7700 three times -> one alert; 1200 -> none; 300 nm in 60 s -> SPEED_JUMP; normal 480 kn over 12 min -> none
for i in range(3): flight("abc123", T0+i*12*M, 40.0, -90.0+i, 450, "7700")
for i in range(3): flight("def456", T0+i*12*M, 41.0, -91.0+i, 450, "1200")
flight("fff000", T0+20*M, 35.0, -100.0, 450); flight("fff000", T0+21*M, 40.0, -100.0, 450)
flight("aaa111", T0+20*M, 35.0, -80.0, 480); flight("aaa111", T0+32*M, 36.6, -80.0, 480)
# earthquake (other feed) -> ignored
rows.append((T0+M, {"schema_version":1,"captured_at":iso(T0+M),"entity":{"id":"us123","entityType":"EARTHQUAKE","position":{"lat":1,"lng":2},"properties":{}}}))
rows.sort(key=lambda r: r[0])
with open(os.path.join(OUT, "events.jsonl"), "w") as fh:
    for _, r in rows: fh.write(json.dumps(r)+"\n")
print(len(rows), "rows")
