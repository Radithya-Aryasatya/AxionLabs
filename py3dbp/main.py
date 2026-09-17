#main.py from py3dbp
from .constants import RotationType, Axis
from .auxiliary_methods import intersect, set2Decimal
import numpy as np
# required to plot a representation of Bin and contained items 
from matplotlib.patches import Rectangle,Circle
import matplotlib.pyplot as plt
import mpl_toolkits.mplot3d.art3d as art3d
from collections import Counter
import copy
DEFAULT_NUMBER_OF_DECIMALS = 0
START_POSITION = [0, 0, 0]

# --- Rejection-reason taxonomy (3 canonical buckets) -------------------------
# Every item that fails to pack is tagged with exactly ONE of these on the
# item itself (item.rejection_reason) AND recorded per-bin in
# bin.unfitted_reasons[partno]. Reporting layers (app.py, fleet_state) read
# these instead of guessing, so "packed vs unpacked" accounting is exact and
# packed + unpacked == total_items always holds.
REJECTION_NO_SPACE = "no_space"
REJECTION_OVERWEIGHT = "overweight"
REJECTION_UNSTABLE = "footprint_instability"


def _set_rejection(item, reason, detail=""):
    '''Tag an item with its rejection reason (sticky-note, side-channel).

    Kept as a side attribute so Bin.putItem keeps its plain bool return
    value — no existing caller breaks. detail is a human-readable hint that
    reporting layers may show.
    '''
    try:
        item.rejection_reason = reason
        item.rejection_detail = detail
    except AttributeError:
        pass



class Item:

    def __init__(self, partno,name,typeof, WHD, weight, level, loadbear, updown, color):
        ''' '''
        self.partno = partno
        self.name = name
        self.typeof = typeof
        self.width = WHD[0]
        self.height = WHD[1]
        self.depth = WHD[2]
        self.weight = weight
        # Packing Priority level ,choose 1-3
        self.level = level
        # loadbear
        self.loadbear = loadbear
        # Upside down? True or False
        self.updown = updown if typeof == 'cube' else False
        # Draw item color
        self.color = color
        self.rotation_type = 0
        self.position = START_POSITION
        self.number_of_decimals = DEFAULT_NUMBER_OF_DECIMALS
        # Rejection sticky-note: WHY this item could not be packed (if not).
        # None while packed/untouched; one of the REJECTION_* constants once
        # a placement attempt failed. Preserved through copy.deepcopy.
        self.rejection_reason = None
        self.rejection_detail = ""


    def formatNumbers(self, number_of_decimals):
        ''' '''
        self.width = set2Decimal(self.width, number_of_decimals)
        self.height = set2Decimal(self.height, number_of_decimals)
        self.depth = set2Decimal(self.depth, number_of_decimals)
        self.weight = set2Decimal(self.weight, number_of_decimals)
        self.number_of_decimals = number_of_decimals


    def string(self):
        ''' '''
        return "%s(%sx%sx%s, weight: %s) pos(%s) rt(%s) vol(%s)" % (
            self.partno, self.width, self.height, self.depth, self.weight,
            self.position, self.rotation_type, self.getVolume()
        )


    def getVolume(self):
        ''' '''
        return set2Decimal(self.width * self.height * self.depth, self.number_of_decimals)


    def getMaxArea(self):
        ''' '''
        a = sorted([self.width,self.height,self.depth],reverse=True) if self.updown == True else [self.width,self.height,self.depth]
    
        return set2Decimal(a[0] * a[1] , self.number_of_decimals)


    def getDimension(self):
        ''' rotation type '''
        if self.rotation_type == RotationType.RT_WHD:
            dimension = [self.width, self.height, self.depth]
        elif self.rotation_type == RotationType.RT_HWD:
            dimension = [self.height, self.width, self.depth]
        elif self.rotation_type == RotationType.RT_HDW:
            dimension = [self.height, self.depth, self.width]
        elif self.rotation_type == RotationType.RT_DHW:
            dimension = [self.depth, self.height, self.width]
        elif self.rotation_type == RotationType.RT_DWH:
            dimension = [self.depth, self.width, self.height]
        elif self.rotation_type == RotationType.RT_WDH:
            dimension = [self.width, self.depth, self.height]
        else:
            dimension = []

        return dimension



