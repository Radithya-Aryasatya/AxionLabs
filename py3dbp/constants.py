class RotationType:
    RT_WHD = 0
    RT_HWD = 1
    RT_HDW = 2
    RT_DHW = 3
    RT_DWH = 4
    RT_WDH = 5

    ALL = [RT_WHD, RT_HWD, RT_HDW, RT_DHW, RT_DWH, RT_WDH]

    # The two "upright" poses: the item's declared height stays vertical
    # (the y-axis). RT_WHD and RT_DHW differ only by a floor-spin (swapping
    # width and depth), which is always allowed. All four of the other poses
    # tip the item onto its side or flip it upside-down — these are the
    # forbidden "(_I_) flips" and must NOT be used when the item is flagged
    # as not-upside-down (updown=False).
    Notupdown = [RT_WHD, RT_DHW]
 
class Axis:
    WIDTH = 0
    HEIGHT = 1
    DEPTH = 2

    ALL = [WIDTH, HEIGHT, DEPTH]

