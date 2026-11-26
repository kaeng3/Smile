"""Optional research hypotheses, not validated trading rules or default thresholds."""
from dataclasses import dataclass
from math import isfinite
from statistics import mean

@dataclass(frozen=True)
class Extensions:
    trend_days:int
    trend_min_slope_pct:float
    trend_max_width_pct:float
    trend_min_width_pct:float
    trend_touch_tolerance_pct:float
    trend_min_touches:int
    older_days:int
    gap_min_pct:float
    high_play_min_days:int
    high_play_max_days:int
    high_play_max_width_pct:float
    high_play_min_width_pct:float
    high_play_floor_tolerance_pct:float
    def __post_init__(self):
        if not all(type(v) in (float,int) and isfinite(v) for v in vars(self).values()):
            raise ValueError("Invalid extension parameters")
        for k in ("trend_days","trend_min_touches","older_days","high_play_min_days","high_play_max_days"):
            if type(getattr(self,k)) is not int:
                raise ValueError("Integer window required")
        if not (5<=self.trend_days<=120 and 2<=self.trend_min_touches<=self.trend_days
                and 1<=self.older_days<=500 and 2<=self.high_play_min_days<=self.high_play_max_days<=60
                and 0<self.trend_min_width_pct<self.trend_max_width_pct
                and 0<self.high_play_min_width_pct<self.high_play_max_width_pct
                and self.trend_min_slope_pct>0 and self.gap_min_pct>0
                and 0<=self.trend_touch_tolerance_pct<self.trend_max_width_pct
                and 0<=self.high_play_floor_tolerance_pct<self.high_play_max_width_pct):
            raise ValueError("Invalid research windows or percentages")

def slope(values):
    n=len(values);mx=(n-1)/2;my=mean(values)
    return sum((i-mx)*(v-my) for i,v in enumerate(values))/sum((i-mx)**2 for i in range(n))

def trend_box(b,i,e):
    if i<e.trend_days:return None
    w=b[i-e.trend_days:i];n=len(w)
    highs=[max(x["open"],x["close"]) for x in w]
    lows=[min(x["open"],x["close"]) for x in w]
    s= slope(highs);lower_s=slope(lows)
    if min(s/mean(highs),lower_s/mean(lows))*100<e.trend_min_slope_pct:return None
    # Fit parallel envelopes with common positive slope, then project one bar.
    m=(s+lower_s)/2
    u=max(v-m*j for j,v in enumerate(highs));l=min(v-m*j for j,v in enumerate(lows))
    if l<=0:return None
    width=100*(u-l)/l
    if not e.trend_min_width_pct<=width<=e.trend_max_width_pct:return None
    touches=sum(100*(u+m*j-v)/(u+m*j)<=e.trend_touch_tolerance_pct for j,v in enumerate(highs))
    if touches<e.trend_min_touches:return None
    return {"start":w[0]["day"],"end":w[-1]["day"],"upper":u+m*n,"lower":l+m*n,
            "upper_start":u,"lower_start":l,"upper_end":u+m*(n-1),"lower_end":l+m*(n-1),
            "width_pct":width,"touches":touches,"slope_pct_per_bar":100*m/mean(highs),
            "method":"rising_body_channel_candidate"}

def older_resistance(b,i,window,days):
    older=b[max(0,i-window-days):max(0,i-window)]
    if not older:return None
    x=max(older,key=lambda r:max(r["open"],r["close"]))
    level=max(x["open"],x["close"])
    return {"day":x["day"],"level":level,"distance_pct":100*(b[i]["close"]/level-1),
            "method":"older_body_high_reference"}

def rising_first(b,i,r,e):
    from .patterns import metrics,strong
    if not strong(b,i,r):return None
    box=trend_box(b,i,e)
    if box is None:return None
    m=metrics(b,i);distance=100*(m["close"]/box["upper"]-1)
    if distance < -r.near_breakout_pct:return None
    return {"first_day":m["day"],"first":m,"box":box,"distance_pct":distance,
            "older_resistance":older_resistance(b,i,e.trend_days,e.older_days),
            "breakout":"close_above" if distance>0 else "touching" if distance==0 else "near"}

def high_play(b,i,e,r):
    from .patterns import metrics
    if i<e.high_play_min_days+1:return None
    # Choose latest qualifying gap anchor; do not shorten the window to force a box.
    for j in range(i-e.high_play_min_days,i-e.high_play_max_days-1,-1):
        if j<1:break
        anchor=b[j];previous=b[j-1]
        gap=100*(anchor["open"]/previous["close"]-1)
        if gap<e.gap_min_pct or anchor["open"]<=previous["high"] or anchor["close"]<=anchor["open"]:
            continue
        window=b[j+1:i]
        if len(window)<e.high_play_min_days-1:continue
        upper=max(max(x["open"],x["close"]) for x in window)
        lower=min(min(x["open"],x["close"]) for x in window)
        width=100*(upper/lower-1)
        # Preserve the high price zone; reject a closed gap or weak base.
        if not e.high_play_min_width_pct<=width<=e.high_play_max_width_pct or lower<anchor["open"]:
            return None
        if min(x["low"] for x in window)<=previous["high"]:return None
        m=metrics(b,i);floor=lower*(1-e.high_play_floor_tolerance_pct/100)
        if m["close"]<floor:state="하단 이탈 주의"
        elif m["candle"]=="bull" and b[i-1]["close"]<b[i-1]["open"] and m["close"]>upper:
            state="조정 후 상단 재돌파 후보"
        elif b[i]["low"]<=lower*(1+e.high_play_floor_tolerance_pct/100) and m["close"]>=floor:
            state="하단 지지 후보"
        else:state="고가 박스 유지 관찰"
        return {"strategy":"고가놀이","state":state,"first_day":anchor["day"],"first":metrics(b,j),"today":m,
                "gap_pct":gap,"box":{"start":window[0]["day"],"end":window[-1]["day"],"upper":upper,"lower":lower,
                "width_pct":width,"method":"post_gap_high_body_box_candidate"}}
    return None

def scan_extended(b,r,e):
    from .patterns import metrics
    if len(b)<2:return []
    i=len(b)-1;m=metrics(b,i);out=[]
    previous=rising_first(b,i-1,r,e)
    if previous and m["candle"]=="bull":
        out.append({"strategy":"이일홍 상승형","state":"완성 후보","today":m,**previous})
    else:
        first=rising_first(b,i,r,e)
        if first:out.append({"strategy":"이일홍 상승형","state":"첫 꽃 후보","today":m,**first})
    play=high_play(b,i,e,r)
    if play:out.append(play)
    return out