class Bin:

    def __init__(self, partno, WHD, max_weight,corner=0,put_type=1):
        ''' '''
        self.partno = partno
        self.width = WHD[0]
        self.height = WHD[1]
        self.depth = WHD[2]
        self.max_weight = max_weight
        self.corner = corner
        self.items = []
        self.fit_items = np.array([[0,WHD[0],0,WHD[1],0,0]])
        self.unfitted_items = []
        # partno -> REJECTION_* constant. Written by Packer.pack2Bin whenever
        # an item lands in unfitted_items, so the report can split unpacked
        # items into no_space / overweight / footprint_instability.
        self.unfitted_reasons = {}
        self.number_of_decimals = DEFAULT_NUMBER_OF_DECIMALS
        self.fix_point = False
        self.check_stable = False
        self.support_surface_ratio = 0
        self.put_type = put_type
        # used to put gravity distribution
        self.gravity = []


    def formatNumbers(self, number_of_decimals):
        ''' '''
        self.width = set2Decimal(self.width, number_of_decimals)
        self.height = set2Decimal(self.height, number_of_decimals)
        self.depth = set2Decimal(self.depth, number_of_decimals)
        self.max_weight = set2Decimal(self.max_weight, number_of_decimals)
        self.number_of_decimals = number_of_decimals


    def string(self):
        ''' '''
        return "%s(%sx%sx%s, max_weight:%s) vol(%s)" % (
            self.partno, self.width, self.height, self.depth, self.max_weight,
            self.getVolume()
        )


    def getVolume(self):
        ''' '''
        return set2Decimal(
            self.width * self.height * self.depth, self.number_of_decimals
        )


    def getTotalWeight(self):
        ''' '''
        total_weight = 0

        for item in self.items:
            total_weight += item.weight

        return set2Decimal(total_weight, self.number_of_decimals)


    def putItem(self, item, pivot, axis=None, seq=None):
        ''' put item in bin.

        seq (optional, default None): the item's unloading sequence. When
        set, a candidate placement is rejected if it would trap this box
        behind an already-placed higher-sequence box in the same width lane
        and height shelf — i.e. a box that unloads LATER sits between this
        one and the door (soft-LIFO accessibility, see _isAccessibleAt).
        None = no sequence constraint (the plain packer.pack() path).
        '''
        fit = False
        valid_item_position = item.position
        item.position = pivot
        # Sticky-note default: R1 (no_space) until a more specific failure
        # overwrites it. Cleared again the moment the item is placed, so a
        # packed item never carries a stale rejection reason.
        _set_rejection(item, REJECTION_NO_SPACE, "no valid placement found")
        rotate = RotationType.ALL if item.updown == True else RotationType.Notupdown

        # Iterate over the rotation types themselves (not their positions in
        # the list). The old `for i in range(len(rotate)): item.rotation_type = i`
        # silently ignored the contents of `rotate` and only ever tried the
        # first N poses — so Notupdown = [RT_WHD, RT_HWD] was the *only* combo
        # that "worked", and it even permitted a tip-over. Using the values
        # makes the allowed-list an actual source of truth.
        for rotation_type in rotate:
            item.rotation_type = rotation_type
            dimension = item.getDimension()
            # rotate
            # NOTE: pivot may carry Decimals (first-item path reuses
            # bin.fit_items entries) while dimension entries may be Decimal
            # or float — compare in float space so mixed types never raise.
            try:
                _px, _py, _pz = float(pivot[0]), float(pivot[1]), float(pivot[2])
                _dw, _dh, _dd = float(dimension[0]), float(dimension[1]), float(dimension[2])
            except (TypeError, IndexError, ValueError):
                continue
            if (
                float(self.width) < _px + _dw or
                float(self.height) < _py + _dh or
                float(self.depth) < _pz + _dd
            ):
                # Out of bounds for this pose: R1 (no_space). Try next
                # rotation before giving up.
                _set_rejection(
                    item, REJECTION_NO_SPACE,
                    "exceeds bin bounds in every allowed orientation",
                )
                continue
            fit = True

            for current_item_in_bin in self.items:
                if intersect(current_item_in_bin, item):
                    fit = False
                    # Collides with an already-placed box at this pivot: R1.
                    _set_rejection(
                        item, REJECTION_NO_SPACE,
                        "overlaps an already-packed box at every tried position",
                    )
                    break

            # Soft-LIFO accessibility at the pivot: reject a pivot that would
            # trap this box behind an already-placed higher-sequence box in the
            # same width lane and height shelf (closer to the door). Boxes
            # stacked on top of each other or side-by-side can never trap each
            # other, so they are always allowed.
            if fit and not self._isAccessibleAt(_px, _py, _pz, _dw, _dh, _dd, seq):
                fit = False
                # Sub-tag of R1: this pivot would trap the box behind a
                # later-unloading box (soft-LIFO accessibility).
                _set_rejection(
                    item, REJECTION_NO_SPACE,
                    "trapped behind a later-unloading box (soft-LIFO)",
                )

            if fit:
                # cal total weight
                if self.getTotalWeight() + item.weight > self.max_weight:
                    fit = False
                    # R2: bin payload would be exceeded. No later rotation
                    # changes the weight, so fail immediately.
                    _set_rejection(
                        item, REJECTION_OVERWEIGHT,
                        "bin max weight would be exceeded",
                    )
                    return fit

                # Sequence-mode fast path: prefer placing the box exactly at the
                # validated pivot so same-sequence boxes stay face-adjacent (the
                # door-side face of one box touches the back-side face of the
                # next). Only fall back to the fix-point settling below if the
                # exact pivot is blocked (collision or stability failure).
                if seq is not None and self.fix_point:
                    if self._tryPlaceAtPivot(
                        item, _px, _py, _pz, _dw, _dh, _dd, seq=seq,
                    ):
                        # Placed: clear the sticky-note left by earlier failed
                        # rotations of this same call so a packed item never
                        # carries a stale rejection reason.
                        _set_rejection(item, None)
                        return True
                    # fall through to settling

                # fix point float prob
                if self.fix_point == True :

                    [w,h,d] = dimension
                    [x,y,z] = [float(pivot[0]),float(pivot[1]),float(pivot[2])]

                    for _ in range(3):
                        y_prev, x_prev, z_prev = y, x, z
                        # fix height
                        y = self.checkHeight([x,x+float(w),y,y+float(h),z,z+float(d)])
                        # fix width
                        x = self.checkWidth([x,x+float(w),y,y+float(h),z,z+float(d)])
                        # fix depth
                        z = self.checkDepth([x,x+float(w),y,y+float(h),z,z+float(d)])
                        # Converged: deterministic in (x,y,z) -> stop.
                        if (x, y, z) == (x_prev, y_prev, z_prev):
                            break

                    # BUG FIX: checkHeight/checkWidth/checkDepth above can move
                    # the item to a different (x, y, z) than the pivot position
                    # that was already collision-checked against self.items
                    # (lines ~165-168). Nothing re-validates the ADJUSTED spot
                    # against existing items - only a support/stability check
                    # runs below, which can pass even when boxes now overlap.
                    # Re-run the same intersect() check at the fixed position
                    # before committing to it, and fail the placement (instead
                    # of silently overlapping) if it collides.
                    item.position = [set2Decimal(x), set2Decimal(y), set2Decimal(z)]
                    for current_item_in_bin in self.items:
                        if intersect(current_item_in_bin, item):
                            item.position = valid_item_position
                            fit = False
                            # R1: collides at the SETTLED position (after
                            # checkHeight/Width/Depth slid it there).
                            _set_rejection(
                                item, REJECTION_NO_SPACE,
                                "collides with a packed box after position settling",
                            )
                            return fit

                    # Soft-LIFO accessibility re-check at the settled position:
                    # settling may slide the box in z to a depth that is now
                    # behind a higher-seq box in the same lane and shelf
                    # (closer to the door). Reject rather than ship a trapped
                    # box.
                    if seq is not None and not self._isAccessibleAt(
                        x, y, z, float(w), float(h), float(d), seq,
                    ):
                        item.position = valid_item_position
                        fit = False
                        # Sub-tag of R1: trapped behind a later-unloading box.
                        _set_rejection(
                            item, REJECTION_NO_SPACE,
                            "trapped behind a later-unloading box (soft-LIFO)",
                        )
                        return fit

                    # check stability on item
                    # rule :
                    # 1. Define a support ratio, if the ratio below the support surface does not exceed this ratio, compare the second rule.
                    # 2. If there is no support under any vertices of the bottom of the item, then fit = False.
                    # 3. Center of mass must be supported (the item's footprint center must rest on a supporter or the bin floor).
                    #
                    # "Below" is the vertical (height) axis, i.e. pivot's y / self.height,
                    # NOT the depth (z) axis. The supporting surface is therefore the
                    # item's *footprint* -- its width x depth (x/z) plane -- measured
                    # against other items whose top face (i[3], their y1) sits exactly
                    # at this item's bottom (y). An item resting directly on the bin
                    # floor (y == 0) is always fully supported.
                    MIN_VERTEX_RULE_SUPPORT = 0.25  # minimum support ratio to allow the 4-vertex fallback
                    if self.check_stable == True :
                        if y == 0 :
                            support_area_upper = None  # fully supported by the bin floor
                            center_supported = True
                        else :
                            # Cal the footprint (width x depth) area of the item.
                            item_area_lower = int(dimension[0] * dimension[2])
                            # Cal the area of the underlying support.
                            support_area_upper = 0
                            center_supported = False
                            for i in self.fit_items:
                                # Verify that the lower support surface area is greater than the upper support surface area * support_surface_ratio.
                                if y == i[3] :
                                    ix0 = int(x); ix1 = int(x + int(w))
                                    jx0 = int(i[0]); jx1 = int(i[1])
                                    iz0 = int(z); iz1 = int(z + int(d))
                                    jz0 = int(i[4]); jz1 = int(i[5])
                                    ox = (min(ix1, jx1) - max(ix0, jx0)) if (max(ix0, jx0) < min(ix1, jx1)) else 0
                                    oz = (min(iz1, jz1) - max(iz0, jz0)) if (max(iz0, jz0) < min(iz1, jz1)) else 0
                                    area = ox * oz
                                    support_area_upper += area
                                    # Track whether the item's center of mass is supported
                                    cx = x + float(w) / 2
                                    cz = z + float(d) / 2
                                    if (i[0] <= cx <= i[1]) and (i[4] <= cz <= i[5]):
                                        center_supported = True

                        # Check stability rules
                        stable = True
                        stability_detail = ""
                        if support_area_upper is not None:
                            # Rule 1: support ratio must meet threshold
                            if support_area_upper / item_area_lower < self.support_surface_ratio:
                                # Rule 2: four vertices (only if minimum support met)
                                if support_area_upper / item_area_lower < MIN_VERTEX_RULE_SUPPORT:
                                    stable = False
                                    stability_detail = (
                                        "rests on less than 25% of its footprint "
                                        "(below minimum vertex-rule support)"
                                    )
                                else:
                                    four_vertices = [[x,z],[x+float(w),z],[x,z+float(d)],[x+float(w),z+float(d)]]
                                    c = [False,False,False,False]
                                    for i in self.fit_items:
                                        if y == i[3] :
                                            for jdx,j in enumerate(four_vertices) :
                                                if (i[0] <= j[0] <= i[1]) and (i[4] <= j[1] <= i[5]) :
                                                    c[jdx] = True
                                    if False in c:
                                        stable = False
                                        stability_detail = (
                                            "support below threshold and not all 4 "
                                            "footprint corners are supported"
                                        )
                            # Rule 3: center of mass must be supported
                            if stable and not center_supported:
                                stable = False
                                stability_detail = "center of mass is not supported"

                        if not stable:
                            # Slide-to-support rescue: try sliding toward the largest supporter
                            rescued = False
                            if support_area_upper is not None and support_area_upper > 0:
                                # Find the largest supporter
                                best_supporter = None
                                best_area = 0
                                for i in self.fit_items:
                                    if y == i[3]:
                                        ix0 = int(x); ix1 = int(x + int(w))
                                        jx0 = int(i[0]); jx1 = int(i[1])
                                        iz0 = int(z); iz1 = int(z + int(d))
                                        jz0 = int(i[4]); jz1 = int(i[5])
                                        ox = (min(ix1, jx1) - max(ix0, jx0)) if (max(ix0, jx0) < min(ix1, jx1)) else 0
                                        oz = (min(iz1, jz1) - max(iz0, jz0)) if (max(iz0, jz0) < min(iz1, jz1)) else 0
                                        area = ox * oz
                                        if area > best_area:
                                            best_area = area
                                            best_supporter = i
                                if best_supporter is not None:
                                    sup_cx = (best_supporter[0] + best_supporter[1]) / 2
                                    sup_cz = (best_supporter[4] + best_supporter[5]) / 2
                                    item_cx = x + float(w) / 2
                                    item_cz = z + float(d) / 2
                                    slide_x = sup_cx - item_cx
                                    slide_z = sup_cz - item_cz
                                    slide_dist = (slide_x ** 2 + slide_z ** 2) ** 0.5
                                    if slide_dist > 0.5:
                                        for factor in [1.0, 0.5, 1.5]:
                                            trial_x = x + slide_x * factor
                                            trial_z = z + slide_z * factor
                                            trial_x = max(0.0, min(trial_x, float(self.width) - float(w)))
                                            _zlo = 0.0
                                            _zhi = float(self.depth) - float(d)
                                            trial_z = max(_zlo, min(trial_z, _zhi))
                                            item.position = [set2Decimal(trial_x), set2Decimal(y), set2Decimal(trial_z)]
                                            collision = False
                                            for current_item_in_bin in self.items:
                                                if intersect(current_item_in_bin, item):
                                                    collision = True
                                                    break
                                            if collision:
                                                continue
                                            trial_stable = True
                                            trial_support = 0
                                            trial_center_ok = False
                                            for i in self.fit_items:
                                                if y == i[3]:
                                                    ix0 = int(trial_x); ix1 = int(trial_x + int(w))
                                                    jx0 = int(i[0]); jx1 = int(i[1])
                                                    iz0 = int(trial_z); iz1 = int(trial_z + int(d))
                                                    jz0 = int(i[4]); jz1 = int(i[5])
                                                    ox = (min(ix1, jx1) - max(ix0, jx0)) if (max(ix0, jx0) < min(ix1, jx1)) else 0
                                                    oz = (min(iz1, jz1) - max(iz0, jz0)) if (max(iz0, jz0) < min(iz1, jz1)) else 0
                                                    trial_support += ox * oz
                                                    cx = trial_x + float(w) / 2
                                                    cz = trial_z + float(d) / 2
                                                    if (i[0] <= cx <= i[1]) and (i[4] <= cz <= i[5]):
                                                        trial_center_ok = True
                                            if trial_support / item_area_lower < self.support_surface_ratio:
                                                if trial_support / item_area_lower < MIN_VERTEX_RULE_SUPPORT:
                                                    trial_stable = False
                                                else:
                                                    four_vertices = [[trial_x,trial_z],[trial_x+float(w),trial_z],[trial_x,trial_z+float(d)],[trial_x+float(w),trial_z+float(d)]]
                                                    c = [False,False,False,False]
                                                    for i in self.fit_items:
                                                        if y == i[3]:
                                                            for jdx,j in enumerate(four_vertices):
                                                                if (i[0] <= j[0] <= i[1]) and (i[4] <= j[1] <= i[5]):
                                                                    c[jdx] = True
                                                    if False in c:
                                                        trial_stable = False
                                            if trial_stable and not trial_center_ok:
                                                trial_stable = False
                                            if trial_stable:
                                                x = trial_x
                                                z = trial_z
                                                rescued = True
                                                break
                            if not rescued:
                                item.position = valid_item_position
                                fit = False
                                # R3: footprint instability — THE reported bug.
                                # An item that fails the support/stability rules
                                # must be strictly UNPACKED, never counted as
                                # packed. Tag the reason so reporting can show
                                # it in the footprint_instability bucket.
                                _set_rejection(
                                    item, REJECTION_UNSTABLE,
                                    stability_detail or
                                    "footprint not sufficiently supported",
                                )
                                return fit

                    self.fit_items = np.append(self.fit_items,np.array([[x,x+float(w),y,y+float(h),z,z+float(d)]]),axis=0)
                    item.position = [set2Decimal(x),set2Decimal(y),set2Decimal(z)]

                if fit :
                    # Placed: clear the sticky-note left by earlier failed
                    # rotations of this same call.
                    _set_rejection(item, None)
                    self.items.append(copy.deepcopy(item))

            else :
                item.position = valid_item_position

            return fit

        else :
            item.position = valid_item_position

        return fit


    def _isStableAt(self, x, y, z, w, h, d):
        '''Stability check at a candidate position, using fit_items (float math).

        Mirrors the stability rules used in putItem but with float
        comparisons (no int() truncation) so fractional coordinates from
        3-decimal packing are handled correctly.
        '''
        if y <= 1e-9:
            return True  # on the bin floor
        footprint = float(w) * float(d)
        if footprint <= 0:
            return True
        support_area = 0.0
        center_ok = False
        for i in self.fit_items:
            if abs(y - float(i[3])) > 1e-6:
                continue
            ix0 = float(x); ix1 = float(x) + float(w)
            jx0 = float(i[0]); jx1 = float(i[1])
            iz0 = float(z); iz1 = float(z) + float(d)
            jz0 = float(i[4]); jz1 = float(i[5])
            ox = (min(ix1, jx1) - max(ix0, jx0)) if (max(ix0, jx0) < min(ix1, jx1)) else 0.0
            oz = (min(iz1, jz1) - max(iz0, jz0)) if (max(iz0, jz0) < min(iz1, jz1)) else 0.0
            support_area += ox * oz
            cx = float(x) + float(w) / 2.0
            cz = float(z) + float(d) / 2.0
            if (float(i[0]) <= cx <= float(i[1])) and (float(i[4]) <= cz <= float(i[5])):
                center_ok = True
        ratio = support_area / footprint
        if ratio >= self.support_surface_ratio:
            return center_ok
        if ratio < 0.25:
            return False
        four_vertices = [[x, z], [x + w, z], [x, z + d], [x + w, z + d]]
        c = [False, False, False, False]
        for i in self.fit_items:
            if abs(y - float(i[3])) > 1e-6:
                continue
            for jdx, j in enumerate(four_vertices):
                if (float(i[0]) <= j[0] <= float(i[1])) and (float(i[4]) <= j[1] <= float(i[5])):
                    c[jdx] = True
        if False in c:
            return False
        return center_ok


    def _tryPlaceAtPivot(self, item, px, py, pz, dw, dh, dd, seq=None):
        '''Try to place item exactly at the validated pivot (soft-LIFO fast path).

        Keeps same-sequence boxes face-adjacent. Returns True if placed.
        On failure, restores item.position and returns False so the caller
        can fall back to fix-point settling.
        '''
        valid_item_position = item.position
        item.position = [set2Decimal(px, self.number_of_decimals),
                         set2Decimal(py, self.number_of_decimals),
                         set2Decimal(pz, self.number_of_decimals)]
        # Collision re-check at the exact pivot
        for current_item_in_bin in self.items:
            if intersect(current_item_in_bin, item):
                item.position = valid_item_position
                return False
        # Soft-LIFO accessibility at the exact pivot: a higher-seq box in the
        # same lane and shelf in front of this box would trap it. (Redundant
        # with the rotation-loop check above, but kept for defence-in-depth.)
        if seq is not None and not self._isAccessibleAt(px, py, pz, dw, dh, dd, seq):
            item.position = valid_item_position
            return False
        # Stability check at the exact pivot (against fit_items)
        if self.check_stable and not self._isStableAt(px, py, pz, dw, dh, dd):
            item.position = valid_item_position
            return False
        self.fit_items = np.append(
            self.fit_items,
            np.array([[px, px + dw, py, py + dh, pz, pz + dd]]),
            axis=0,
        )
        item.position = [set2Decimal(px, self.number_of_decimals),
                         set2Decimal(py, self.number_of_decimals),
                         set2Decimal(pz, self.number_of_decimals)]
        self.items.append(copy.deepcopy(item))
        return True


    def checkDepth(self,unfix_point):
        ''' fix item position z '''
        z_ = [[0,0],[float(self.depth),float(self.depth)]]
        for j in self.fit_items:
            x0 = float(j[0]); x1 = float(j[1])
            x2 = float(unfix_point[0]); x3 = float(unfix_point[1])
            if x0 < x3 and x2 < x1:
                y0 = float(j[2]); y1 = float(j[3])
                y2 = float(unfix_point[2]); y3 = float(unfix_point[3])
                if y0 < y3 and y2 < y1:
                    z_.append([float(j[4]), float(j[5])])
        top_depth = unfix_point[5] - unfix_point[4]
        # find diff set on z_.
        z_ = sorted(z_, key = lambda z_ : z_[1])
        for j in range(len(z_)-1):
            if z_[j+1][0] -z_[j][1] >= top_depth:
                return z_[j][1]
        return unfix_point[4]


    def _isAccessibleAt(self, x, y, z, w, h, d, seq, moving_ids=None):
        ''' Soft-LIFO accessibility predicate.

        A candidate box at position (x, y, z) with dimensions (w, h, d) and
        unloading sequence `seq` is ACCESSIBLE (returns True) iff no already-
        placed box that unloads LATER sits between it and the door in the same
        width lane and same height shelf.

        Concretely, for each already-placed box J with seq(J) > seq, J blocks
        the candidate I when ALL of these hold:
          (a) J is fully in front of I (closer to the door): J.z_start >= I.z_end
          (b) x-intervals overlap  -> same width lane
          (c) y-intervals overlap  -> same height shelf

        Boxes stacked on top of each other (non-overlapping y) or side-by-side
        (non-overlapping x) can NEVER trap each other, even at the same depth
        and even when a higher-seq box is "above" or "beside" a lower-seq one.

        The door lives at the maximum z (deepest z coordinate), so "in front of"
        / "between I and the door" means a higher z than I. z=0 is the back wall.

        Parameters
        ----------
        x, y, z : candidate box origin (cm).
        w, h, d : candidate box dimensions (cm). NOTE: h (height) is needed
            for the y-overlap test; the plan's signature omitted it but it is
            required for correctness.
        seq : candidate box unloading sequence (int/float), or None. None means
            "no sequence constraint" -> always accessible (returns True).
        moving_ids : optional set of id(item) values to ignore. Reserved for
            bulk-move scenarios; unused on the main soft-LIFO path.

        Returns
        -------
        True  -> placement is LIFO-safe (no higher-seq box traps it).
        False -> placement would trap this box behind a later-unloading box.
        '''
        if seq is None:
            return True
        seq = float(seq)
        # Candidate I's extent.
        ix0 = float(x); ix1 = ix0 + float(w)
        iy0 = float(y); iy1 = iy0 + float(h)
        iz1 = float(z) + float(d)  # I's front face (door-side z)
        for other in self.items:
            if moving_ids is not None and id(other) in moving_ids:
                continue
            oseq = getattr(other, 'sequence', None)
            if oseq is None:
                continue
            if float(oseq) <= seq:
                continue
            # J unloads later than I. Does J sit in front of I in the same
            # lane and shelf?
            try:
                od = other.getDimension()
                jx0 = float(other.position[0]); jx1 = jx0 + float(od[0])
                jy0 = float(other.position[1]); jy1 = jy0 + float(od[1])
                jz0 = float(other.position[2])
            except (TypeError, ValueError, IndexError):
                continue
            # (b) same width lane: x intervals overlap
            if not (ix0 < jx1 and jx0 < ix1):
                continue
            # (c) same height shelf: y intervals overlap
            if not (iy0 < jy1 and jy0 < iy1):
                continue
            # (a) J fully in front of I (closer to the door). J's back face is
            # at or beyond I's front face. A box touching I's front face still
            # blocks it (you'd have to move J to pull I out), so use >= with a
            # small epsilon equal to half a 3-decimal quantization step.
            if jz0 >= iz1 - 5e-4:
                return False
        return True


    def checkWidth(self,unfix_point):
        ''' fix item position x ''' 
        x_ = [[0,0],[float(self.width),float(self.width)]]
        for j in self.fit_items:
            z0 = float(j[4]); z1 = float(j[5])
            z2 = float(unfix_point[4]); z3 = float(unfix_point[5])
            if z0 < z3 and z2 < z1:
                y0 = float(j[2]); y1 = float(j[3])
                y2 = float(unfix_point[2]); y3 = float(unfix_point[3])
                if y0 < y3 and y2 < y1:
                    x_.append([float(j[0]), float(j[1])])
        top_width = unfix_point[1] - unfix_point[0]
        # find diff set on x_bottom and x_top.
        x_ = sorted(x_,key = lambda x_ : x_[1])
        for j in range(len(x_)-1):
            if x_[j+1][0] -x_[j][1] >= top_width:
                return x_[j][1]
        return unfix_point[0]
    

    def checkHeight(self,unfix_point):
        '''fix item position y '''
        y_ = [[0,0],[float(self.height),float(self.height)]]
        for j in self.fit_items:
            x0 = float(j[0]); x1 = float(j[1])
            x2 = float(unfix_point[0]); x3 = float(unfix_point[1])
            if x0 < x3 and x2 < x1:
                z0 = float(j[4]); z1 = float(j[5])
                z2 = float(unfix_point[4]); z3 = float(unfix_point[5])
                if z0 < z3 and z2 < z1:
                    y_.append([float(j[2]), float(j[3])])
        top_height = unfix_point[3] - unfix_point[2]
        # find diff set on y_bottom and y_top.
        y_ = sorted(y_,key = lambda y_ : y_[1])
        for j in range(len(y_)-1):
            if y_[j+1][0] -y_[j][1] >= top_height:
                return y_[j][1]

        return unfix_point[2]


    def addCorner(self):
        '''add container coner '''
        if self.corner != 0 :
            corner = set2Decimal(self.corner)
            corner_list = []
            for i in range(8):
                a = Item(
                    partno='corner{}'.format(i),
                    name='corner', 
                    typeof='cube',
                    WHD=(corner,corner,corner), 
                    weight=0, 
                    level=0, 
                    loadbear=0, 
                    updown=True, 
                    color='#000000')

                corner_list.append(a)
            return corner_list


    def putCorner(self,info,item):
        '''put coner in bin '''
        fit = False
        x = set2Decimal(self.width - self.corner)
        y = set2Decimal(self.height - self.corner)
        z = set2Decimal(self.depth - self.corner)
        pos = [[0,0,0],[0,0,z],[0,y,z],[0,y,0],[x,y,0],[x,0,0],[x,0,z],[x,y,z]]
        item.position = pos[info]
        self.items.append(item)

        corner = [float(item.position[0]),float(item.position[0])+float(self.corner),float(item.position[1]),float(item.position[1])+float(self.corner),float(item.position[2]),float(item.position[2])+float(self.corner)]

        self.fit_items = np.append(self.fit_items,np.array([corner]),axis=0)
        return


    def clearBin(self):
        ''' clear item which in bin '''
        self.items = []
        self.fit_items = np.array([[0,self.width,0,self.height,0,0]])
        return


class Packer:

    def __init__(self):
        ''' '''
        self.bins = []
        self.items = []
        self.unfit_items = []
        self.total_items = 0
        self.binding = []
        # self.apex = []


    def addBin(self, bin):
        ''' '''
        return self.bins.append(bin)


    def addItem(self, item):
        ''' '''
        self.total_items = len(self.items) + 1

        return self.items.append(item)


    def pack2Bin(self, bin, item, fix_point, check_stable, support_surface_ratio, seq=None):
        ''' pack item to bin.

        seq (optional): the item's unloading sequence. When set, Bin.putItem
        enforces soft-LIFO accessibility (no higher-sequence box may trap
        this box behind it in the same lane+shelf). The axis order is also
        switched to DEPTH->WIDTH->HEIGHT so same-sequence boxes fill depth
        rows first and stay face-adjacent. None = plain packing (the
        packer.pack() path) with no sequence guarantee.
        '''
        fitted = False
        bin.fix_point = fix_point
        bin.check_stable = check_stable
        bin.support_surface_ratio = support_surface_ratio

        # first put item on (0,0,0) , if corner exist ,first add corner in box.
        if bin.corner != 0 and not bin.items:
            corner_lst = bin.addCorner()
            for i in range(len(corner_lst)) :
                bin.putCorner(i,corner_lst[i])

        elif not bin.items:
            response = bin.putItem(item, item.position, seq=seq)
            if not response:
                bin.unfitted_items.append(item)
                # Record WHY (no_space / overweight / footprint_instability)
                # so the packed-vs-unpacked report is exact.
                bin.unfitted_reasons[item.partno] = (
                    item.rejection_reason or REJECTION_NO_SPACE
                )
            return

        # Soft-LIFO: when a sequence is set, STACK vertically first
        # (HEIGHT->WIDTH->DEPTH) so boxes of the same sequence pile up
        # at the deep back wall, then fill a column beside them,
        # then move toward the door. Plain packing keeps the classic
        # WIDTH->HEIGHT->DEPTH order.
        if seq is not None:
            _axes = (Axis.HEIGHT, Axis.WIDTH, Axis.DEPTH)
        else:
            _axes = (Axis.WIDTH, Axis.HEIGHT, Axis.DEPTH)
        for axis in _axes:
            items_in_bin = bin.items
            for ib in items_in_bin:
                pivot = [0, 0, 0]
                w, h, d = ib.getDimension()
                if axis == Axis.WIDTH:
                    pivot = [ib.position[0] + w,ib.position[1],ib.position[2]]
                elif axis == Axis.HEIGHT:
                    pivot = [ib.position[0],ib.position[1] + h,ib.position[2]]
                elif axis == Axis.DEPTH:
                    pivot = [ib.position[0],ib.position[1],ib.position[2] + d]

                if bin.putItem(item, pivot, axis, seq=seq):
                    fitted = True
                    break
            if fitted:
                break

        if not fitted:
            bin.unfitted_items.append(item)
            # Record WHY (no_space / overweight / footprint_instability).
            # item.rejection_reason holds the failure of the LAST attempted
            # pivot/rotation, which is the most specific reason available.
            bin.unfitted_reasons[item.partno] = (
                item.rejection_reason or REJECTION_NO_SPACE
            )


    def sortBinding(self,bin):
        ''' sorted by binding '''
        b = [[] for _ in range(len(self.binding))]
        bound_names = set()
        for group in self.binding:
            bound_names.update(group)

        # Preserve the original relative order of unbound items, split
        # around the first bound item: items before it go to the front,
        # the rest to the back.
        first_bound_idx = None
        for idx, item in enumerate(self.items):
            if item.name in bound_names:
                first_bound_idx = idx
                break

        front, back = [], []
        for idx, item in enumerate(self.items):
            if item.name in bound_names:
                for i, group in enumerate(self.binding):
                    if item.name in group:
                        b[i].append(item)
                        break
            elif first_bound_idx is None or idx < first_bound_idx:
                front.append(item)
            else:
                back.append(item)

        # Round-robin interleave the binding groups so no single group
        # monopolizes the packing order. Empty groups are handled by the
        # bounds check (no more min_c == 0 crash, no items dropped).
        sort_bind = []
        max_len = max((len(g) for g in b), default=0)
        for i in range(max_len):
            for j in range(len(b)):
                if i < len(b[j]):
                    sort_bind.append(b[j][i])

        self.items = front + sort_bind + back
        return


    def checkStable(self, bin, item, fix_point, support_surface_ratio):
        '''Check whether `item` is stable at its current position in `bin`.

        Mirrors the stability rules in Bin.putItem but evaluates against the
        live positions of bin.items (so it works during _compactBin moves,
        where fit_items is stale). Rules:
          1. Support ratio (overlap area / footprint area) >= support_surface_ratio.
          2. If below, fall back to the 4-vertex rule (min 25% support).
          3. Center of mass must be supported.
        An item on the bin floor (y == 0) is always stable.
        '''
        try:
            dim = item.getDimension()
            w = float(dim[0]); h = float(dim[1]); d = float(dim[2])
            x = float(item.position[0]); y = float(item.position[1]); z = float(item.position[2])
        except (TypeError, ValueError, IndexError):
            return True

        if y <= 1e-9:
            return True  # on the floor

        footprint = w * d
        if footprint <= 0:
            return True

        support_area = 0.0
        center_ok = False
        for other in bin.items:
            if other is item:
                continue
            try:
                odim = other.getDimension()
                ow = float(odim[0]); oh = float(odim[1]); od = float(odim[2])
                ox = float(other.position[0]); oy = float(other.position[1]); oz = float(other.position[2])
            except (TypeError, ValueError, IndexError):
                continue
            # other's top face must touch item's bottom
            if abs(y - (oy + oh)) > 1e-6:
                continue
            ox0 = max(x, ox); ox1 = min(x + w, ox + ow)
            oz0 = max(z, oz); oz1 = min(z + d, oz + od)
            if ox0 < ox1 and oz0 < oz1:
                support_area += (ox1 - ox0) * (oz1 - oz0)
                cx = x + w / 2.0
                cz = z + d / 2.0
                if ox <= cx <= ox + ow and oz <= cz <= oz + od:
                    center_ok = True

        ratio = support_area / footprint
        if ratio >= support_surface_ratio:
            return center_ok
        if ratio < 0.25:
            return False
        # 4-vertex fallback
        four_vertices = [[x, z], [x + w, z], [x, z + d], [x + w, z + d]]
        c = [False, False, False, False]
        for other in bin.items:
            if other is item:
                continue
            try:
                odim = other.getDimension()
                ow = float(odim[0]); oh = float(odim[1]); od = float(odim[2])
                ox = float(other.position[0]); oy = float(other.position[1]); oz = float(other.position[2])
            except (TypeError, ValueError, IndexError):
                continue
            if abs(y - (oy + oh)) > 1e-6:
                continue
            for jdx, j in enumerate(four_vertices):
                if (ox <= j[0] <= ox + ow) and (oz <= j[1] <= oz + od):
                    c[jdx] = True
        if False in c:
            return False
        return center_ok


    def _compactBin(self, bin, fix_point, check_stable, support_surface_ratio):
        '''Small fix: gentle push-together to close walkways between groups.

        Two passes, both height-preserving:
          A) inside each delivery zone, slide boxes back then left;
          B) slide each whole delivery zone back toward the rear wall so
             empty air between colour groups closes up. Delivery order is
             kept: zones never cross each other, boxes never leave their
             own zone, support is re-checked for every move.
        '''
        if len(bin.items) <= 1:
            return
        try:
            seq_floor = getattr(bin, '_seq_floor', None) or {}
        except Exception:
            seq_floor = {}

        def _f(v):
            try:
                return float(v)
            except Exception:
                return 0.0

        def _box_of(it):
            d = it.getDimension()
            p = it.position
            return (_f(p[0]), _f(p[0]) + _f(d[0]),
                    _f(p[1]), _f(p[1]) + _f(d[1]),
                    _f(p[2]), _f(p[2]) + _f(d[2]))

        def _overlaps(a, b):
            eps = 1e-9
            return (a[0] < b[1] - eps and b[0] < a[1] - eps and
                    a[2] < b[3] - eps and b[2] < a[3] - eps and
                    a[4] < b[5] - eps and b[4] < a[5] - eps)

        def _supported(it):
            if not check_stable:
                return True
            try:
                return self.checkStable(bin, it, fix_point, support_surface_ratio)
            except Exception:
                return True

        # Pass A: slide each support-connected stack back then left as a
        # rigid unit. Sliding a whole stack together (instead of one box at
        # a time) preserves stacking: a box on top of another can never be
        # left floating when its support slides away. Support is re-checked
        # for every move via checkStable().
        def _rests_on(a, b):
            '''True if a's bottom face rests on b's top face (touching + overlap).'''
            try:
                ad = a.getDimension(); bd = b.getDimension()
                ax0 = _f(a.position[0]); ay0 = _f(a.position[1]); az0 = _f(a.position[2])
                aw = _f(ad[0]); ah = _f(ad[1]); ad_ = _f(ad[2])
                bx0 = _f(b.position[0]); by0 = _f(b.position[1]); bz0 = _f(b.position[2])
                bw = _f(bd[0]); bh = _f(bd[1]); bd_ = _f(bd[2])
            except Exception:
                return False
            if abs(ay0 - (by0 + bh)) > 1e-6:
                return False
            ox = min(ax0 + aw, bx0 + bw) - max(ax0, bx0)
            oz = min(az0 + ad_, bz0 + bd_) - max(az0, bz0)
            return ox > 1e-6 and oz > 1e-6

        _by_id = {id(it): it for it in bin.items}

        # Undirected connected components of the support graph.
        components = []
        unvisited = set(_by_id.keys())
        while unvisited:
            start = next(iter(unvisited))
            comp = set()
            frontier = [start]
            while frontier:
                sid = frontier.pop()
                if sid not in unvisited:
                    continue
                unvisited.discard(sid)
                comp.add(sid)
                for other in bin.items:
                    oid = id(other)
                    if oid in comp or oid not in unvisited:
                        continue
                    if _rests_on(_by_id[sid], other) or _rests_on(other, _by_id[sid]):
                        frontier.append(oid)
            components.append([_by_id[sid] for sid in comp])

        # Backmost components first so front components can slide further.
        components.sort(key=lambda comp: min(_f(it.position[2]) for it in comp))

        def _ok_at(it, moving_ids):
            '''True if `it`'s current position is in-bounds, inside its zone
            floor, and non-overlapping with any item outside `moving_ids`.'''
            try:
                dim = it.getDimension()
                dw, dh, dd = _f(dim[0]), _f(dim[1]), _f(dim[2])
                nx = _f(it.position[0]); oy = _f(it.position[1]); nz = _f(it.position[2])
            except Exception:
                return False
            if nx < -1e-9 or nz < -1e-9:
                return False
            if nx + dw > _f(bin.width) + 1e-9:
                return False
            if nz + dd > _f(bin.depth) + 1e-9:
                return False
            try:
                floor = seq_floor.get(it.partno, None)
                z_low = float(floor) if floor is not None else 0.0
            except Exception:
                z_low = 0.0
            if float(nz) < float(z_low) - 1e-9:
                return False
            cand = (nx, nx + dw, oy, oy + dh, nz, nz + dd)
            for other in bin.items:
                if id(other) in moving_ids:
                    continue
                if _overlaps(cand, _box_of(other)):
                    return False
            return True

        def _try_slide(comp, dx, dz):
            '''Try to move every item in comp by (dx, dz). Returns True if
            committed; rolls back on any failure.'''
            moving_ids = {id(it) for it in comp}
            olds = {id(it): list(it.position) for it in comp}
            for it in comp:
                try:
                    q = it.number_of_decimals
                except Exception:
                    q = 0
                it.position = [set2Decimal(_f(it.position[0]) + dx, q),
                               set2Decimal(_f(it.position[1]), q),
                               set2Decimal(_f(it.position[2]) + dz, q)]
            ok = all(_ok_at(it, moving_ids) for it in comp)
            if ok:
                ok = all(_supported(it) for it in comp)
            if not ok:
                for it in comp:
                    it.position = olds[id(it)]
                return False
            return True

        for comp in components:
            try:
                # Slide back (toward the rear wall, -z) first.
                step_z = max(
                    min(_f(it.getDimension()[2]) for it in comp) / 20.0,
                    float(bin.depth) / 200.0, 0.05,
                )
                guard = 0
                while guard < 60:
                    guard += 1
                    if _try_slide(comp, 0.0, -step_z):
                        continue
                    if _try_slide(comp, 0.0, -step_z / 4.0):
                        continue
                    break
                # Slide left (toward the left wall, -x) next.
                step_x = max(
                    min(_f(it.getDimension()[0]) for it in comp) / 20.0,
                    float(bin.width) / 200.0, 0.05,
                )
                guard = 0
                while guard < 60:
                    guard += 1
                    if _try_slide(comp, -step_x, 0.0):
                        continue
                    if _try_slide(comp, -step_x / 4.0, 0.0):
                        continue
                    break
            except Exception:
                continue

        # Pass B: close the walkway BETWEEN delivery zones. Move each zone
        # (deepest first) back as one solid block until it touches the zone
        # behind it or the rear wall. Inside-zone layout never changes, so
        # boxes keep their neighbours and support; only empty air between
        # colour groups disappears. Zones can never cross: each stops at
        # the front face of the zone behind it.
        #
        # BUG FIX (vs the original): shifts are applied one group at a time
        # and only the ACTUAL committed shift of the previous group feeds the
        # next group's target. The old code precomputed every shift from the
        # PLANNED shift of the previous group, so if a group's shift failed
        # (e.g. support check), the next group still moved as if it had
        # succeeded — sliding into overlap with the un-moved group. Each
        # candidate shift is also validated against the zone floor and
        # against every item outside the moving group (overlap), and falls
        # back to progressively smaller shifts before giving up.
        try:
            if seq_floor:
                groups = {}
                for it in bin.items:
                    try:
                        # Fall back to the item's current z when no floor was
                        # recorded (e.g. non-zone packing), so it is grouped
                        # by its actual position rather than lumped with the
                        # backmost zone.
                        groups.setdefault(float(seq_floor.get(it.partno, _f(it.position[2]))), []).append(it)
                    except Exception:
                        continue
                if len(groups) > 1:
                    ordered_floors = sorted(groups.keys())
                    shift_of = {}
                    for _idx, _fl in enumerate(ordered_floors):
                        _grp = groups[_fl]
                        _back = min(_f(_it.position[2]) for _it in _grp)
                        if _idx == 0:
                            _target = 0.0
                        else:
                            _prev = ordered_floors[_idx - 1]
                            # Front face of the previous group AFTER its
                            # actual committed shift.
                            _prev_front = max(
                                _f(_it.position[2]) + _f(_it.getDimension()[2])
                                for _it in groups[_prev]
                            )
                            _target = _prev_front
                        _max_shift = min(0.0, _target - _back)
                        if abs(_max_shift) < 1e-9:
                            shift_of[_fl] = 0.0
                            continue
                        # Try the full shift, then halves, then quarters.
                        _committed = 0.0
                        for _factor in (1.0, 0.5, 0.25, 0.125):
                            _cand = _max_shift * _factor
                            if abs(_cand - _committed) < 1e-9:
                                continue
                            _delta = _cand - _committed
                            _moving_ids = {id(_it) for _it in _grp}
                            _olds = {id(_it): list(_it.position) for _it in _grp}
                            for _it in _grp:
                                try:
                                    _q = _it.number_of_decimals
                                except Exception:
                                    _q = 0
                                _it.position = [set2Decimal(float(_it.position[0]), _q),
                                                set2Decimal(float(_it.position[1]), _q),
                                                set2Decimal(float(_it.position[2]) + _delta, _q)]
                            _ok = True
                            for _it in _grp:
                                try:
                                    _dim = _it.getDimension()
                                    _dw = _f(_dim[0]); _dd = _f(_dim[2])
                                    _nx = _f(_it.position[0]); _nz = _f(_it.position[2])
                                except Exception:
                                    _ok = False
                                    break
                                if _nx < -1e-9 or _nz < -1e-9:
                                    _ok = False
                                    break
                                if _nx + _dw > _f(bin.width) + 1e-9:
                                    _ok = False
                                    break
                                if _nz + _dd > _f(bin.depth) + 1e-9:
                                    _ok = False
                                    break
                                try:
                                    _floor = seq_floor.get(_it.partno, None)
                                    _z_low = float(_floor) if _floor is not None else 0.0
                                except Exception:
                                    _z_low = 0.0
                                if float(_nz) < float(_z_low) - 1e-9:
                                    _ok = False
                                    break
                                _cand_box = (_nx, _nx + _dw,
                                             _f(_it.position[1]), _f(_it.position[1]) + _f(_dim[1]),
                                             _nz, _nz + _dd)
                                for _other in bin.items:
                                    if id(_other) in _moving_ids:
                                        continue
                                    if _overlaps(_cand_box, _box_of(_other)):
                                        _ok = False
                                        break
                                if not _ok:
                                    break
                            if _ok:
                                _ok = all(_supported(_it) for _it in _grp)
                            if not _ok:
                                for _it in _grp:
                                    _it.position = _olds[id(_it)]
                                continue
                            _committed = _cand
                            break
                        shift_of[_fl] = _committed
                    try:
                        for _fl in ordered_floors:
                            for _it in groups[_fl]:
                                seq_floor[_it.partno] = float(_fl) + float(shift_of.get(_fl, 0.0))
                        bin._seq_floor = seq_floor
                    except Exception:
                        pass
        except Exception:
            pass


    def putOrder(self):
        '''Arrange the order of items '''
        for i in self.bins:
            # open top container
            if i.put_type == 2:
                i.items.sort(key=lambda item: item.position[0], reverse=False)
                i.items.sort(key=lambda item: item.position[1], reverse=False)
                i.items.sort(key=lambda item: item.position[2], reverse=False)
            # general container: depth (z) primary, then height (y), then
            # width (x) — a natural loading-order view (deepest first,
            # bottom-up, left-to-right). The old order had width primary,
            # which scattered the sequence view.
            elif i.put_type == 1:
                i.items.sort(key=lambda item: item.position[0], reverse=False)
                i.items.sort(key=lambda item: item.position[1], reverse=False)
                i.items.sort(key=lambda item: item.position[2], reverse=False)
            else :
                pass
        return


    def gravityCenter(self,bin):
        ''' 
        Deviation Of Cargo gravity distribution
        ''' 
        w = int(bin.width)
        h = int(bin.height)
        d = int(bin.depth)

        area1 = [set(range(0,w//2+1)),set(range(0,h//2+1)),0]
        area2 = [set(range(w//2+1,w+1)),set(range(0,h//2+1)),0]
        area3 = [set(range(0,w//2+1)),set(range(h//2+1,h+1)),0]
        area4 = [set(range(w//2+1,w+1)),set(range(h//2+1,h+1)),0]
        area = [area1,area2,area3,area4]

        for i in bin.items:

            x_st = int(i.position[0])
            y_st = int(i.position[1])
            if i.rotation_type == 0:
                x_ed = int(i.position[0] + i.width)
                y_ed = int(i.position[1] + i.height)
            elif i.rotation_type == 1:
                x_ed = int(i.position[0] + i.height)
                y_ed = int(i.position[1] + i.width)
            elif i.rotation_type == 2:
                x_ed = int(i.position[0] + i.height)
                y_ed = int(i.position[1] + i.depth)
            elif i.rotation_type == 3:
                x_ed = int(i.position[0] + i.depth)
                y_ed = int(i.position[1] + i.height)
            elif i.rotation_type == 4:
                x_ed = int(i.position[0] + i.depth)
                y_ed = int(i.position[1] + i.width)
            elif i.rotation_type == 5:
                x_ed = int(i.position[0] + i.width)
                y_ed = int(i.position[1] + i.depth)

            x_set = set(range(x_st,int(x_ed)+1))
            y_set = set(range(y_st,y_ed+1))

            # cal gravity distribution
            for j in range(len(area)):
                if x_set.issubset(area[j][0]) and y_set.issubset(area[j][1]) : 
                    area[j][2] += int(i.weight)
                    break
                # include x and !include y
                elif x_set.issubset(area[j][0]) == True and y_set.issubset(area[j][1]) == False and len(y_set & area[j][1]) != 0 : 
                    y = len(y_set & area[j][1]) / (y_ed - y_st) * int(i.weight)
                    area[j][2] += y
                    if j >= 2 :
                        area[j-2][2] += (int(i.weight) - y)
                    else :
                        area[j+2][2] += (int(i.weight) - y)
                    break
                # include y and !include x
                elif x_set.issubset(area[j][0]) == False and y_set.issubset(area[j][1]) == True and len(x_set & area[j][0]) != 0 : 
                    x = len(x_set & area[j][0]) / (x_ed - x_st) * int(i.weight)
                    area[j][2] += x
                    if j >= 2 :
                        area[j-2][2] += (int(i.weight) - x)
                    else :
                        area[j+2][2] += (int(i.weight) - x)
                    break
                # !include x and !include y
                elif x_set.issubset(area[j][0])== False and y_set.issubset(area[j][1]) == False and len(y_set & area[j][1]) != 0  and len(x_set & area[j][0]) != 0 :
                    all = (y_ed - y_st) * (x_ed - x_st)
                    y = len(y_set & area[0][1])
                    y_2 = y_ed - y_st - y
                    x = len(x_set & area[0][0])
                    x_2 = x_ed - x_st - x
                    area[0][2] += x * y / all * int(i.weight)
                    area[1][2] += x_2 * y / all * int(i.weight)
                    area[2][2] += x * y_2 / all * int(i.weight)
                    area[3][2] += x_2 * y_2 / all * int(i.weight)
                    break
            
        r = [area[0][2],area[1][2],area[2][2],area[3][2]]
        result = []
        for i in r :
            result.append(round(i / sum(r) * 100,2))
        return result


    def pack(self, bigger_first=False,distribute_items=True,fix_point=True,check_stable=True,support_surface_ratio=0.75,binding=[],number_of_decimals=DEFAULT_NUMBER_OF_DECIMALS):
        '''pack master func '''
        # set decimals
        for bin in self.bins:
            bin.formatNumbers(number_of_decimals)

        for item in self.items:
            item.formatNumbers(number_of_decimals)
        # add binding attribute
        self.binding = binding
        # Bin : sorted by volumn
        self.bins.sort(key=lambda bin: bin.getVolume(), reverse=bigger_first)
        # Item : single explicit sort. The old three chained stable sorts
        # applied volume -> loadbear -> level, but because list.sort is
        # stable the LAST sort wins, so the effective priority was actually
        # level (asc) -> loadbear (desc) -> volume (asc/desc per
        # bigger_first). One tuple-key sort makes the priority explicit and
        # preserves that exact effective ordering.
        def _item_sort_key(item):
            _vol = float(item.getVolume())
            return (item.level, -float(item.loadbear), -_vol if bigger_first else _vol)

        self.items.sort(key=_item_sort_key)
        # sorted by binding
        if binding != []:
            self.sortBinding(bin)

        for idx,bin in enumerate(self.bins):
            # pack item to bin
            for item in self.items:
                self.pack2Bin(bin, item, fix_point, check_stable, support_surface_ratio)

            if binding != []:
                # resorted (same explicit priority as above)
                self.items.sort(key=_item_sort_key)
                # clear bin
                bin.items = []
                bin.unfitted_items = self.unfit_items
                bin.fit_items = np.array([[0,bin.width,0,bin.height,0,0]])
                # repacking
                for item in self.items:
                    self.pack2Bin(bin, item,fix_point,check_stable,support_surface_ratio)
            
            # --- Small fix: gentle push-together (gap compaction) ---------------
            # Slides every box as far back (-depth) and then as far left
            # (-width) as it can go until it touches another box or the
            # truck wall. Moves are blocked by real boxes so a front-stop
            # box can never jump behind a back-stop box; support + bounds
            # are re-checked for every move. This only closes empty
            # walkways between colour groups, it never changes stacking.
            try:
                self._compactBin(bin, fix_point, check_stable, support_surface_ratio)
            except Exception:
                pass

            # Deviation Of Cargo Gravity Center 
            try:
                self.bins[idx].gravity = self.gravityCenter(bin)
            except Exception:
                self.bins[idx].gravity = []

            if distribute_items :
                for bitem in bin.items:
                    no = bitem.partno
                    for item in self.items :
                        if item.partno == no :
                            self.items.remove(item)
                            break

        # --- Orientation enforcement audit (defence-in-depth) ----------------
        # Steps 1 + 2 already guarantee putItem only ever assigns an allowed
        # rotation, but this guard makes the rule explicit at the output
        # boundary: any item flagged updown=False that somehow ended up in a
        # tipped pose is moved to unfitted_items instead of being silently
        # shipped as a forbidden "(_I_) flip".
        for bin in self.bins:
            still_fitted = []
            for item in bin.items:
                if item.updown == False and item.rotation_type not in RotationType.Notupdown:
                    # Tag the reason before moving to unpacked: forbidden
                    # tipped orientation is a geometry rejection (R1 bucket)
                    # with an explicit detail.
                    _set_rejection(
                        item, REJECTION_NO_SPACE,
                        "forbidden tipped orientation (updown=False)",
                    )
                    bin.unfitted_items.append(item)
                    bin.unfitted_reasons.setdefault(item.partno, REJECTION_NO_SPACE)
                else:
                    still_fitted.append(item)
            bin.items = still_fitted

        # put order of items
        self.putOrder()

        if self.items != []:
            self.unfit_items = copy.deepcopy(self.items)
            for _it in self.unfit_items:
                # Items that never made it into ANY bin keep whatever reason
                # their last placement attempt produced; default to R1.
                if getattr(_it, 'rejection_reason', None) is None:
                    _set_rejection(_it, REJECTION_NO_SPACE, "remaining after packing")
            self.items = []
        # for item in self.items.copy():
        #     if item in bin.unfitted_items:
        #         self.items.remove(item)

    def summary_counts(self):
        '''Accurate packed/unpacked accounting with rejection reasons.

        Guarantees the report invariant:
            len(packed_items) + len(unpacked_items) == total items offered
        and no item is ever counted as BOTH packed and unpacked (deduped by
        partno across bins, leftover packer.items and packer.unfit_items).

        Returns dict:
            packed         -> int
            unpacked       -> int
            by_reason      -> {REJECTION_*: count}
            packed_items   -> [Item]
            unpacked_items -> [Item]
        '''
        packed_items = []
        unpacked_items = []
        seen_packed = set()
        seen_unpacked = set()

        for bin in self.bins:
            for it in bin.items:
                if it.partno not in seen_packed:
                    seen_packed.add(it.partno)
                    packed_items.append(it)
            for it in getattr(bin, 'unfitted_items', []):
                if it.partno in seen_packed or it.partno in seen_unpacked:
                    continue
                seen_unpacked.add(it.partno)
                unpacked_items.append(it)

        # Items still in the queue (the soft-LIFO path leaves them here) or
        # moved to the leftover list by pack(): both mean "unpacked".
        for source in (self.items, self.unfit_items):
            for it in source:
                if it.partno in seen_packed or it.partno in seen_unpacked:
                    continue
                seen_unpacked.add(it.partno)
                unpacked_items.append(it)

        by_reason = {}
        for it in unpacked_items:
            reason = getattr(it, 'rejection_reason', None)
            if not reason:
                reason = REJECTION_NO_SPACE
            by_reason[reason] = by_reason.get(reason, 0) + 1

        return {
            "packed": len(packed_items),
            "unpacked": len(unpacked_items),
            "by_reason": by_reason,
            "packed_items": packed_items,
            "unpacked_items": unpacked_items,
        }



class Painter:

    def __init__(self,bins):
        ''' '''
        self.items = bins.items
        self.width = bins.width
        self.height = bins.height
        self.depth = bins.depth


    def _plotCube(self, ax, x, y, z, dx, dy, dz, color='red',mode=2,linewidth=1,text="",fontsize=15,alpha=0.5):
        """ Auxiliary function to plot a cube. code taken somewhere from the web.  """
        xx = [x, x, x+dx, x+dx, x]
        yy = [y, y+dy, y+dy, y, y]
        
        kwargs = {'alpha': 1, 'color': color,'linewidth':linewidth }
        if mode == 1 :
            ax.plot3D(xx, yy, [z]*5, **kwargs)
            ax.plot3D(xx, yy, [z+dz]*5, **kwargs)
            ax.plot3D([x, x], [y, y], [z, z+dz], **kwargs)
            ax.plot3D([x, x], [y+dy, y+dy], [z, z+dz], **kwargs)
            ax.plot3D([x+dx, x+dx], [y+dy, y+dy], [z, z+dz], **kwargs)
            ax.plot3D([x+dx, x+dx], [y, y], [z, z+dz], **kwargs)
        else :
            p = Rectangle((x,y),dx,dy,fc=color,ec='black',alpha = alpha)
            p2 = Rectangle((x,y),dx,dy,fc=color,ec='black',alpha = alpha)
            p3 = Rectangle((y,z),dy,dz,fc=color,ec='black',alpha = alpha)
            p4 = Rectangle((y,z),dy,dz,fc=color,ec='black',alpha = alpha)
            p5 = Rectangle((x,z),dx,dz,fc=color,ec='black',alpha = alpha)
            p6 = Rectangle((x,z),dx,dz,fc=color,ec='black',alpha = alpha)
            ax.add_patch(p)
            ax.add_patch(p2)
            ax.add_patch(p3)
            ax.add_patch(p4)
            ax.add_patch(p5)
            ax.add_patch(p6)
            
            if text != "":
                ax.text( (x+ dx/2), (y+ dy/2), (z+ dz/2), str(text),color='black', fontsize=fontsize, ha='center', va='center')

            art3d.pathpatch_2d_to_3d(p, z=z, zdir="z")
            art3d.pathpatch_2d_to_3d(p2, z=z+dz, zdir="z")
            art3d.pathpatch_2d_to_3d(p3, z=x, zdir="x")
            art3d.pathpatch_2d_to_3d(p4, z=x + dx, zdir="x")
            art3d.pathpatch_2d_to_3d(p5, z=y, zdir="y")
            art3d.pathpatch_2d_to_3d(p6, z=y + dy, zdir="y")


    def _plotCylinder(self, ax, x, y, z, dx, dy, dz, color='red',mode=2,text="",fontsize=10,alpha=0.2):
        """ Auxiliary function to plot a Cylinder  """
        # plot the two circles above and below the cylinder
        p = Circle((x+dx/2,y+dy/2),radius=dx/2,color=color,alpha=0.5)
        p2 = Circle((x+dx/2,y+dy/2),radius=dx/2,color=color,alpha=0.5)
        ax.add_patch(p)
        ax.add_patch(p2)
        art3d.pathpatch_2d_to_3d(p, z=z, zdir="z")
        art3d.pathpatch_2d_to_3d(p2, z=z+dz, zdir="z")
        # plot a circle in the middle of the cylinder
        center_z = np.linspace(0, dz, 10)
        theta = np.linspace(0, 2*np.pi, 10)
        theta_grid, z_grid=np.meshgrid(theta, center_z)
        x_grid = dx / 2 * np.cos(theta_grid) + x + dx / 2
        y_grid = dy / 2 * np.sin(theta_grid) + y + dy / 2
        z_grid = z_grid + z
        ax.plot_surface(x_grid, y_grid, z_grid,shade=False,fc=color,alpha=alpha,color=color)
        if text != "" :
            ax.text( (x+ dx/2), (y+ dy/2), (z+ dz/2), str(text),color='black', fontsize=fontsize, ha='center', va='center')

    def plotBoxAndItems(self,title="",alpha=0.2,write_num=False,fontsize=10):
        """ side effective. Plot the Bin and the items it contains. """
        fig = plt.figure()
        axGlob = plt.axes(projection='3d')
        
        # plot bin 
        self._plotCube(axGlob,0, 0, 0, float(self.width), float(self.height), float(self.depth),color='black',mode=1,linewidth=2,text="")

        counter = 0
        # fit rotation type
        for item in self.items:
            rt = item.rotation_type  
            x,y,z = item.position
            [w,h,d] = item.getDimension()
            color = item.color
            text= item.partno if write_num else ""

            if item.typeof == 'cube':
                 # plot item of cube
                self._plotCube(axGlob, float(x), float(y), float(z), float(w),float(h),float(d),color=color,mode=2,text=text,fontsize=fontsize,alpha=alpha)
            elif item.typeof == 'cylinder':
                # plot item of cylinder
                self._plotCylinder(axGlob, float(x), float(y), float(z), float(w),float(h),float(d),color=color,mode=2,text=text,fontsize=fontsize,alpha=alpha)
            
            counter = counter + 1  

        
        plt.title(title)
        self.setAxesEqual(axGlob)
        return plt


    def setAxesEqual(self,ax):
        '''Make axes of 3D plot have equal scale so that spheres appear as spheres,
        cubes as cubes, etc..  This is one possible solution to Matplotlib's
        ax.set_aspect('equal') and ax.axis('equal') not working for 3D.

        Input
        ax: a matplotlib axis, e.g., as output from plt.gca().'''
        x_limits = ax.get_xlim3d()
        y_limits = ax.get_ylim3d()
        z_limits = ax.get_zlim3d()

        x_range = abs(x_limits[1] - x_limits[0])
        x_middle = np.mean(x_limits)
        y_range = abs(y_limits[1] - y_limits[0])
        y_middle = np.mean(y_limits)
        z_range = abs(z_limits[1] - z_limits[0])
        z_middle = np.mean(z_limits)

        # The plot bounding box is a sphere in the sense of the infinity
        # norm, hence I call half the max range the plot radius.
        plot_radius = 0.5 * max([x_range, y_range, z_range])

        ax.set_xlim3d([x_middle - plot_radius, x_middle + plot_radius])
        ax.set_ylim3d([y_middle - plot_radius, y_middle + plot_radius])
        ax.set_zlim3d([z_middle - plot_radius, z_middle + plot_radius])